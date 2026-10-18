"""Expose a prepared market dossier for review, never as submission authority.

This read-only bridge is separate from the GitHub patch ready.json protocol.
Every referenced artifact must be contained in the checkout and hash-pinned by
an exact registry match. Missing, stale and inconsistent evidence stays visible.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from atlas.automation_compatibility import persistent_rejection_reason
from atlas.production_policy import evaluate_candidate


MAX_EVIDENCE_AGE_HOURS = 24


def market_handoff(root: Path, policy: dict, *, checked_at: datetime | None = None) -> dict:
    result = {"mission": None, "errors": []}
    checked_at = checked_at or datetime.now(timezone.utc)

    def load(relative, default):
        path = root / relative
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    try:
        router = load("results/internet_opportunity_router.json", {})
        cash = load("results/cash_first_market.json", {})
        selected = router.get("selected") or {}
        top = cash.get("top_cash_first") or {}
        candidate_id = selected.get("opportunity_id")
        if not candidate_id:
            return result
        if candidate_id != top.get("opportunity_id"):
            raise ValueError("market_selection_mismatch")
        metadata = selected.get("metadata") or {}
        if not metadata.get("submission_dossier_prepared"):
            return result
        if (selected.get("internet_opportunity_router") or {}).get("decision") not in {"execute_now", "prepare_then_gate"}:
            raise ValueError("market_selection_not_eligible")
        if top.get("decision_status") not in {"executable_now", "prepare_then_gate"}:
            raise ValueError("cash_selection_not_eligible")
        if selected.get("upstream_rejected") or (selected.get("decision") or {}).get("status") == "rejected":
            raise ValueError("market_selection_rejected")
        for value in (router.get("generated_at"), cash.get("generated_at"), selected.get("observed_at")):
            timestamp = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
            age = (checked_at - timestamp).total_seconds() / 3600
            if age < 0 or age > MAX_EVIDENCE_AGE_HOURS:
                raise ValueError("market_evidence_stale_or_future")
        rejected = load("config/persistent_opportunity_rejections.json", {"items": []})
        if persistent_rejection_reason(selected, rejected):
            raise ValueError("market_selection_persistently_rejected")
        context = dict(selected, estimated_effort_hours=metadata.get("estimated_effort_hours", selected.get("effort_hours")))
        if not evaluate_candidate(context, policy).allowed:
            raise ValueError("market_selection_blocked_by_production_policy")
        registry = load("config/prepared_opportunity_artifacts.json", {"items": []})
        matches = [entry for entry in registry["items"]
                   if entry.get("active") is not False
                   and entry.get("opportunity_id") == candidate_id
                   and entry.get("source_url") == selected.get("source_url")]
        if len(matches) != 1:
            raise ValueError("market_artifact_registry_match_missing_or_ambiguous")
        entry = matches[0]
        paths = entry.get("artifact_paths") or []
        hashes = entry.get("sha256") or {}
        if not paths or paths != metadata.get("prepared_artifacts"):
            raise ValueError("market_artifact_list_mismatch")
        for relative in paths:
            path = Path(relative)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("market_artifact_path_outside_checkout")
            path = (root / path).resolve()
            if not path.is_relative_to(root.resolve()):
                raise ValueError("market_artifact_path_outside_checkout")
            expected = hashes.get(relative, "")
            if not re.fullmatch(r"[0-9a-f]{64}", expected):
                raise ValueError("market_artifact_hash_missing")
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError("market_artifact_hash_mismatch")
        intents = load("results/degraded/intents.json", {"items": []})["items"]
        receipts = load("results/degraded/receipts.json", {"receipts": []})["receipts"]
        for relative in ("results/external_action_receipts.json", "results/submission_receipts.json"):
            receipts += load(relative, {"receipts": []})["receipts"]
        if any(item.get("candidate_id") == candidate_id for item in intents + receipts):
            raise ValueError("market_candidate_already_attempted_reconcile_first")
        result["mission"] = {
            "candidate_id": candidate_id,
            "candidate_url": selected.get("source_url"),
            "title": selected.get("title"),
            "artifact_paths": paths,
            "sha256": {path: hashes[path] for path in paths},
            "source_path": "results/internet_opportunity_router.json",
            "source_generated_at": router["generated_at"],
            "cash_generated_at": cash["generated_at"],
            "listing_observed_at": selected["observed_at"],
            "missing_receipt_registries": [relative for relative in (
                "results/degraded/intents.json", "results/degraded/receipts.json",
                "results/external_action_receipts.json", "results/submission_receipts.json")
                if not (root / relative).is_file()],
            "review_required": True,
            "validation_scope": "artifact_integrity_only_not_factual_acceptance_or_payment",
            "human_actions": top.get("human_actions") or [],
            "next_action": "review_existing_market_gate_without_resubmitting_or_repreparing",
            "submission_authorized": False,
            "external_submission_verified": False,
            "payment_verified": False,
        }
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        # Never turn a broken bridge into a silently empty, apparently healthy handoff.
        result["errors"].append(str(exc) if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError)
                                else type(exc).__name__)
    return result
