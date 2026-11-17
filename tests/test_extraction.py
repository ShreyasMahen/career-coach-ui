import copy
import importlib
import json
import tempfile
import unittest
from pathlib import Path

from rdflib import Graph, RDF, XSD

from career_coach.data_extraction import HybridPipeline
from career_coach.data_extraction.rdf import EX, HR, PROV, to_graph


TEXT = "José García\nSoftware Engineer\nSkills: C++, C#, .NET, UnknownTool\nExperience\nSoftware Engineer\nExample Corp\n2020 - 2023\nEducation\nExample University\nBS\nComputer Science\n2015 - 2019\n"


def span(quote, kind, text=TEXT):
    start = text.index(quote)
    return {"kind": kind, "start": start, "end": start + len(quote), "quote": quote}


def evidence(start, end):
    return {"start": start, "end": end, "quote": TEXT[start:end]}


def enrichment():
    entities = [span(value, kind) for value, kind in [
        ("Example Corp", "organization"), ("Software Engineer", "job_title"),
        ("2020", "year"), ("2023", "year"), ("Example University", "organization"),
        ("BS", "degree"), ("Computer Science", "field_of_study"), ("2015", "year"), ("2019", "year")]]
    # Job title must refer to the occurrence inside the employment evidence.
    entities[1] = span("Software Engineer", "job_title", TEXT[TEXT.index("Experience"):])
    entities[1]["start"] += TEXT.index("Experience")
    entities[1]["end"] += TEXT.index("Experience")
    return {"entities": entities, "employments": [{"job_title": 1, "employer": 0, "start_year": 2, "end_year": 3,
        "evidence": evidence(TEXT.index("Software Engineer", TEXT.index("Experience")), TEXT.index("Education"))}],
        "educations": [{"institution": 4, "degree": 5, "field_of_study": 6, "start_year": 7, "end_year": 8,
        "evidence": evidence(TEXT.index("Example University"), len(TEXT))}]}


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.taxonomy = Path(self.directory.name)
        (self.taxonomy / "manifest.json").write_text(json.dumps({"version": "31.0"}), encoding="utf-8")
        for filename, rows in {
            "skills.jsonl": [],
            "software_examples.jsonl": [{"id": label, "namespace": "local:onet-software", "label": label, "source_version": "31.0"} for label in ["C++", "C#", ".NET"]],
            "occupations.jsonl": [{"id": str(i), "namespace": "onet:occupation", "label": label, "aliases": ["Engineer"], "source_version": "31.0"} for i, label in enumerate(["Software Engineer", "Civil Engineer"])],
        }.items():
            (self.taxonomy / filename).write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    def pipeline(self, payload=None, **kwargs):
        if payload is not None:
            kwargs.update(llm=lambda request: copy.deepcopy(payload), llm_model="test-model-v1")
        return HybridPipeline(self.taxonomy, **kwargs)

    def test_rules_preserve_evidence_and_skill_identity(self):
        result = self.pipeline().extract_text(TEXT, source_id="test")
        self.assertEqual(result["source"]["text"], TEXT)
        skills = [e for e in result["entities"] if e["kind"] == "skill"]
        self.assertEqual([e["quote"] for e in skills], ["C++", "C#", ".NET", "UnknownTool"])
        self.assertEqual([e["normalization"]["status"] for e in skills], ["matched"] * 3 + ["unmapped"])
        for entity in result["entities"]:
            self.assertEqual(TEXT[entity["start"]:entity["end"]], entity["quote"])
        self.assertEqual(result["educations"], [])  # No invented association.

    def test_ambiguous_taxonomy_abstains(self):
        normalization = self.pipeline().taxonomy.normalize("job_title", "ENGINEER")
        self.assertEqual(normalization["status"], "ambiguous")
        self.assertEqual(len(normalization["candidates"]), 2)

    def test_ner_and_llm_merge_with_provenance_and_export(self):
        class NER:
            model_id = "test-ner-v1"
            def __call__(self, text):
                return [span("José García", "person"), span("C++", "skill")]
        result = self.pipeline(enrichment(), ner=NER()).extract_text(TEXT, source_id="test")
        skill = next(e for e in result["entities"] if e["quote"] == "C++")
        self.assertEqual([x["method"] for x in skill["extractors"]], ["rules", "ner"])
        graph = to_graph(result)
        Graph().parse(data=graph.serialize(format="turtle"), format="turtle")
        self.assertEqual(len(list(graph.subjects(RDF.type, HR.Education))), 1)
        self.assertEqual(len(list(graph.triples((None, HR.institution, None)))), 1)
        years = list(graph.objects(None, HR.educationEndYear))
        self.assertEqual(str(years[0]), "2019")
        self.assertEqual(years[0].datatype, XSD.gYear)
        self.assertTrue(list(graph.triples((None, PROV.wasDerivedFrom, None))))
        self.assertTrue(list(graph.triples((None, EX.quote, None))))
        # The exporter uses declared HR terms; annotations live in other namespaces.
        ontology = Graph().parse("data/ontologies/resume.ttl", format="turtle")
        for subject, predicate, obj in graph:
            for term in (predicate, obj if predicate == RDF.type else None):
                if term is not None and str(term).startswith(str(HR)):
                    self.assertTrue(list(ontology.triples((term, None, None))), term)

    def test_llm_rejects_hallucinations_and_invalid_relationships(self):
        for mutation in ("quote", "reference", "outside", "reversed", "extra", "boolean"):
            with self.subTest(mutation=mutation):
                payload = enrichment()
                if mutation == "quote":
                    payload["entities"][0]["quote"] = "Invented Corp"
                elif mutation == "reference":
                    payload["employments"][0]["employer"] = 999
                elif mutation == "outside":
                    payload["employments"][0]["employer"] = 4
                elif mutation == "reversed":
                    payload["employments"][0].update(start_year=3, end_year=2)
                elif mutation == "extra":
                    payload["educations"][0]["confidence"] = 1
                else:
                    payload["employments"][0]["employer"] = True
                with self.assertRaises(ValueError):
                    self.pipeline(payload).extract_text(TEXT, source_id="test")

    def test_legacy_entry_point_and_empty_input(self):
        legacy = importlib.import_module("career_coach.data-extraction")
        result = legacy.ResumeParser().extract_hybrid(TEXT, source_id="test", taxonomy_dir=self.taxonomy)
        self.assertTrue(result["entities"])
        with self.assertRaises(ValueError):
            self.pipeline().extract_text(" ", source_id="test")


if __name__ == "__main__":
    unittest.main()
