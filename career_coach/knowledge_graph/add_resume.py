"""Add ONE resume to the knowledge graph: Kelly's pipeline (no LLM) -> Neo4j.

Command line:
    NEO4J_PASSWORD=... uv run --with neo4j python -m career_coach.knowledge_graph.add_resume <resume.pdf>

From Python (e.g. the agent's upload handler); models load once, reuse for each upload:
    from career_coach.knowledge_graph.add_resume import ResumeAdder
    adder = ResumeAdder()
    person_id = adder.add("uploaded.pdf")
"""

import shutil
import sys
import tempfile
from pathlib import Path

from career_coach.knowledge_graph.extract_resumes import Extractor
from career_coach.knowledge_graph.load_neo4j import connect, load, resume_graphs, setup


class ResumeAdder:
    def __init__(self):
        self.extractor = Extractor()
        self.driver = connect()
        with self.driver.session() as session:
            setup(session)

    def add(self, pdf_path):
        """Extract one PDF, MERGE it into Neo4j and return the new Person node id."""
        with tempfile.TemporaryDirectory() as folder:  # Kelly's parser reads a folder of PDFs
            shutil.copy(pdf_path, Path(folder) / Path(pdf_path).name)
            data = self.extractor.run(folder)
        graph = next(resume_graphs(data))
        with self.driver.session() as session:
            load(session, graph)
        return next(n["id"] for n in graph["nodes"] if n["labels"] == ["Person"])

    def close(self):
        self.driver.close()


def main():
    adder = ResumeAdder()
    try:
        print(f"Added {sys.argv[1]} as {adder.add(sys.argv[1])}")
    finally:
        adder.close()


if __name__ == "__main__":
    main()
