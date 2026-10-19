from copy import deepcopy
from pathlib import Path
import unittest
from urllib.error import HTTPError

from scripts.taskmarket_public_followup import API, CLAIMS, WALLET, NoRedirect, amount_usdc, build_snapshot, fetch_public, semantic


class TaskmarketPublicFollowupTests(unittest.TestCase):
    def setUp(self):
        self.responses = {}
        for _, task, submission in CLAIMS:
            self.responses[API + task] = {
                'id': task, 'status': 'completed', 'submissionVisibility': 'public',
                'reward': '64000000', 'awards': [
                    {'workerAddress': '0xother', 'settlementTxHash': '0xother-settlement'},
                ],
            }
            self.responses[API + task + '/submissions'] = [{
                'id': submission, 'taskId': task, 'workerAddress': WALLET,
                'rejectedAt': None, 'signature': 'NEVER_PERSIST', 'fileUrl': 'NEVER_PERSIST',
            }]

    def snapshot(self):
        return build_snapshot(self.responses.__getitem__, checked_at='2026-10-19T17:18:00Z')

    def test_reconciles_closed_contests_without_counting_others_awards(self):
        result = self.snapshot()
        self.assertTrue(result['monitor_healthy'])
        self.assertFalse(result['selection_signal_any'])
        self.assertFalse(result['payout_evidence_candidate'])
        self.assertFalse(result['payment_verified'])
        for claim in result['claims']:
            self.assertTrue(claim['own_submission_found'])
            self.assertEqual(claim['submission_outcome'], 'completed_without_own_award_observed')
            self.assertIsNone(claim['own_submission_rejected_at'])
        self.assertNotIn('NEVER_PERSIST', str(result))

    def test_wallet_and_euro_revenue_are_unknown_not_fabricated_zero(self):
        result = self.snapshot()
        self.assertIsNone(result['wallet_balance_usdc'])
        self.assertIsNone(result['revenue_confirmed_eur'])
        self.assertEqual(result['wallet_balance_verification'], 'not_read_public_monitor')

    def test_matching_award_is_only_candidate_not_verified_payment(self):
        self.responses[API + CLAIMS[0][1]]['awards'][0]['workerAddress'] = WALLET.lower()
        result = self.snapshot()
        self.assertTrue(result['selection_signal_any'])
        self.assertTrue(result['payout_evidence_candidate'])
        self.assertFalse(result['payment_verified'])

    def test_legacy_winner_signal_is_not_lost_or_counted_as_payment(self):
        self.responses[API + CLAIMS[0][1]]['winner'] = WALLET.lower()
        result = self.snapshot()
        self.assertTrue(result['selection_signal_any'])
        self.assertFalse(result['payment_verified'])

    def test_http_errors_preserve_unknown_and_incomplete_health(self):
        def fetch(url):
            raise HTTPError(url, 404, 'Not Found', {}, None)
        result = build_snapshot(fetch)
        self.assertFalse(result['monitor_healthy'])
        self.assertTrue(any('HTTP_404' in error for error in result['errors']))
        self.assertTrue(all(row['own_submission_found'] is None for row in result['claims']))
        self.assertTrue(all(row['task_status'] == 'unknown' for row in result['claims']))

    def test_missing_private_submission_is_not_proof_of_absence(self):
        for _, task, _ in CLAIMS:
            self.responses[API + task]['submissionVisibility'] = 'never'
            self.responses[API + task + '/submissions'] = []
        result = self.snapshot()
        self.assertFalse(result['monitor_healthy'])
        self.assertIsNone(result['claims'][0]['own_submission_found'])

    def test_task_or_submission_identity_mismatch_remains_visible(self):
        self.responses[API + CLAIMS[0][1]]['id'] = 'wrong-task'
        self.responses[API + CLAIMS[1][1] + '/submissions'][0]['workerAddress'] = '0xother'
        result = self.snapshot()
        self.assertFalse(result['monitor_healthy'])
        self.assertIsNone(result['claims'][1]['own_submission_found'])

    def test_invalid_schema_or_missing_awards_cannot_appear_healthy(self):
        self.responses[API + CLAIMS[0][1] + '/submissions'] = {'unexpected': []}
        del self.responses[API + CLAIMS[1][1]]['awards']
        result = self.snapshot()
        self.assertFalse(result['monitor_healthy'])
        self.assertIsNone(result['claims'][1]['own_awards_observed'])

    def test_open_task_with_no_award_stays_unselected_not_rejected(self):
        self.responses[API + CLAIMS[0][1]].update(status='open', awards=[])
        self.assertEqual(self.snapshot()['claims'][0]['submission_outcome'], 'no_selection_observed')

    def test_base_unit_conversion_does_not_guess_by_amount_threshold(self):
        self.assertEqual(amount_usdc('1000'), 0.001)
        self.assertEqual(amount_usdc('64000000'), 64)
        for invalid in (None, 'not-a-number', 'NaN', '-1'):
            self.assertIsNone(amount_usdc(invalid))

    def test_only_four_exact_public_get_endpoints_no_redirect(self):
        called = []
        build_snapshot(lambda url: called.append(url) or self.responses[url])
        self.assertEqual(len(called), 4)
        with self.assertRaises(ValueError):
            fetch_public('https://api.taskmarket.dev/api/wallet/balance')
        with self.assertRaises(ValueError):
            NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.example')

    def test_probe_time_alone_does_not_create_meaningful_change(self):
        first = self.snapshot()
        later = deepcopy(first)
        later['checked_at'] = '2026-10-20T17:18:00Z'
        self.assertEqual(semantic(first), semantic(later))
        later['errors'] = ['HTTP_429']
        self.assertNotEqual(semantic(first), semantic(later))

    def test_workflow_keeps_schedule_removes_cloud_and_preserves_evidence_before_failure(self):
        text = (Path(__file__).resolve().parents[1] / '.github/workflows/monitor-taskmarket-claims.yml').read_text()
        self.assertIn('cron: "31 23 * * *"', text)
        self.assertIn('environment: production', text)
        for prohibited in ('gcloud ', 'google-github-actions/', 'id-token: write', 'gh issue comment 77'):
            self.assertNotIn(prohibited, text)
        self.assertLess(text.index('Persist meaningful change'), text.index('Require complete public reads'))
        self.assertLess(text.index('Preserve dated public evidence'), text.index('Require complete public reads'))
        self.assertNotIn("m['last_external_wallet_balance_usdc']=", text)


if __name__ == '__main__':
    unittest.main()
