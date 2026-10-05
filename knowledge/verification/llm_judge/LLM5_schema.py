"""Validate LLM5 stage outputs without inventing or repairing judgments."""

import json

DIMENSIONS = (
    "cross_domain_necessity", "fusion_dependency", "correctness_evaluability",
    "knowledge_grounding", "naturalness_clarity",
)
STAGES = ("blind_structure", "evidence_scoring", "adjudication")
FLAG_DIMENSIONS = {
    "key_answer_error": "correctness_evaluability",
    "single_domain_shortcut": "cross_domain_necessity",
    "subset_shortcut": "cross_domain_necessity",
    "redundant_domain": "cross_domain_necessity",
    "invalid_dependency": "fusion_dependency",
    "source_contradiction": "knowledge_grounding",
}
UNKNOWN_REASONS = (
    "missing_source", "insufficient_expertise", "missing_grading_rule",
    "insufficient_visible_input", "unresolved_evidence_conflict",
    "unresolved_necessity",
)


def _require(condition, message):
    """Raise a validation error when a contract condition is false."""
    if not condition:
        raise ValueError(message)


def _object(value, required, location):
    """Require an object containing the specified fields."""
    _require(isinstance(value, dict), f"{location}: expected an object")
    _require(set(required) <= value.keys(), f"{location}: missing required fields")


def _text(value, location, nonempty=True):
    """Check a string and optionally require nonwhitespace content."""
    _require(isinstance(value, str), f"{location}: expected a string")
    _require(not nonempty or bool(value.strip()), f"{location}: empty text")


def _list(value, location):
    """Check an array."""
    _require(isinstance(value, list), f"{location}: expected an array")


def _texts(value, location):
    """Check an array of nonempty strings."""
    _list(value, location)
    for item in value:
        _text(item, location)


def _enum(value, choices, location):
    """Check a string enum without accepting arbitrary JSON values."""
    _require(isinstance(value, str) and value in choices,
             f"{location}: invalid value (expected one of {choices})")


def _score(status, score, location):
    """Validate a score/status pair, explicitly rejecting boolean scores."""
    _enum(status, ("scored", "unjudgeable"), location)
    if status == "scored":
        _require(type(score) is int and 0 <= score <= 4,
                 f"{location}: scored requires an integer from 0 through 4")
    else:
        _require(score is None, f"{location}: unjudgeable requires null")


def _strings(value):
    """Yield original textual leaves, avoiding synthetic JSON quote matches."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child)
    elif value is not None:
        yield json.dumps(value, ensure_ascii=False)


def _pointer_map(sample, blind=False):
    """Build only real input pointers, excluding metadata from all stages."""
    visible = sample["visible"]
    pointers = {key: visible[key] for key in ("question", "visible_inputs")
                if key in visible and visible[key] is not None}
    pointers.update({f"options.{key}": value
                     for key, value in (visible.get("options") or {}).items()})
    if not blind:
        bundle = sample["review_bundle"]
        pointers.update({key: bundle[key] for key in
                         ("reference_answer", "reference_explanation", "grading_rule")
                         if key in bundle and bundle[key] is not None})
        pointers.update({source["source_id"]: source["content"]
                         for source in bundle.get("sources", [])})
    return pointers


def _pointers(value, pointers, location):
    """Validate fixed pointers against the sample's actual available inputs."""
    _texts(value, location)
    for pointer in value:
        _require(pointer in pointers, f"{location}: unknown pointer {pointer!r}")


def _edges(value):
    """Require concise semantic dependency edges without forcing graph density."""
    _list(value, "dependency_edges")
    for edge in value:
        fields = ("from", "to", "transferred_information", "effect")
        _object(edge, fields, "dependency_edges")
        for field in fields:
            _text(edge[field], f"dependency_edges.{field}")


