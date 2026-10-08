"""Conservative whole-group conflict handling and exact-repeat auditing."""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import replace
from typing import Iterable, Mapping, Optional, Tuple

from ._raw import snapshot_raw
from .adapters.canonical import normalize_record
from .models import BatchReport, Issue, RecordResult


def _identity(record: RecordResult) -> Optional[Tuple[str, str]]:
    if record.flight:
        return record.flight.source, record.flight.record_id
    source, identity = record.raw.get("source"), record.raw.get("record_id")
    if isinstance(source, str) and source.strip() and isinstance(identity, str) and identity.strip():
        return source.strip(), identity.strip()
    return None


def analyze_results(records: Iterable[RecordResult]) -> BatchReport:
    records = tuple(replace(record, raw=snapshot_raw(record.raw)) for record in records)
    groups = defaultdict(list)
    payloads = []
    for index, record in enumerate(records):
        identity = _identity(record)
        # Missing identities are deliberately not grouped together.
        groups[identity if identity is not None else (None, index)].append(index)
        payloads.append(json.dumps(dict(record.raw), ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":"), allow_nan=False))
    categories = {}
    for indices in groups.values():
        different = len({payloads[index] for index in indices}) > 1
        if different:
            issue = Issue("DUPLICATE_CONFLICT", "error", ("source", "record_id"),
                          "One identity has conflicting raw payloads; all group members require reconciliation.")
            for index in indices:
                categories[index] = ("quarantined", replace(records[index], issues=records[index].issues + (issue,)))
            continue
        first, *repeats = indices
        record = records[first]
        categories[first] = ("accepted" if record.accepted else "quarantined", record)
        for index in repeats:
            issue = Issue("DUPLICATE_EXACT", "info", ("source", "record_id"),
                          "Exact raw repeat; the first occurrence determines the flight disposition.")
            categories[index] = ("duplicates", replace(records[index], issues=records[index].issues + (issue,)))
    output = {"accepted": [], "quarantined": [], "duplicates": []}
    for index in range(len(records)):
        category, record = categories[index]
        output[category].append(record)
    return BatchReport(tuple(output["accepted"]), tuple(output["quarantined"]),
                       tuple(output["duplicates"]), len(records))


def analyze_records(rows: Iterable[Mapping]) -> BatchReport:
    return analyze_results(normalize_record(row, row_number=number) for number, row in enumerate(rows, start=1))
