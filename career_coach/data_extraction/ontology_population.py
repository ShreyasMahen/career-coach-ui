"""Deterministic, evidence-grounded population of the job-match ontology.

No model calls, database access, or schema changes. The report preserves evidence
and omissions that cannot be represented by the current Turtle vocabulary.
"""

import hashlib
import json
import re
from dataclasses import dataclass

from rdflib import Graph, Literal, RDF, URIRef

from .entity_extraction import TaxonomyResolver
from .ontology import NodeMetadata, OntologyNode, load_ontology


POPULATION_VERSION = "explicit-population-v3"
# A small, versioned policy, not a universal ordering of all credentials.
DEGREE_LEVELS = {
    "associate": (1, {"aa", "as", "aas", "associate", "associate degree", "associate of science", "associate of arts"}),
    "bachelor": (2, {"bs", "ba", "bsc", "bachelor", "bachelors", "bachelor of science", "bachelor of arts"}),
    "master": (3, {"ms", "ma", "msc", "master", "masters", "master of science", "master of arts"}),
    "doctorate": (4, {"phd", "doctorate", "doctor of philosophy"}),
}
UNCERTAIN = re.compile(
    r"\b(?:no|not|without|lack\w*|unfamiliar|never|learning|hypothetical|"
    r"expected|anticipated|pursuing|candidate|incomplete|unfinished|required|preferred)\b|\bin progress\b", re.I)
COMPLETED = re.compile(r"\b(?:earned|awarded|completed|received)\s*:?\s+(?:(?:an?|the)\s+)?$", re.I)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _key(value):
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _line(text, start, end):
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    return text[line_start:line_end if line_end != -1 else len(text)]


def _blocks(features, section, category=None):
    text = features["section_texts"].get(section, "")
    blocks = (features.get("education_refined", {}).get(category, []) if category
              else features.get("experience_refined", []))
    previous_end = 0
    for block in blocks:
        start, end = block.get("start"), block.get("end")
        if (type(start) is not int or type(end) is not int
                or not previous_end <= start < end <= len(text)
                or text[start:end] != block.get("text")):
            raise ValueError(f"Invalid or overlapping {section} source blocks")
        previous_end = end
    return blocks


def _mask(text, start, mentions, labels):
    remainder = list(text)
    for item in mentions:
        e = item["entity"]
        if e["label"] in labels and start <= e["start"] < e["end"] <= start + len(text):
            remainder[e["start"] - start:e["end"] - start] = " " * (e["end"] - e["start"])
    return "".join(remainder)


def _title_slot(raw, start, entity, mentions):
    """Recognize title fields in either employer/title order, not narrative roles."""
    prefix = _mask(raw[:entity["start"] - start], start, mentions,
                   {"organization", "location", "date"})
    prefix = re.sub(r"\b(?:job\s*title|title|role|position|employer|company|organization|location|date|present|current|to)\b",
                    "", prefix, flags=re.I)
    return not re.search(r"\w", prefix)


