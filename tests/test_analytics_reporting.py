import unittest
import json
from datetime import date, datetime, timedelta, timezone

from flightops_quality.analytics import summarize
from flightops_quality.models import BatchReport, FlightLeg, Issue, RecordResult
from flightops_quality.reporting import audit_document, render_html


class AuditTests(unittest.TestCase):
    def record(self, identity, delay=None, **status):
        start = datetime(2026, 10, 9, 9, tzinfo=timezone.utc)
        end = start + timedelta(hours=2)
        leg = FlightLeg("demo", identity, date(2026, 10, 9), "DEMO", "1", "IST", "FRA",
                        sobt=start, sibt=end, aobt=start,
                        aibt=end + timedelta(minutes=delay) if delay is not None else None,
                        **status)
        return RecordResult(leg, (), {"record_id": identity})

    def test_otp_denominator_and_exact_fifteen_boundary(self):
        records = tuple(self.record(str(i), delay, **flags) for i, (delay, flags) in enumerate([
            (-4, {}), (14, {}), (15, {}), (None, {}), (3, {"cancelled": True}),
            (3, {"diverted": True}),
        ]))
        summary = summarize(BatchReport(records, (), (), 6))
        otp = summary["arrival_otp_15_completed"]
        self.assertEqual((otp["eligible"], otp["on_time"], otp["late"]), (3, 2, 1))
        self.assertAlmostEqual(otp["percent"], 200 / 3)
        self.assertEqual(otp["excluded_missing_arrival_delay"], 1)
        self.assertEqual(otp["excluded_cancelled_or_diverted"], 2)

    def test_empty_population_is_not_zero_percent(self):
        summary = summarize(BatchReport((), (), (), 0))
        self.assertIsNone(summary["arrival_otp_15_completed"]["percent"])
        self.assertIsNone(summary["accepted_population"]["cancellation_rate_percent"])

    def test_raw_hash_and_escaped_html(self):
        record = self.record('<script>alert("ID")</script>', 14)
        record = RecordResult(record.flight,
                              (Issue("DEMO", "warning", ("field",), "<img onerror=evil>"),),
                              {"payload": "<script>alert(1)</script>"})
        document = audit_document(BatchReport((record,), (), (), 1))
        self.assertEqual(json.loads(json.dumps(document)), document)
        self.assertEqual(len(document["accepted"][0]["raw_sha256"]), 64)
        html = render_html(document)
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img onerror", html)
        self.assertIn("&lt;script&gt;", html)


if __name__ == "__main__":
    unittest.main()
