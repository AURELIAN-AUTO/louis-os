#!/usr/bin/env python3
"""Refresh official simple-mission sources and merge them into market evidence."""
from __future__ import annotations

from dataclasses import asdict, fields
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from atlas.agentpact_need_source import AgentPactNeedsSource
from atlas.bountybook_agent_source import BountyBookAgentJobsSource
from atlas.guru_simple_mission_source import GuruPublicJobsSource
from atlas.superteam_agent_source import SuperteamAgentListingsSource
from atlas.moltjobs_agent_source import MoltJobsAgentJobsSource
from atlas.simple_mission_sources import FreelancerPublicJobsSource
from atlas.software_micro_missions import SoftwareFreelancerPublicJobsSource
from atlas.truelancer_simple_mission_source import TruelancerPublicJobsSource
from atlas.universal_market import CapabilityRegistry, InternetOpportunity, SourceState, UniversalMarketEngine

RESULTS = ROOT / "results"
MARKET_PATH = RESULTS / "universal_market_opportunities.json"
CYCLE_PATH = RESULTS / "universal_market_cycle.json"
BACKLOG_PATH = RESULTS / "capability_backlog.json"
RECEIPT_PATH = RESULTS / "simple_mission_source_refresh.json"
CAPABILITIES_PATH = ROOT / "config" / "universal_capabilities.json"
MAX_RECEIPT_OPPORTUNITIES = 80
ROUTER_PATH = RESULTS / "internet_opportunity_router.json"


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def opportunity_from_dict(item: Mapping[str, Any]) -> InternetOpportunity:
    names = {field.name for field in fields(InternetOpportunity)}
    payload = {name: item.get(name) for name in names}
    for name in ("payment_evidence", "required_capabilities", "evidence"):
        payload[name] = tuple(payload.get(name) or [])
    payload["metadata"] = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    return InternetOpportunity(**payload)


def opportunity_to_dict(item: InternetOpportunity, source_id: str) -> dict[str, Any]:
    payload = asdict(item)
    for name in ("payment_evidence", "required_capabilities", "evidence"):
        payload[name] = list(payload.get(name) or [])
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    metadata = dict(metadata)
    metadata.setdefault("collector_source_id", source_id)
    payload["metadata"] = metadata
    payload["source_id"] = str(payload.get("source_id") or source_id)
    payload["collector_source_id"] = source_id
    return payload


def source_state_from_dict(item: Mapping[str, Any]) -> SourceState:
    return SourceState(
        source_id=str(item.get("source_id") or ""),
        category=str(item.get("category") or ""),
        status=str(item.get("status") or ""),
        reason=str(item.get("reason") or ""),
        evidence=tuple(str(value) for value in item.get("evidence") or []),
        observed_count=int(item.get("observed_count") or 0),
    )


def select_detailed_rows(
    source_results: list[tuple[list[InternetOpportunity], SourceState]],
    *,
    maximum: int = MAX_RECEIPT_OPPORTUNITIES,
) -> list[dict[str, Any]]:
    """Persist a source-balanced receipt instead of starving later adapters."""
    selected: list[dict[str, Any]] = []
    positions = [0 for _ in source_results]
    while len(selected) < maximum:
        progressed = False
        for index, (rows, state) in enumerate(source_results):
            if positions[index] >= len(rows):
                continue
            selected.append(opportunity_to_dict(rows[positions[index]], state.source_id))
            positions[index] += 1
            progressed = True
            if len(selected) >= maximum:
                break
        if not progressed:
            break
    return selected


