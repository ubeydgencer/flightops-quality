import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flightops_quality.adapters.bts import normalize_bts_row, parse_bts_clock
from flightops_quality.rules import flight_metrics

ZONES = {"JFK": "America/New_York", "LAX": "America/Los_Angeles"}


def bts_row():
    return dict(FlightDate="2026-07-01", Reporting_Airline="ZZ", Flight_Number_Reporting_Airline="1",
                Origin="JFK", Dest="LAX", Cancelled="0", Diverted="0", CRSDepTime="2300",
                CRSArrTime="0200", CRSElapsedTime="360", DepTime="2250", DepDelay="-10",
                ArrTime="0140", ArrDelay="-20", ActualElapsedTime="350", TaxiOut="20",
                TaxiIn="15", WheelsOff="2310", WheelsOn="0125", AirTime="315")


class BtsTests(unittest.TestCase):
    def test_clock_parsing(self):
        self.assertEqual(parse_bts_clock("2400"), 1440)
        self.assertEqual(parse_bts_clock("600.0"), 360)
        self.assertEqual(parse_bts_clock("0001"), 1)
        self.assertIsNone(parse_bts_clock(""))
        for invalid in ("1260", "2401", "-1", "5.5", "nan", "inf", True):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    parse_bts_clock(invalid)

    def test_overnight_different_timezones_and_negative_delay(self):
        result = normalize_bts_row(bts_row(), ZONES)
        self.assertTrue(result.accepted, result.issues)
        self.assertEqual(result.flight.sibt, datetime(2026, 7, 2, 9, tzinfo=timezone.utc))
        self.assertEqual(flight_metrics(result.flight)["departure_delay_minutes"], -10)
        self.assertEqual(flight_metrics(result.flight)["arrival_delay_minutes"], -20)
        self.assertEqual(result.flight.provenance["aobt"][-2], "DepDelay")

    def test_midnight_anchor_and_delay_over_twenty_four_hours(self):
        row = {**bts_row(), "CRSDepTime": "2400", "CRSArrTime": "0300", "DepDelay": "1500",
               "DepTime": "0100", "ArrTime": "0400", "ArrDelay": "1500", "ActualElapsedTime": "360",
               "TaxiOut": "", "TaxiIn": "", "WheelsOff": "", "WheelsOn": "", "AirTime": ""}
        result = normalize_bts_row(row, ZONES, midnight_policy="end")
        self.assertTrue(result.accepted, result.issues)
        self.assertEqual(result.flight.sobt.day, 2)
        self.assertEqual(result.flight.aobt.day, 3)
        self.assertEqual(flight_metrics(result.flight)["arrival_delay_minutes"], 1500)
        start = normalize_bts_row(row, ZONES, midnight_policy="start")
        self.assertTrue(start.accepted, start.issues)
        self.assertEqual(start.flight.sobt.day, 1)
        unresolved = normalize_bts_row(row, ZONES)
        self.assertFalse(unresolved.accepted)
        self.assertIn("BTS_MIDNIGHT_UNRESOLVED", [i.code for i in unresolved.issues])

    def test_cancelled_after_gate_departure(self):
        row = {**bts_row(), "Cancelled": "1", "ArrTime": "", "ArrDelay": "", "ActualElapsedTime": "",
               "TaxiOut": "", "TaxiIn": "", "WheelsOff": "", "WheelsOn": "", "AirTime": ""}
        result = normalize_bts_row(row, ZONES)
        self.assertTrue(result.accepted, result.issues)
        self.assertIsNotNone(result.flight.aobt)
        self.assertIsNone(result.flight.aibt)

    def test_diverted_null_normal_arrival(self):
        row = {**bts_row(), "Diverted": "1", "ArrTime": "", "ArrDelay": "", "ActualElapsedTime": "",
               "TaxiIn": "", "WheelsOn": "", "AirTime": ""}
        result = normalize_bts_row(row, ZONES)
        self.assertTrue(result.accepted, result.issues)
        self.assertIsNone(result.flight.aibt)
        self.assertIsNone(flight_metrics(result.flight)["arrival_delay_minutes"])

    def test_missing_signed_delay_is_not_inferred_from_clock(self):
        result = normalize_bts_row({**bts_row(), "DepDelay": ""}, ZONES)
        self.assertTrue(result.accepted)
        self.assertIsNone(result.flight.aobt)
        self.assertIn("BTS_TIME_UNRESOLVED", [i.code for i in result.issues])

    def test_dst_ambiguity_needs_fold(self):
        row = {**bts_row(), "FlightDate": "2026-11-01", "CRSDepTime": "0130", "CRSArrTime": "0430",
               "DepTime": "", "DepDelay": "", "ArrTime": "", "ArrDelay": "", "ActualElapsedTime": "",
               "TaxiOut": "", "TaxiIn": "", "WheelsOff": "", "WheelsOn": "", "AirTime": "", "Cancelled": "1"}
        result = normalize_bts_row(row, ZONES)
        self.assertIn("TIME_AMBIGUOUS", [i.code for i in result.issues])
        # fold 1 is 06:30 UTC + 6 hours = 04:30 PST at LAX.
        resolved = normalize_bts_row(row, ZONES, departure_fold=1)
        self.assertTrue(resolved.accepted, resolved.issues)

    def test_mismatch_and_invalid_numbers_are_quarantined(self):
        for changes in ({"CRSArrTime": "0300"}, {"AirTime": "314"}, {"ArrDelay": "0"},
                        {"CRSDepTime": "1260"}, {"TaxiOut": "-1"}, {"DepDelay": "1e100"}):
            with self.subTest(changes=changes):
                result = normalize_bts_row({**bts_row(), **changes}, ZONES)
                self.assertFalse(result.accepted)

    def test_unknown_airport_and_date(self):
        self.assertFalse(normalize_bts_row(bts_row(), {}).accepted)
        self.assertIsNone(normalize_bts_row({**bts_row(), "FlightDate": "invalid"}, ZONES).flight)

    def test_midnight_rollover_across_leap_month_and_year(self):
        for flight_date, expected_date in [("2024-02-28", "2024-02-29"),
                                           ("2024-02-29", "2024-03-01"),
                                           ("2026-12-31", "2027-01-01")]:
            row = {**bts_row(), "FlightDate": flight_date, "CRSDepTime": "2400",
                   "CRSArrTime": "0300", "Cancelled": "1", "DepTime": "", "DepDelay": "",
                   "ActualElapsedTime": "", "ArrTime": "", "ArrDelay": "", "TaxiOut": "",
                   "TaxiIn": "", "WheelsOff": "", "WheelsOn": "", "AirTime": ""}
            with self.subTest(flight_date=flight_date):
                result = normalize_bts_row(row, ZONES, midnight_policy="end")
                self.assertTrue(result.accepted, result.issues)
                local = result.flight.sobt.astimezone(ZoneInfo("America/New_York"))
                self.assertEqual(local.date().isoformat(), expected_date)


if __name__ == "__main__":
    unittest.main()
