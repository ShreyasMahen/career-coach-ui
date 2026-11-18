# Resume/job ontology mapping rules

The authoritative schema is `resume-job.ttl`. `career_coach/data_extraction/ontology.py`
loads it with RDFLib and generates Pydantic models for its explicit declarations.
It does not populate records, infer relationships, export RDF, or access Neo4j.
`ontology_population.py` now applies the initial conservative subset below after
LLM review. `main` serializes only the final Pydantic ontology object as JSON;
graphs and evidence/diagnostics reports remain in memory.
Rules marked deferred remain unimplemented and produce no assertions.

## Python schema usage

```python
from career_coach.data_extraction.ontology import load_ontology

schema = load_ontology()
Person = schema.models["Person"]
Skill = schema.models["Skill"]

skill = Skill(id="urn:skill:python")
person = Person(id="urn:resume:example:person", has_skill=[skill.id])
schema.validate_instances([person, skill])
print(person.model_dump(by_alias=True))  # hasSkill, hasExperience, holdsDegree
print(Person.model_json_schema())
```

The example shows structure only; it is not an assertion extracted from a resume.
Every property is a list: the TTL has no required fields, functional properties,
or cardinality restrictions. An empty list means no assertion. Fields use strict
Python types, reject extra fields and non-finite floats, and preserve TTL aliases.
IDs are absolute IRIs. References are IRIs rather than nested duplicate objects;
`validate_instances` requires a complete set of referenced nodes and checks types
and unique IDs. It does not verify textual evidence or perform OWL reasoning.
The loader supports the current named classes, explicit single domains/ranges,
and integer, float, string and boolean datatypes. More complex OWL constraints or
inheritance require an explicit implementation; they are not inferred by Pydantic.

## Identity and evidence rules

- Use the final LLM-reviewed mappings together with the original `section_texts`
  and refined blocks. Require matching source/document provenance and source spans
  before accepting an assertion. A quoted span establishes traceability, not truth.
- Process `resolved`, `unresolved`, and `not_applicable`. The latter includes useful
  person, university, organization, degree and date mentions outside O*NET coverage.
- A taxonomy mapping normalizes a concept; it does not establish possession,
  employment, degree completion, employer identity or a job requirement.
- Build deterministic document/revision-scoped IDs for the Person, Experience and
  Degree records. A filename alone is not a globally unique applicant ID. Link to
  a stable application-owned person ID later rather than merging people by name.
- Share Skill/Role concepts by taxonomy namespace + ID + version. Labels alone
  must not merge concepts. Preserve the original label and evidence separately.
  Organization names alone are also insufficient for cross-document identity.
- Explicit unmapped skills in Skills become document-scoped local Skill nodes with
  `metadata.resolution_status=unresolved`, their source label/evidence, and no taxonomy
  reference. Canonical concepts have `resolution_status=resolved`. Other unresolved
  concept types remain in memory; never fabricate an O*NET identifier.
- Resolve block membership from source offsets and boundaries. `block_index` is
  scoped to a section/category and is supporting metadata, not relationship proof.
- Multiple plausible associations must produce a diagnostic, not an arbitrary
  first match or a Cartesian product of entities. Missing values stay unknown.
- Retain assertion-level provenance in a separate evidence manifest until the
  ontology defines how to represent it. The current TTL has no provenance terms.

## Class creation rules

| Class | Creation rule |
| --- | --- |
| Person | One resume subject per document revision, even if name extraction fails. Do not turn people mentioned elsewhere into additional resume subjects. |
| Experience | One supported employment entry from a refined experience block. An ambiguous/combined block needs review; not every role or organization mention creates a job. |
| Organization | An explicitly identified organization with supporting context. Creation alone does not make it an employer or posting company. |
| Role | A supported occupation concept, preferably taxonomy-normalized; preserve the original job title outside the current TTL. |
| Skill | A supported taxonomy-normalized concept, or an explicit skill-list item with a local ID and unresolved metadata. Node existence alone does not establish applicant possession. |
| Degree | A specific applicant degree record with evidence. Do not use a shared degree-level node as an applicant's individual degree. |
| DegreeLevel | A controlled degree-level concept from a curated alias table; not an arbitrary academic-major prediction. |
| JobPosting | One source posting, identified by source + posting ID; requires a separate job-posting extraction input. Resume mentions must not create postings. |

