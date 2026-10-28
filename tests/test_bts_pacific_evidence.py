"""Keep the dated Pacific cohort evidence reproducible and honestly scoped."""
import hashlib
import importlib.util
import json
import unittest
from pathlib import Path

from test_bts_validation_html import ParsedReport

ROOT = Path(__file__).resolve().parents[1]


class PacificEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = json.loads((ROOT / 'docs/evidence/bts-2025-03-pacific-cohort.json')
                                  .read_text(encoding='utf-8'))

    def test_mapping_artifact_and_observed_airports_agree(self):
        mapping = ROOT / 'examples/airport_timezones_pacific.json'
        cohort = self.document['cohort']
        self.assertEqual(json.loads(mapping.read_text()), cohort['airport_timezones'])
        self.assertEqual(hashlib.sha256(mapping.read_bytes()).hexdigest(),
                         cohort['timezone_mapping_sha256'])
        self.assertEqual(set(self.document['validation']['airport_ids']), {'HNL', 'LAX', 'PHX'})
        self.assertFalse(cohort['truncated'])
        self.assertFalse(self.document['validation']['policy']['absolute_utc_validation'])

    def test_every_holdout_row_and_target_is_accounted_for(self):
        validation = self.document['validation']
        for field in ('ArrDelay', 'AirTime'):
            check = validation['holdout_checks'][field]
            self.assertTrue(check['reconciled'])
            self.assertEqual(check['checked'] + sum(check['excluded_counts'].values()),
                             validation['input_rows'])
            self.assertEqual(check['matched'] + check['mismatched'], check['checked'])
            self.assertGreater(check['checked'], 0)
            self.assertEqual(check['mismatched'], 0)

    def test_transition_examples_change_only_the_dst_observing_zone(self):
        validation = self.document['validation']
        self.assertIsNone(validation['policy']['departure_fold'])
        self.assertIsNone(validation['policy']['midnight_policy'])
        # This cohort has no ambiguous/error rows; do not imply fold coverage.
        self.assertEqual(validation['normalizer_issue_examples'], [])
        for population in ('scheduled', 'actual'):
            coverage = validation['timezone_offset_transitions'][population]
            self.assertTrue(coverage['reconciled'])
            self.assertEqual(coverage['offset_change_rows'], 4)
            self.assertEqual(len(coverage['examples']), 4)
            for example in coverage['examples']:
                self.assertEqual(example['route'], 'HNL-LAX')
                self.assertEqual(len(example['changes']), 1)
                change = example['changes'][0]
                self.assertEqual(change['timezone'], 'America/Los_Angeles')
                self.assertEqual((change['offset_start_seconds'], change['offset_end_seconds']),
                                 (-28800, -25200))

    def test_static_report_matches_recorded_evidence_and_has_no_remote_resources(self):
        spec = importlib.util.spec_from_file_location(
            'pacific_evidence_html', ROOT / 'examples/bts_validation_html.py')
        renderer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(renderer)
        payload = (ROOT / 'docs/evidence/bts-2025-03-pacific-cohort.json').read_bytes()
        markup = renderer.render_validation_html(
            self.document, input_sha256=hashlib.sha256(payload).hexdigest())
        self.assertEqual(markup, (ROOT / 'docs/evidence/bts-2025-03-pacific-report.html')
                         .read_text(encoding='utf-8'))
        report = ParsedReport(markup)
        for label in ('2025-03', 'HNL', 'PHX', 'ArrDelay', 'AirTime',
                      'Pacific/Honolulu', 'America/Phoenix'):
            self.assertIn(label, report.text)
        self.assertFalse(any(tag in {'script', 'iframe', 'img', 'link'}
                             for tag, _ in report.tags))
        self.assertTrue(all(attrs.get('href', '').startswith('#')
                            for tag, attrs in report.tags if tag == 'a'))


if __name__ == '__main__':
    unittest.main()
