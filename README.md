# career-coach

## Standalone rule parser and GLiNER

```powershell
uv run python -m career_coach.data-extraction.main data
uv run python -m career_coach.data-extraction.main data --rules-only
```

The first command writes `data.json` with parsed features and a separate
`data.entities.json` with GLiNER predictions and grouped O*NET entity mappings.
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

These are lexical mappings of emitted entity mentions, not verified facts or
corrections to GLiNER classifications. Missing entities are not reconstructed,
and no LLM calls or ontology writes occur. Unresolved entries retain evidence
for the later LLM resolution stage. Courses and awards remain in features.

Focused validation for this active pipeline:

```powershell
uv run python -m unittest discover -s tests -p test_resume_parser.py -v
uv run python -m unittest discover -s tests -p test_entity_resolution.py -v
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
