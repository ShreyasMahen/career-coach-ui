"""Extract one PDF or UTF-8 text resume; models are opt-in."""

import argparse
import json
from pathlib import Path

from .pipeline import HybridPipeline, SpacyNER
from .rdf import to_graph


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--taxonomy", type=Path, default=Path("data/taxonomy/onet/31.0"))
    parser.add_argument("--spacy-model", help="Installed spaCy model name/path; enables local NER")
    parser.add_argument("--output", type=Path, required=True, help="Output prefix for .json and .ttl")
    args = parser.parse_args()
    pipeline = HybridPipeline(args.taxonomy, ner=SpacyNER(args.spacy_model) if args.spacy_model else None)
    result = pipeline.extract_pdf(args.input) if args.input.suffix.lower() == ".pdf" else pipeline.extract_text(args.input.read_text(encoding="utf-8"), source_id=args.input.name)
    graph = to_graph(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    graph.serialize(destination=args.output.with_suffix(".ttl"), format="turtle")
    print(f"Extracted {len(result['entities'])} entities; wrote JSON and Turtle to {args.output}")


if __name__ == "__main__":
    main()
