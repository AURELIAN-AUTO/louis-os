#!/usr/bin/env python3
"""Reconcile the two existing Taskmarket deliveries using anonymous public GETs.

No CLI, wallet, signature, credentials, cloud VM, paid request or external write.
Public award observations are not independent payment verification.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

API = "https://api.taskmarket.dev/api/tasks/"
WALLET = "0xCB5e092121C0dc63e62d215b8B8ceFf8a1a96c0C"
CLAIMS = (
    ("blue_square_arcade", "0x34a65b919752f9b4500aae1574f44865a92c1b625e77c9a72741370c0daadccc", "99cba5cc-7c8a-4fd2-97ea-492df2ef1eb3"),
    ("rooftop_world_2030", "0xb4e0e2150a5b69a781769fe71f9092de3cffe978a03fd7286ebd408b99b152e3", "3761b8e9-22ed-4d4c-ada8-b3a9c687e6a5"),
)
ALLOWED_URLS = frozenset(API + task + suffix for _, task, _ in CLAIMS for suffix in ("", "/submissions"))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("redirect_refused")


def fetch_public(url: str) -> Any:
    if url not in ALLOWED_URLS:
        raise ValueError("endpoint_not_allowed")
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "Louis-OS-public-followup/1.0"}, method="GET")
    with build_opener(NoRedirect()).open(request, timeout=15) as response:
        raw = response.read(3_000_001)
    if len(raw) > 3_000_000:
        raise ValueError("response_too_large")
    return json.loads(raw)


def amount_usdc(value: Any) -> float | None:
    try:
        value = Decimal(str(value))
        return float(value / 1_000_000) if value.is_finite() and value >= 0 else None
    except (InvalidOperation, ValueError):
        return None


def build_snapshot(fetcher: Callable[[str], Any] = fetch_public, *, checked_at: str | None = None) -> dict[str, Any]:
    errors: list[str] = []
    claims = []
    for label, task_id, submission_id in CLAIMS:
        task_url = API + task_id
        task, submissions = None, None
        for suffix in ("", "/submissions"):
            try:
                payload = fetcher(task_url + suffix)
                if not suffix:
                    if (not isinstance(payload, dict) or payload.get("id") != task_id
                            or not isinstance(payload.get("status"), str)):
                        raise ValueError("invalid_task_schema_or_identity")
                    task = payload
                else:
                    if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
                        raise ValueError("invalid_submissions_schema")
                    submissions = payload
            except Exception as exc:
                # Do not log raw response bodies, exception URLs or credentials.
                code = f"HTTP_{exc.code}" if isinstance(exc, HTTPError) else type(exc).__name__
                errors.append(f"{label}:{'submissions' if suffix else 'task'}:{code}")
        task = task or {}
        own = next((row for row in submissions or [] if row.get("id") == submission_id), None)
        if own and (str(own.get("workerAddress", "")).lower() != WALLET.lower()
                    or own.get("taskId") != task_id):
            errors.append(f"{label}:submission_identity_mismatch")
            own = None
            submissions = None
        visibility = task.get("submissionVisibility")
        found = True if own else False if submissions is not None and visibility == "public" else None
        if found is None:
            errors.append(f"{label}:own_submission_visibility_or_read_unknown")
        awards = task.get("awards")
        awards_valid = isinstance(awards, list) and all(
            isinstance(row, dict) and isinstance(row.get("workerAddress"), str)
            for row in awards
        )
        if not awards_valid:
            errors.append(f"{label}:awards_unknown")
            awards = []
        own_awards = [row for row in awards if row["workerAddress"].lower() == WALLET.lower()]
        selected = (bool(own_awards) or str(task.get("winner", "")).lower() == WALLET.lower()
                    or str((own or {}).get("status", "")).lower() in {"accepted", "winner", "won", "paid"})
        settled_refs = sorted({str(row["settlementTxHash"]) for row in awards if row.get("settlementTxHash")})
        outcome = "selection_observed_verify_payment" if selected else (
            "completed_without_own_award_observed"
            if task.get("status") == "completed" and awards_valid and awards and found is True
            else "unknown" if not task or found is None or not awards_valid
            else "no_selection_observed"
        )
        claims.append({
            "label": label, "task_id": task_id, "submission_id": submission_id,
            "task_status": task.get("status", "unknown"),
            "task_reward_usdc": amount_usdc(task.get("reward")),
            "task_expiry": task.get("expiryTime"), "own_submission_found": found,
            "own_submission_status": (own or {}).get("status"),
            "own_submission_rejected_at": (own or {}).get("rejectedAt"),
            "task_winner": task.get("winner"), "selection_signal": selected,
            "submission_outcome": outcome, "awards_observed": len(awards) if awards_valid else None,
            "own_awards_observed": len(own_awards) if awards_valid else None,
            "award_settlement_references": settled_refs,
            "own_submission_evidence": {key: own.get(key) for key in ("id", "workerAddress", "submittedAt", "deliverableHash", "submitTxHash")} if own else None,
            "evidence_urls": [task_url, task_url + "/submissions"],
        })
    return {
        "schema_version": "2.0", "platform": "taskmarket", "worker_wallet": WALLET,
        "wallet_balance_usdc": None, "wallet_balance_verification": "not_read_public_monitor",
        "claims": claims, "claim_count": len(claims),
        "selection_signal_any": any(row["selection_signal"] for row in claims),
        "payout_evidence_candidate": any(row["own_awards_observed"] for row in claims),
        "payment_verified": False, "revenue_confirmed_eur": None,
        "errors": sorted(set(errors)), "monitor_healthy": not errors,
        "checked_at": checked_at or datetime.now(timezone.utc).isoformat(),
        "monitoring_mode": "anonymous_public_get_only_without_vm",
        "coverage": "Public task/submission/award observations only; no wallet balance or independent settlement verification.",
        "revenue_policy": "No award for this wallet observed is not a formal rejection. An API award is not an independently verified payment. Unknowns are not zero balances.",
    }


def semantic(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Exclude only probe time; unchanged reads do not create repeated commits."""
    return {key: value for key, value in snapshot.items() if key != "checked_at"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    snapshot = build_snapshot()
    args.output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"monitor_healthy": snapshot["monitor_healthy"], "errors": snapshot["errors"], "claims": len(snapshot["claims"])}))


if __name__ == "__main__":
    main()
