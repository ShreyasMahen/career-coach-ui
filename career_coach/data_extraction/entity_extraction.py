"""Local GLiNER inference and conservative O*NET entity resolution."""

import hashlib
import json
import unicodedata
from collections import defaultdict
from pathlib import Path


class EntityExtractor:
    def __init__(self, model_name="urchade/gliner_small-v2.1", threshold=0.5, *, model=None):
        self.model_name = model_name
        self.threshold = threshold
        self._entity_model = model

    # =========================
    # GLiNER ENTITY EXTRACTION
    # =========================
    SECTION_LABELS = {
        "education": {
            "context": ["university", "location"],
            "degree_entries": ["degree", "academic major", "date"],
        },
        "title": ["person", "job title", "location"],
        "summary": ["job title", "technical skill"],
        "experience": ["organization", "job title", "date", "location", "technical skill"],
        "projects": ["project name", "organization", "technical skill"],
        "skills": ["programming language", "framework", "software tool", "cloud platform"],
    }


    def _entity_windows(self, text: str):
        """Cover long blocks with overlapping windows using the model's splitter."""
        model = self._entity_model
        tokens = list(model.data_processor.words_splitter(text))
        size = min(int(model.config.max_len), 256)
        overlap = min(max(int(model.config.max_width) - 1, 32), size - 1)
        for first in range(0, len(tokens), size - overlap):
            last = min(first + size, len(tokens))
            start, end = tokens[first][1], tokens[last - 1][2]
            yield start, text[start:end]
            if last == len(tokens):
                break

    def extract_entities(self, sections: dict) -> list:
        # Load once per extractor instance, then reuse across resumes and sections.
        if self._entity_model is None:
            from gliner import GLiNER
            self._entity_model = GLiNER.from_pretrained(self.model_name)

        texts = sections.get("section_texts", sections)
        jobs = []
        for section, labels in self.SECTION_LABELS.items():
            if section == "education":
                refined = sections.get("education_refined", {})
                jobs.extend((section, kind, refined.get(kind, []), category_labels)
                            for kind, category_labels in labels.items())
                continue
            text = texts.get(section, "")
            blocks = sections.get("experience_refined", [{"text": text, "start": 0, "end": len(text)}]) if section == "experience" else [{"text": text, "start": 0, "end": len(text)}]
            jobs.append((section, "employment_entries" if section == "experience" else section, blocks, labels))
        unique = {}
        for section, category, blocks, labels in jobs:
            for index, block in enumerate(blocks):
                for window_start, window in self._entity_windows(block["text"]):
                    for prediction in self._entity_model.predict_entities(window, labels=labels, threshold=self.threshold):
                        start = block["start"] + window_start + prediction["start"]
                        end = block["start"] + window_start + prediction["end"]
                        if texts[section][start:end] != prediction["text"]:
                            raise ValueError("Entity evidence does not match its source section")
                        entity = {**prediction, "start": start, "end": end, "section": section,
                                  "category": category, "block_index": index,
                                  "source_field": f"section_texts.{section}" if "section_texts" in sections else section}
                        key = (section, start, end, prediction["label"])
                        if key not in unique or entity["score"] > unique[key]["score"]:
                            unique[key] = entity
        entities = list(unique.values())

        return entities


class TaxonomyResolver:
    """Resolve skill/job-title mentions; unsupported types remain explicitly separate."""

    SKILL_LABELS = {"technical skill", "skill", "programming language", "framework",
                    "software tool", "cloud platform"}
    # Explicit, reviewable lexical aliases; never delete punctuation or infer proficiency.
    SKILL_ALIASES = {
        "java": "Oracle Java", ".net": "Microsoft .NET Framework",
        "asp.net": "Microsoft ASP.NET", "react.js": "React",
        "jira": "Atlassian JIRA", "gcp": "Google Cloud software",
        "aws": "Amazon Web Services AWS software", "sql": "Structured query language SQL",
    }

    @staticmethod
    def match_key(text):
        return " ".join(unicodedata.normalize("NFKC", text).casefold().split())

    def __init__(self, taxonomy_dir):
        directory = Path(taxonomy_dir)
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        self.taxonomy = {"source": manifest.get("source", "O*NET Database"),
                         "version": manifest["version"], "alias_version": "1"}
        self.index = {"skill": defaultdict(list), "occupation": defaultdict(list)}
        for filename, kind in (("skills.jsonl", "skill"), ("software_examples.jsonl", "skill"),
                               ("occupations.jsonl", "occupation")):
            with (directory / filename).open(encoding="utf-8") as stream:
                for line in stream:
                    row = json.loads(line)
                    candidate = {key: row[key] for key in ("id", "namespace", "label", "source_version")}
                    for alias in set([row["label"], *row.get("aliases", [])]):
                        bucket = self.index[kind][self.match_key(alias)]
                        if candidate not in bucket:
                            bucket.append(candidate)
        for index in self.index.values():
            for bucket in index.values():
                bucket.sort(key=lambda c: (c["namespace"], c["id"]))

    def resolve_entities(self, entities: list, *, document_id: str) -> dict:
        result = {"taxonomy": self.taxonomy, "resolved": [], "unresolved": [], "not_applicable": []}
        for entity in entities:
            label = self.match_key(entity["label"])
            kind = "skill" if label in self.SKILL_LABELS else "occupation" if label == "job title" else None
            identity = [document_id, entity.get("source_field"), entity.get("section"),
                        entity.get("start"), entity.get("end"), entity["text"], entity["label"]]
            entity_id = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
            item = {"entity_id": entity_id, "entity": dict(entity), "taxonomy_type": kind,
                    "method": None, "mapping": None, "candidates": []}
            if kind is None:
                item.update(status="not_applicable", reason="entity_type_not_covered_by_onet_lookups")
                result["not_applicable"].append(item)
                continue
            key = self.match_key(entity["text"])
            candidates = self.index[kind].get(key, [])
            method = "exact_match"
            if not candidates and kind == "skill" and key in self.SKILL_ALIASES:
                candidates = self.index[kind].get(self.match_key(self.SKILL_ALIASES[key]), [])
                method = "curated_alias"
            item["candidates"] = list(candidates)
            if len(candidates) == 1:
                item.update(status="resolved", method=method, mapping=candidates[0], reason=None)
                result["resolved"].append(item)
            else:
                item.update(status="unresolved", method=method if candidates else None,
                            reason="ambiguous_match" if candidates else "no_taxonomy_match")
                result["unresolved"].append(item)
        result["counts"] = {key: len(result[key]) for key in ("resolved", "unresolved", "not_applicable")}
        return result


