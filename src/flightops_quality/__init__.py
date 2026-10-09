"""Explainable quality checks for flight operations data."""
__version__ = "0.2.0"

from .batch import analyze_records, analyze_results
from .gates import QualityPolicy, evaluate_quality
from .models import BatchReport, FlightLeg, Issue, RecordResult, TimestampResult
from .rules import flight_metrics, turnaround_minutes, validate_leg
from .time import resolve_timestamp

__all__ = ["__version__", "BatchReport", "FlightLeg", "Issue", "RecordResult",
           "TimestampResult", "analyze_records", "analyze_results", "flight_metrics",
           "turnaround_minutes", "validate_leg", "resolve_timestamp",
           "QualityPolicy", "evaluate_quality"]
