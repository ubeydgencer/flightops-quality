import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

from flightops_quality.models import FlightLeg
from flightops_quality.rules import flight_metrics, turnaround_minutes, validate_leg


class RuleTests(unittest.TestCase):
    def setUp(self):
        start = datetime(2026, 10, 9, 9, tzinfo=timezone.utc)
        self.leg = FlightLeg("demo", "1", date(2026, 10, 9), "ZZ", "100", "IST", "FRA",
                             aircraft_registration="SYNTH-01", sobt=start,
                             sibt=start + timedelta(hours=3), aobt=start - timedelta(minutes=5),
                             atot=start + timedelta(minutes=15), aldt=start + timedelta(hours=3),
                             aibt=start + timedelta(hours=3, minutes=10))

    def test_gate_runway_distinction_and_early_delay(self):
        metrics = flight_metrics(self.leg)
        self.assertEqual(metrics, dict(departure_delay_minutes=-5, arrival_delay_minutes=10,
                                      block_minutes=195, taxi_out_minutes=20,
                                      taxi_in_minutes=10, airborne_minutes=165))
        self.assertFalse(validate_leg(self.leg))

    def test_cancelled_gate_departure_is_preserved(self):
        cancelled = replace(self.leg, cancelled=True, aibt=None, atot=None, aldt=None)
        self.assertFalse(validate_leg(cancelled))
        self.assertTrue(all(value is None for value in flight_metrics(cancelled).values()))

    def test_diverted_null_arrival_is_expected(self):
        diverted = replace(self.leg, diverted=True, aibt=None, aldt=None)
        self.assertFalse(validate_leg(diverted))
        self.assertEqual(flight_metrics(diverted)["departure_delay_minutes"], -5)
        self.assertIsNone(flight_metrics(diverted)["arrival_delay_minutes"])

    def test_partial_actual_chronology(self):
        bad = replace(self.leg, atot=None, aldt=None, aibt=self.leg.aobt - timedelta(minutes=1))
        self.assertIn("ACTUAL_ORDER", [i.code for i in validate_leg(bad)])

    def test_naive_timestamps_are_rejected(self):
        bad = replace(self.leg, aobt=self.leg.aobt.replace(tzinfo=None))
        self.assertIn("TIME_NOT_AWARE", [i.code for i in validate_leg(bad)])
        self.assertIsNone(flight_metrics(bad)["departure_delay_minutes"])

    def test_turnaround_needs_explicit_same_aircraft_airport_pair(self):
        outbound = replace(self.leg, record_id="2", origin="FRA", destination="IST",
                           sobt=self.leg.sobt + timedelta(hours=5),
                           sibt=self.leg.sibt + timedelta(hours=5),
                           aobt=self.leg.aibt + timedelta(minutes=40),
                           aibt=self.leg.aibt + timedelta(hours=4), atot=None, aldt=None)
        self.assertEqual(turnaround_minutes(self.leg, outbound), 40)
        for bad in (replace(outbound, aircraft_registration=None),
                    replace(outbound, origin="LHR"), replace(outbound, diverted=True),
                    replace(outbound, aobt=self.leg.aibt - timedelta(minutes=1))):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    turnaround_minutes(self.leg, bad)


if __name__ == "__main__":
    unittest.main()
