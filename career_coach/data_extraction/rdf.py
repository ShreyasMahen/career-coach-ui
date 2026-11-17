"""Map grounded resume records to resume.ttl, with statement-level provenance."""

from urllib.parse import quote

from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef, XSD

HR = Namespace("http://example.org/hr#")
EX = Namespace("urn:career-coach:extraction:")
PROV = Namespace("http://www.w3.org/ns/prov#")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")


def to_graph(result):
    graph = Graph()
    for prefix, namespace in (("hr", HR), ("extract", EX), ("prov", PROV), ("skos", SKOS)):
        graph.bind(prefix, namespace)
    digest = result["source"]["text_sha256"]
    base = f"urn:career-coach:resume:{digest}:"
    source, person = URIRef(base + "source"), URIRef(base + "person")
    graph.add((source, RDF.type, PROV.Entity))
    graph.add((source, EX.sourceId, Literal(result["source"]["id"])))
    graph.add((source, EX.textSha256, Literal(digest)))
    if "file_sha256" in result["source"]:
        graph.add((source, EX.fileSha256, Literal(result["source"]["file_sha256"])))
    graph.add((person, RDF.type, HR.Person))
    graph.add((person, PROV.wasDerivedFrom, source))
    entities = {e["id"]: e for e in result["entities"]}

    def assert_fact(subject, predicate, value, evidence):
        graph.add((subject, predicate, value))
        node = URIRef(base + f"assertion:{len(graph)}")
        for pred, obj in ((RDF.type, RDF.Statement), (RDF.subject, subject),
                          (RDF.predicate, predicate), (RDF.object, value),
                          (PROV.wasDerivedFrom, source), (EX.startChar, Literal(evidence["start"])),
                          (EX.endChar, Literal(evidence["end"])), (EX.quote, Literal(evidence["quote"]))):
            graph.add((node, pred, obj))
        for extractor in evidence.get("extractors", [{"method": "llm", "model": evidence.get("model")}]):
            graph.add((node, EX.method, Literal(extractor["method"])))
            if extractor.get("model"):
                graph.add((node, EX.model, Literal(extractor["model"])))
        if evidence.get("page") is not None:
            graph.add((node, EX.page, Literal(evidence["page"])))

    def normalize(node, entity):
        normalization = entity["normalization"]
        if normalization["status"] == "matched":
            candidate = normalization["candidates"][0]
            concept = URIRef("urn:career-coach:taxonomy:" + quote(candidate["namespace"], safe="") + ":" + quote(candidate["id"], safe=""))
            assert_fact(node, SKOS.closeMatch, concept, entity)
            graph.add((concept, RDFS.label, Literal(candidate["label"])))
            graph.add((concept, EX.taxonomyVersion, Literal(candidate["source_version"])))

    # A resume belongs to one subject. Multiple PERSON candidates remain unresolved.
    names = [e for e in entities.values() if e["kind"] == "person" and e["section"] == "title"]
    if len({e["quote"] for e in names}) == 1:
        for entity in names:
            assert_fact(person, HR.name, Literal(entity["quote"]), entity)
    for entity in entities.values():
        if entity["kind"] == "skill" and entity["section"] == "skills":
            node = URIRef(base + quote(entity["id"], safe=""))
            assert_fact(node, RDF.type, HR.Skill, entity)
            assert_fact(node, HR.name, Literal(entity["quote"]), entity)
            assert_fact(person, HR.hasSkill, node, entity)
            normalize(node, entity)
    mapping = {
        "employments": (HR.Employment, HR.hasEmployment, {"job_title": HR.jobTitle, "start_year": HR.startDate, "end_year": HR.endDate}),
        "educations": (HR.Education, HR.hasEducation, {"degree": HR.degree, "field_of_study": HR.fieldOfStudy, "start_year": HR.educationStartYear, "end_year": HR.educationEndYear}),
    }
    for collection, (cls, link, properties) in mapping.items():
        for index, record in enumerate(result[collection]):
            node = URIRef(base + f"{collection}:{index}")
            evidence = {**record["evidence"], "model": record["model"]}
            assert_fact(node, RDF.type, cls, evidence)
            assert_fact(person, link, node, evidence)
            for field, prop in properties.items():
                if record[field] is not None:
                    entity = entities[record[field]]
                    value = Literal(entity["quote"], datatype=XSD.gYear if field.endswith("year") else XSD.string)
                    assert_fact(node, prop, value, entity)
                    if field == "job_title":
                        normalize(node, entity)
            org_field, prop, org_cls = ("employer", HR.employer, HR.Company) if collection == "employments" else ("institution", HR.institution, HR.University)
            if record[org_field] is not None:
                entity = entities[record[org_field]]
                org = URIRef(str(node) + ":organization")
                assert_fact(org, RDF.type, org_cls, evidence)
                assert_fact(org, HR.name, Literal(entity["quote"]), entity)
                assert_fact(node, prop, org, evidence)
    return graph
