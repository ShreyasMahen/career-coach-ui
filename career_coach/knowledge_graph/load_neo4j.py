"""Load resume and job graphs into Neo4j.

Usage:
    uv run --with neo4j python -m career_coach.knowledge_graph.load_neo4j <resumes.json> [job_folder]

<resumes.json>  output of extract_resumes.py (or Kelly's data_extraction.main)
[job_folder]    folder of per-job JSON files from Kelly's job_ingestion
                (default: data/job_postings_sample)

Connection: NEO4J_URI (default bolt://localhost:7687), NEO4J_USER (default neo4j),
NEO4J_PASSWORD. Re-running is safe: nodes and edges are MERGEd by id.
"""

import json
import os
import sys
from collections import defaultdict
from pathlib import Path

from neo4j import GraphDatabase

from career_coach.data_extraction.ontology import load_ontology
from career_coach.job_ingestion.parser import ontology_graph

ROOT = Path(__file__).resolve().parents[2]


def connect():
    return GraphDatabase.driver(os.getenv("NEO4J_URI", "bolt://localhost:7687"),
                                auth=(os.getenv("NEO4J_USER", "neo4j"), os.environ["NEO4J_PASSWORD"]))


def resume_graphs(data):
    """Convert each resume in {"resumes": [...]} to Kelly's flat {nodes, relationships} format."""
    schema = load_ontology()
    names = {iri: name for name, iri in schema.classes.items()}
    for resume in data["resumes"]:
        nodes = [schema.models[names[n["type"]]].model_validate({k: v for k, v in n.items() if k != "type"})
                 for n in resume["nodes"]]
        graph = ontology_graph(nodes, schema)
        for node in graph["nodes"]:
            if node["labels"] == ["Person"]:
                node["properties"]["cv_id"] = resume["cv_id"]  # keep the source PDF name
        yield graph


def job_graphs(folder):
    for path in sorted(Path(folder).glob("[!.]*.json")):
        yield json.loads(path.read_text(encoding="utf-8"))


def load(session, graph):
    by_label, by_type = defaultdict(list), defaultdict(list)
    for node in graph["nodes"]:
        by_label[node["labels"][0]].append({"id": node["id"], "props": node["properties"]})
    for rel in graph["relationships"]:
        by_type[rel["type"]].append(rel)
    for label, rows in by_label.items():
        session.run(f"UNWIND $rows AS r MERGE (n:Entity {{id: r.id}}) SET n:{label}, n += r.props", rows=rows)
    for kind, rows in by_type.items():
        session.run(f"UNWIND $rows AS r MATCH (a:Entity {{id: r.start}}), (b:Entity {{id: r.end}}) "
                    f"MERGE (a)-[:{kind}]->(b)", rows=rows)


def setup(session):
    session.run("CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (n:Entity) REQUIRE n.id IS UNIQUE")


def main():
    resumes = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    jobs = sys.argv[2] if len(sys.argv) > 2 else ROOT / "data/job_postings_sample"
    with connect() as driver, driver.session() as session:
        setup(session)
        i = j = 0
        for i, graph in enumerate(resume_graphs(resumes), 1):
            load(session, graph)
        print(f"Loaded {i} resumes")
        for j, graph in enumerate(job_graphs(jobs), 1):
            load(session, graph)
        print(f"Loaded {j} jobs")
        for record in session.run("MATCH (n) UNWIND labels(n) AS l WITH l WHERE l <> 'Entity' "
                                  "RETURN l, count(*) AS c ORDER BY c DESC"):
            print(f"  {record['l']}: {record['c']}")


if __name__ == "__main__":
    main()