def _blind(obj, pointers):
    """Validate the independent, visible-input-only structural assessment."""
    fields = ("task_summary", "inferred_knowledge", "dependency_edges",
              "shortcut_checks", "candidate_answer", "answer_status", "open_questions")
    _object(obj, fields, "blind_structure")
    _require(set(obj) == set(fields) | {"sample_id", "stage"},
             "blind_structure: unexpected fields")
    _text(obj["task_summary"], "task_summary")
    _list(obj["inferred_knowledge"], "inferred_knowledge")
    for item in obj["inferred_knowledge"]:
        _object(item, ("label", "role", "input_pointer"), "inferred_knowledge")
        _text(item["label"], "inferred_knowledge.label")
        _text(item["role"], "inferred_knowledge.role")
        _pointers([item["input_pointer"]], pointers, "inferred_knowledge.input_pointer")
    _edges(obj["dependency_edges"])
    _list(obj["shortcut_checks"], "shortcut_checks")
    for check in obj["shortcut_checks"]:
        _object(check, ("type", "status", "description", "input_pointers"), "shortcut_checks")
        _enum(check["type"], ("single_domain", "subset", "question_leakage",
                              "option_shortcut", "generic"), "shortcut_checks.type")
        _enum(check["status"], ("found", "not_found", "uncertain"), "shortcut_checks.status")
        _text(check["description"], "shortcut_checks.description")
        _pointers(check["input_pointers"], pointers, "shortcut_checks.input_pointers")
    _enum(obj["answer_status"], ("determined", "uncertain"), "answer_status")
    _require(obj["candidate_answer"] is None or isinstance(obj["candidate_answer"], str),
             "candidate_answer: expected a string or null")
    if obj["answer_status"] == "determined":
        _text(obj["candidate_answer"], "determined candidate_answer")
    _texts(obj["open_questions"], "open_questions")


def _claims(claims, pointers, source_ids):
    """Check references and literal quote provenance, not semantic entailment."""
    _list(claims, "claim_evidence")
    seen = set()
    for claim in claims:
        fields = ("claim_id", "claim", "support_type", "source_ids", "quote", "brief_check")
        _object(claim, fields, "claim_evidence")
        for field in ("claim_id", "claim", "brief_check"):
            _text(claim[field], f"claim_evidence.{field}")
        _require(claim["claim_id"] not in seen, "claim_evidence: duplicate claim_id")
        seen.add(claim["claim_id"])
        support = claim["support_type"]
        _enum(support, ("direct", "derived", "task_assumption", "unsupported",
                        "contradicted", "unjudgeable"), "claim_evidence.support_type")
        _pointers(claim["source_ids"], source_ids, "claim_evidence.source_ids")
        refs = claim["source_ids"] + claim.get("evidence_pointers", [])
        _pointers(claim.get("evidence_pointers", []), pointers, "claim_evidence.evidence_pointers")
        quote = claim["quote"]
        _text(quote, "claim_evidence.quote", nonempty=False)
        if support in ("direct", "derived", "task_assumption", "contradicted"):
            _require(bool(refs) and bool(quote.strip()),
                     "claim_evidence: supported/contradicted claims require references and a quote")
        if quote.strip():
            normalized = " ".join(quote.split())
            _require(any(normalized in " ".join(text.split())
                         for ref in refs for text in _strings(pointers[ref])),
                     "claim_evidence.quote: not found in the referenced original text")


