from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import unittest

from scripts.cash_first_market_postprocess import attach_prepared_artifacts
from scripts.internet_opportunity_router_cycle import build_cycle
from atlas.cash_first_market import build_cash_first_portfolio


ROOT = Path(__file__).resolve().parents[1]
DELIVERY_DIR = ROOT / "deliverables" / "bountybook_cicd_comparison_d47a42b6"
DELIVERABLE = DELIVERY_DIR / "cicd_comparison.json"
MANIFEST = DELIVERY_DIR / "manifest.json"
REGISTRY = ROOT / "config" / "prepared_opportunity_artifacts.json"
EXPECTED_NAMES = {"GitHub Actions", "GitLab CI/CD", "CircleCI", "Jenkins", "Drone CI"}
REQUIRED_FIELDS = {
    "name",
    "open_source",
    "self_hosted_runner",
    "free_tier_minutes",
    "free_tier_notes",
    "config_format",
    "config_file",
    "parallel_jobs",
    "matrix_builds",
    "docker_support",
    "secret_management",
    "best_for",
    "limitations",
    "pricing_summary",
}


class BountyBookCicdComparisonDeliveryTests(unittest.TestCase):
    def test_matches_public_acceptance_contract(self) -> None:
        payload = json.loads(DELIVERABLE.read_text(encoding="utf-8"))
        self.assertRegex(payload["generated_at"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(len(payload["platforms"]), 5)
        self.assertEqual({item["name"] for item in payload["platforms"]}, EXPECTED_NAMES)
        for item in payload["platforms"]:
            self.assertTrue(REQUIRED_FIELDS.issubset(item))
            for field in ("open_source", "self_hosted_runner", "parallel_jobs", "matrix_builds", "docker_support"):
                self.assertIs(type(item[field]), bool)
            self.assertIs(type(item["free_tier_minutes"]), int)
            self.assertGreater(len(item["best_for"]), 10)
            self.assertGreater(len(item["limitations"]), 10)
            self.assertTrue(item["config_format"])
            self.assertTrue(item.get("sources"))
            self.assertTrue(all(re.match(r"^https://", url) for url in item["sources"]))

    def test_manifest_and_registry_hashes_are_exact(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        deliverable_relative = str(DELIVERABLE.relative_to(ROOT))
        manifest_relative = str(MANIFEST.relative_to(ROOT))
        deliverable_hash = hashlib.sha256(DELIVERABLE.read_bytes()).hexdigest()
        manifest_hash = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
        self.assertEqual(manifest["deliverable_sha256"], deliverable_hash)
        entry = next(
            item for item in registry["items"]
            if item.get("opportunity_id") == "market-685081cabe16a6b0"
        )
        self.assertEqual(entry["source_url"], "https://www.bountybook.ai/job/d47a42b6-8203-4bc7-8bbf-c22ef912c232")
        self.assertEqual(entry["sha256"][deliverable_relative], deliverable_hash)
        self.assertEqual(entry["sha256"][manifest_relative], manifest_hash)

    def test_exact_registry_entry_unlocks_only_the_selected_candidate(self) -> None:
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        selected = {
            "opportunity_id": "market-685081cabe16a6b0",
            "source_url": "https://www.bountybook.ai/job/d47a42b6-8203-4bc7-8bbf-c22ef912c232",
            "decision": {"status": "prepare_then_gate"},
            "metadata": {"submission_dossier_required": True, "submission_dossier_prepared": False},
        }
        other = {
            "opportunity_id": "market-other",
            "source_url": "https://www.bountybook.ai/job/other",
            "decision": {"status": "prepare_then_gate"},
            "metadata": {"submission_dossier_required": True, "submission_dossier_prepared": False},
        }
        selected_result, other_result = attach_prepared_artifacts([selected, other], registry)
        self.assertTrue(selected_result["metadata"]["submission_dossier_prepared"])
        self.assertTrue(selected_result["metadata"]["prepared_artifact_registry_verified"])
        self.assertFalse(other_result["metadata"]["submission_dossier_prepared"])

    def test_current_market_selection_reaches_operator_gate(self) -> None:
        market = json.loads((ROOT / "results" / "universal_market_opportunities.json").read_text(encoding="utf-8"))
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        market["opportunities"] = attach_prepared_artifacts(market["opportunities"], registry)
        portfolio = build_cash_first_portfolio(market)
        self.assertEqual(portfolio["top_cash_first"]["opportunity_id"], "market-685081cabe16a6b0")
        self.assertTrue(portfolio["top_cash_first"]["ready_for_human_action"])
        cycle = build_cycle([
            ("universal_market_opportunities.json", market),
            ("cash_first_market.json", portfolio),
            (
                "universal_market_cycle.json",
                json.loads((ROOT / "results" / "universal_market_cycle.json").read_text(encoding="utf-8")),
            ),
        ])
        self.assertEqual(cycle["selected"]["opportunity_id"], "market-685081cabe16a6b0")
        self.assertEqual(cycle["selection_source"], "canonical_cash_first")
        self.assertEqual(
            cycle["next_action"],
            "request exact platform account and terms gate for tested deliverable",
        )


if __name__ == "__main__":
    unittest.main()
