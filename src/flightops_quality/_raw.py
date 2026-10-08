"""Finite UTF-8 JSON snapshots, independent of subsequent input mutations."""
from __future__ import annotations

import math
from typing import Mapping

MAX_JSON_DEPTH = 32
MAX_INTEGER_BITS = 4096


def snapshot_raw(row: Mapping) -> dict:
    if not isinstance(row, Mapping):
        raise ValueError("Raw input must be a JSON-compatible mapping")

    def copy(value, depth):
        if depth > MAX_JSON_DEPTH:
            raise ValueError("Raw JSON nesting exceeds the 32-level limit")
        if isinstance(value, Mapping):
            result = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ValueError("Raw JSON objects must have string keys at every level")
                try:
                    key.encode("utf-8")
                except UnicodeEncodeError as exc:
                    raise ValueError("Raw JSON keys must be valid UTF-8 strings") from exc
                result[key] = copy(item, depth + 1)
            return result
        if isinstance(value, list):
            return [copy(item, depth + 1) for item in value]
        if isinstance(value, str):
            try:
                value.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise ValueError("Raw JSON strings must be valid UTF-8") from exc
            return value
        if value is None or isinstance(value, bool):
            return value
        if isinstance(value, int):
            if value.bit_length() > MAX_INTEGER_BITS:
                raise ValueError("Raw JSON integers exceed the 4096-bit limit")
            return value
        if isinstance(value, float) and math.isfinite(value):
            return value
        raise ValueError("Raw input must contain finite JSON-compatible values")

    return copy(row, 0)
