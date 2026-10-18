from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from scripts import reconcile_external_outcomes as probe


WALLET = "RTC-test-wallet"
TARGET = "https://github.com/Scottcjn/rustchain-bounties/issues/12442"


class ExternalOutcomeProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        for name, filename in (
            ("RECEIPTS_PATH", "receipts.json"), ("LEDGER_PATH", "ledger.json"),
            ("STATE_PATH", "state.json"), ("HEALTH_PATH", "health.json"),
        ):
            patcher = patch.object(probe, name, root / filename)
            patcher.start()
            self.addCleanup(patcher.stop)
        probe.save_json(probe.RECEIPTS_PATH, {"receipts": [{
            "action_id": "accepted-test", "target_url": TARGET,
            "payout_wallet": WALLET, "accepted_verified": True,
            "accepted_reward_rtc": 3.0, "payout_status": "queued",
        }]})
        probe.save_json(probe.LEDGER_PATH, {
            "revenue_confirmed_eur": 0.0, "revenue_received": 0.0,
            "rustchain_wallet_baseline_rtc": 0.0,
            "rustchain_wallet_balance_verified_at": "2026-08-24T00:00:00Z",
            "rustchain_wallet_balance_rtc": 11.0,
            "revenue_received_rtc": 11.0,
            "payouts_received_verified": 1,
        })

    def run_probe(self, *, comments=None, balance=None) -> tuple[int, dict]:
        def getter(url: str):
            value = comments if "api.github.com" in url else balance
            if isinstance(value, Exception):
                raise value
            return value

        out = io.StringIO()
        with patch.object(probe, "get_json", side_effect=getter), redirect_stdout(out):
            code = probe.main()
        return code, json.loads(out.getvalue())

    def test_404_is_degraded_even_without_an_economic_transition(self) -> None:
        error = HTTPError(TARGET, 404, "private response text", {}, None)
        code, first = self.run_probe(comments=error, balance={"balance": 11})
        self.assertEqual(code, 2)
        self.assertEqual(first["health"]["status"], "degraded")
        self.assertEqual(first["health"]["sources_successful"], 1)
        self.assertEqual(first["errors"], [f"comments:{TARGET}:HTTP_404"])
        self.assertNotIn("private response text", json.dumps(first))
        code, second = self.run_probe(comments=error, balance={"balance": 11})
        self.assertEqual(code, 2)
        self.assertFalse(second["changed"])
        self.assertFalse(second["health_changed"])
        self.assertEqual(probe.load_json(probe.HEALTH_PATH, {})["status"], "degraded")

    def test_recovery_is_a_health_transition_without_new_money(self) -> None:
        self.run_probe(comments=HTTPError(TARGET, 404, "missing", {}, None), balance={"balance": 11})
        code, result = self.run_probe(comments=[], balance={"balance": 11})
        self.assertEqual(code, 0)
        self.assertTrue(result["health_changed"])
        self.assertFalse(result["changed"])
        self.assertEqual(result["health"]["status"], "healthy")
        self.assertTrue(result["health"]["sources"][f"comments:{TARGET}"]["last_success_at"])
        self.assertEqual(probe.load_json(probe.LEDGER_PATH, {})["revenue_confirmed_eur"], 0)

    def test_invalid_wallet_payload_cannot_renew_cached_verification(self) -> None:
        self.run_probe(comments=[], balance={"balance": 11})
        ledger = probe.load_json(probe.LEDGER_PATH, {})
        verified_at = ledger["rustchain_wallet_balance_verified_at"]
        # A new authoritative acceptance changes the economic summary while
        # the wallet read fails. That must not renew the cached wallet proof.
        receipts = probe.load_json(probe.RECEIPTS_PATH, {})
        receipts["receipts"].append({
            "action_id": "second", "target_url": TARGET, "payout_wallet": WALLET,
            "accepted_verified": True, "accepted_reward_rtc": 30, "payout_status": "queued",
        })
        probe.save_json(probe.RECEIPTS_PATH, receipts)
        code, result = self.run_probe(comments=[], balance={"message": "service unavailable"})
        current = probe.load_json(probe.LEDGER_PATH, {})
        self.assertEqual(code, 2)
        self.assertTrue(result["changed"])
        self.assertFalse(result["wallet_evidence_fresh"])
        self.assertEqual(result["health"]["cached_wallets"], [WALLET])
        self.assertEqual(current["rustchain_wallet_balance_verified_at"], verified_at)
        self.assertEqual(current["revenue_received_rtc"], ledger["revenue_received_rtc"])
        self.assertEqual(current["payouts_received_verified"], ledger["payouts_received_verified"])
        self.assertEqual(current["revenue_confirmed_eur"], 0)

    def test_comment_schema_error_is_not_an_authoritative_empty_list(self) -> None:
        code, result = self.run_probe(comments={"message": "unavailable"}, balance={"balance": 11})
        self.assertEqual(code, 2)
        self.assertIn(f"comments:{TARGET}:INVALID_COMMENTS_PAYLOAD", result["errors"])
        self.assertEqual(result["accepted_count"], 1)

    def test_wallet_failure_keeps_last_success_time_and_historical_balance(self) -> None:
        self.run_probe(comments=[], balance={"balance": 11})
        before = probe.load_json(probe.HEALTH_PATH, {})
        code, result = self.run_probe(comments=[], balance=TimeoutError("sensitive details"))
        self.assertEqual(code, 2)
        self.assertEqual(result["wallet_balances_rtc"], {WALLET: 11})
        self.assertEqual(result["health"]["sources"][f"wallet:{WALLET}"]["last_success_at"],
                         before["sources"][f"wallet:{WALLET}"]["last_success_at"])
        self.assertNotIn("sensitive details", json.dumps(result))

    def test_non_finite_or_negative_balances_are_rejected(self) -> None:
        for value in ("NaN", "Infinity", -1, True):
            with self.subTest(value=value):
                code, result = self.run_probe(comments=[], balance={"balance": value})
                self.assertEqual(code, 2)
                self.assertFalse(result["wallet_evidence_fresh"])

    def test_recovery_reconciles_new_acceptance_against_same_fresh_balance(self) -> None:
        self.run_probe(comments=[], balance={"balance": 11})
        receipts = probe.load_json(probe.RECEIPTS_PATH, {})
        receipts["receipts"].append({
            "action_id": "second", "target_url": TARGET, "payout_wallet": WALLET,
            "accepted_verified": True, "accepted_reward_rtc": 3, "payout_status": "queued",
        })
        probe.save_json(probe.RECEIPTS_PATH, receipts)
        self.run_probe(comments=[], balance=TimeoutError())
        self.assertEqual(probe.load_json(probe.LEDGER_PATH, {})["payouts_received_verified"], 1)
        code, result = self.run_probe(comments=[], balance={"balance": 11})
        self.assertEqual(code, 0)
        self.assertTrue(result["changed"])
        self.assertEqual(probe.load_json(probe.LEDGER_PATH, {})["payouts_received_verified"], 2)

    def test_fresh_wallet_can_advance_crypto_without_fabricating_euros(self) -> None:
        code, result = self.run_probe(comments=[], balance={"balance": 12})
        self.assertEqual(code, 0)
        self.assertTrue(result["wallet_evidence_fresh"])
        ledger = probe.load_json(probe.LEDGER_PATH, {})
        self.assertEqual(ledger["rustchain_wallet_balance_rtc"], 12)
        self.assertEqual(ledger["revenue_received_rtc"], 12)
        self.assertEqual(ledger["revenue_confirmed_eur"], 0)


if __name__ == "__main__":
    unittest.main()
