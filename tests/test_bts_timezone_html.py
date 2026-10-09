import copy
import importlib.util
import json
import unittest
from pathlib import Path

from test_bts_validation_html import ParsedReport

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('timezone_html_tested', ROOT / 'examples/bts_validation_html.py')
HTML = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HTML)


class TimezoneHtmlTests(unittest.TestCase):
    def document(self):
        document = json.loads((ROOT / 'docs/evidence/bts-2025-01-route-cohort.json').read_text())
        # Synthetic added observations test display contracts, not January DST evidence.
        example = {
            'source_row_number': 20, 'record_id': 'synthetic-change', 'service_date': '2025-03-08',
            'origin': 'LAX', 'destination': 'JFK',
            'window_start_utc': '2025-03-09T06:30:00+00:00',
            'window_end_utc': '2025-03-09T11:30:00+00:00',
            'changes': [{'timezone': 'America/New_York', 'offset_start_seconds': -18000,
                         'offset_end_seconds': -14400, 'change_seconds': 3600,
                         'local_start': '2025-03-09T01:30:00-05:00',
                         'local_end': '2025-03-09T07:30:00-04:00'}],
        }
        coverage = {'policy': {'absolute_utc_validation': False}}
        for window, population in (('scheduled', 2928), ('actual', 2909)):
            coverage[window] = {
                'population_rows': population, 'checked': population - 1,
                'excluded_counts': {'missing_timestamps': 1}, 'offset_change_rows': 1,
                'zone_change_observations': 1, 'reconciled': True,
                'examples': [copy.deepcopy(example)],
            }
        document['validation']['timezone_offset_transitions'] = coverage
        return document

    def render(self, document):
        return ParsedReport(HTML.render_validation_html(document))

    def test_optional_section_displays_same_zone_offsets_and_separate_populations(self):
        report = self.render(self.document())
        for text in ('Timezone offset changes', 'Same IANA zone', 'Rows with change',
                     'Zone-change observations', 'multiple offset changes that cancel out',
                     'synthetic-change', '3,600', '-18,000', '-14,400'):
            self.assertIn(text.replace(',', ''), report.text)
        self.assertTrue(any('Scheduled 2928 2927 1 1 1' in row for row in report.rows))
        self.assertTrue(any('Actual 2909 2908 1 1 1' in row for row in report.rows))
        self.assertIn(('a', {'href': '#timezone-coverage'}), report.tags)

    def test_old_evidence_has_no_fabricated_transition_coverage(self):
        document = self.document()
        del document['validation']['timezone_offset_transitions']
        report = self.render(document)
        self.assertNotIn('Timezone offset changes within flight windows', report.text)
        self.assertNotIn(('a', {'href': '#timezone-coverage'}), report.tags)

    def test_present_null_coverage_is_rejected_instead_of_hidden(self):
        document = self.document()
        document['validation']['timezone_offset_transitions'] = None
        with self.assertRaises(ValueError):
            self.render(document)

    def test_zero_changes_and_missing_windows_do_not_produce_examples(self):
        document = self.document()
        for item in document['validation']['timezone_offset_transitions'].values():
            if 'offset_change_rows' in item:
                item.update(offset_change_rows=0, zone_change_observations=0, examples=[])
        report = self.render(document)
        self.assertNotIn('synthetic-change', report.text)
        self.assertIn('Rows with change', report.text)

    def test_transition_values_and_policy_cannot_inject_markup(self):
        document = self.document()
        payload = '<img src=x onerror="MARK">'
        coverage = document['validation']['timezone_offset_transitions']
        coverage['policy'][payload] = payload
        document['cohort']['airport_timezones']['JFK'] = payload
        for window in ('scheduled', 'actual'):
            ex = coverage[window]['examples'][0]
            for key in ('record_id', 'service_date', 'origin', 'destination', 'window_start_utc', 'window_end_utc'):
                ex[key] = payload
            ex['changes'][0].update(timezone=payload, local_start=payload, local_end=payload)
        report = self.render(document)
        self.assertIn('MARK', report.text)
        self.assertFalse(any(tag in {'img', 'script', 'svg'} for tag, _ in report.tags))
        self.assertFalse(any(k.startswith('on') for _, attrs in report.tags for k in attrs))

    def test_inconsistent_population_or_change_counts_fail_closed(self):
        for key, value in (('population_rows', 2929), ('checked', 2928),
                           ('offset_change_rows', 2928), ('zone_change_observations', 0),
                           ('zone_change_observations', 2), ('zone_change_observations', 3), ('reconciled', False),
                           ('checked', True), ('examples', []),
                           ('excluded_counts', {'unknown': 1})):
            with self.subTest(key=key, value=value):
                document = self.document()
                document['validation']['timezone_offset_transitions']['scheduled'][key] = value
                with self.assertRaises(ValueError):
                    self.render(document)

    def test_distinct_records_can_share_source_row_number_but_repeated_examples_fail(self):
        document = self.document()
        item = document['validation']['timezone_offset_transitions']['scheduled']
        second = copy.deepcopy(item['examples'][0])
        second['record_id'] = 'second-distinct-record'
        item.update(offset_change_rows=2, zone_change_observations=2)
        item['examples'].append(second)
        self.assertIn('second-distinct-record', self.render(document).text)
        second['record_id'] = item['examples'][0]['record_id']
        with self.assertRaises(ValueError):
            self.render(document)

    def test_invalid_or_duplicate_zone_observations_and_offsets_are_rejected(self):
        for mutation in ('unknown_zone', 'duplicate_zone', 'wrong_delta', 'boolean', 'zero_change', 'bad_row'):
            with self.subTest(mutation=mutation):
                document = self.document()
                item = document['validation']['timezone_offset_transitions']['scheduled']
                ex = item['examples'][0]
                change = ex['changes'][0]
                if mutation == 'unknown_zone':
                    change['timezone'] = 'unmapped'
                elif mutation == 'duplicate_zone':
                    ex['changes'].append(copy.deepcopy(change))
                    item['zone_change_observations'] = 2
                elif mutation == 'wrong_delta':
                    change['change_seconds'] = 3599
                elif mutation == 'boolean':
                    change['offset_start_seconds'] = True
                elif mutation == 'zero_change':
                    change.update(offset_end_seconds=-18000, change_seconds=0)
                else:
                    ex['source_row_number'] = 0
                with self.assertRaises(ValueError):
                    self.render(document)


if __name__ == '__main__':
    unittest.main()
