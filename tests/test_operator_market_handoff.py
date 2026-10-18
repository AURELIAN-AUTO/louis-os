from __future__ import annotations

from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import degraded_monetization_cycle as runtime
from scripts.operator_market_handoff import market_handoff


class OperatorMarketHandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root / "results/degraded"
        self.at = datetime(2026, 10, 18, 23, 0, tzinfo=timezone.utc)
        self.stamp = self.at.isoformat()
        self.policy = json.loads((runtime.ROOT / "config/production_policy.json").read_text())
        self.write("config/production_policy.json", self.policy)
        self.write("config/degraded_runtime.json", {"enabled": True, "submission_driver": "connected_github_operator"})
        self.path = "deliverables/mission/output.json"
        self.write(self.path, {"result": "reviewable"})
        self.selected = {
            "opportunity_id": "market-one", "source_url": "https://market.example/jobs/one",
            "title": "Compare CI tools", "description": "A narrow public-source research task",
            "observed_at": self.stamp,
            "family": "research", "reward_amount": 7, "reward_verified": True,
            "decision": {"status": "prepare_then_gate"},
            "internet_opportunity_router": {"decision": "prepare_then_gate"},
            "metadata": {"submission_dossier_prepared": True, "estimated_effort_hours": 2,
                         "prepared_artifacts": [self.path]},
        }
        self.router = {"generated_at": self.stamp, "selected": self.selected}
        self.cash = {"generated_at": self.stamp, "top_cash_first": {
            "opportunity_id": "market-one", "decision_status": "prepare_then_gate",
            "human_actions": ["Review existing account and terms authorization."]}}
        self.registry = {"items": [{"active": True, "opportunity_id": "market-one",
            "source_url": self.selected["source_url"], "artifact_paths": [self.path],
            "sha256": {self.path: hashlib.sha256((self.root / self.path).read_bytes()).hexdigest()}}]}
        self.write("results/internet_opportunity_router.json", self.router)
        self.write("results/cash_first_market.json", self.cash)
        self.write("config/prepared_opportunity_artifacts.json", self.registry)

    def write(self, relative, payload):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def handoff(self):
        return market_handoff(self.root, self.policy, checked_at=self.at)

    def test_integrity_verified_mission_is_visible_but_never_authorized(self):
        before = {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        result = self.handoff()
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["mission"]["candidate_id"], "market-one")
        for key in ("submission_authorized", "external_submission_verified", "payment_verified"):
            self.assertFalse(result["mission"][key])
        self.assertIn("not_factual_acceptance", result["mission"]["validation_scope"])
        self.assertEqual(before, {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*") if path.is_file()})

    def test_no_github_patch_does_not_hide_prepared_market_mission(self):
        self.write("results/degraded/status.json", {"cycle_outcome": "no_eligible_candidate", "runtime_status": "healthy"})
        with patch("scripts.operator_market_handoff.datetime") as clock:
            clock.now.return_value = self.at
            clock.fromisoformat = datetime.fromisoformat
            brief = runtime.operator_briefing(self.state, self.root)
        self.assertFalse(brief["package_available_for_review"])
        self.assertEqual(brief["prepared_market_mission"]["candidate_id"], "market-one")
        self.assertEqual(brief["next_action"], "review_prepared_market_mission")
        self.assertFalse(brief["submission_authorized"])
        self.assertIn("results/degraded/intents.json", brief["prepared_market_mission"]["missing_receipt_registries"])

    def test_refreshing_router_cannot_refresh_stale_listing_evidence(self):
        self.selected["observed_at"] = (self.at - timedelta(hours=25)).isoformat()
        self.write("results/internet_opportunity_router.json", self.router)
        self.assertEqual(self.handoff()["errors"], ["market_evidence_stale_or_future"])

    def test_tampered_or_missing_artifact_never_becomes_reviewable(self):
        (self.root / self.path).write_text("tampered")
        self.assertEqual(self.handoff()["errors"], ["market_artifact_hash_mismatch"])
        (self.root / self.path).unlink()
        self.assertIsNone(self.handoff()["mission"])

    def test_every_artifact_requires_hash(self):
        self.registry["items"][0]["sha256"] = {}
        self.write("config/prepared_opportunity_artifacts.json", self.registry)
        self.assertEqual(self.handoff()["errors"], ["market_artifact_hash_missing"])

    def test_path_traversal_and_symlink_are_rejected(self):
        for relative in ("../outside.json", "/tmp/outside.json"):
            with self.subTest(relative=relative):
                self.registry["items"][0]["artifact_paths"] = [relative]
                self.selected["metadata"]["prepared_artifacts"] = [relative]
                self.write("config/prepared_opportunity_artifacts.json", self.registry)
                self.write("results/internet_opportunity_router.json", self.router)
                self.assertEqual(self.handoff()["errors"], ["market_artifact_path_outside_checkout"])
        relative = "deliverables/escape.json"
        (self.root / relative).symlink_to(self.root.parent / "outside.json")
        self.registry["items"][0]["artifact_paths"] = [relative]
        self.selected["metadata"]["prepared_artifacts"] = [relative]
        self.write("config/prepared_opportunity_artifacts.json", self.registry)
        self.write("results/internet_opportunity_router.json", self.router)
        self.assertEqual(self.handoff()["errors"], ["market_artifact_path_outside_checkout"])

    def test_stale_future_or_mismatched_selection_is_visible_error(self):
        for offset in (-25, 1):
            with self.subTest(offset=offset):
                self.router["generated_at"] = (self.at + timedelta(hours=offset)).isoformat()
                self.write("results/internet_opportunity_router.json", self.router)
                self.assertEqual(self.handoff()["errors"], ["market_evidence_stale_or_future"])
        self.router["generated_at"] = self.stamp
        self.cash["top_cash_first"]["opportunity_id"] = "different"
        self.write("results/internet_opportunity_router.json", self.router)
        self.write("results/cash_first_market.json", self.cash)
        self.assertEqual(self.handoff()["errors"], ["market_selection_mismatch"])

    def test_corrupt_evidence_not_silently_treated_as_empty(self):
        (self.root / "results/cash_first_market.json").write_text("not json")
        self.assertEqual(self.handoff()["errors"], ["JSONDecodeError"])

    def test_attempts_receipts_and_persistent_rejections_block_duplicates(self):
        for relative, key in (("results/degraded/intents.json", "items"),
                              ("results/degraded/receipts.json", "receipts"),
                              ("results/external_action_receipts.json", "receipts"),
                              ("results/submission_receipts.json", "receipts")):
            with self.subTest(relative=relative):
                self.write(relative, {key: [{"candidate_id": "market-one"}]})
                self.assertEqual(self.handoff()["errors"], ["market_candidate_already_attempted_reconcile_first"])
                (self.root / relative).unlink()
        self.write("config/persistent_opportunity_rejections.json", {"items": [{
            "active": True, "opportunity_id": "market-one", "reason": "provider_failure"}]})
        self.assertEqual(self.handoff()["errors"], ["market_selection_persistently_rejected"])

    def test_production_limits_and_kill_switch_remain_authoritative(self):
        self.selected["metadata"]["estimated_effort_hours"] = 4
        self.write("results/internet_opportunity_router.json", self.router)
        self.assertEqual(self.handoff()["errors"], ["market_selection_blocked_by_production_policy"])
        self.policy["kill_switch"] = True
        self.write("config/production_policy.json", self.policy)
        brief = runtime.operator_briefing(self.state, self.root)
        self.assertIsNone(brief["prepared_market_mission"])

    def test_pending_intent_retains_priority_and_submit_stays_delegated(self):
        self.write("results/degraded/intents.json", {"items": [{"candidate_id": "other", "status": "operator_reserved"}]})
        with patch("scripts.operator_market_handoff.datetime") as clock:
            clock.now.return_value = self.at
            clock.fromisoformat = datetime.fromisoformat
            brief = runtime.operator_briefing(self.state, self.root)
        self.assertEqual(brief["next_action"], "reconcile_intents")
        with patch.object(runtime, "submit_patch") as send:
            self.assertEqual(runtime.submit(self.root, self.state)["status"], "delegated_to_connected_operator")
            send.assert_not_called()

    def test_router_workflow_persists_briefing_without_new_schedule(self):
        workflow = (runtime.ROOT / ".github/workflows/internet-opportunity-router.yml").read_text()
        self.assertIn("python scripts/degraded_monetization_cycle.py report", workflow)
        self.assertIn("git add -f results/degraded/operator-briefing.json results/degraded/report.md", workflow)
        self.assertNotIn("schedule:", workflow)


if __name__ == "__main__":
    unittest.main()
