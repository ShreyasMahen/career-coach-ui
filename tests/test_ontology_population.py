"""Evidence and ambiguity checks for offline deterministic graph population."""

import copy
import hashlib
import json
import unittest

from rdflib import Graph, Namespace, RDF, URIRef

from career_coach.data_extraction.ontology import OntologyDocument
from career_coach.data_extraction.ontology_population import OntologyPopulator


JM = Namespace("http://example.org/jobmatch#")


class PopulationTests(unittest.TestCase):
    def setUp(self):
        self.features = {
            "cv_id": "example.pdf",
            "section_texts": {
                "skills": "Python, Python\nNo experience with Docker\nNode.js",
                "experience": "Example Corp\nJanuary 2020 - May 2024\nSoftware Engineer\n• Collaborated with Partner Inc and lead developers using Python.",
                "education": "Earned B.S. in Computer Science\n2020 - 2024\nM.S. in Computer Science\nExpected May 2027",
                "projects": "Built Python tools.",
            },
        }
        text = self.features["section_texts"]["experience"]
        self.features["experience_refined"] = [{"start": 0, "end": len(text), "text": text}]
        text = self.features["section_texts"]["education"]
        split = text.index("M.S.")
        self.features["education_refined"] = {"degree_entries": [
            {"start": 0, "end": split, "text": text[:split]},
            {"start": split, "end": len(text), "text": text[split:]},
        ]}
        self.reviewed = {"cv_id": self.features["cv_id"], "entity_mappings": {
            "resolved": [], "unresolved": [], "not_applicable": []}}
        self.next_id = 0
        self.add("skills", "Python", "programming language", "resolved", "python")
        self.add("skills", "Python", "programming language", "resolved", "python", occurrence=1)
        self.add("skills", "Docker", "software tool", "resolved", "docker")
        self.add("skills", "Node.js", "runtime", "unresolved")
        self.add("experience", "Example Corp", "organization")
        self.add("experience", "January 2020 - May 2024", "date")
        self.add("experience", "Software Engineer", "job title", "resolved", "developer")
        self.add("experience", "Partner Inc", "organization")
        self.add("experience", "lead developers", "job title", "resolved", "lead-developer")
        self.add("experience", "Python", "programming language", "resolved", "python")
        self.add("projects", "Python", "programming language", "resolved", "python")
        self.add("education", "B.S.", "degree")
        self.add("education", "M.S.", "degree")
        self.populator = OntologyPopulator()

    def add(self, section, quote, label, status="not_applicable", canonical=None, occurrence=0):
        text = self.features["section_texts"][section]
        start = -1
        for _ in range(occurrence + 1):
            start = text.index(quote, start + 1)
        entity = {"section": section, "source_field": f"section_texts.{section}",
                  "text": quote, "start": start, "end": start + len(quote), "label": label,
                  "block_index": 999, "category": section}
        item = {"entity_id": f"entity-{self.next_id}",
                "entity": entity, "status": status, "mapping": None}
        self.next_id += 1
        if canonical:
            item.update(taxonomy_type="occupation" if label == "job title" else "skill", method="exact_match",
                        mapping={"id": canonical, "namespace": "test:occupation" if label == "job title" else "test:software",
                                 "source_version": "31.0", "label": quote})
        self.reviewed["entity_mappings"][status].append(item)
        return item

    def populate(self):
        return self.populator.populate(self.features, self.reviewed)

    def replace_experience(self, text):
        self.features["section_texts"]["experience"] = text
        self.features["experience_refined"] = [{"start": 0, "end": len(text), "text": text}]
        for group in self.reviewed["entity_mappings"]:
            self.reviewed["entity_mappings"][group] = [
                i for i in self.reviewed["entity_mappings"][group] if i["entity"]["section"] != "experience"]

    def test_metadata_survives_final_serialization(self):
        self.features["section_texts"]["title"] = "Jane Doe"
        self.add("title", "Jane Doe", "person")
        result = self.populate()
        document = OntologyDocument(cv_id=self.features["cv_id"], nodes=result.nodes)
        nodes = json.loads(document.model_dump_json())["nodes"]
        skill = next(n for n in nodes if n["type"].endswith("#Skill"))
        self.assertEqual(skill["metadata"]["label"], "Python")
        self.assertEqual(skill["metadata"]["taxonomy"]["source_version"], "31.0")
        self.assertEqual(len(skill["metadata"]["evidence"]), 2)
        experience = next(n for n in nodes if n["type"].endswith("#Experience"))
        self.assertEqual(experience["metadata"]["original_title"], "Software Engineer")
        person = next(n for n in nodes if n["type"].endswith("#Person"))
        self.assertEqual(person["metadata"]["label"], "Jane Doe")
        for node in nodes:
            for evidence in node["metadata"]["evidence"]:
                section = evidence["source_field"].split(".")[1]
                self.assertEqual(self.features["section_texts"][section][evidence["start"]:evidence["end"]], evidence["text"])
                self.assertEqual(evidence["source_document"], "example.pdf")

    def test_unbulleted_achievement_organization_is_not_part_of_header(self):
        self.replace_experience("American Express\nJune - August 2025\nSoftware Engineer Intern | Python\nPhoenix, Arizona\nTransitioned tools used by reliability engineering team onto an internal platform.")
        self.add("experience", "American Express", "organization")
        self.add("experience", "June - August 2025", "date")
        self.add("experience", "Software Engineer Intern", "job title", "resolved", "developer")
        self.add("experience", "Phoenix", "location")
        self.add("experience", "Arizona", "location")
        team = self.add("experience", "reliability engineering team", "organization")
        result = self.populate()
        experience = next(result.graph.subjects(RDF.type, JM.Experience))
        employer = next(result.graph.objects(experience, JM.atOrganization))
        self.assertEqual(result.report["nodes"][str(employer)]["label"], "American Express")
        block = result.report["nodes"][str(experience)]["block"]
        self.assertEqual(block["end"], self.features["section_texts"]["experience"].index("Transitioned"))
        self.assertNotIn(team["entity_id"], result.report["nodes"][str(experience)]["entity_ids"])

    def test_wrapped_achievement_with_role_reference_is_not_header(self):
        self.replace_experience("Example Corp\n2024 - Present\nSoftware Engineer\nCollaborated with lead developers to build features for a game\nusing a research platform.")
        self.add("experience", "Example Corp", "organization")
        self.add("experience", "2024 - Present", "date")
        self.add("experience", "Software Engineer", "job title", "resolved", "developer")
        colleague = self.add("experience", "lead developers", "job title", "resolved", "lead-developer")
        result = self.populate()
        experience = next(result.graph.subjects(RDF.type, JM.Experience))
        self.assertNotIn(colleague["entity_id"], result.report["nodes"][str(experience)]["entity_ids"])
        self.assertEqual(len(list(result.graph.objects(experience, JM.inRole))), 1)

    def test_organization_and_date_lines_after_title_are_preserved(self):
        self.replace_experience("Software Engineer\nExample Corp\n2024 - Present\nBuilt services for Partner Inc.")
        self.add("experience", "Software Engineer", "job title", "resolved", "developer")
        self.add("experience", "Example Corp", "organization")
        self.add("experience", "2024 - Present", "date")
        self.add("experience", "Partner Inc", "organization")
        result = self.populate()
        experience = next(result.graph.subjects(RDF.type, JM.Experience))
        employer = next(result.graph.objects(experience, JM.atOrganization))
        self.assertEqual(result.report["nodes"][str(employer)]["label"], "Example Corp")

    def test_populates_and_round_trips_supported_relationships(self):
        before = copy.deepcopy((self.features, self.reviewed))
        result = self.populate()
        self.assertEqual((self.features, self.reviewed), before)
        graph = result.graph
        person = next(graph.subjects(RDF.type, JM.Person))
        self.assertEqual(len(list(graph.objects(person, JM.hasSkill))), 1)
        experience = next(graph.objects(person, JM.hasExperience))
        self.assertEqual(len(list(graph.objects(experience, JM.inRole))), 1)
        employer = next(graph.objects(experience, JM.atOrganization))
        self.assertEqual(result.report["nodes"][str(employer)]["label"], "Example Corp")
        self.assertFalse(list(graph.objects(experience, JM.yearsExperience)))
        self.assertFalse(list(graph.subjects(RDF.type, JM.JobPosting)))
        self.assertEqual(set(Graph().parse(data=graph.serialize(format="turtle"), format="turtle")), set(graph))
        self.assertTrue(all(a["entity_ids"] for a in result.report["assertions"]))

    def test_negated_unresolved_and_non_skills_section_mentions_do_not_add_skills(self):
        result = self.populate()
        skills = list(result.graph.subjects(RDF.type, JM.Skill))
        self.assertEqual(len(skills), 1)
        self.assertEqual(result.report["nodes"][str(skills[0])]["taxonomy"]["id"], "python")
        codes = {d["code"] for d in result.report["diagnostics"]}
        self.assertIn("negated_or_uncertain_skill", codes)
        self.assertIn("no_supported_canonical_mapping", codes)
        self.assertIn("skill_usage_relationship_not_established", codes)
        self.assertEqual(len(result.report["nodes"][str(skills[0])]["entity_ids"]), 2)

    def test_degrees_normalize_but_only_explicit_completion_establishes_holding(self):
        result = self.populate()
        person = next(result.graph.subjects(RDF.type, JM.Person))
        degrees = list(result.graph.subjects(RDF.type, JM.Degree))
        self.assertEqual(len(degrees), 2)
        held = list(result.graph.objects(person, JM.holdsDegree))
        self.assertEqual(len(held), 1)
        self.assertEqual(result.report["nodes"][str(held[0])]["label"], "B.S.")
        for degree in degrees:
            level = next(result.graph.objects(degree, JM.degreeLevel))
            self.assertIn(int(next(result.graph.objects(level, JM.rank))), (2, 3))

    def test_ambiguous_employer_is_reported_without_guessing(self):
        # A conflicting organization classification at the title span is ambiguous.
        self.add("experience", "Software Engineer", "organization")
        result = self.populate()
        self.assertEqual(len(list(result.graph.subjects(RDF.type, JM.Experience))), 1)
        self.assertFalse(list(result.graph.triples((None, JM.atOrganization, None))))
        self.assertIn("employer_relationship_not_established", {d["code"] for d in result.report["diagnostics"]})

    def test_ambiguous_titles_or_missing_blocks_do_not_create_employment(self):
        self.add("experience", "Example Corp", "job title", "resolved", "other-role")
        result = self.populate()
        self.assertFalse(list(result.graph.subjects(RDF.type, JM.Experience)))
        self.features.pop("experience_refined")
        result = self.populate()
        self.assertFalse(list(result.graph.subjects(RDF.type, JM.Experience)))
        self.assertIn("missing_experience_blocks", {d["code"] for d in result.report["diagnostics"]})

    def test_stale_evidence_source_hash_and_wrong_document_fail(self):
        original = copy.deepcopy(self.reviewed)
        item = self.reviewed["entity_mappings"]["resolved"][0]
        item["entity"]["start"] += 1
        with self.assertRaisesRegex(ValueError, "Entity evidence"):
            self.populate()
        self.reviewed = copy.deepcopy(original)
        self.reviewed["llm_audit"] = {"source_sha256": "stale"}
        with self.assertRaisesRegex(ValueError, "source hash"):
            self.populate()
        self.reviewed = copy.deepcopy(original)
        self.reviewed["cv_id"] = "another.pdf"
        with self.assertRaisesRegex(ValueError, "different resume"):
            self.populate()

    def test_overlapping_or_stale_blocks_fail(self):
        block = self.features["experience_refined"][0]
        self.features["experience_refined"].append(dict(block))
        with self.assertRaisesRegex(ValueError, "overlapping"):
            self.populate()
        self.features["experience_refined"] = [{**block, "text": "wrong"}]
        with self.assertRaisesRegex(ValueError, "source blocks"):
            self.populate()

    def test_repeat_population_is_stable_and_taxonomy_versions_are_distinct(self):
        self.reviewed["llm_audit"] = {"source_sha256": hashlib.sha256(
            json.dumps(self.features["section_texts"], sort_keys=True, ensure_ascii=False).encode()).hexdigest()}
        first, again = self.populate(), self.populate()
        self.assertEqual(set(first.graph), set(again.graph))
        self.assertEqual(first.report, again.report)
        # Revision changes only concept identity; document/person identity is stable.
        self.reviewed["entity_mappings"]["resolved"][0]["mapping"]["source_version"] = "32.0"
        changed = self.populate()
        self.assertEqual(first.report["document_id"], changed.report["document_id"])
        self.assertEqual(len(list(changed.graph.subjects(RDF.type, JM.Skill))), 2)

    def test_incomplete_canonical_mapping_is_not_used(self):
        for item in self.reviewed["entity_mappings"]["resolved"]:
            if item["entity"]["text"] == "Python":
                item["mapping"].pop("namespace")
        result = self.populate()
        self.assertFalse(list(result.graph.subjects(RDF.type, JM.Skill)))

    def test_evidence_is_preserved_for_every_input_mention(self):
        result = self.populate()
        input_ids = {i["entity_id"] for group in self.reviewed["entity_mappings"].values() for i in group}
        self.assertEqual(set(result.report["evidence"]), input_ids)
        self.assertIn("not_applicable", {i["status"] for i in result.report["evidence"].values()})

    def test_past_dates_alone_do_not_assert_graduation(self):
        # Preserve offsets while removing the explicit completion cue.
        text = self.features["section_texts"]["education"].replace("Earned", "Degree")
        self.features["section_texts"]["education"] = text
        for block in self.features["education_refined"]["degree_entries"]:
            block["text"] = text[block["start"]:block["end"]]
        result = self.populate()
        self.assertFalse(list(result.graph.triples((None, JM.holdsDegree, None))))

    def test_documents_share_only_canonical_concepts(self):
        first = self.populate()
        self.features["cv_id"] = self.reviewed["cv_id"] = "another.pdf"
        second = self.populate()
        self.assertEqual(set(first.graph.subjects(RDF.type, JM.Skill)), set(second.graph.subjects(RDF.type, JM.Skill)))
        self.assertNotEqual(set(first.graph.subjects(RDF.type, JM.Person)), set(second.graph.subjects(RDF.type, JM.Person)))
        self.assertNotEqual(set(first.graph.subjects(RDF.type, JM.Organization)), set(second.graph.subjects(RDF.type, JM.Organization)))
