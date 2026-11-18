# CareerCoach UI

This is the public UI fork of the CareerCoach project. The **`browser-ui` branch**
contains the browser workspace shown in the demo. Anyone can view or download
this repository without an invitation. The GitHub link shares the source code;
the app runs on your own computer after you start it.

The workspace uses the project's existing matching and agent modules to show
ranked jobs, documented and missing skills, source evidence, and editable outreach
drafts. The original extraction, matching, agent, and evaluation code is unchanged.

## Get the UI version

Clone this branch, then run the commands below from the cloned folder:

```sh
git clone --branch browser-ui https://github.com/ShreyasMahen/career-coach-ui.git
cd career-coach-ui
```

Alternatively, [download the UI branch as a ZIP](https://github.com/ShreyasMahen/career-coach-ui/archive/refs/heads/browser-ui.zip),
unzip it, and open a terminal in the extracted folder.

## Start the UI with Docker

With Docker Desktop installed and running:

```sh
docker compose -f compose.ui.yaml up --build -d
```

Open **[http://localhost:8501](http://localhost:8501)** in your browser. The first
build installs the project dependencies. This separate UI configuration uses CPU
PyTorch and publishes the app only on your local computer.

To stop the UI:

```sh
docker compose -f compose.ui.yaml down
```

## Start the UI without Docker

Docker is optional. With **Python 3.13+ and uv** installed, run:

```sh
uv sync
uv run python ui_server.py
```

Then open **[http://localhost:8501](http://localhost:8501)**. If the project's
dependencies are already installed in your active Python environment, you can
instead run `python ui_server.py`. Keep that terminal open while using the UI;
press Ctrl+C to stop it.

## What to try

1. Start with the included parsed resume and **eight synthetic job postings**.
2. Search for a skill or location, such as `Python` or `remote`, and select a job.
3. Review **Why this match** for required/preferred skills and other requirements.
4. Open **Source evidence** to compare posting text with the normalized graph facts.
5. Open **Draft outreach**, create a recruiter/referral draft, then edit and copy it.
6. Use the left panel to upload the project's **parsed resume JSON** or postings
   **JSONL**. The UI does not parse PDFs directly. Reset returns to the starting data.

The default run needs **no API key, Neo4j service, or downloaded model weights**.
It uses S2/BM25 ranking, with S1/TF-IDF and S3/skill overlap also available. Chat is
disabled and outreach uses the existing verified template. Nothing is sent
automatically. Unknown resume facts remain labeled “not documented.”

For graph-export inputs, real S4–S7 dense retrieval, optional Voyager chat, and
the mapping between UI actions and the proposal, see [UI-README.md](UI-README.md).
The current UI reads ontology facts through the existing in-memory matcher;
live Neo4j query integration is separate work. The full proposal benchmark and
human evaluation are not established by this demo.

## Run the checks

```sh
docker compose -f compose.ui.yaml run --rm --no-deps ui python -m unittest discover -s tests -v
docker compose -f compose.ui.yaml run --rm --no-deps ui python -m unittest test_ui -v
```

The tested UI implementation passed **143 original tests and 10 UI integration
tests in Docker**. Those checks use offline fixtures. Real dense models, live
Voyager responses, and live Neo4j integration were not tested. Without Docker,
use `uv run python -m unittest discover -s tests -v` and
`uv run python -m unittest test_ui -v`.

## Original extraction pipeline documentation

The sections below describe the original resume pipeline and matching/agent CLI.
Its extraction stage populates an ontology using GLiNER, O*NET, and constrained
LLM review. The Voyager settings below apply to those optional/model-based
workflows; they are not required for the default browser demo above.

### Project structure

`career_coach/data_extraction/`

- `main.py` runs the complete pipeline and saves the final JSON.
- `parser.py` extracts PDF text and segments resume sections.
- `entity_extraction.py` seeds explicit skills/degrees, enriches them with GLiNER, and resolves O*NET mappings.
- `llm_mapping.py` reviews explicit entities and unresolved taxonomy mappings.
- `ontology.py` generates Pydantic models from `data/ontologies/resume-job.ttl`.
- `ontology_population.py` populates and validates ontology instances using deterministic rules.

### Quick start

From the project root:

```powershell
uv sync
```

Set these values in `.env`:

```dotenv
VOYAGER_API_KEY=your-api-key
VOYAGER_MODEL=deepseek-v4-1-flash
```

Place resume PDFs in a `resumes/` folder, then run `main()` through its module:

```powershell
uv run python -m career_coach.data_extraction.main resumes
```

### Output

The pipeline writes only `resumes.json` next to the input folder after all resumes succeed.

- `resumes`: the list of populated resume objects.
- `cv_id`: the source PDF filename for each resume.
- `nodes`: validated ontology instances with `id`, `type`, and properties such as `hasSkill`.
- `metadata`: labels, taxonomy identifiers/version, resolution status, original titles, and source evidence.

Relationships reference node IDs; unknown or unsupported relationships remain unasserted.
All degrees listed in Education are linked, without checking completion status.
`yearsExperience` uses only each employment header's month/year range; ongoing roles use the current month.
Explicit unmapped skills retain local IDs and an `unresolved` status.
Intermediate results stay in memory. The pipeline does not write to Neo4j.

### Matching module and career agent

`career_coach/matching/` ranks job postings for a parsed resume and explains each match.
`career_coach/agent/` is a chat assistant on top of it. Both read the parser's output JSON
directly and use the same O*NET concept IDs, so a resume's `hasSkill` node and a posting's
required skill are the same node when they name the same concept.

#### Setup

```powershell
uv sync --extra matching   # sentence-transformers + faiss-cpu (first run downloads the models)
```

Without the extra, use `--embeddings none` (systems S1-S3 only). `--embeddings hashing`
swaps the Sentence-BERT models for an offline hashing encoder; it is only for checking the
pipeline, and its numbers are not S4-S7 results.

#### Job postings

Either use the postings exported by `career_coach.job_ingestion` (GLiNER + O*NET, the same
graph JSON that goes to Neo4j) by passing that folder as `--jobs`, together with the source
CSV so the rankers can read the description text:

```powershell
uv run python -m career_coach.matching.cli match --resumes resumes.json --jobs outputs/job_postings --postings-csv data/postings.csv
```

or extract skills with the matching module's own lighter rules (no GLiNER), which also keeps
preferred skills:

```powershell
# Kaggle "LinkedIn Job Postings 2023-24" postings.csv -> postings with O*NET skills
uv run python -m career_coach.matching.cli jobs --kaggle data/raw/job_postings.csv --out data/jobs.jsonl --limit 5000
```

Resume skills without an O*NET match are re-keyed by their normalized label, the same way
`job_ingestion` keys unmatched job skills, so "CSS" on a resume matches "CSS" in a posting.

Skills are found in the posting text with the parser's O*NET aliases and conservative rules
(longest match, unambiguous aliases only, ordinary English words must look like product
names). Sentences with "preferred", "nice to have", "a plus" or a "Preferred" heading mark
preferred skills; about-us and benefits sections are ignored. The TTL has `requiresSkill`
only, so preferred skills live in the job record, not in the ontology yet.

#### Matching (ablation ladder)

```powershell
uv run python -m career_coach.matching.cli match --resumes resumes/resumes.json --jobs data/jobs.jsonl --system S7 --top-k 10
```

| System | Rankers | Type |
| --- | --- | --- |
| S1 | TF-IDF cosine | classical |
| S2 | BM25 | classical |
| S3 | Jaccard over skill IDs | classical |
| S4 | MiniLM (`all-MiniLM-L6-v2`) + FAISS | deep |
| S5 | SBERT (`all-mpnet-base-v2`) + FAISS | deep |
| S6 | RRF(BM25, S5) | hybrid |
| S7 | RRF(BM25, S5, KG skill score) | hybrid + KG |

RRF uses k = 60. Dense retrieval chunks postings into 200-word windows with 10% overlap
and scores a posting by its best chunk. Posting embeddings are cached in `.cache/embeddings`
(already git-ignored), so later runs on the same postings and model skip re-encoding. The KG skill score is

    g(c, j) = (2 * sum over required m(r, c) + 1 * sum over preferred m(p, c)) / (2|R_j| + |P_j|)

with m = 1 for a skill the candidate has, 0.5 when the candidate has a skill whose
Sentence-BERT cosine similarity with it is at least tau (default 0.7; tune it on a
development split, not on test resumes), and 0 otherwise.

Each result lists matched, similar and missing skills, every ranker's rank and score,
the posting text that matched best, and years/degree requirements ("unknown from resume"
when the resume does not state them).

#### Evaluation

```powershell
uv run python -m career_coach.matching.cli pool --resumes resumes/resumes.json --jobs data/jobs.jsonl --out pool.csv
# graders fill the grade column: 0 not relevant, 1 partly relevant, 2 strong match
uv run python -m career_coach.matching.cli evaluate --resumes resumes/resumes.json --jobs data/jobs.jsonl --qrels pool.csv --baseline S2
```

`pool` merges every system's top 10 per resume and shuffles it, so graders cannot see which
system found a posting. `evaluate` reports P@5, P@10, MRR and nDCG@10, plus paired bootstrap
tests on nDCG@10 against the baseline with Holm correction. `weighted_kappa` in
`career_coach/matching/evaluation.py` computes agreement on the double-graded subset.

#### Chat agent

```powershell
uv run python -m career_coach.agent.chat --resumes resumes/resumes.json --jobs data/jobs.jsonl
```

It uses `VOYAGER_API_KEY` and `VOYAGER_MODEL` from `.env` (and `VOYAGER_API_URL` if set).
One LLM calls four tools: `search_jobs`, `explain_match`, `skill_gap` and `draft_outreach`.
`--context graph` (default) grounds answers in resume facts, posting facts and graph paths;
`--context text` is the text-only RAG baseline. Every skill named in an answer must be the
candidate's or belong to a posting retrieved in that turn, and drafts may only claim the
candidate's own skills and stated years. A failing draft is regenerated once, then replaced
by a template built from verified facts. Drafts are marked `requires_human_review` and are
never sent. Direct commands work without an LLM: `/search [keywords]`, `/explain <job_id>`,
`/gap [job_id]`, `/draft <job_id> [recruiter|referral]`.

The claim checks only recognize skills in O*NET; a skill O*NET does not list cannot be checked.

#### Tests

```powershell
uv run python -m unittest discover -s tests -p "test_*.py"
```

The matching and agent tests run offline with small synthetic fixtures in `tests/fixtures/`;
they never download models or call the LLM. `run_e2e.sh` runs the whole pipeline on your
machine (install, tests, resume parsing, matching, chatbot) and writes the results to `logs/`.