def collect_with_source_pivot(
    sources: list[Any], router: Any, previous_receipt: Any,
    *, now: datetime | None = None,
) -> tuple[list[tuple[list[InternetOpportunity], SourceState]], dict[str, Any]]:
    """Apply one reversible source pause; never invent or activate a new adapter.

    The router's aggregate rejection threshold is a trigger, not a count of
    distinct historical missions for any individual source. Only its measured
    zero-eligible sources are candidates, and a new snapshot cannot pause the
    same source twice consecutively. Replaying one snapshot is idempotent.
    """
    now = now or datetime.now(timezone.utc)
    receipt: dict[str, Any] = {
        "status": "not_applied", "router_generated_at": None,
        "paused_source_id": None, "continued_source_ids": [], "errors": [],
        "replacement_status": "existing_reviewed_sources_only_no_new_source_activated",
        "economic_effect": "unmeasured_not_submission_or_revenue",
    }
    router = router if isinstance(router, dict) else {}
    previous_receipt = previous_receipt if isinstance(previous_receipt, dict) else {}
    previous = previous_receipt.get("source_pivot")
    previous = previous if isinstance(previous, dict) else {}
    timestamp = router.get("generated_at")
    receipt["router_generated_at"] = timestamp
    fresh = False
    try:
        generated = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        if generated.tzinfo is None or not 0 <= (now - generated).total_seconds() <= 86400:
            raise ValueError("router timestamp outside freshness window")
        fresh = True
    except (TypeError, ValueError, OverflowError):
        receipt["errors"].append("router_evidence_missing_invalid_stale_or_future")

    metrics = router.get("source_metrics")
    if not isinstance(metrics, dict):
        receipt["errors"].append("router_source_metrics_missing_or_invalid")
        metrics = {}
    candidates = []
    if fresh and router.get("next_pivot") == "pause_source_and_replace":
        for source in sources:
            metric = metrics.get(source.source_id)
            if metric is None:
                continue  # unmeasured is not evidence of zero yield
            if (not isinstance(metric, dict)
                    or type(metric.get("seen")) is not int
                    or type(metric.get("eligible")) is not int
                    or not 0 <= metric["eligible"] <= metric["seen"]):
                receipt["errors"].append(f"invalid_source_metric:{source.source_id}")
                continue
            if metric["seen"] <= 0 or metric["eligible"] != 0:
                continue
            if (previous.get("router_generated_at") != timestamp
                    and previous.get("paused_source_id") == source.source_id):
                continue
            candidates.append((-metric["seen"], source.source_id))
    paused = min(candidates)[1] if candidates else None
    if paused:
        receipt.update(status="applied_source_pause", paused_source_id=paused,
                       measured_source_sample=dict(metrics[paused]))
        prior_sources = previous_receipt.get("sources")
        prior_sources = prior_sources if isinstance(prior_sources, list) else []
        prior_state = next((row for row in prior_sources
                            if isinstance(row, dict) and row.get("source_id") == paused), None)
        receipt["previous_source_observation"] = {
            "generated_at": previous_receipt.get("generated_at"),
            "source_state": prior_state,
            "current_probe_performed": False,
        }
    results = []
    for source in sources:
        if source.source_id == paused:
            results.append(([], SourceState(
                source_id=source.source_id, category=source.source_category,
                status="paused_by_router",
                reason="One-cycle zero-eligible source pause; not a successful or empty probe.",
                evidence=("results/internet_opportunity_router.json",), observed_count=0,
            )))
        else:
            receipt["continued_source_ids"].append(source.source_id)
            results.append(source.collect())
    return results, receipt


def capability_issue_payload(gap: Mapping[str, Any]) -> dict[str, str]:
    capability_id = str(gap["capability_id"])
    specification = gap.get("specification") or {}
    marker = str(gap.get("marker") or f"<!-- louis-capability-gap:{capability_id} -->")
    body = "\n".join(
        [
            marker,
            "## Market-backed objective",
            str(specification.get("objective") or ""),
            "",
            f"- Priority score: {gap.get('priority_score')}",
            f"- Referenced market value: {gap.get('market_value')}",
            f"- Originating opportunity IDs: {', '.join(gap.get('originating_opportunity_ids') or [])}",
            f"- Market evidence: {specification.get('originating_market_url')}",
            "",
            "## Required interface",
            "```json",
            json.dumps(specification.get("required_interface") or {}, indent=2, ensure_ascii=False),
            "```",
            "",
            "## Acceptance tests",
            *[f"- [ ] {value}" for value in specification.get("acceptance_tests") or []],
            "",
            "## Promotion and budget",
            f"- {specification.get('promotion_rule')}",
            f"- {specification.get('budget_rule')}",
            "",
            "## Mandatory continuation",
            str(specification.get("retry_action") or "Re-run universal market qualification after promotion."),
            "",
            "No external submission, account creation, legal acceptance or revenue claim is authorized by this internal issue.",
        ]
    )
    return {"title": f"Capability gap: {capability_id}", "body": body, "marker": marker}


