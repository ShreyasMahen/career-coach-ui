"""Parse resumes, extract entities, resolve taxonomy, then run constrained LLM review."""

import argparse
import json
from pathlib import Path
from time import perf_counter

from .parser import ResumeParser
from .entity_extraction import EntityExtractor, TaxonomyResolver


def main():
    started = perf_counter()
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
        from .llm_mapping import LLMMappingResolver
        extractor = EntityExtractor()
        resolver = TaxonomyResolver(args.taxonomy)
        llm = LLMMappingResolver(resolver)
        entity_records = []
        llm_records = []
        entity_output = output.with_suffix(".entities.json")
        try:
            for features in records:
                entities = extractor.extract_entities(features)
                mappings = resolver.resolve_entities(entities, document_id=features["cv_id"])
                entity_records.append({"cv_id": features["cv_id"], "parsing_output": output.name,
                                       "entity_mappings": mappings})
                print(f"Reviewing explicit entities and mappings for {features['cv_id']}")
                reviewed = llm.resolve(features, mappings)
                audit = reviewed["llm_audit"]
                if "timing" in audit:
                    print(f"LLM review completed in {audit['timing']['total_seconds']:.2f}s ({audit['calls']} requests)")
                llm_records.append({"cv_id": features["cv_id"], "parsing_output": output.name,
                                    "entity_output": entity_output.name,
                                    **reviewed})
        finally:
            # Preserve completed taxonomy results even when an LLM request fails.
            entity_output.write_text(json.dumps(entity_records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"Saved {len(entity_records)} entity results to {entity_output}")
        llm_output = output.with_suffix(".llm.json")
        llm_output.write_text(json.dumps(llm_records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Saved LLM-reviewed mappings to {llm_output}")
    print(f"Pipeline completed in {perf_counter() - started:.2f}s")

if __name__ == "__main__":
    main()
