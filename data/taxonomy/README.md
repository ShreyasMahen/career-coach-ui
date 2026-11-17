# O*NET taxonomy for extraction normalization

This folder contains a pinned subset of the official O*NET 31.0 Database.
Source: https://www.onetcenter.org/database.html
Data dictionary: https://www.onetcenter.org/dictionary/31.0/csv/

## Download and import

From the repository root, with Python 3 (no third-party packages or API key):

```powershell
python .\src\career_coach\data-extraction\import_onet.py --download
```

The importer downloads missing CSVs from the official versioned URLs, validates
columns and references, and generates JSON Lines lookup files. Existing source
files are reused. To rebuild entirely offline:

```powershell
python .\src\career_coach\data-extraction\import_onet.py
```

`--version 31.0` makes the default release explicit. Future releases can be
imported into separate directories if they retain the same source schemas;
review changes before updating a production normalizer.

## Files

All data lives under `onet/31.0/`:

| File | Purpose |
| --- | --- |
| `occupations.jsonl` | Official O*NET-SOC codes, titles, descriptions, job-title aliases and matching keys |
| `skills.jsonl` | Official element IDs, labels and definitions for essential skills, transferable skills and software categories; distinguish these using `kind` |
| `software_examples.jsonl` | Software names, matching keys, category IDs and associated occupation codes; example IDs beginning `local:` are project-generated |
| `manifest.json` | Source URLs, release, row counts, SHA-256 checksums, attribution and transformation notes |
| `raw/occupation_data.csv` | Official occupation identifiers, labels and definitions |
| `raw/job_titles.csv` | Job-title and short-title aliases mapped to occupations |
| `raw/essential_skills.csv`, `raw/transferable_skills.csv` | Occupation-to-skill ratings, including scale, suppression and relevance fields |
| `raw/software_skills.csv` | Occupation-to-software examples and category IDs, including hot/in-demand flags |
| `raw/content_model_reference.csv` | Full content-model element hierarchy, labels and descriptions |
| `raw/scales_reference.csv` | Scale definitions and numeric ranges for interpreting ratings |

## Using the lookups

```python
import json
from collections import defaultdict
from pathlib import Path
from career_coach.data_extraction.import_onet import match_key

root = Path("data/taxonomy/onet/31.0")
occupation_index = defaultdict(set)
with (root / "occupations.jsonl").open(encoding="utf-8") as stream:
    for line in stream:
        occupation = json.loads(line)
        for key in occupation["match_keys"]:
            occupation_index[key].add(occupation["id"])

candidates = sorted(occupation_index.get(match_key("Chief Executives"), set()))
print(candidates)  # ['11-1011.00']
```

Extract the original text first, then retrieve candidate occupations or skills.
Use case folding, Unicode normalization and whitespace normalization through
`match_key`; preserve punctuation so C++, C#, C and .NET remain distinguishable.
Store the original mention, namespace, canonical ID, source version, matching
method and confidence with each normalized result. IDs are strings.

An alias can map to several occupations: retain all candidates and disambiguate
using the surrounding job description. A unique text match is still a candidate,
not proof of semantic equivalence. Use definitions and context for semantic
matching; leave unsupported mentions unresolved. The importer does not invent
skill synonyms or equate product abbreviations automatically.

Software examples have category IDs rather than official individual product
IDs. Their local IDs hash the normalized example name and remain separate from
official O*NET element IDs. The same name can belong to several categories.
Occupation-to-skill ratings and occupation-to-software links provide contextual
evidence; they do not establish that a person possesses a skill. When using
ratings, join `Scale ID` to `scales_reference.csv` and inspect suppression and
relevance flags in the raw files.

The importer builds file-based lookups consumed by the
[data extraction pipeline](../../src/career_coach/data-extraction/README.md).
The full RDF graph is also available on the official download page if a
triplestore is needed later. With the project installed through uv, the same
importer is available as `uv run career-coach-import-onet`.

## Attribution

Includes information from the O*NET 31.0 Database by the U.S. Department of Labor,
Employment and Training Administration (USDOL/ETA), used under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
O*NET® is a trademark of USDOL/ETA. This project selected and grouped source
records and added matching keys and local software-example IDs. USDOL/ETA has
not approved, endorsed, or tested these modifications.

See https://www.onetcenter.org/license_db.html for the source license and
`onet/31.0/manifest.json` for the exact source files and transformations.