def _evidence(obj, sample, pointers):
    """Validate the five scores, per-domain coverage, evidence, and contradictions."""
    fields = ("answer_check", "domain_checks", "dependency_edges", "claim_evidence",
              "dimensions", "flags", "stage1_revisions", "missing_information", "necessity_audit")
    _object(obj, fields, "evidence_scoring")
    _require(set(obj) == set(fields) | {"sample_id", "stage"},
             "evidence_scoring: unexpected fields")
    answer = obj["answer_check"]
    _object(answer, ("status", "independent_answer", "brief_basis"), "answer_check")
    _enum(answer["status"], ("correct", "incorrect", "ambiguous", "unjudgeable"), "answer_check.status")
    _text(answer["brief_basis"], "answer_check.brief_basis")
    _require(answer["independent_answer"] is None or isinstance(answer["independent_answer"], str),
             "answer_check.independent_answer: expected a string or null")
    domains = sample["review_bundle"]["declared_domains"]
    _list(obj["domain_checks"], "domain_checks")
    checked = []
    for item in obj["domain_checks"]:
        _object(item, ("domain", "contribution", "necessity", "basis"), "domain_checks")
        for field in ("domain", "contribution", "basis"):
            _text(item[field], f"domain_checks.{field}")
        _enum(item["necessity"], ("necessary", "redundant", "uncertain"), "domain_checks.necessity")
        checked.append(item["domain"])
    _require(len(checked) == len(domains) and set(checked) == set(domains),
             "domain_checks: each declared domain must occur exactly once")
    _edges(obj["dependency_edges"])
    sources = {source["source_id"] for source in sample["review_bundle"].get("sources", [])}
    _claims(obj["claim_evidence"], pointers, sources)
    dimensions = obj["dimensions"]
    _object(dimensions, DIMENSIONS, "dimensions")
    _require(set(dimensions) == set(DIMENSIONS), "dimensions: expected exactly the five fixed keys")
    for name, dimension in dimensions.items():
        fields = ("status", "score", "reason", "evidence_pointers", "issues", "unknown_reason")
        _object(dimension, fields, name)
        _score(dimension["status"], dimension["score"], name)
        _text(dimension["reason"], f"{name}.reason")
        _pointers(dimension["evidence_pointers"], pointers, f"{name}.evidence_pointers")
        _texts(dimension["issues"], f"{name}.issues")
        if dimension["status"] == "unjudgeable":
            _enum(dimension["unknown_reason"], UNKNOWN_REASONS, f"{name}.unknown_reason")
        else:
            _require(dimension["unknown_reason"] is None, f"{name}: scored unknown_reason must be null")
    _list(obj["flags"], "flags")
    for flag in obj["flags"]:
        _object(flag, ("type", "status", "description", "evidence_pointers"), "flags")
        _enum(flag["type"], tuple(FLAG_DIMENSIONS), "flags.type")
        _enum(flag["status"], ("confirmed", "suspected"), "flags.status")
        _text(flag["description"], "flags.description")
        _pointers(flag["evidence_pointers"], pointers, "flags.evidence_pointers")
        _require(bool(flag["evidence_pointers"]), "flags: locate the reported issue with evidence_pointers")
        if flag["status"] == "confirmed":
            _not_passing(dimensions, FLAG_DIMENSIONS[flag["type"]], flag["type"])
    if answer["status"] in ("incorrect", "ambiguous", "unjudgeable"):
        _not_passing(dimensions, "correctness_evaluability", "answer_check")
    if any(item["necessity"] == "redundant" for item in obj["domain_checks"]):
        _not_passing(dimensions, "cross_domain_necessity", "redundant domain")
    audit = obj["necessity_audit"]
    _necessity_audit(audit, sample, pointers, dimensions["cross_domain_necessity"])
    necessity_flags = [flag for flag in obj["flags"]
                       if FLAG_DIMENSIONS[flag["type"]] == "cross_domain_necessity"]
    if (any(flag["status"] == "confirmed" for flag in necessity_flags)
            or any(item["necessity"] == "redundant" for item in obj["domain_checks"])):
        _require(audit["status"] == "verified_shortcut",
                 "confirmed shortcut/redundancy requires verified_shortcut audit")
    if (any(flag["status"] == "suspected" for flag in necessity_flags)
            or any(item["necessity"] == "uncertain" for item in obj["domain_checks"])):
        _require(audit["status"] in ("unresolved", "verified_shortcut"),
                 "unresolved necessity concern requires unresolved audit unless a shortcut is verified")
    if audit["status"] == "verified_shortcut":
        by_domain = {item["domain"]: item["necessity"] for item in obj["domain_checks"]}
        _require(all(by_domain[domain] == "redundant" for domain in audit["omitted_domains"]),
                 "verified omitted domains must be marked redundant")
    _texts(obj["stage1_revisions"], "stage1_revisions")
    _texts(obj["missing_information"], "missing_information")


def _not_passing(dimensions, dimension, issue):
    """Reject an explicit failure and a conflicting passing score."""
    value = dimensions[dimension]
    _require(value["status"] != "scored" or value["score"] < 3,
             f"contradiction: {issue} conflicts with passing {dimension}")


