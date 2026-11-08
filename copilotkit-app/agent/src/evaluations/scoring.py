"""Explicit deterministic checks; no fabricated semantic-judge scores."""
from decimal import Decimal, InvalidOperation
import math
import re


def percentile(values, probability):
    if not values: return None
    ordered = sorted(values); position = (len(ordered)-1)*probability
    low = math.floor(position); high = math.ceil(position)
    return round(ordered[low] + (ordered[high]-ordered[low])*(position-low), 3)


def assess(case, output):
    expected = case["expected"]; checks = {}; metrics = {}
    hits = output.get("citations", [])
    if case["target"] in {"retrieval", "agent", "graph"}:
        checks["citations_valid"] = output.get("invalid_citations", 0) == 0
        checks["no_date_leak"] = output.get("date_leaks", 0) == 0
        metrics["citation_count"] = len(hits)
        metrics["citation_validity"] = max(0,(len(hits)-output.get("invalid_citations", 0))/len(hits)) if hits else None
        pages = {(p["document_id"], p["page_number"]) for p in expected.get("pages", [])}
        retrieved = {(p["document_id"], p["page_number"]) for p in hits[:5]}
        if pages:
            metrics["recall_at_5" if case["target"] == "retrieval" else "cited_page_coverage"] = len(pages & retrieved)/len(pages)
            checks["expected_pages_at_5"] = pages <= retrieved
    if expected.get("minimum_edges") is not None:
        checks["minimum_edges"] = output.get("edge_count", 0) >= expected["minimum_edges"]
    if expected.get("number"):
        value = expected["number"]; actual = output.get("calculation", {})
        try: checks["numeric_tolerance"] = abs(Decimal(str(actual["value"]))-Decimal(str(value["value"]))) <= Decimal(str(value["tolerance"]))
        except (KeyError, InvalidOperation): checks["numeric_tolerance"] = False
        for field in ("currency", "unit", "period_start", "period_end"):
            if value.get(field): checks[field] = str(actual.get(field, "")) == value[field]
    refusal = expected.get("refusal", "not_scored")
    if refusal != "not_scored":
        # This is an explicitly labeled lexical classification, not semantic accuracy.
        abstained = bool(re.search(r"insufficient|cannot (?:verify|determine|answer)|not enough evidence|no (?:eligible |matching )?evidence|证据不足|无法(?:核实|判断|回答)|资料不足|未找到", output.get("answer", ""), re.I))
        checks["lexical_refusal"] = abstained == (refusal == "must_abstain")
        metrics["refusal_classifier"] = "lexical-v1; inspect output for semantic interpretation"
    if case["target"] == "task_list": checks["list_contract"] = output.get("list_valid", False)
    meaningful = bool(hits or expected.get("pages") or expected.get("number") or expected.get("minimum_edges") is not None or refusal != "not_scored" or case["target"] == "task_list")
    scoring = meaningful and bool(checks) and not expected.get("manual_review_required",False)
    return {"checks": checks, "metrics": metrics, "passed": scoring and all(checks.values()),
        "scored": scoring, "manual_review_required":expected.get("manual_review_required",False),
        "notice": "Deterministic checks only; source validity is not semantic entailment. Unspecified or unadapted imported rules are not scored."}


def aggregate(items):
    counts = {status: sum(x["status"] == status for x in items) for status in
        ("pending", "in_flight", "passed", "failed", "unscored", "error", "timeout", "unsupported", "budget_exceeded", "cancelled", "interrupted")}
    finished = [x for x in items if x["status"] not in {"pending", "in_flight"}]
    samples = [float(x["elapsed_ms"]) for x in finished if x.get("elapsed_ms") is not None]
    recalls = [x["metrics"]["recall_at_5"] for x in items if x.get("metrics", {}).get("recall_at_5") is not None]
    tokens = [x.get("usage", {}).get("total_tokens") for x in items if x.get("model_calls", 0)]
    def stage(name):
        values=[float(x[name]) for x in finished if x.get(name) is not None]
        return {"samples":len(values),"p50_ms":percentile(values,.5),"p95_ms":percentile(values,.95)}
    return {"total": len(items), "finished": len(finished), "counts": counts,
        "pass_rate_all": counts["passed"]/len(items) if items else None,
        "recall_at_5": sum(recalls)/len(recalls) if recalls else None, "recall_samples": len(recalls),
        "latency": {"samples": len(samples), "p50_ms": percentile(samples, .5), "p95_ms": percentile(samples, .95), "raw_ms": samples},
        "stages": {"retrieval":stage("retrieval_ms"), "model":stage("model_ms")},
        "model_calls": sum(x.get("model_calls", 0) for x in items),
        "reported_tokens": sum(t for t in tokens if t is not None) if any(t is not None for t in tokens) else None,
        "usage_unknown_attempts": sum(t is None for t in tokens),
        "unreported_calls": sum(max(0,x.get("model_calls",0)-x.get("reported_calls",0)) for x in items),
        "denominator": "All planned attempts, including failures, unsupported, cancelled and budget-limited cases. Pending results are not final."}
