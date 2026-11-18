"""Turn recorded history into OTLP span requests and score requests.

A history record holds one trace as recorded from a real run of the agent: its spans
with times relative to the trace start, how long before the load each trace started,
and its five judge scores. Converting a record with the same run ID and anchor time
always gives the same IDs and timestamps, so a resumed load sends identical data.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from typing import Any

MIN_AGE_SECONDS = 600
RESOURCE = {"service.name": "price-insight"}
SCORE_NAMESPACE = uuid.UUID("9a3c5f0e-4f0b-4d55-9a57-8f2f0c1c7a21")


def _hex(*parts: str, length: int) -> str:
    return hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()[:length]


def trace_id(run_id: str, record_key: str) -> str:
    return _hex(run_id, record_key, length=32)


def span_id(run_id: str, record_key: str, span_key: str) -> str:
    return _hex(run_id, record_key, span_key, length=16)


def score_id(trace: str, name: str) -> str:
    return str(uuid.uuid5(SCORE_NAMESPACE, f"{trace}:{name}"))


def age_shift(records: list[dict[str, Any]]) -> float:
    """Seconds to add to every offset so the newest trace is at least ten minutes old."""
    newest = min((r["offset_s"] for r in records), default=MIN_AGE_SECONDS)
    return max(0.0, MIN_AGE_SECONDS - newest)


def _start_ns(record: dict[str, Any], anchor_ns: int, shift_s: float) -> int:
    return anchor_ns - int((record["offset_s"] + shift_s) * 1_000_000_000)


def _value(v: Any) -> dict[str, Any]:
    if isinstance(v, bool):
        return {"boolValue": v}
    if isinstance(v, int):
        return {"intValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    return {"stringValue": str(v)}


def _attributes(values: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"key": k, "value": _value(v)} for k, v in values.items()]


def spans_request(records: list[dict[str, Any]], run_id: str, anchor_ns: int, shift_s: float) -> dict[str, Any]:
    """One OTLP JSON request body holding every span of the given records."""
    scopes: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in records:
        start = _start_ns(record, anchor_ns, shift_s)
        tid = trace_id(run_id, record["key"])
        scope = record.get("scope", {})
        bucket = scopes.setdefault((scope.get("name", "langfuse-sdk"), scope.get("version", "")), [])
        for span in record["spans"]:
            body = {
                "traceId": tid,
                "spanId": span_id(run_id, record["key"], span["key"]),
                "name": span["name"],
                "kind": 1,
                "startTimeUnixNano": str(start + int(span["start_ms"] * 1_000_000)),
                "endTimeUnixNano": str(start + int(span["end_ms"] * 1_000_000)),
                "attributes": _attributes(span["attributes"]),
                "status": {},
            }
            if span.get("parent") is not None:
                body["parentSpanId"] = span_id(run_id, record["key"], span["parent"])
            bucket.append(body)
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": _attributes(RESOURCE)},
                "scopeSpans": [
                    {"scope": {"name": name, "version": version}, "spans": spans}
                    for (name, version), spans in scopes.items()
                ],
            }
        ]
    }


def root_span(record: dict[str, Any]) -> dict[str, Any]:
    return next(s for s in record["spans"] if s.get("parent") is None)


def scores(record: dict[str, Any], run_id: str, anchor_ns: int, shift_s: float) -> list[dict[str, Any]]:
    """Score requests for one record: boolean, on the root observation, at its end time."""
    tid = trace_id(run_id, record["key"])
    root = root_span(record)
    end_ns = _start_ns(record, anchor_ns, shift_s) + int(root["end_ms"] * 1_000_000)
    stamp = dt.datetime.fromtimestamp(end_ns / 1_000_000_000, tz=dt.timezone.utc)
    return [
        {
            "id": score_id(tid, name),
            "traceId": tid,
            "observationId": span_id(run_id, record["key"], root["key"]),
            "name": name,
            "value": 1 if passed else 0,
            "dataType": "BOOLEAN",
            "timestamp": stamp.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        }
        for name, passed in record["scores"].items()
    ]
