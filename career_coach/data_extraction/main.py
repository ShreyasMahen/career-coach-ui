"""Parse a folder of PDF resumes and extract section-specific GLiNER entities."""

import argparse
import json
from pathlib import Path

from .parser import ResumeParser
from .entity_extraction import EntityExtractor, TaxonomyResolver


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--rules-only", action="store_true", help="Skip GLiNER and save only parsed features")
    parser.add_argument("--taxonomy", type=Path,
                        default=Path(__file__).resolve().parents[2] / "data/taxonomy/onet/31.0",
                        help="Directory containing the pinned O*NET JSONL lookups")
    args = parser.parse_args()

    parser = ResumeParser()
    results = parser.run(args.input)
    records = results.to_dict(orient="records")

    output = args.input.with_suffix(".json")
    output.write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Saved {len(records)} parsed resumes to {output}")

    if not args.rules_only:
        extractor = EntityExtractor()
        resolver = TaxonomyResolver(args.taxonomy)
        entity_records = []
        for features in records:
            entities = extractor.extract_entities(features)
            entity_records.append({
                "cv_id": features["cv_id"],
                "parsing_output": output.name,
                "entity_mappings": resolver.resolve_entities(entities, document_id=features["cv_id"]),
            })
        entity_output = output.with_suffix(".entities.json")
        entity_output.write_text(
            json.dumps(entity_records, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Saved {len(entity_records)} entity results to {entity_output}")

if __name__ == "__main__":
    main()
