import copy
import importlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

cli = importlib.import_module("career_coach.data_extraction.main")


class ExtractionOutputTests(unittest.TestCase):
    def run_cli(self, rules_only=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        features = [{"cv_id": "resume.pdf", "section_texts": {"skills": "Python"}, "skills_list": ["python"]}]
        original = copy.deepcopy(features)
        parsed = Mock()
        parsed.to_dict.return_value = features
        arguments = ["extract", str(root / "data")]
        if rules_only:
            arguments.append("--rules-only")
        with patch("sys.argv", arguments), patch.object(cli, "ResumeParser") as parser, patch.object(cli, "EntityExtractor") as extractor, patch.object(cli, "TaxonomyResolver") as resolver, patch("career_coach.data_extraction.llm_mapping.LLMMappingResolver") as llm_resolver:
            parser.return_value.run.return_value = parsed
            extractor.return_value.extract_entities.return_value = [{"text": "Python", "label": "technical skill"}]
            resolver.return_value.resolve_entities.return_value = {"resolved": [], "unresolved": []}
            llm_resolver.return_value.resolve.return_value = {"entity_mappings": {"resolved": []}, "llm_audit": {"calls": 1}}
            cli.main()
            if rules_only:
                extractor.assert_not_called()
                resolver.assert_not_called()
                llm_resolver.assert_not_called()
            else:
                llm_resolver.return_value.resolve.assert_called_once_with(features[0], resolver.return_value.resolve_entities.return_value)
        self.assertEqual(features, original)
        self.assertEqual(json.loads((root / "data.json").read_text(encoding="utf-8")), original)
        return root

    def test_entities_are_saved_separately_without_mutating_features(self):
        root = self.run_cli()
        record = json.loads((root / "data.entities.json").read_text(encoding="utf-8"))[0]
        self.assertEqual(record["cv_id"], "resume.pdf")
        self.assertEqual(record["parsing_output"], "data.json")
        self.assertNotIn("entities", record)
        self.assertIn("entity_mappings", record)

    def test_rules_only_writes_only_parsed_features(self):
        root = self.run_cli(rules_only=True)
        self.assertFalse((root / "data.entities.json").exists())

    def test_default_pipeline_always_writes_llm_result(self):
        root = self.run_cli()
        result = json.loads((root / "data.llm.json").read_text(encoding="utf-8"))[0]
        baseline = json.loads((root / "data.entities.json").read_text(encoding="utf-8"))[0]
        self.assertEqual(result["entity_output"], "data.entities.json")
        self.assertEqual(result["llm_audit"]["calls"], 1)
        self.assertNotIn("llm_audit", baseline)

    def test_llm_failure_preserves_baseline_files(self):
        from career_coach.data_extraction.llm_mapping import LLMMappingError
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parsed = Mock()
            parsed.to_dict.return_value = [{"cv_id": "resume.pdf"}]
            with patch("sys.argv", ["extract", str(root / "data")]), patch.object(cli, "ResumeParser") as parser, patch.object(cli, "EntityExtractor") as extractor, patch.object(cli, "TaxonomyResolver") as taxonomy, patch("career_coach.data_extraction.llm_mapping.LLMMappingResolver") as llm:
                parser.return_value.run.return_value = parsed
                extractor.return_value.extract_entities.return_value = []
                taxonomy.return_value.resolve_entities.return_value = {"resolved": [], "unresolved": [], "not_applicable": []}
                llm.return_value.resolve.side_effect = LLMMappingError("Test schema failure")
                with self.assertRaises(LLMMappingError):
                    cli.main()
            self.assertTrue((root / "data.json").exists())
            self.assertTrue((root / "data.entities.json").exists())
            self.assertFalse((root / "data.llm.json").exists())

    def test_llm_runs_immediately_after_taxonomy_for_each_resume(self):
        with tempfile.TemporaryDirectory() as temporary:
            events = []
            records = [{"cv_id": "first.pdf"}, {"cv_id": "second.pdf"}]
            parsed = Mock()
            parsed.to_dict.return_value = records
            def extract(features):
                events.append(("extract", features["cv_id"]))
                return []
            def resolve(entities, *, document_id):
                events.append(("taxonomy", document_id))
                return {"document_id": document_id}
            def review(features, mappings):
                events.append(("llm", features["cv_id"]))
                return {"entity_mappings": mappings, "llm_audit": {}}
            with patch("sys.argv", ["extract", str(Path(temporary) / "data")]), patch.object(cli, "ResumeParser") as parser, patch.object(cli, "EntityExtractor") as extractor, patch.object(cli, "TaxonomyResolver") as taxonomy, patch("career_coach.data_extraction.llm_mapping.LLMMappingResolver") as llm:
                parser.return_value.run.return_value = parsed
                extractor.return_value.extract_entities.side_effect = extract
                taxonomy.return_value.resolve_entities.side_effect = resolve
                llm.return_value.resolve.side_effect = review
                cli.main()
            self.assertEqual(events, [(stage, name) for name in ("first.pdf", "second.pdf") for stage in ("extract", "taxonomy", "llm")])