def main() -> int:
    market = load_json(MARKET_PATH, {})
    if not isinstance(market, Mapping) or not isinstance(market.get("opportunities"), list):
        raise SystemExit("universal market evidence is missing or invalid")

    opportunities = [opportunity_from_dict(item) for item in market.get("opportunities", []) if isinstance(item, Mapping)]
    existing_states = [
        source_state_from_dict(item) for item in market.get("source_states", []) if isinstance(item, Mapping)
    ]
    source_results, source_pivot = collect_with_source_pivot(
        [SuperteamAgentListingsSource(), BountyBookAgentJobsSource(),
         AgentPactNeedsSource(), MoltJobsAgentJobsSource(),
         FreelancerPublicJobsSource(), SoftwareFreelancerPublicJobsSource(),
         GuruPublicJobsSource(), TruelancerPublicJobsSource()],
        load_json(ROUTER_PATH, {}), load_json(RECEIPT_PATH, {}),
    )

    refreshed_ids = {state.source_id for _, state in source_results}
    # A paused or failed refresh must not silently revive an older source row.
    opportunities = [row for row in opportunities if row.source_id not in refreshed_ids]
    states = [state for state in existing_states if state.source_id not in refreshed_ids]
    for rows, state in source_results:
        opportunities.extend(rows)
        states.append(state)
    detailed_rows = select_detailed_rows(source_results)

    evaluation = UniversalMarketEngine(CapabilityRegistry.from_file(CAPABILITIES_PATH)).evaluate(opportunities, states)
    payload = evaluation.to_dict()
    payload["mission_prompt"] = market.get("mission_prompt")
    payload["mission_prompt_sha256"] = market.get("mission_prompt_sha256")
    save_json(MARKET_PATH, payload)

    issue_payloads = [capability_issue_payload(item) for item in payload["capability_gaps"]]
    save_json(
        BACKLOG_PATH,
        {
            "schema_version": "1.0",
            "generated_at": payload["generated_at"],
            "count": len(issue_payloads),
            "items": [
                {**gap, "issue": issue}
                for gap, issue in zip(payload["capability_gaps"], issue_payloads, strict=True)
            ],
        },
    )

    decision_counts = payload["decision_counts"]
    cycle = load_json(CYCLE_PATH, {})
    cycle.update(
        {
            "generated_at": payload["generated_at"],
            "sources_total": len(states),
            "sources_ok_or_partial": sum(state.status in {"ok", "partial"} for state in states),
            "sources_credential_gated": sum("credential" in state.status for state in states),
            "opportunities_observed": len(payload["opportunities"]),
            "opportunities_executable_now": decision_counts["executable_now"],
            "opportunities_prepare_then_gate": decision_counts["prepare_then_gate"],
            "opportunities_capability_build": decision_counts["capability_build"],
            "opportunities_rejected": decision_counts["rejected"],
            "capability_gaps_created": len(payload["capability_gaps"]),
            "simple_mission_sources_refreshed": sorted(refreshed_ids),
            "simple_mission_opportunities_observed": sum(state.observed_count for _, state in source_results),
            "simple_mission_detailed_opportunities_persisted": len(detailed_rows),
            "next_action": (
                "prepare_simple_mission_proposal_dossiers"
                if decision_counts["prepare_then_gate"]
                else "build_highest_priority_market_backed_capability"
                if payload["capability_gaps"]
                else "activate_next_authorized_official_source"
            ),
        }
    )
    evidence = list(cycle.get("evidence") or [])
    relative = str(RECEIPT_PATH.relative_to(ROOT))
    if relative not in evidence:
        evidence.append(relative)
    cycle["evidence"] = evidence
    save_json(CYCLE_PATH, cycle)

    receipt = {
        "schema_version": "1.1",
        "generated_at": payload["generated_at"],
        "source_pivot": source_pivot,
        "sources": [
            {
                "source_id": state.source_id,
                "status": state.status,
                "reason": state.reason,
                "observed_count": state.observed_count,
                "detailed_count": sum(1 for row in detailed_rows if row.get("collector_source_id") == state.source_id),
                "evidence": list(state.evidence),
            }
            for _, state in source_results
        ],
        "opportunities": detailed_rows,
        "opportunities_observed": sum(state.observed_count for _, state in source_results),
        "detailed_opportunities_persisted": len(detailed_rows),
        "external_submissions_verified": 0,
        "revenue_verified_eur": 0.0,
    }
    save_json(RECEIPT_PATH, receipt)
    print(json.dumps(receipt, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
