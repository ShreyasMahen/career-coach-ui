"""Conservative O*NET normalization: exact aliases, explicit ambiguity, no fuzzy guesses."""

import json
import unicodedata
from collections import defaultdict
from pathlib import Path


def match_key(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


class Taxonomy:
    def __init__(self, directory):
        directory = Path(directory)
        self.manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        self.index = {"skill": defaultdict(list), "job_title": defaultdict(list)}
        for filename, kind in (("skills.jsonl", "skill"),
                               ("software_examples.jsonl", "skill"),
                               ("occupations.jsonl", "job_title")):
            with (directory / filename).open(encoding="utf-8") as stream:
                for line in stream:
                    row = json.loads(line)
                    candidate = {key: row[key] for key in ("id", "namespace", "label", "source_version")}
                    for alias in set([row["label"], *row.get("aliases", [])]):
                        bucket = self.index[kind][match_key(alias)]
                        if candidate not in bucket:
                            bucket.append(candidate)

    def normalize(self, kind, text):
        candidates = self.index.get(kind, {}).get(match_key(text), [])
        return {"status": "matched" if len(candidates) == 1 else
                "ambiguous" if candidates else "unmapped", "candidates": candidates}