def _employer_fields(text, start, end, mentions):
    """Return supported organization spans and their evidence, or an omission reason.

    Comma/parenthesis-separated names in one affiliation field remain distinct.
    Whitespace-adjacent or overlapping NER spans form one printed name. This does
    not infer organization identity, a primary employer, or parent/subunit edges.
    """
    candidates = []
    excluded = re.compile(r"^\s*(client|customer|vendor|partner|recruiter|agency|staffing\s+agency|tools?|technologies|stack)\s*:", re.I)
    employer_label = re.compile(r"^\s*(?:employer|company|organization)\s*:\s*", re.I)
    conflicting_context = False
    for field in re.finditer(r"[^|;\t\n]+", text[start:end]):
        field_start = start + field.start()
        field_end = start + field.end()
        raw = field[0]
        excluded_label = excluded.match(raw)
        if excluded_label:
            if excluded_label[1].casefold() not in {"tool", "tools", "technologies", "stack"}:
                conflicting_context = True
            continue
        explicit = bool(employer_label.match(raw))
        contained = [i for i in mentions if field_start <= i["entity"]["start"] < i["entity"]["end"] <= field_end]
        organizations = []
        for item in contained:
            e = item["entity"]
            if e["label"] != "organization":
                continue
            # A conflicting role/date classification is not employer evidence.
            if any(i["entity"]["label"] in {"job title", "date"}
                   and i["entity"]["start"] < e["end"] and e["start"] < i["entity"]["end"]
                   for i in contained):
                continue
            organizations.append(item)
        if not organizations:
            continue
        remainder = _mask(raw, field_start, contained, {"organization", "job title", "date", "location", "project name"})
        remainder = re.sub(r"\b(?:employer|company|organization|job\s*title|title|role|position|location|date|present|current|to)\b",
                           "", remainder, flags=re.I)
        if any(i["entity"]["label"] == "job title" for i in contained):
            remainder = re.sub(r"\b(?:at|for)\b", "", remainder, flags=re.I)
        if re.search(r"\bor\b|/", remainder, re.I):
            return [], "alternative_employers"
        # Free prose or unclassified name material is not a complete header field.
        if re.search(r"\w", remainder):
            continue
        groups = []
        for item in sorted(organizations, key=lambda i: (i["entity"]["start"], i["entity"]["end"])):
            e = item["entity"]
            if groups and (e["start"] <= groups[-1]["end"]
                           or not text[groups[-1]["end"]:e["start"]].strip()):
                groups[-1]["end"] = max(groups[-1]["end"], e["end"])
                groups[-1]["mentions"].append(item)
            else:
                groups.append({"start": e["start"], "end": e["end"], "mentions": [item]})
        candidates.append({"explicit": explicit, "groups": groups})
    explicit = [c for c in candidates if c["explicit"]]
    if explicit:
        selected = explicit
    elif conflicting_context:
        return [], "unqualified_employer_client_context"
    elif len(candidates) == 1:
        selected = candidates
    else:
        return [], "competing_or_missing_employer_fields"
    return [group for candidate in selected for group in candidate["groups"]], None


def _header_end(block, mentions=()):
    """End after the title and subsequent fully entity-covered header lines.

    Organization mentions inside unbulleted achievement sentences do not extend
    the header. All positions refer to the original section text.
    """
    offset, count = block["start"], 0
    rows = []
    for raw in block["text"].splitlines(keepends=True):
        line = raw.strip()
        if line:
            if count == 5 or len(line) > 160 or re.match(r"^[•*\-–]", line):
                break
            # Headers may end in abbreviation punctuation, so use word count too.
            if line.endswith(".") and len(line.split()) > 8:
                break
            count += 1
            rows.append((offset, offset + len(raw), raw))
        offset += len(raw)
    cap = min(offset, block["end"])
    for index, (start, end, raw) in enumerate(rows):
        titles = [i["entity"] for i in mentions if i["entity"]["label"] == "job title"
                  and start <= i["entity"]["start"] < i["entity"]["end"] <= end]
        if not any(_title_slot(raw, start, e, mentions) for e in titles):
            continue
        boundary = end
        for next_start, next_end, next_raw in rows[index + 1:]:
            leftover = _mask(next_raw, next_start, mentions, {"date", "location", "organization", "job title"})
            leftover = re.sub(r"\b(?:present|current|to|location|dates?|employer|company|organization|client|customer|vendor|partner|agency|recruiter)\b", "", leftover, flags=re.I)
            if re.search(r"\w", leftover):
                break
            boundary = next_end
        return min(boundary, block["end"])
    return cap


@dataclass
class PopulatedOntology:
    nodes: list[OntologyNode]
    graph: Graph
    report: dict


