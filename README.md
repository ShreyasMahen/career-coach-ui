# career-coach

## Standalone rule parser and GLiNER

```powershell
uv run python -m career_coach.data_extraction.main data
uv run python -m career_coach.data_extraction.main data --rules-only
```

The first command writes `data.json` with parsed features, `data.entities.json`
with baseline GLiNER/O*NET mappings, and `data.llm.json` with LLM-reviewed mappings.
Each entity record includes `cv_id` and `parsing_output` to locate the source
features. Parsed features are saved before inference and are not mutated by it.
The second command skips inference and writes only parsing output.
One model instance serves all resumes and
section-specific calls. Experience is heuristically separated using date-range
headers; undated entries may remain combined and require review. Long blocks use
overlapping model-token windows with duplicate predictions reconciled by score.

`section_texts` preserves case, punctuation and line boundaries for inference.
Each entity's `source_field` identifies the section string addressed by its
zero-based, exclusive-end offsets. `experience_refined` contains job blocks;
`education_refined` retains courses and awards for later LLM processing, excluded
from GLiNER. Entity mentions are candidates, not verified employment relationships.

`parser.py` handles segmentation/refinement and has no GLiNER dependency.
`entity_extraction.py` contains `EntityExtractor` (inference, windows, evidence
validation) and `TaxonomyResolver` (local lookup resolution). `main.py` runs the
stages in order, reusing one model and one taxonomy index across resumes.
Education refinement now uses the corresponding original `section_texts` string
so its offsets remain valid when passed between stages.

Each resume's `entity_mappings` in `data.entities.json` contains:

| Group | Meaning |
| --- | --- |
| `resolved` | Exactly one matching skill/software or occupation concept |
| `unresolved` | Eligible mention with no match, or multiple competing candidates |
| `not_applicable` | Person, date, organization, university, or another type outside these O*NET lookups |

Mappings preserve the original entity, stable document-scoped `entity_id`,
canonical ID/namespace/label/version, method, candidates, and unresolved reason.
Resolution first uses case/whitespace/Unicode-normalized exact labels and aliases,
then a small reviewable `SKILL_ALIASES` table (e.g. Java → Oracle Java). It does not
remove meaningful punctuation: C, C++, C#, and .NET remain distinct. Ambiguous
matches are never automatically selected. `--taxonomy PATH` selects another
directory containing the pinned manifest and three JSONL lookup files.

These baseline mappings are lexical matches of emitted entity mentions, not verified
facts. The deterministic pass does not correct labels or recover missing entities,
and no ontology writes occur. Unresolved entries retain evidence for the automatic
LLM resolution stage, which runs automatically after taxonomy resolution. Courses
and awards remain in features.

## Constrained LLM mapping review

Set `VOYAGER_API_KEY` and `VOYAGER_MODEL=deepseek-v4-1-flash` in `.env`
(see `.env.example`). The model is read only from `VOYAGER_MODEL`; there is no
model CLI flag or fallback model. The API endpoint is fixed to
`https://openai.rc.asu.edu/v1`. Client creation and requests are lazy: imports and
rules-only runs do not contact Voyager. Normal `main` runs invoke the LLM
immediately after taxonomy resolution for each resume.

Run the entire pipeline:

```powershell
uv run python -m career_coach.data_extraction.main data
```

`llm_mapping.py` is an imported pipeline component, with no standalone entry point.
LLM settings are constants in that file: 64 calls per resume, 3 parallel source
reviews, 3,000-character chunks, and a 60-second request timeout. There are no
LLM tuning flags in `main.py`. Taxonomy selection batches up to 8 queries per call.

This writes `data.llm.json`; `data.json` and `data.entities.json` remain the parsing
and deterministic mapping baselines. If LLM review fails, parsing results and taxonomy
results for resumes processed so far are preserved, and no partial LLM output is
written. `--rules-only` stops before entity extraction and taxonomy, rather than
skipping LLM review after taxonomy.

Review is limited to three tasks:

1. Recover missed **explicit** entity mentions from bounded source blocks.
2. Confirm or reclassify existing unresolved/not-applicable entities at the same
   evidence span. Already resolved mappings are read-only context.
3. Retrieve local O*NET candidates for remaining taxonomy gaps and ask the model
   to select a supplied candidate ID or abstain. Retrieval scores never resolve
   mappings automatically, and the model cannot introduce taxonomy IDs.

Coursework and awards blocks are excluded from LLM review; their features remain
available for later work. No employment relationships, graph triples, proficiency
or skills inferred from courses are accepted by this stage's schema.

Voyager currently advertises `supports_response_schema=false` for the selected
DeepSeek model. The implementation therefore uses JSON-object mode, supplies a
closed JSON schema in each request, and **validates locally using strict Pydantic
models**. This is not server-side schema-constrained decoding. No fallback to
unvalidated prose is allowed. Refusals, incomplete/truncated replies and malformed
responses fail the review without committing partial LLM output. Individual
ungrounded or out-of-scope proposals are rejected and recorded in the audit.

Python locates the exact quoted text and computes source offsets; repeated quotes
require an occurrence index or a known eligible entity ID. Corrected/new entities
carry LLM provenance; changed classifications clear the old score rather than
reusing a GLiNER confidence value for a different label. The audit includes original
entities, model/prompt version, source and baseline hashes, rejected proposals,
abstentions and call count. Valid quotes establish traceability, not semantic truth;
inspect and evaluate accepted classifications and taxonomy selections before graph
ingestion. A confirmed university/person/date appropriately stays `not_applicable`
to these O*NET lookups, with `llm_review.action=confirm`, rather than receiving an
invented taxonomy mapping.

