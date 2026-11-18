"""Validation checks for the CareerCoach knowledge graph in Neo4j.

Usage:
    NEO4J_PASSWORD=... uv run --with neo4j python -m career_coach.knowledge_graph.validate_graph

Rules come from Kelly's ontology (data/ontologies/resume-job.ttl): every edge must
connect the classes its property declares (domain -> range). FAIL = graph is wrong;
WARN = allowed, but worth knowing for the demo. Exit code 1 if any check FAILs.
"""

import sys

from career_coach.data_extraction.ontology import load_ontology
from career_coach.knowledge_graph.load_neo4j import connect

TYPES = {"float": "FLOAT", "integer": "INTEGER"}


def local(iri):
    return iri.rsplit("#", 1)[-1]


def checks(schema):
    classes = sorted(schema.classes)
    edges = [(local(p.iri), local(p.domain), local(p.range)) for p in schema.properties.values() if p.kind == "object"]
    values = [(local(p.iri), local(p.domain), TYPES[local(p.range)]) for p in schema.properties.values() if p.kind == "datatype"]
    yield "FAIL", "id uniqueness constraint exists", \
        "SHOW CONSTRAINTS YIELD labelsOrTypes, properties, type WHERE labelsOrTypes = ['Entity'] " \
        "AND properties = ['id'] AND type IN ['UNIQUENESS', 'NODE_PROPERTY_UNIQUENESS'] RETURN CASE count(*) WHEN 0 THEN 1 ELSE 0 END"
    yield "FAIL", "every node has an id", "MATCH (n) WHERE n.id IS NULL RETURN count(n)"
    yield "FAIL", "every node has exactly one ontology class", \
        f"MATCH (n) WHERE size([l IN labels(n) WHERE l IN {classes}]) <> 1 " \
        f"OR any(l IN labels(n) WHERE NOT l IN {classes + ['Entity']}) RETURN count(n)"
    yield "FAIL", "only ontology relationship types", \
        f"MATCH ()-[r]->() WHERE NOT type(r) IN {[e[0] for e in edges]} RETURN count(r)"
    for name, domain, range_ in edges:
        yield "FAIL", f"{name} goes {domain} -> {range_}", \
            f"MATCH (a)-[r:{name}]->(b) WHERE NOT a:{domain} OR NOT b:{range_} RETURN count(r)"
    for name, domain, kind in values:
        yield "FAIL", f"{name} only on {domain}, as {kind.lower()} values", \
            f"MATCH (n) WHERE n.{name} IS NOT NULL AND (NOT n:{domain} " \
            f"OR NOT valueType(n.{name}) STARTS WITH 'LIST<{kind}') RETURN count(n)"
    yield "FAIL", "every Person has a unique cv_id (traces back to the PDF)", \
        "MATCH (p:Person) WITH p.cv_id AS cv, count(*) AS c WHERE cv IS NULL OR c > 1 RETURN coalesce(sum(c), 0)"
    yield "FAIL", "every Skill, Role and Organization has a label", \
        "MATCH (n) WHERE (n:Skill OR n:Role OR n:Organization) AND n.label IS NULL RETURN count(n)"
    yield "WARN", "Persons with no skills", "MATCH (p:Person) WHERE NOT (p)-[:hasSkill]->() RETURN count(p)"
    yield "WARN", "JobPostings with no required skills", \
        "MATCH (j:JobPosting) WHERE NOT (j)-[:requiresSkill]->() RETURN count(j)"
    yield "WARN", "nodes with no relationships", "MATCH (n) WHERE NOT (n)--() RETURN count(n)"
    yield "WARN", "Persons sharing no skill with any job", \
        "MATCH (p:Person) WHERE NOT (p)-[:hasSkill]->(:Skill)<-[:requiresSkill]-(:JobPosting) RETURN count(p)"


def main():
    failed = 0
    with connect() as driver, driver.session() as session:
        for level, name, query in checks(load_ontology()):
            bad = session.run(query).single()[0]
            status = "PASS" if bad == 0 else level
            failed += status == "FAIL"
            print(f"{status:4}  {name}" + (f"  ({bad})" if bad else ""))
        counts = session.run("MATCH (p:Person) WITH count(p) AS p MATCH (j:JobPosting) "
                             "WITH p, count(j) AS j MATCH ()-[r]->() RETURN p, j, count(r) AS r").single()
        print(f"\n{counts['p']} persons, {counts['j']} jobs, {counts['r']} relationships; "
              f"{'all checks passed' if not failed else f'{failed} check(s) FAILED'}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
