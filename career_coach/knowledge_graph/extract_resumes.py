"""Run Kelly's resume pipeline WITHOUT the Voyager LLM review step.

Same steps as career_coach.data_extraction.main, minus llm.resolve():
parse PDFs -> GLiNER entities -> O*NET mapping -> ontology nodes.

Usage:
    uv run python -m career_coach.knowledge_graph.extract_resumes <pdf_folder>
<pdf_folder> can hold PDFs directly or one subfolder per category.
Writes <pdf_folder>.json in the same format as Kelly's main.py.
"""

import json
import sys
from pathlib import Path
from time import perf_counter

from career_coach.data_extraction.entity_extraction import EntityExtractor, TaxonomyResolver
from career_coach.data_extraction.ontology import OntologyDocument, OntologyOutput
from career_coach.data_extraction.ontology_population import OntologyPopulator
from career_coach.data_extraction.parser import ResumeParser

TAXONOMY = Path(__file__).resolve().parents[2] / "data/taxonomy/onet/31.0"


class Extractor:
    """Loads the models once; reuse it to process many folders or single uploads."""

    def __init__(self):
        self.parser = ResumeParser()
        self.extractor = EntityExtractor()
        self.resolver = TaxonomyResolver(TAXONOMY)
        self.populator = OntologyPopulator()

    def run(self, folder, verbose=False):
        """Return {"resumes": [...]} for every PDF in folder (or its subfolders)."""
        folder = Path(folder)
        folders = [folder] if any(folder.glob("*.pdf")) else sorted(d for d in folder.iterdir() if d.is_dir())
        records = [r for f in folders for r in self.parser.run(f).to_dict(orient="records")]
        documents = []
        for i, features in enumerate(records, 1):
            entities = self.extractor.extract_entities(features)
            mappings = self.resolver.resolve_entities(entities, document_id=features["cv_id"])
            populated = self.populator.populate(features, {"entity_mappings": mappings})
            documents.append(OntologyDocument(cv_id=features["cv_id"], nodes=populated.nodes))
            if verbose:
                print(f"[{i}/{len(records)}] {features['cv_id']}: {len(populated.nodes)} nodes")
        return json.loads(OntologyOutput(resumes=documents).model_dump_json())


def main():
    folder = Path(sys.argv[1])
    started = perf_counter()
    data = Extractor().run(folder, verbose=True)
    output = folder.with_suffix(".json")
    output.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Saved {len(data['resumes'])} resumes to {output} in {perf_counter() - started:.1f}s")


if __name__ == "__main__":
    main()
