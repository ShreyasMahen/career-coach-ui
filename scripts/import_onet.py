"""Download pinned O*NET CSVs and build entity-normalization lookups (stdlib only)."""

import argparse
import csv
import hashlib
import json
import re
import unicodedata
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "data" / "taxonomy" / "onet"
FILES = {
    "occupation_data": {"O*NET-SOC Code", "Title", "Description"},
    "job_titles": {"O*NET-SOC Code", "Job Title", "Short Title"},
    "essential_skills": {"O*NET-SOC Code", "Element ID", "Element Name", "Scale ID", "Data Value"},
    "transferable_skills": {"O*NET-SOC Code", "Element ID", "Element Name", "Scale ID", "Data Value"},
    "software_skills": {"O*NET-SOC Code", "Workplace Example", "Element ID", "Hot Technology", "In Demand"},
    "content_model_reference": {"Element ID", "Element Name", "Description"},
    "scales_reference": {"Scale ID", "Minimum", "Maximum"},
}


def match_key(value):
    # Preserve punctuation: C, C++, C#, .NET, and R must stay distinct.
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def read_csv(path, required):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"Unexpected CSV columns in {path}")
        rows = list(reader)
    if not rows:
        raise ValueError(f"Empty source file: {path}")
    return rows


def write_jsonl(path, records):
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="31.0", help="Pinned database release (default: 31.0)")
    parser.add_argument("--download", action="store_true", help="Download missing source CSVs")
    args = parser.parse_args()
    if not re.fullmatch(r"\d+\.\d+", args.version):
        parser.error("--version must look like 31.0")
    release = ROOT / args.version
    raw = release / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    base = f"https://www.onetcenter.org/dl_files/database/db_{args.version.replace('.', '_')}_csv/"
    tables = {}
    sources = []
    for name, required in FILES.items():
        path = raw / f"{name}.csv"
        url = base + path.name
        if not path.exists():
            if not args.download:
                parser.error(f"Missing {path}; run again with --download")
            print(f"Downloading {url}", flush=True)
            with urllib.request.urlopen(url, timeout=90) as response:
                payload = response.read()
            temporary = path.with_suffix(".csv.part")
            temporary.write_bytes(payload)
            read_csv(temporary, required)
            temporary.replace(path)
        tables[name] = read_csv(path, required)
        sources.append({"file": f"raw/{path.name}", "url": url,
                        "rows": len(tables[name]), "bytes": path.stat().st_size,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})

    occupations = {}
    for row in tables["occupation_data"]:
        code = row["O*NET-SOC Code"]
        if code in occupations:
            raise ValueError(f"Duplicate occupation: {code}")
        occupations[code] = {
            "id": code, "namespace": "onet:occupation", "label": row["Title"],
            "description": row["Description"], "aliases": {row["Title"]},
            "source_version": args.version,
        }
    for row in tables["job_titles"]:
        occupation = occupations[row["O*NET-SOC Code"]]
        occupation["aliases"].update(row[key] for key in ("Job Title", "Short Title") if row[key])
    for occupation in occupations.values():
        occupation["aliases"] = sorted(occupation["aliases"])
        occupation["match_keys"] = sorted({match_key(alias) for alias in occupation["aliases"]})

    model = {row["Element ID"]: row for row in tables["content_model_reference"]}
    skills = {}
    for table, kind in (("essential_skills", "essential"),
                        ("transferable_skills", "transferable"),
                        ("software_skills", "software_category")):
        for row in tables[table]:
            # Validate joins while preserving the source's occupation/skill relationships.
            if row["O*NET-SOC Code"] not in occupations:
                raise ValueError(f"Unknown occupation in {table}: {row}")
            element = model[row["Element ID"]]
            skills[element["Element ID"]] = {
                "id": element["Element ID"], "namespace": "onet:element",
                "label": element["Element Name"], "description": element["Description"],
                "kind": kind, "match_key": match_key(element["Element Name"]),
                "source_version": args.version,
            }

    software = {}
    for row in tables["software_skills"]:
        label = row["Workplace Example"]
        key = match_key(label)
        entry = software.setdefault(key, {
            "id": "local:onet-software:" + hashlib.sha256(key.encode("utf-8")).hexdigest(),
            "namespace": "local:onet-software", "label": label, "match_key": key,
            "aliases": set(), "category_ids": set(), "occupation_ids": set(),
            "source_version": args.version,
        })
        entry["aliases"].add(label)
        entry["category_ids"].add(row["Element ID"])
        entry["occupation_ids"].add(row["O*NET-SOC Code"])
    for entry in software.values():
        for field in ("aliases", "category_ids", "occupation_ids"):
            entry[field] = sorted(entry[field])

    outputs = {
        "occupations.jsonl": sorted(occupations.values(), key=lambda item: item["id"]),
        "skills.jsonl": sorted(skills.values(), key=lambda item: item["id"]),
        "software_examples.jsonl": sorted(software.values(), key=lambda item: item["match_key"]),
    }
    for name, records in outputs.items():
        write_jsonl(release / name, records)
    manifest = {
        "source": "O*NET Database", "version": args.version,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_page": "https://www.onetcenter.org/database.html",
        "license": "https://creativecommons.org/licenses/by/4.0/",
        "license_details": "https://www.onetcenter.org/license_db.html",
        "attribution": f"O*NET {args.version} Database, U.S. Department of Labor, Employment and Training Administration (USDOL/ETA). Used under CC BY 4.0. O*NET is a trademark of USDOL/ETA.",
        "modifications": "Selected source tables; grouped labels and aliases; added match keys and local software-example IDs. USDOL/ETA has not approved, endorsed, or tested these modifications.",
        "sources": sources,
        "outputs": {name: {"rows": len(records),
                            "sha256": hashlib.sha256((release / name).read_bytes()).hexdigest()}
                    for name, records in outputs.items()},
    }
    (release / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"release_directory": str(release),
                      "counts": {name: len(records) for name, records in outputs.items()}}, indent=2))


if __name__ == "__main__":
    main()
