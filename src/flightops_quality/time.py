"""Resolve instants without choosing a DST fold or inventing a timezone."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional, Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import Issue, TimestampResult

UTC = timezone.utc
ISO_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}[T ](?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d(?:\.\d{1,6})?)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)?$")


def _failure(code: str, message: str) -> TimestampResult:
    return TimestampResult(None, (Issue(code, "error", ("timestamp",), message),))


def resolve_timestamp(value: Union[str, datetime, None], zone: Optional[str] = None,
                      fold: Optional[int] = None) -> TimestampResult:
    if value is None or value == "":
        return TimestampResult(None)
    if fold is not None and (isinstance(fold, bool) or not isinstance(fold, int) or fold not in (0, 1)):
        return _failure("TIME_FOLD_INVALID", "A local fold must be integer 0 or 1.")
    if isinstance(value, str):
        if not ISO_TIMESTAMP.fullmatch(value):
            return _failure("TIME_INVALID", "Expected an ISO datetime with date and clock, optionally an offset.")
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return _failure("TIME_INVALID", "The ISO datetime has an invalid date, clock or offset.")
    if not isinstance(value, datetime):
        return _failure("TIME_INVALID", "Timestamp must be a datetime or ISO datetime string.")
    try:
        if value.tzinfo is not None and value.utcoffset() is not None:
            return TimestampResult(value.astimezone(UTC))
    except (ValueError, OverflowError):
        return _failure("TIME_INVALID", "Timestamp cannot be represented in UTC.")
    if not zone:
        return _failure("TIME_ZONE_REQUIRED", "A naive datetime requires an explicit IANA timezone.")
    try:
        tz = ZoneInfo(zone)
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        return _failure("TIME_ZONE_UNKNOWN", "IANA timezone is unknown or its database is unavailable.")
    candidates = {}
    try:
        for candidate_fold in (0, 1):
            candidate = value.replace(tzinfo=tz, fold=candidate_fold).astimezone(UTC)
            returned = candidate.astimezone(tz)
            if returned.replace(tzinfo=None) == value.replace(tzinfo=None):
                candidates[candidate_fold] = candidate
    except (ValueError, OverflowError):
        return _failure("TIME_INVALID", "Local datetime cannot be represented in UTC.")
    if not candidates:
        return _failure("TIME_NONEXISTENT", "Local clock falls in a timezone transition gap.")
    if len(set(candidates.values())) > 1:
        if fold is None:
            return _failure("TIME_AMBIGUOUS", "Local clock occurs twice; supply an offset or explicit fold 0/1.")
        return TimestampResult(candidates[fold])
    return TimestampResult(next(iter(candidates.values())))
