#!/usr/bin/env python3
"""Read public counterparty evidence and reconcile accepted/queued/paid states."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
from typing import Any
from urllib.parse import quote
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from atlas.external_outcome_reconciliation import (
    apply_summary_to_ledger,
    github_comments_api_url,
    reconcile_receipts,
    wallet_settlement_view,
)

RESULTS = ROOT / "results"
RECEIPTS_PATH = RESULTS / "external_action_receipts.json"
LEDGER_PATH = RESULTS / "monetization.json"
STATE_PATH = RESULTS / "external_outcome_reconciliation.json"
HEALTH_PATH = RESULTS / "external_outcome_health.json"


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def get_json(url: str) -> Any:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json, application/json",
            "User-Agent": "Louis-OS-External-Outcome-Reconciler/1.0",
        },
    )
    with urlopen(request, timeout=25) as response:  # nosec B310: URLs are constructed from strict allowlists
        return json.load(response)


def _balance(payload: Any) -> float | None:
    if not isinstance(payload, dict):
        return None
    for key in ("amount_rtc", "balance_rtc", "balance", "amount"):
        if payload.get(key) is None or isinstance(payload[key], bool):
            continue
        try:
            value = float(payload[key])
            if math.isfinite(value) and value >= 0:
                return value
        except (TypeError, ValueError):
            continue
    return None


def _error_code(exc: Exception) -> str:
    # Do not put response bodies, request headers or arbitrary exception text
    # in persisted diagnostics. The source and error class identify the fault.
    if isinstance(exc, HTTPError):
        return f"HTTP_{exc.code}"
    return type(exc).__name__


def _health_fingerprint(health: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": health.get("status"),
        "sources": {
            key: {field: row.get(field) for field in ("status", "error")}
            for key, row in health.get("sources", {}).items()
        },
    }


def main() -> int:
    checked_at = datetime.now(timezone.utc).isoformat()
    receipts = load_json(RECEIPTS_PATH, {"receipts": []})
    ledger = load_json(LEDGER_PATH, {})
    comments_by_target: dict[str, list[dict[str, Any]]] = {}
    balances: dict[str, float] = {}
    errors: list[str] = []
    previous_health = load_json(HEALTH_PATH, {})
    sources: dict[str, dict[str, Any]] = {}

    def record_source(key: str, *, error: str | None = None) -> None:
        previous = previous_health.get("sources", {}).get(key, {})
        sources[key] = {
            "status": "error" if error else "ok",
            "error": error,
            "checked_at": checked_at,
            "last_success_at": previous.get("last_success_at") if error else checked_at,
        }
        if error:
            errors.append(f"{key}:{error}")

    targets = sorted(
        {
            str(row.get("target_url") or "")
            for row in receipts.get("receipts") or []
            if isinstance(row, dict) and github_comments_api_url(str(row.get("target_url") or ""))
        }
    )
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(targets)))) as pool:
        pending_comments = {
            pool.submit(get_json, api_url): target
            for target in targets
            if (api_url := github_comments_api_url(target))
        }
        for future in as_completed(pending_comments):
            target = pending_comments[future]
            try:
                payload = future.result()
                if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
                    record_source(f"comments:{target}", error="INVALID_COMMENTS_PAYLOAD")
                    continue
                comments_by_target[target] = payload
                record_source(f"comments:{target}")
            except Exception as exc:
                record_source(f"comments:{target}", error=_error_code(exc))

    wallets = sorted(
        {
            str(row.get("payout_wallet") or "").strip()
            for row in receipts.get("receipts") or []
            if isinstance(row, dict) and str(row.get("payout_wallet") or "").startswith("RTC")
        }
    )
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(wallets)))) as pool:
        pending_balances = {
            pool.submit(
                get_json,
                f"https://rustchain.org/wallet/balance?miner_id={quote(wallet, safe='')}",
            ): wallet
            for wallet in wallets
        }
        for future in as_completed(pending_balances):
            wallet = pending_balances[future]
            try:
                value = _balance(future.result())
                if value is not None:
                    balances[wallet] = value
                    record_source(f"wallet:{wallet}")
                else:
                    record_source(f"wallet:{wallet}", error="INVALID_WALLET_BALANCE")
            except Exception as exc:
                record_source(f"wallet:{wallet}", error=_error_code(exc))

    errors.sort()
    fresh_wallets = sorted(balances)
    wallet_observation_complete = bool(wallets) and fresh_wallets == wallets

    # A transient wallet outage must not look like an economic transition.  If
    # the probe fails, retain the last authoritative balance until a new value
    # is observed successfully.
    previous_state = load_json(STATE_PATH, {})
    previous_semantic = (
        previous_state.get("semantic") if isinstance(previous_state.get("semantic"), dict) else {}
    )
    previous_balances = previous_semantic.get("wallet_balances_rtc")
    cached_wallets: list[str] = []
    if isinstance(previous_balances, dict):
        for wallet, value in previous_balances.items():
            if wallet not in balances:
                try:
                    cached = _balance({"balance": value})
                    if cached is not None:
                        balances[str(wallet)] = cached
                        cached_wallets.append(str(wallet))
                except (TypeError, ValueError):
                    pass

    reconciled_receipts, summary = reconcile_receipts(
        receipts,
        comments_by_target=comments_by_target,
        wallet_balances_rtc=balances,
        checked_at=checked_at,
    )
    summary.update(wallet_settlement_view(ledger, summary))
    semantic = dict(summary)
    updated_ledger = apply_summary_to_ledger(
        ledger, summary, checked_at=checked_at,
        wallet_observation_complete=wallet_observation_complete,
    )
    # Recovery can verify the same balance that was previously cached. Do not
    # lose that transition just because the aggregate numbers did not change.
    wallet_transition = wallet_observation_complete and any(
        updated_ledger.get(key) != ledger.get(key)
        for key in (
            "rustchain_wallet_balance_rtc", "last_external_wallet_balance_rtc",
            "revenue_received_rtc", "payouts_received_verified", "crypto_payment_verified",
            "rustchain_aggregate_wallet_settlement_verified",
        )
    )
    changed = semantic != previous_state.get("semantic") or wallet_transition

    if changed:
        reconciled_receipts["updated_at"] = checked_at
        save_json(RECEIPTS_PATH, reconciled_receipts)
        save_json(LEDGER_PATH, updated_ledger)
        save_json(
            STATE_PATH,
            {
                "schema_version": "1.0",
                "changed_at": checked_at,
                "semantic": semantic,
                "errors_at_change": errors,
                "truth_policy": (
                    "Acceptance and queued payout are not payment. RTC is not EUR revenue without verified liquidity."
                ),
            },
        )

    health = {
        "schema_version": "1.0",
        "status": "degraded" if errors else "healthy" if sources else "no_sources",
        "checked_at": checked_at,
        "sources": dict(sorted(sources.items())),
        "sources_expected": len(sources),
        "sources_successful": sum(row["status"] == "ok" for row in sources.values()),
        "errors": errors,
        "fresh_wallets": fresh_wallets,
        "cached_wallets": sorted(cached_wallets),
        "wallet_evidence_fresh": wallet_observation_complete,
    }
    health_changed = _health_fingerprint(health) != _health_fingerprint(previous_health)
    # Persist probe health independently of an economic transition. Stable
    # failures do not produce repeated commits; each run keeps a fresh artifact.
    save_json(HEALTH_PATH, health)
    output = {
        "changed": changed, **summary, "errors": errors, "checked_at": checked_at,
        "health_changed": health_changed, "health": health,
        "wallet_evidence_fresh": wallet_observation_complete,
    }
    print(json.dumps(output, ensure_ascii=False))
    return 0 if health["status"] == "healthy" else 2


if __name__ == "__main__":
    raise SystemExit(main())
