import copy
import importlib.util
import json
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def normalized_text(text):
    text = re.sub(r"(?<=\d),(?=\d)", "", text)
    return " ".join(text.split())


class ParsedReport(HTMLParser):
    """Observe visible text and actual HTML attributes after entity decoding."""

    def __init__(self, markup):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.visible_parts = []
        self.style_parts = []
        self.rows = []
        self.code_parts = []
        self.hidden_depth = 0
        self.code_depth = 0
        self.row_parts = None
        self.feed(markup)
        self.close()

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        if tag in {"style", "script"}:
            self.hidden_depth += 1
        if tag == "code":
            self.code_depth += 1
        if tag == "tr":
            self.row_parts = []

    def handle_startendtag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_endtag(self, tag):
        if tag in {"style", "script"}:
            self.hidden_depth -= 1
        if tag == "code":
            self.code_depth -= 1
        if tag == "tr" and self.row_parts is not None:
            self.rows.append(normalized_text(" ".join(self.row_parts)))
            self.row_parts = None

    def handle_data(self, text):
        if self.hidden_depth:
            self.style_parts.append(text)
            return
        self.visible_parts.append(text)
        if self.row_parts is not None:
            self.row_parts.append(text)
        if self.code_depth:
            self.code_parts.append(text)

    @property
    def text(self):
        return normalized_text(" ".join(self.visible_parts))


class BtsValidationHtmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("bts_validation_html_tested", ROOT / "examples/bts_validation_html.py")
        cls.renderer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.renderer)
        cls.evidence = json.loads((ROOT / "docs/evidence/bts-2025-01-route-cohort.json").read_text(encoding="utf-8"))

    def document(self):
        return copy.deepcopy(self.evidence)

    def parse(self, document):
        markup = self.renderer.render_validation_html(document)
        self.assertIsInstance(markup, str)
        return ParsedReport(markup)

    def assert_number_visible(self, report, number):
        self.assertRegex(report.text, rf"(?<!\d){number}(?!\d)")

    def test_committed_benchmark_shows_distinct_source_cohort_and_kpi_populations(self):
        report = self.parse(self.document())
        for number in (539747, 2929, 2928, 2909, 2910, 2510, 399, 400):
            self.assert_number_visible(report, number)
        for label in ("ArrDelay", "AirTime", "2025-01", "JFK", "LAX", "ORD"):
            self.assertIn(label, report.text)
        percentages = [float(v) for v in re.findall(r"(?<![\w.])(\d+(?:\.\d+)?)\s*%", report.text)]
        self.assertTrue(any(abs(value - 86.28394637332417) < 0.1 for value in percentages))
        self.assertIn("BTS_CLOCK_MISMATCH", report.text)
        self.assert_number_visible(report, 441440)

    def test_holdout_rows_show_checked_matches_mismatches_and_exclusions(self):
        document = self.document()
        check = document["validation"]["holdout_checks"]["ArrDelay"]
        check.update(checked=2889, matched=2886, mismatched=3)
        check["excluded_counts"] = {"cancelled": 11, "diverted": 8, "missing_target": 9,
                                   "invalid_target": 7, "probe_clock_mismatch": 5}
        check["mismatch_examples"] = [{"source_row_number": 12345, "source": "bts", "record_id": "example-leg",
                                        "metric": "arrival_delay_minutes", "predicted": -20, "reported": -19}]
        report = self.parse(document)
        rows = [row for row in report.rows if "ArrDelay" in row]
        self.assertTrue(any(all(re.search(rf"(?<!\d){n}(?!\d)", row) for n in (2889, 2886, 3)) for row in rows), rows)
        for reason in ("missing_target", "invalid_target", "probe_clock_mismatch"):
            self.assertIn(reason, report.text)
        for number in (9, 7, 5, 12345):
            self.assert_number_visible(report, number)
        self.assertIn("example-leg", report.text)

    def test_null_percentages_are_unavailable_instead_of_zero_or_nan(self):
        document = self.document()
        validation = document["validation"]
        validation["input_rows"] = 0
        validation["group_dispositions"] = {"input": 0, "accepted": 0, "quarantined": 0, "duplicates": 0}
        summary = validation["batch_summary"]
        summary["counts"] = dict(validation["group_dispositions"])
        summary["accepted_population"] = {"flights": 0, "cancelled": 0, "diverted": 0,
                                          "cancellation_rate_percent": None, "diversion_rate_percent": None}
        summary["arrival_otp_15_completed"].update(eligible=0, on_time=0, late=0, percent=None,
                                                coverage_population=0, coverage_percent=None,
                                                excluded_cancelled_or_diverted=0, excluded_missing_arrival_delay=0)
        for cohort in ("all_source_rows", "accepted_unique_rows"):
            validation["source_input_kpis"][cohort].update(input_rows=0, coverage_population=0, eligible=0,
                                                         on_time=0, late=0, percent=None, coverage_percent=None,
                                                         excluded_counts={})
        for metric, parity in validation["source_input_kpis"]["accepted_parity"].items():
            value = None if "percent" in metric else 0
            parity.update(source=value, derived=value, matched=True)
        for check in validation["holdout_checks"].values():
            check.update(input_rows=0, checked=0, matched=0, mismatched=0, excluded_counts={}, mismatch_examples=[])
        validation["normalizer_issue_examples"] = []
        validation["normalizer_issue_counts"] = {}
        validation["route_counts"] = {}
        validation["source_missing_fields"] = {}
        validation["airport_ids"] = {}
        validation["date_range"] = {"start": None, "end": None, "valid_rows": 0, "invalid_rows": 0}
        for counts in validation["source_status_counts"].values():
            for key in counts:
                counts[key] = 0
        report = self.parse(document)
        self.assertIn("Unavailable", report.text)
        self.assertNotRegex(report.text, r"(?i)\b(?:none|null|nan)\s*%")
        self.assertNotRegex(report.text, r"\b(?:86\.28|86\.25)\s*%")

    def test_all_rendered_source_values_are_escaped_as_text(self):
        document = self.document()
        document["source"]["archive_name"] = '<img src=x onerror="ARCHIVE_MARK">'
        document["source"]["archive_sha256"] = '<script>HASH_MARK</script>'
        document["source"]["csv_member"] = '<svg onload="MEMBER_MARK"></svg>'
        document["environment"]["package_version"] = '<script>VERSION_MARK</script>'
        document["cohort"]["timezone_mapping_sha256"] = '<script>MAP_HASH_MARK</script>'
        document["cohort"]["airport_timezones"] = {'<img src=x onerror="AIRPORT_MARK">': '<script>TZ_MARK</script>'}
        routes = document["validation"]["route_counts"]
        first_route = next(iter(routes))
        routes['<script>ROUTE_MARK</script>'] = routes.pop(first_route)
        example = document["validation"]["normalizer_issue_examples"][0]
        example["source_row_number"] = '<script>ROW_MARK</script>'
        example["record_id"] = '<script>ID_MARK</script>'
        example["flight"]["record_id"] = example["record_id"]
        example["raw_sha256"] = '<script>RAW_HASH_MARK</script>'
        example["raw_fields"]["ArrTime"] = '<svg onload="RAW_MARK"></svg>'
        example["issues"][0]["message"] = '<img src=x onerror="ISSUE_MARK">'
        report = self.parse(document)
        for marker in ("ARCHIVE_MARK", "HASH_MARK", "MEMBER_MARK", "VERSION_MARK", "MAP_HASH_MARK",
                       "AIRPORT_MARK", "TZ_MARK", "ROUTE_MARK", "ROW_MARK", "ID_MARK", "RAW_HASH_MARK",
                       "RAW_MARK", "ISSUE_MARK"):
            self.assertIn(marker, report.text)
        self.assertFalse({tag for tag, _ in report.tags} & {"script", "img", "svg", "iframe", "object", "embed"})
        self.assertFalse(any(name.lower().startswith("on") for _, attrs in report.tags for name in attrs))

    def test_unsafe_source_urls_are_code_text_without_links(self):
        for label in ("javascript:alert(1)", "data:text/html,<svg onload=alert(1)>",
                      "https://example.org/' onclick='alert(1)", "//example.org/untrusted"):
            with self.subTest(label=label):
                document = self.document()
                document["source"]["source_url_label"] = label
                report = self.parse(document)
                self.assertIn(label, " ".join(report.code_parts))
                self.assertFalse(any(attrs.get("href") == label for _, attrs in report.tags))
                self.assertFalse(any(name.lower().startswith("on") for _, attrs in report.tags for name in attrs))

    def test_report_has_inline_csp_and_no_scripts_or_external_assets(self):
        report = self.parse(self.document())
        csp = [attrs.get("content", "") for tag, attrs in report.tags
               if tag == "meta" and attrs.get("http-equiv", "").lower() == "content-security-policy"]
        self.assertEqual(len(csp), 1)
        self.assertIn("default-src 'none'", csp[0])
        self.assertIn("base-uri 'none'", csp[0])
        self.assertFalse({tag for tag, _ in report.tags} & {"script", "iframe", "object", "embed"})
        for tag, attrs in report.tags:
            self.assertNotIn("src", attrs)
            self.assertNotIn("srcset", attrs)
            if "href" in attrs:
                self.assertTrue(attrs["href"].startswith("#"), (tag, attrs))
        self.assertNotRegex(" ".join(report.style_parts), r"(?i)@import|url\s*\(")

    def test_missing_required_top_level_containers_fail_clearly(self):
        for key in ("source", "environment", "cohort", "validation"):
            with self.subTest(key=key):
                document = self.document()
                document.pop(key)
                with self.assertRaises(ValueError):
                    self.renderer.render_validation_html(document)

    def test_bad_top_level_container_types_fail_clearly(self):
        for key in ("source", "environment", "cohort", "validation"):
            for value in (None, [], "bad container"):
                with self.subTest(key=key, value=value):
                    document = self.document()
                    document[key] = value
                    with self.assertRaises(ValueError):
                        self.renderer.render_validation_html(document)

    def test_huge_integer_percentage_is_a_value_error_not_numeric_overflow(self):
        document = self.document()
        document["validation"]["source_input_kpis"]["all_source_rows"]["percent"] = 1 << 2048
        with self.assertRaises(ValueError):
            self.renderer.render_validation_html(document)

    def test_missing_either_required_holdout_is_rejected(self):
        for field in ("ArrDelay", "AirTime"):
            with self.subTest(field=field):
                document = self.document()
                document["validation"]["holdout_checks"].pop(field)
                with self.assertRaises(ValueError):
                    self.renderer.render_validation_html(document)

    def test_contradictory_counts_and_boolean_counters_are_rejected(self):
        for case in ("holdout_sum", "holdout_total", "route_sum", "otp_sum", "otp_percent",
                     "holdout_bool", "route_bool", "disposition_bool", "otp_bool"):
            with self.subTest(case=case):
                document = self.document()
                validation = document["validation"]
                check = validation["holdout_checks"]["ArrDelay"]
                if case == "holdout_sum":
                    check["matched"] -= 1
                elif case == "holdout_total":
                    check["input_rows"] -= 1
                elif case == "route_sum":
                    validation["route_counts"]["JFK-LAX"] -= 1
                elif case == "otp_sum":
                    validation["source_input_kpis"]["all_source_rows"]["late"] -= 1
                elif case == "otp_percent":
                    validation["source_input_kpis"]["all_source_rows"]["percent"] = 100
                elif case == "holdout_bool":
                    check["mismatched"] = False
                elif case == "route_bool":
                    validation["route_counts"]["JFK-LAX"] = True
                elif case == "disposition_bool":
                    validation["group_dispositions"]["quarantined"] = True
                else:
                    validation["source_input_kpis"]["all_source_rows"]["eligible"] = True
                with self.assertRaises(ValueError):
                    self.renderer.render_validation_html(document)


if __name__ == "__main__":
    unittest.main()