def _necessity_audit(audit, sample, pointers, dimension, recommended=False):
    """Enforce the declared audit/score contract, not semantic proof of a shortcut."""
    fields = ("status", "omitted_domains", "solution_sketch", "candidate_answer",
              "uniquely_determines_answer", "evidence_pointers", "basis")
    _object(audit, fields, "necessity_audit")
    _enum(audit["status"], ("verified_shortcut", "unresolved", "not_found"), "necessity_audit.status")
    _texts(audit["omitted_domains"], "necessity_audit.omitted_domains")
    domains = sample["review_bundle"]["declared_domains"]
    omitted = audit["omitted_domains"]
    _require(len(set(omitted)) == len(omitted) and set(omitted) <= set(domains),
             "necessity_audit: omitted domains must be unique declared domains")
    for field in ("solution_sketch", "basis"):
        _text(audit[field], f"necessity_audit.{field}")
    _require(audit["candidate_answer"] is None or isinstance(audit["candidate_answer"], str),
             "necessity_audit.candidate_answer: expected a string or null")
    unique = audit["uniquely_determines_answer"]
    _require(unique is None or type(unique) is bool,
             "necessity_audit.uniquely_determines_answer: expected boolean or null")
    # A solver's shortcut may cite only formally visible input, not hidden gold/materials.
    visible = _pointer_map(sample, blind=True)
    _pointers(audit["evidence_pointers"], visible, "necessity_audit.evidence_pointers")
    _require(bool(audit["evidence_pointers"]), "necessity_audit: locate the tested route or uncertainty")
    prefix = "recommended_" if recommended else ""
    status, score = dimension[prefix + "status"], dimension[prefix + "score"]
    if audit["status"] == "verified_shortcut":
        _require(bool(omitted) and unique is True, "verified shortcut must omit a domain and determine the answer")
        _text(audit["candidate_answer"], "verified shortcut candidate_answer")
        _require(status == "scored" and type(score) is int and 0 <= score < 3,
                 "verified shortcut requires a numeric necessity score from 0 through 2")
    elif audit["status"] == "unresolved":
        _require(status == "unjudgeable" and score is None,
                 "unresolved necessity requires unjudgeable/null, not a numeric score")
    else:
        _require(not omitted and unique is None,
                 "not_found requires empty omitted_domains and null uniquely_determines_answer")


def _adjudication(obj, sample, pointers):
    """Validate all dimension resolutions and the explicit human-review state."""
    fields = ("dimension_resolutions", "changes_from_independent", "unresolved_issues",
              "human_review_required", "human_review_reasons", "necessity_audit")
    _object(obj, fields, "adjudication")
    _require(set(obj) <= set(fields) | {"sample_id", "stage"}, "adjudication: unexpected fields")
    _list(obj["dimension_resolutions"], "dimension_resolutions")
    found = []
    for item in obj["dimension_resolutions"]:
        fields = ("dimension", "recommended_status", "recommended_score", "basis",
                  "review_p_assessment", "review_q_assessment")
        _object(item, fields, "dimension_resolutions")
        _enum(item["dimension"], DIMENSIONS, "dimension_resolutions.dimension")
        found.append(item["dimension"])
        _score(item["recommended_status"], item["recommended_score"], item["dimension"])
        for field in ("basis", "review_p_assessment", "review_q_assessment"):
            _text(item[field], f"dimension_resolutions.{field}")
    _require(len(found) == 5 and set(found) == set(DIMENSIONS), "dimension_resolutions: cover each dimension once")
    necessity = next(item for item in obj["dimension_resolutions"]
                     if item["dimension"] == "cross_domain_necessity")
    _necessity_audit(obj["necessity_audit"], sample, pointers, necessity, recommended=True)
    for field in ("changes_from_independent", "unresolved_issues", "human_review_reasons"):
        _texts(obj[field], field)
    _require(type(obj["human_review_required"]) is bool, "human_review_required: expected a boolean")
    if obj["human_review_required"]:
        _require(bool(obj["human_review_reasons"]), "human_review_reasons: required for human review")
    if obj["necessity_audit"]["status"] != "not_found" or obj["unresolved_issues"] or any(item["recommended_status"] == "unjudgeable"
                                      for item in obj["dimension_resolutions"]):
        _require(obj["human_review_required"], "contradiction: unresolved issues require human review")


def validate_output(stage, obj, sample):
    """Validate a parsed model output against the specified stage and sample.

    Args:
        stage: One of blind_structure, evidence_scoring, or adjudication.
        obj: Parsed JSON object returned by the model.
        sample: Prepared internal sample with visible and review_bundle objects.

    Raises:
        ValueError: The structure, evidence reference, quote, or score is invalid.
    """
    try:
        _enum(stage, STAGES, "stage")
        _object(obj, ("sample_id",), "output")
        _require(obj["sample_id"] == sample["sample_id"], "sample_id: mismatch")
        if stage != "adjudication" or "stage" in obj:
            _require(obj.get("stage") == stage, "stage: mismatch")
        pointers = _pointer_map(sample, blind=stage == "blind_structure")
        if stage == "blind_structure":
            _blind(obj, pointers)
        elif stage == "evidence_scoring":
            _evidence(obj, sample, pointers)
        else:
            _adjudication(obj, sample, pointers)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"Invalid LLM5 output or prepared sample: {exc}") from exc
