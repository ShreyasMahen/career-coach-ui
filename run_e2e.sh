#!/bin/bash
# End-to-end check on your Mac: install, tests, parse resumes, extract job skills,
# match (S3 and S7), and chatbot smoke tests. Everything is also written to logs/
# so Claude can read the results. Your Voyager key is never printed.
#
#   cd ~/PycharmProjects/career-coach-parser && bash run_e2e.sh
#   LIMIT=500 bash run_e2e.sh      # fewer job postings for a faster run

set -u -o pipefail
cd "$(dirname "$0")"
mkdir -p logs data/raw
LOG="logs/e2e-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee "$LOG") 2>&1
LIMIT="${LIMIT:-2000}"

step() { echo; echo "===== $1 ====="; }
ok() { echo "[OK] $1"; }
fail() { echo "[FAIL] $1"; }
skip() { echo "[SKIP] $1"; }

step "Environment"
sw_vers 2>/dev/null; uname -m
if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv (official installer from astral.sh)..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
uv --version || { fail "uv is not available"; exit 1; }

# Files you placed in ~/PycharmProjects are moved into the project.
[ -f ../.env ] && [ ! -f .env ] && mv ../.env .env
for name in job_postings.csv postings.csv; do   # newer dataset versions call the file postings.csv
  [ -f "../$name" ] && [ ! -f data/raw/job_postings.csv ] && mv "../$name" data/raw/job_postings.csv
done
[ -d ../resumes ] && [ ! -d resumes ] && mv ../resumes resumes
HAS_KEY=no; grep -Eq '^VOYAGER_API_KEY=.+' .env 2>/dev/null && HAS_KEY=yes
HAS_CSV=no; [ -f data/raw/job_postings.csv ] && HAS_CSV=yes
PDFS=$(ls resumes/*.pdf 2>/dev/null | wc -l | tr -d ' ')
echo "Voyager key in .env: $HAS_KEY | job_postings.csv: $HAS_CSV | resume PDFs: $PDFS | job limit: $LIMIT"

step "Install (uv sync --extra matching)"
uv sync --extra matching && ok "install" || { fail "install"; exit 1; }

step "Unit tests (Kelly's and Ritish's)"
uv run python -m unittest discover -s tests -p "test_*.py" && ok "tests" || fail "tests"

step "Parse resumes (Kelly's pipeline)"
RESUMES=tests/fixtures/legacy_resume_output.json
if [ "$PDFS" -gt 0 ] && [ "$HAS_KEY" = yes ]; then
  if uv run python -m career_coach.data_extraction.main resumes; then ok "parser"; RESUMES=resumes.json
  else fail "parser (falling back to the sample resume)"; fi
else
  skip "needs resume PDFs in resumes/ and a Voyager key; using the sample resume in tests/fixtures"
fi
echo "Resumes file: $RESUMES"

step "Extract job skills"
if [ "$HAS_CSV" = yes ]; then
  uv run python -m career_coach.matching.cli jobs --kaggle data/raw/job_postings.csv --out data/jobs.jsonl --limit "$LIMIT" \
    && ok "jobs" || { fail "jobs"; exit 1; }
else
  skip "no data/raw/job_postings.csv; using the 8 synthetic test postings"
  uv run python -m career_coach.matching.cli jobs --jsonl tests/fixtures/sample_jobs.jsonl --out data/jobs.jsonl || exit 1
fi

step "Match S3 (classical, no models)"
uv run python -m career_coach.matching.cli match --resumes "$RESUMES" --jobs data/jobs.jsonl --embeddings none \
  --system S3 --top-k 5 > logs/match_S3.json && ok "S3 -> logs/match_S3.json" || fail "S3"

step "Match S7 (BM25 + SBERT + KG; first run downloads models)"
uv run python -m career_coach.matching.cli match --resumes "$RESUMES" --jobs data/jobs.jsonl \
  --system S7 --top-k 5 > logs/match_S7.json && ok "S7 -> logs/match_S7.json" || fail "S7"
uv run python - <<'PY'
import json
try:
    data = json.load(open("logs/match_S7.json"))
except Exception as error:
    print("Could not read S7 results:", error)
else:
    for cv, rows in data.items():
        print(cv)
        for r in rows:
            print(f"  {r['rank']}. {r['title']} @ {r['company']} | kg {r['kg_score']} | "
                  f"matched {r['matched_skills'][:4]} | missing {r['missing_required'][:4]}")
PY

step "Chatbot commands (no LLM)"
FIRST=$(uv run python -c "import json;d=json.load(open('logs/match_S7.json'));print(next(iter(d.values()))[0]['job_id'])" 2>/dev/null)
printf '/search\n/gap\n/draft %s\n/quit\n' "$FIRST" | uv run python -m career_coach.agent.chat --resumes "$RESUMES" \
  --jobs data/jobs.jsonl --no-llm > logs/chat_commands.txt 2>&1 && ok "commands -> logs/chat_commands.txt" || fail "commands"
tail -25 logs/chat_commands.txt

step "Chatbot with Voyager"
if [ "$HAS_KEY" = yes ]; then
  printf 'Which jobs fit me best, and which required skills am I missing for the top one?\n/quit\n' | \
    uv run python -m career_coach.agent.chat --resumes "$RESUMES" --jobs data/jobs.jsonl > logs/chat_llm.txt 2>&1 \
    && ok "LLM chat -> logs/chat_llm.txt" || fail "LLM chat"
  tail -25 logs/chat_llm.txt
else
  skip "no VOYAGER_API_KEY in .env"
fi

step "Done"
echo "Full log: $LOG"