The live integration was smoke-tested with synthetic text only: B.S. classification
repair, missing M.S. recovery, and occupation candidate selection. This is not a
measurement of extraction quality on the user's datasets.

Focused validation for this active pipeline:

```powershell
uv run python -m unittest discover -s tests -p test_resume_parser.py -v
uv run python -m unittest discover -s tests -p test_entity_resolution.py -v
uv run python -m unittest discover -s tests -p test_extraction_cli.py -v
uv run python -m unittest discover -s tests -p test_llm_mapping.py -v
```

Minimal resume extraction for later resume/job matching. No database or web service
is required yet. The legacy DataFrame parser remains available; the new API is
`career_coach.data_extraction.HybridPipeline` (underscores make it importable normally).

## Pipeline

1. Extract PDF text with PyMuPDF, retaining page ranges, original case, Unicode,
   and punctuation. Text/CSV resume fields can call `extract_text` directly.
2. Locate rule-based sections, explicit skill lists, years, and exact O*NET job titles.
3. Optionally run a local spaCy NER model to add person, organization and date spans.
4. Optionally call an injected LLM adapter, requiring a closed JSON schema, exact
   quotations, offsets, typed references, and evidence for employment/education links.
5. Normalize skill and occupation mentions against the local O*NET 31.0 JSONL files.
   Multiple exact matches stay ambiguous; missing matches stay unmapped. No fuzzy
   guesses or automatically invented aliases (C, C++, C#, and .NET stay distinct).
6. Write JSON with all candidates and provenance, and a Turtle graph using
   `data/ontologies/resume.ttl`. Each asserted extracted fact has an RDF statement
   containing its source, quote, character range, extraction method, and model ID.

Offsets are zero-based Python Unicode character indices with exclusive ends into
the exact `source.text` saved in JSON, **not** PDF byte offsets. PDF results also
include page ranges and file/text SHA-256 hashes. Treat JSON outputs as resume data:
they contain the original text.

## Run

From the project root, for rules and taxonomy only:

```powershell
uv sync
uv run python -m career_coach.data_extraction.main resume.pdf --output outputs/resume
```

To enable local NER, install the optional dependencies and an English model:

```powershell
uv sync --extra ner
uv run --extra ner python -m spacy download en_core_web_sm
uv run --extra ner python -m career_coach.data_extraction.main resume.pdf --spacy-model en_core_web_sm --output outputs/resume
```

The model download needs internet; inference runs locally. A general spaCy English
model recognizes people and organizations; it is not a resume-trained skill or
employment relationship model. Custom local models may additionally emit `SKILL`
and `JOB_TITLE`. The output records exactly which stages ran; omitted models do
not silently masquerade as completed stages.

## LLM adapter contract

No provider is selected and no resume is transmitted by this implementation.
Supply `llm=request_to_response_callable` and `llm_model="provider/model/version"`
when constructing `HybridPipeline`. The callable receives instructions, raw text,
sections, existing candidates, and `schema` (also exported as `LLM_SCHEMA` from
`pipeline.py`). Return a dict or JSON string with exactly `entities`, `employments`,
and `educations` arrays. An empty result is:

```json
{"entities": [], "employments": [], "educations": []}
```

Entities require `kind`, `start`, `end`, and exact `quote`. Relationship fields are
zero-based indices into the response's own entity array, or null for unknown values.
Every record also requires enclosing `evidence: {start, end, quote}` within its
experience/education section. See the schema and test fixtures for full examples.
Provider adapters should request schema-constrained output and enforce their own
timeouts/token budgets. Validation rejects fabricated quotes, invalid references,
wrong field types, reversed years and unexpected keys; failures raise `ValueError`.
Quoted evidence proves traceability, not semantic truth: a model can still pair
the wrong title and employer within the same evidence span. Evaluate these links
on labeled examples before accepting production graph writes.

`to_graph(result)` in `rdf.py` exports person skills from the skills section,
unambiguous header names, and validated employment/education records. Organization
NER alone does not establish an employer or university; rules/NER-only runs leave
those associations empty. Unknown properties are omitted. The exporter never
infers a company's technology use from an applicant's skills. Education has its
own year properties so it is not accidentally inferred to be Employment by an
RDFS domain constraint. Normalization links use local concept URNs and preserve
O*NET IDs/version; they do not claim invented official O*NET URIs.

## Validation and next data step

```powershell
uv run python -m unittest discover -s tests -v
```

Tests cover evidence integrity, Unicode/punctuation, ambiguity, stage merging,
model-output rejection, education mapping and Turtle round trips. They use
deterministic model doubles, not a downloaded statistical model or cloud API.

`data/datasets.json` currently contains dataset locations/URLs, not the downloaded
resume/job examples. Provide local dataset paths and a small manually annotated
holdout with entity spans, employment/education links, and expected O*NET IDs.
Measure span precision/recall/F1, relationship accuracy, normalization accuracy and
abstention rate separately. A provider, data samples and labels are needed before
extraction quality can be measured. Job-posting extraction, OCR for image-only
PDFs, Neo4j loading, identity resolution across resumes and matching/ranking are
subsequent work. The generated graph is RDF, not an automatic Neo4j import.
