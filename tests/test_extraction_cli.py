import copy
import importlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

cli = importlib.import_module("career_coach.data-extraction.main")


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
        with patch("sys.argv", arguments), patch.object(cli, "ResumeParser") as parser, patch.object(cli, "EntityExtractor") as extractor, patch.object(cli, "TaxonomyResolver") as resolver:
            parser.return_value.run.return_value = parsed
            extractor.return_value.extract_entities.return_value = [{"text": "Python", "label": "technical skill"}]
            resolver.return_value.resolve_entities.return_value = {"resolved": [], "unresolved": []}
            cli.main()
            if rules_only:
                extractor.assert_not_called()
                resolver.assert_not_called()
        self.assertEqual(features, original)
        self.assertEqual(json.loads((root / "data.json").read_text(encoding="utf-8")), original)
        return root

    def test_entities_are_saved_separately_without_mutating_features(self):
        root = self.run_cli()
        record = json.loads((root / "data.entities.json").read_text(encoding="utf-8"))[0]
        self.assertEqual(record["cv_id"], "resume.pdf")
        self.assertEqual(record["parsing_output"], "data.json")
        self.assertEqual(record["entities"][0]["text"], "Python")
        self.assertIn("entity_mappings", record)

    def test_rules_only_writes_only_parsed_features(self):
        root = self.run_cli(rules_only=True)
        self.assertFalse((root / "data.entities.json").exists())