## Object-property rules

| Property (domain → range) | Required mapping rule |
| --- | --- |
| `hasExperience` (Person → Experience) | Attach only an entry belonging to the resume subject. Projects and hypothetical descriptions do not automatically count as employment. |
| `atOrganization` (Experience → Organization) | Associate organizations explicitly occupying an employer/affiliation header field. Preserve separate affiliations and combine only overlapping or whitespace-adjacent fragments of one printed name. Do not infer a primary employer or hierarchy, or attach clients, vendors and narrative mentions. |
| `inRole` (Experience → Role) | Use the title belonging to that employment entry and its supported occupation mapping. References to colleagues' roles do not qualify. |
| `hasSkill` (Person → Skill) | Accept explicit skills-list membership or a clearly attributed applicant usage statement. Negated skills, job requirements, vendor mentions, and coursework titles alone do not qualify. Do not derive skills from occupations. |
| `holdsDegree` (Person → Degree) | Link every explicit degree entity in the resume's education section to the resume subject. Completion wording, dates, status, and the number of degrees in a block do not restrict the link. This means a listed qualification, not confirmed attainment. |
| `degreeLevel` (Degree → DegreeLevel) | Normalize explicit degree text with a curated abbreviation/alias table. Do not derive level from dates, university name, or academic major. |
| `forRole` (JobPosting → Role) | Map the advertised role from posting title/context, not roles mentioned as collaborators or prerequisites. Deferred until posting extraction exists. |
| `minDegreeLevel` (JobPosting → DegreeLevel) | Use explicit minimum education requirements. Preferred education, equivalent experience and alternative qualifications must not silently become hard requirements. Deferred. |
| `postedBy` (JobPosting → Organization) | Require explicit posting-company attribution; distinguish recruiting agency, employer, and client when unclear. Deferred. |
| `requiresSkill` (JobPosting → Skill) | Require an explicit skill requirement, separating required from preferred and negated mentions. General company technology descriptions do not establish a requirement. Deferred. |

## Datatype-property rules

| Property | Required mapping rule |
| --- | --- |
| `rank` (DegreeLevel → integer) | Assign from a curated, versioned degree-level ordering, never from GLiNER confidence or an LLM guess. Not every credential is comparable; leave unsupported levels unranked. |
| `minExperience` (JobPosting → float) | Normalize explicit minimum duration to years. Do not sum alternatives or confuse preferred experience with a minimum. Per-skill/role requirements need a schema extension. Deferred. |
| `yearsExperience` (Experience → float) | Calculate calendar-month difference divided by 12, rounded to six decimals, from one unambiguous range in that employment entry's header. Education and other entries never supply dates. Present uses a recorded reference month. Missing precision, reversed/future ranges and ambiguity leave the value empty. |

Nonnegative durations and the allowed degree ranking are application rules to
validate during population; the current TTL only specifies primitive datatypes.

## Current schema gaps

The TTL does not yet represent names, original job titles, education institutions,
academic majors, attendance dates, ongoing/expected degree status, projects,
locations, source spans, taxonomy metadata or evidence. Preserve those in the
in-memory features/mappings until the schema is extended; do not invent predicates
or squeeze them into unrelated fields. In particular, `atOrganization` has domain
Experience and cannot be reused for Degree without changing the schema.

`holdsDegree` intentionally represents all listed qualifications without completion
tracking. A separate Education/attendance model can be added later if institution
and attendance details are needed. Also decide how to represent alternative/preferred
job qualifications and assertion provenance.
Entity-to-record grouping and these schema extensions precede graph ingestion;
Neo4j insertion and match scoring are outside this step.

## Initial population coverage

