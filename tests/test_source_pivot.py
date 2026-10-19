from datetime import datetime, timedelta, timezone
from dataclasses import asdict
from contextlib import ExitStack
from unittest.mock import patch
import unittest

from atlas.universal_market import SourceState, InternetOpportunity
from scripts import refresh_simple_mission_sources as refresh
from scripts.refresh_simple_mission_sources import collect_with_source_pivot


NOW = datetime(2026, 10, 19, 10, tzinfo=timezone.utc)


class FakeSource:
    source_category = "test"

    def __init__(self, source_id):
        self.source_id = source_id
        self.calls = 0

    def collect(self):
        self.calls += 1
        return [], SourceState(self.source_id, "test", "empty", observed_count=0)


class SourcePivotTests(unittest.TestCase):
    def setUp(self):
        self.sources = [FakeSource(name) for name in ("funded", "unfunded", "alternate")]
        self.router = {
            "generated_at": NOW.isoformat(),
            "next_pivot": "pause_source_and_replace",
            "source_metrics": {
                "funded": {"seen": 20, "eligible": 1},
                "unfunded": {"seen": 17, "eligible": 0},
                "alternate": {"seen": 4, "eligible": 0},
            },
        }

    def collect(self, router=None, previous=None):
        return collect_with_source_pivot(
            self.sources, self.router if router is None else router,
            previous or {}, now=NOW,
        )

    def test_pivot_prevents_actual_collection_and_keeps_other_sources(self):
        rows, receipt = self.collect()
        self.assertEqual([source.calls for source in self.sources], [1, 0, 1])
        self.assertEqual(receipt["paused_source_id"], "unfunded")
        self.assertEqual(receipt["status"], "applied_source_pause")
        state = next(state for _, state in rows if state.source_id == "unfunded")
        self.assertEqual(state.status, "paused_by_router")
        self.assertEqual(state.observed_count, 0)
        self.assertIn("no_new_source_activated", receipt["replacement_status"])

    def test_no_pivot_does_not_change_collection(self):
        self.router["next_pivot"] = "continue_current_allocation"
        self.collect()
        self.assertEqual([source.calls for source in self.sources], [1, 1, 1])

    def test_stale_future_or_missing_evidence_is_visible_and_cannot_pause(self):
        for timestamp in (None, "bad-date", (NOW - timedelta(hours=25)).isoformat(),
                          (NOW + timedelta(seconds=1)).isoformat()):
            with self.subTest(timestamp=timestamp):
                self.router["generated_at"] = timestamp
                _, receipt = self.collect()
                self.assertIsNone(receipt["paused_source_id"])
                self.assertTrue(receipt["errors"])

    def test_source_with_any_eligible_candidate_is_never_paused(self):
        self.router["source_metrics"]["unfunded"]["eligible"] = 1
        _, receipt = self.collect()
        self.assertEqual(receipt["paused_source_id"], "alternate")

    def test_pause_preserves_prior_source_error_as_historical_not_current_health(self):
        prior = {"generated_at": "2026-10-19T09:00:00+00:00", "sources": [
            {"source_id": "unfunded", "status": "failed", "reason": "HTTP_404"},
        ]}
        _, receipt = self.collect(previous=prior)
        observation = receipt["previous_source_observation"]
        self.assertEqual(observation["source_state"]["reason"], "HTTP_404")
        self.assertFalse(observation["current_probe_performed"])

    def test_unmeasured_unknown_and_invalid_metrics_cannot_pause(self):
        self.router["source_metrics"] = {
            "unfunded": {"seen": "17", "eligible": 0},
            "alternate": {"seen": 0, "eligible": 0},
            "unknown_source": {"seen": 1000, "eligible": 0},
        }
        _, receipt = self.collect()
        self.assertIsNone(receipt["paused_source_id"])
        self.assertTrue(receipt["errors"])

    def test_same_snapshot_is_idempotent_but_new_snapshot_cannot_repause(self):
        _, first = self.collect()
        _, second = self.collect(previous={"source_pivot": first})
        self.assertEqual(first["paused_source_id"], second["paused_source_id"])
        self.router["generated_at"] = (NOW - timedelta(seconds=1)).isoformat()
        _, third = self.collect(previous={"source_pivot": first})
        self.assertEqual(third["paused_source_id"], "alternate")

    def test_malformed_router_and_previous_receipt_do_not_hide_errors(self):
        for router in ([], None, {"generated_at": NOW.isoformat(), "next_pivot": "pause_source_and_replace", "source_metrics": []}):
            with self.subTest(router=router):
                _, receipt = collect_with_source_pivot(self.sources, router, [], now=NOW)
                self.assertTrue(receipt["errors"])
                self.assertIsNone(receipt["paused_source_id"])

    def test_main_wires_pause_and_removes_old_opportunities_from_paused_source(self):
        stale = InternetOpportunity(
            source_id="unfunded", source_category="test", source_url="https://example.test/old",
            title="Old CSV mission", description="Old cached description", reward_amount=10,
            currency="USD", reward_verified=False, payment_evidence=(),
            required_capabilities=("python_automation_delivery",), observed_at=NOW.isoformat(),
        )
        saved = {}

        def load(path, default):
            if path == refresh.MARKET_PATH:
                return {"opportunities": [asdict(stale)], "source_states": []}
            if path == refresh.ROUTER_PATH:
                return self.router
            return default

        names = ("SuperteamAgentListingsSource", "BountyBookAgentJobsSource", "AgentPactNeedsSource",
                 "MoltJobsAgentJobsSource", "FreelancerPublicJobsSource", "SoftwareFreelancerPublicJobsSource",
                 "GuruPublicJobsSource", "TruelancerPublicJobsSource")
        sources = self.sources + [FakeSource(f"extra-{i}") for i in range(5)]
        with ExitStack() as stack:
            for name, source in zip(names, sources):
                stack.enter_context(patch.object(refresh, name, return_value=source))
            stack.enter_context(patch.object(refresh, "load_json", side_effect=load))
            stack.enter_context(patch.object(refresh, "save_json", side_effect=lambda p, v: saved.update({p: v})))
            stack.enter_context(patch.object(refresh, "collect_with_source_pivot", side_effect=
                lambda sources, router, previous: collect_with_source_pivot(sources, router, previous, now=NOW)))
            stack.enter_context(patch("builtins.print"))
            self.assertEqual(refresh.main(), 0)
        self.assertEqual(self.sources[1].calls, 0)
        self.assertEqual(saved[refresh.MARKET_PATH]["opportunities"], [])
        receipt = saved[refresh.RECEIPT_PATH]
        self.assertEqual(receipt["source_pivot"]["paused_source_id"], "unfunded")
        self.assertEqual(receipt["external_submissions_verified"], 0)
        self.assertEqual(receipt["revenue_verified_eur"], 0.0)


if __name__ == "__main__":
    unittest.main()
