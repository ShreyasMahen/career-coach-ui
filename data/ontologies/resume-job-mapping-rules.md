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
- Keep unresolved concepts as local mentions in the in-memory mappings until there is
  an explicit policy for local graph concepts; never fabricate an O*NET identifier.
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
| Skill | A supported taxonomy-normalized skill/software concept. Node existence alone does not establish applicant possession. |
| Degree | A specific applicant degree record with evidence. Do not use a shared degree-level node as an applicant's individual degree. |
| DegreeLevel | A controlled degree-level concept from a curated alias table; not an arbitrary academic-major prediction. |
| JobPosting | One source posting, identified by source + posting ID; requires a separate job-posting extraction input. Resume mentions must not create postings. |

## Object-property rules

| Property (domain → range) | Required mapping rule |
| --- | --- |
| `hasExperience` (Person → Experience) | Attach only an entry belonging to the resume subject. Projects and hypothetical descriptions do not automatically count as employment. |
| `atOrganization` (Experience → Organization) | Associate an employer from the entry header/explicit employment statement. Do not attach clients, collaborators, tools/vendors, or every organization in a bullet. |
| `inRole` (Experience → Role) | Use the title belonging to that employment entry and its supported occupation mapping. References to colleagues' roles do not qualify. |
| `hasSkill` (Person → Skill) | Accept explicit skills-list membership or a clearly attributed applicant usage statement. Negated skills, job requirements, vendor mentions, and coursework titles alone do not qualify. Do not derive skills from occupations. |
| `holdsDegree` (Person → Degree) | Require evidence of an attained degree. A degree mention or past end date alone is not proof of completion. Ongoing, expected, and ambiguous degrees remain unasserted here. |
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
| `yearsExperience` (Experience → float) | Calculate only from sufficiently precise dates using a documented policy/as-of date, or an explicit duration unambiguously referring to that entry. Do not invent a missing year or sum overlapping entries into total experience. Defer calculation until date handling exists. |

Nonnegative durations and the allowed degree ranking are application rules to
validate during population; the current TTL only specifies primitive datatypes.

## Current schema gaps

The TTL does not yet represent names, original job titles, education institutions,
academic majors, attendance dates, ongoing/expected degree status, projects,
locations, source spans, taxonomy metadata or evidence. Preserve those in the
in-memory features/mappings until the schema is extended; do not invent predicates
or squeeze them into unrelated fields. In particular, `atOrganization` has domain
Experience and cannot be reused for Degree without changing the schema.

Before production population, decide on an Education/attendance record so ongoing
education can be represented without asserting `holdsDegree`. Also decide how to
represent alternative/preferred job qualifications and assertion provenance.
Entity-to-record grouping and these schema extensions precede graph ingestion;
Neo4j insertion and match scoring are outside this step.

## Initial population coverage

- `hasSkill`: canonical mappings in Skills only, with a line-level uncertainty/
  negation guard. Explicit usage in experience/projects is deferred rather than
  interpreted from a keyword occurrence. Unknown canonical mappings are reported.
- `hasExperience` and `inRole`: one name-leading title in the first five header
  lines, before detected bullets/prose, supported by an organization or date.
  Ambiguous headers are omitted; missing occupation mappings leave `inRole` unset.
- `atOrganization`: exactly one header organization, on a name-leading line with
  no prose suffix. Multiple organizations are reported, not arbitrarily selected.
  Header rules are conservative heuristics and require evaluation on real inputs.
- `degreeLevel`: explicit degree aliases for associate, bachelor, master, doctorate.
  `rank` uses the documented v1 ordering 1, 2, 3, 4 for those levels only.
- `holdsDegree`: explicit "earned/awarded/completed/received [a/the]" immediately
  before a degree in its unique refined entry, without future/uncertain wording.
  Past dates alone are insufficient. Unconfirmed degrees remain unattached nodes.
- `yearsExperience`, all JobPosting properties, and education institution/date
  relationships are deferred. Other mentions are retained in the report.

The report records source and schema hashes, the population policy version,
document/node identities, labels/taxonomy metadata, all input entity evidence,
relationship/literal assertion rules, supporting entity IDs and header spans,
and omission diagnostics. RDF type evidence is recorded per node. Population
does not prove that accepted extraction labels or mappings are semantically true.