- `hasSkill`: explicit skill-list entities in Skills only, with a line-level uncertainty/
  negation guard. Explicit usage in experience/projects is deferred rather than
  interpreted from a keyword occurrence. Unmapped skills are retained as local nodes.
- `hasExperience` and `inRole`: one title occupying a header slot in the first five
  header lines, supported by an organization or date. Employer-first and title-first
  columns and labeled positions are supported. After the title, only fully
  entity-covered header lines (dates, locations, organization names, or another
  title indicating ambiguity) extend the header. Unbulleted achievement prose
  stops it; organization mentions inside that prose cannot become employers.
  Ambiguous headers are omitted; missing occupation mappings leave `inRole` unset.
- `atOrganization`: parse source fields separated by newlines, pipes, semicolons or
  tabs. A single complete employer field can contain multiple comma/parenthesis-
  separated organization affiliations; preserve them individually without choosing
  a primary employer or asserting parent/subunit relationships. Overlapping or
  whitespace-adjacent spans in that field form one exact printed organization name.
  Dates, locations, projects and position spans provide field context but are never
  promoted to organizations. Explicit Employer/Company/Organization labels take
  precedence over other fields. Client/vendor/agency and technical fields are
  excluded. Alternatives ("or", "/"), unqualified agency/client contexts and
  competing unlabeled employer fields remain unresolved. These are structural
  heuristics relying on source segmentation and entity classifications; they are
  not a universal guarantee of semantic correctness for unseen layouts.
- `degreeLevel`: explicit degree aliases for associate, bachelor, master, doctorate.
  `rank` uses the documented v1 ordering 1, 2, 3, 4 for those levels only.
- `holdsDegree`: every source-validated degree entity in Education is linked to the
  resume subject, including expected or ongoing qualifications and multiple degrees
  in a single entry. Refined blocks enrich provenance but are not required. Unknown
  degree levels do not prevent a link. No completion detection is performed.
- `yearsExperience`: only the current employment header is inspected. Named months
  (including abbreviations), MM/YYYY and YYYY-MM ranges are supported. One explicit
  year applies to both named months in a shared-year range such as June–August 2025.
  Present/Current/Now/Ongoing resolve to the run's reference month. September–Present
  has no start year and remains unknown; education dates never fill it. Bare-year
  ranges lack month precision. Multiple, reversed or future ranges remain unknown.
  Same-month ranges produce zero; no inclusive-month increment is added. Calculate
  each employment separately without summing overlapping jobs. `metadata.duration`
  preserves normalized endpoints, month count, exact source span, method and
  reference month. The default reference is the local run month; Python callers
  can supply `OntologyPopulator(as_of=date(...))` for reproducibility.
- All JobPosting properties and education institution/date relationships remain
  deferred. Other mentions are retained in the report.

The report records source and schema hashes, the population policy version,
document/node identities, labels/taxonomy metadata, all input entity evidence,
relationship/literal assertion rules, supporting entity IDs and header spans,
and omission diagnostics. RDF type evidence is recorded per node. Population
does not prove that accepted extraction labels or mappings are semantically true.

The final JSON also preserves typed `metadata` on each node: its label, canonical
taxonomy namespace/ID/version, original job title where applicable, and supporting
entity spans with source document, original text and extraction label. Metadata is
a transport envelope, not an additional TTL predicate. It stays in the same final
JSON file; complete diagnostics and assertion reports remain in memory.

## Explicit extraction before NER

Seed exact spans from delimited skills lists and degree abbreviations in refined
education headings before GLiNER. Split only the known composites C/C++ and
HTML/CSS, retaining actual component spans; preserve other slashes and omit URLs.
Compatible GLiNER predictions refine generic skill labels without duplicating
mentions. Conflicting labels are retained on the entity for existing LLM review;
even canonical matches are eligible when they carry a documented conflict.
Ordinary resolved entities remain read-only. Empty NER output cannot delete seeds.
Final source evidence preserves extraction sources and any remaining conflicts.
