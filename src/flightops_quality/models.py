"""Small, serializable contracts shared by adapters and quality rules."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Mapping, Optional, Tuple


@dataclass(frozen=True)
class Issue:
    code: str
    severity: str
    fields: Tuple[str, ...]
    message: str

    def __post_init__(self) -> None:
        if self.severity not in {"error", "warning", "info"}:
            raise ValueError("severity must be error, warning, or info")

    def to_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity,
                "fields": list(self.fields), "message": self.message}


@dataclass(frozen=True)
class TimestampResult:
    value: Optional[datetime]
    issues: Tuple[Issue, ...] = ()


@dataclass(frozen=True)
class FlightLeg:
    source: str
    record_id: str
    service_date: date
    carrier: str
    flight_number: str
    origin: str
    destination: str
    aircraft_registration: Optional[str] = None
    cancelled: bool = False
    diverted: bool = False
    sobt: Optional[datetime] = None
    sibt: Optional[datetime] = None
    aobt: Optional[datetime] = None
    aibt: Optional[datetime] = None
    atot: Optional[datetime] = None
    aldt: Optional[datetime] = None
    provenance: Mapping[str, Tuple[str, ...]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        result = {name: getattr(self, name) for name in (
            "source", "record_id", "carrier", "flight_number", "origin",
            "destination", "aircraft_registration", "cancelled", "diverted")}
        result["service_date"] = self.service_date.isoformat()
        for name in ("sobt", "sibt", "aobt", "aibt", "atot", "aldt"):
            value = getattr(self, name)
            result[name] = value.isoformat() if value is not None else None
        result["provenance"] = {key: list(value) for key, value in self.provenance.items()}
        return result


@dataclass(frozen=True)
class RecordResult:
    flight: Optional[FlightLeg]
    issues: Tuple[Issue, ...]
    raw: Mapping[str, Any]
    row_number: int = 1

    @property
    def accepted(self) -> bool:
        return self.flight is not None and not any(i.severity == "error" for i in self.issues)

    def to_dict(self) -> dict:
        return {"row_number": self.row_number, "raw": dict(self.raw),
                "flight": self.flight.to_dict() if self.flight else None,
                "issues": [issue.to_dict() for issue in self.issues]}


@dataclass(frozen=True)
class BatchReport:
    accepted: Tuple[RecordResult, ...]
    quarantined: Tuple[RecordResult, ...]
    duplicates: Tuple[RecordResult, ...]
    input_count: int

    def __post_init__(self) -> None:
        if self.input_count != len(self.accepted) + len(self.quarantined) + len(self.duplicates):
            raise ValueError("Every input row must appear in exactly one output category")

    @property
    def counts(self) -> dict:
        return {"input": self.input_count, "accepted": len(self.accepted),
                "quarantined": len(self.quarantined), "duplicates": len(self.duplicates)}

    def to_dict(self) -> dict:
        return {"counts": self.counts, "accepted": [r.to_dict() for r in self.accepted],
                "quarantined": [r.to_dict() for r in self.quarantined],
                "duplicates": [r.to_dict() for r in self.duplicates]}