class OntologyPopulator:
    def __init__(self, schema=None):
        self.schema = schema if schema is not None else load_ontology()

    def populate(self, features: dict, reviewed: dict) -> PopulatedOntology:
        """Populate one resume from final LLM output and matching parsed features.

        No input is mutated. Entity IDs/spans and any supplied source hash must
        match. IDs are stable for identical document content and taxonomy version.
        """
        texts = features.get("section_texts")
        if not isinstance(texts, dict) or not features.get("cv_id"):
            raise ValueError("Population requires cv_id and source-preserving section_texts")
        if reviewed.get("cv_id", features["cv_id"]) != features["cv_id"]:
            raise ValueError("Reviewed mappings belong to a different resume")
        source_hash = _digest(texts)
        audited_hash = reviewed.get("llm_audit", {}).get("source_sha256")
        if audited_hash is not None and audited_hash != source_hash:
            raise ValueError("LLM review source hash does not match parsed features")
        mappings = reviewed["entity_mappings"]
        items, evidence = [], {}
        for group in ("resolved", "unresolved", "not_applicable"):
            for item in mappings.get(group, []):
                entity = item["entity"]
                section = entity["section"]
                text = texts.get(section, "")
                start, end = entity["start"], entity["end"]
                if (entity["source_field"] != f"section_texts.{section}"
                        or type(start) is not int or type(end) is not int
                        or not 0 <= start < end <= len(text)
                        or text[start:end] != entity["text"]):
                    raise ValueError("Entity evidence does not match parsed source")
                if item["entity_id"] in evidence:
                    raise ValueError("Duplicate entity IDs in final mappings")
                if item.get("status", group) != group:
                    raise ValueError("Mapping status does not match its group")
                evidence[item["entity_id"]] = {
                    "entity": dict(entity), "status": group, "method": item.get("method"),
                    "mapping": item.get("mapping")}
                items.append(item)
        items.sort(key=lambda i: (i["entity"]["section"], i["entity"]["start"],
                                  i["entity"]["end"], i["entity_id"]))
        document_id = _digest([features["cv_id"], source_hash])
        nodes, node_sources, assertions, diagnostics = {}, {}, {}, []
        properties = {(p.domain, p.field_name): p for p in self.schema.properties.values()}

        def ids(mentions):
            return sorted({i["entity_id"] for i in mentions})

        def diagnostic(code, mentions=(), **context):
            diagnostics.append({"code": code, "entity_ids": ids(mentions), **context})

        def node(kind, identity, mentions=(), **metadata):
            if identity not in nodes:
                nodes[identity] = self.schema.models[kind](id=identity)
                node_sources[identity] = {"type": self.schema.classes[kind], "entity_ids": [], **metadata}
            elif nodes[identity].rdf_type != self.schema.classes[kind]:
                raise ValueError("Node identity has conflicting ontology types")
            node_sources[identity]["entity_ids"] = sorted(set(node_sources[identity]["entity_ids"]) | set(ids(mentions)))
            return nodes[identity]

        def assert_value(subject, field, value, mentions, rule, block=None):
            prop = properties[(subject.rdf_type, field)]
            target = value.id if isinstance(value, OntologyNode) else value
            values = getattr(subject, field)
            if target not in values:
                values.append(target)
            key = (subject.id, prop.iri, target)
            if key not in assertions:
                assertions[key] = {"subject": subject.id, "predicate": prop.iri,
                                   "object": target, "kind": prop.kind, "rule": rule, "entity_ids": []}
                if block is not None:
                    assertions[key]["block"] = block
            assertions[key]["entity_ids"] = sorted(set(assertions[key]["entity_ids"]) | set(ids(mentions)))

        def concept(item, kind):
            mapping = item.get("mapping")
            expected = "skill" if kind == "Skill" else "occupation"
            if (evidence[item["entity_id"]]["status"] != "resolved"
                    or item.get("taxonomy_type") != expected or not isinstance(mapping, dict)
                    or not all(isinstance(mapping.get(k), str) and mapping[k].strip()
                               for k in ("namespace", "id", "source_version", "label"))):
                diagnostic("no_supported_canonical_mapping", [item])
                return None
            identity = "urn:career-coach:concept:" + expected + ":" + _digest(
                [mapping["namespace"], mapping["id"], mapping["source_version"]])
            return node(kind, identity, [item], label=mapping["label"], taxonomy=dict(mapping))

        names = [i for i in items if i["entity"]["section"] == "title" and i["entity"]["label"] == "person"]
        person = node("Person", f"urn:career-coach:resume:{document_id}:person", names,
                      label=names[0]["entity"]["text"] if len(names) == 1 else None, rule="resume_subject")

        # A skills list explicitly attributes its entries to the applicant. Other
        # sections need stronger relationship extraction, not mere co-occurrence.
        for item in items:
            entity = item["entity"]
            if entity["label"] not in TaxonomyResolver.SKILL_LABELS:
                continue
            if entity["section"] != "skills":
                diagnostic("skill_usage_relationship_not_established", [item])
                continue
            if UNCERTAIN.search(_line(texts["skills"], entity["start"], entity["end"])):
                diagnostic("negated_or_uncertain_skill", [item])
                continue
            skill = concept(item, "Skill")
            if skill is not None:
                assert_value(person, "has_skill", skill, [item], "explicit_skills_list")

        experience_blocks = _blocks(features, "experience")
        if texts.get("experience") and not experience_blocks:
            diagnostic("missing_experience_blocks")
        for block in experience_blocks:
            block_mentions = [i for i in items if i["entity"]["section"] == "experience"
                              and block["start"] <= i["entity"]["start"] < i["entity"]["end"] <= block["end"]]
            header_end = _header_end(block, block_mentions)
            members = [i for i in block_mentions if i["entity"]["end"] <= header_end]
            # Titles embedded in achievement sentences or collaborator references
            # are not applicant job titles, even when GLiNER labelled them so.
            roles = []
            for item in members:
                entity = item["entity"]
                line_start = texts["experience"].rfind("\n", 0, entity["start"]) + 1
                raw = _line(texts["experience"], entity["start"], entity["end"])
                if entity["label"] == "job title" and _title_slot(raw, line_start, entity, members):
                    roles.append(item)
            organizations = [i for i in members if i["entity"]["label"] == "organization"]
            dates = [i for i in members if i["entity"]["label"] == "date"]
            context = {"source_field": "section_texts.experience", "start": block["start"], "end": header_end}
            header_text = texts["experience"][block["start"]:header_end]
            if len(roles) != 1 or not (organizations or dates) or UNCERTAIN.search(header_text):
                diagnostic("ambiguous_employment_header", members, block=context)
                continue
            title = roles[0]
            support = [title, *dates, *organizations]
            experience = node("Experience", f"urn:career-coach:resume:{document_id}:experience:{block['start']}",
                              support, original_title=title["entity"]["text"], block=context)
            assert_value(person, "has_experience", experience, support, "single_title_employment_header", context)
            role = concept(title, "Role")
            if role is not None:
                assert_value(experience, "in_role", role, [title], "employment_header_title", context)
            affiliations, reason = _employer_fields(texts["experience"], block["start"], header_end, members)
            for affiliation in affiliations:
                evidence_items = affiliation["mentions"]
                identity = (evidence_items[0]["entity_id"] if len(evidence_items) == 1
                            else _digest([affiliation["start"], affiliation["end"], ids(evidence_items)]))
                organization = node("Organization", f"urn:career-coach:resume:{document_id}:organization:{identity}",
                                    evidence_items, label=texts["experience"][affiliation["start"]:affiliation["end"]])
                assert_value(experience, "at_organization", organization, [title, *evidence_items], "explicit_employer_field", context)
            if reason is not None:
                diagnostic("employer_relationship_not_established", organizations, block=context, reason=reason)
            diagnostic("experience_duration_deferred", support, block=context)

        degree_blocks = _blocks(features, "education", "degree_entries")
        for item in items:
            entity = item["entity"]
            if entity["section"] != "education" or entity["label"] != "degree":
                continue
            degree = node("Degree", f"urn:career-coach:resume:{document_id}:degree:{entity['start']}:{entity['end']}",
                          [item], label=entity["text"])
            level = next(((name, rank) for name, (rank, aliases) in DEGREE_LEVELS.items()
                          if _key(entity["text"]) in {_key(a) for a in aliases}), None)
            if level is not None:
                name, rank = level
                level_node = node("DegreeLevel", f"urn:career-coach:degree-level:v1:{name}", [item], label=name)
                assert_value(level_node, "rank", rank, [item], "degree_level_order_v1")
                assert_value(degree, "degree_level", level_node, [item], "explicit_degree_alias_v1")
            else:
                diagnostic("unknown_degree_level", [item])
            blocks = [b for b in degree_blocks if b["start"] <= entity["start"] < entity["end"] <= b["end"]]
            if len(blocks) != 1:
                diagnostic("degree_completion_not_established", [item])
                continue
            block = blocks[0]
            degrees = [i for i in items if i["entity"]["section"] == "education" and i["entity"]["label"] == "degree"
                       and block["start"] <= i["entity"]["start"] < i["entity"]["end"] <= block["end"]]
            prefix = texts["education"][texts["education"].rfind("\n", 0, entity["start"]) + 1:entity["start"]]
            if (len(degrees) == 1 and COMPLETED.search(prefix) and not UNCERTAIN.search(block["text"])
                    and not re.search(r"\b(?:will|present|current|future)\b", block["text"], re.I)):
                context = {"source_field": "section_texts.education", "start": block["start"], "end": block["end"]}
                assert_value(person, "holds_degree", degree, [item], "explicit_degree_completion", context)
            else:
                diagnostic("degree_completion_not_established", [item])

        # Preserve every unhandled mention explicitly; not_applicable is not trash.
        used = {identity for info in node_sources.values() for identity in info["entity_ids"]}
        for item in items:
            if item["entity_id"] not in used:
                diagnostic("mention_not_represented_in_current_graph", [item])
        for identity, instance in nodes.items():
            info = node_sources[identity]
            instance.metadata = NodeMetadata(
                label=info.get("label"), taxonomy=info.get("taxonomy"), original_title=info.get("original_title"),
                evidence=[{"entity_id": entity_id, "source_document": features["cv_id"],
                           **{key: evidence[entity_id]["entity"][key]
                              for key in ("source_field", "start", "end", "text", "label")}}
                          for entity_id in info["entity_ids"]])
        ordered_nodes = [nodes[key] for key in sorted(nodes)]
        self.schema.validate_instances(ordered_nodes)
        graph = Graph()
        graph.bind("jm", "http://example.org/jobmatch#")
        for instance in ordered_nodes:
            subject = URIRef(instance.id)
            graph.add((subject, RDF.type, URIRef(instance.rdf_type)))
            for prop in self.schema.properties.values():
                if prop.domain != instance.rdf_type:
                    continue
                for value in getattr(instance, prop.field_name):
                    target = URIRef(value) if prop.kind == "object" else Literal(value, datatype=URIRef(prop.range))
                    graph.add((subject, URIRef(prop.iri), target))
        report = {
            "cv_id": features["cv_id"], "document_id": document_id,
            "source_sha256": source_hash, "schema": str(self.schema.source),
            "schema_sha256": hashlib.sha256(self.schema.source.read_bytes()).hexdigest(),
            "population_version": POPULATION_VERSION,
            "nodes": {key: node_sources[key] for key in sorted(node_sources)},
            "evidence": {key: evidence[key] for key in sorted(evidence)},
            "assertions": [assertions[key] for key in sorted(assertions)],
            "diagnostics": diagnostics,
            "counts": {"nodes": len(nodes), "triples": len(graph), "assertions": len(assertions),
                       "diagnostics": len(diagnostics)},
        }
        return PopulatedOntology(ordered_nodes, graph, report)
