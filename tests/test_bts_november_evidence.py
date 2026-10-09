import copy
import importlib.util
import json
import unittest
from pathlib import Path

from flightops_quality.adapters.bts import normalize_bts_row
from test_bts_validation_html import ParsedReport

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'docs/evidence/bts-2025-11-route-cohort.json'


class NovemberEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = json.loads(EVIDENCE.read_text(encoding='utf-8'))
        spec = importlib.util.spec_from_file_location(
            'november_evidence_html', ROOT / 'examples/bts_validation_html.py')
        cls.renderer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.renderer)

    def test_observed_ambiguous_schedule_excerpt_reproduces_unresolved_instants(self):
        example = self.document['validation']['normalizer_issue_examples'][0]
        original = copy.deepcopy(example['raw_fields'])
        self.assertEqual((example['source_row_number'], original['FlightDate'],
                          original['Origin'], original['Dest'], original['CRSDepTime']),
                         (234864, '2025-11-02', 'LAX', 'ORD', '0120'))
        result = normalize_bts_row(original, self.document['cohort']['airport_timezones'],
                                   row_number=example['source_row_number'])
        self.assertFalse(result.accepted)
        self.assertEqual(result.flight.record_id, example['record_id'])
        codes = {issue.code for issue in result.issues}
        self.assertIn('TIME_AMBIGUOUS', codes)
        for field in ('sobt', 'sibt', 'aobt', 'aibt', 'atot', 'aldt'):
            self.assertIsNone(getattr(result.flight, field))
        self.assertEqual(original, example['raw_fields'])
        # The bounded excerpt reproduces normalization, not the full raw-row hash.
        self.assertIsNone(self.document['validation']['policy']['departure_fold'])

    def test_real_autumn_report_shows_negative_changes_and_the_excluded_fold_row(self):
        parsed = ParsedReport(self.renderer.render_validation_html(self.document))
        for value in ('2025-11', 'TIME_AMBIGUOUS', '234864', '-3600',
                      'Source labels · all selected rows', 'Source labels · accepted unique'):
            self.assertIn(value, parsed.text)
        self.assertTrue(any('Scheduled 3245 3245 0 16 23' in row for row in parsed.rows))
        self.assertTrue(any('Actual 3152 3152 0 14 20' in row for row in parsed.rows))
        self.assertTrue(any('ArrDelay dst_ambiguous 1' in row for row in parsed.rows))
        self.assertTrue(any('AirTime dst_ambiguous 1' in row for row in parsed.rows))
        self.assertFalse(any(tag in {'script', 'iframe', 'img'} for tag, _ in parsed.tags))
        self.assertTrue(all(attrs.get('href', '').startswith('#')
                            for tag, attrs in parsed.tags if tag == 'a'))


if __name__ == '__main__':
    unittest.main()
