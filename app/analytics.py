from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable
from zoneinfo import ZoneInfo

from . import db
from .config import Settings


@dataclass
class TargetStatus:
    target: str
    address: str
    ok: bool
    latency_ms: float | None
    last_seen: int  # unix epoch
    method: str


@dataclass
class Outage:
    start: int
    end: int
    duration_sec: int
    classification: str  # 'isp' | 'local' | 'partial'


def current_status(settings: Settings) -> list[TargetStatus]:
    rows = db.fetch_latest_per_target(settings.db_path)
    return [
        TargetStatus(
            target=r["target"],
            address=r["address"],
            ok=bool(r["ok"]),
            latency_ms=r["latency_ms"],
            last_seen=r["ts"],
            method=r["method"],
        )
        for r in rows
    ]


def uptime_pct(settings: Settings, window_sec: int) -> dict[str, float]:
    since = int(time.time()) - window_sec
    rows = db.fetch_since(settings.db_path, since)
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # [ok_count, total]
    for r in rows:
        totals[r["target"]][1] += 1
        if r["ok"]:
            totals[r["target"]][0] += 1
    return {t: (ok / total * 100) if total else 0.0 for t, (ok, total) in totals.items()}


def _group_by_cycle(rows: Iterable) -> dict[int, dict[str, dict]]:
    """Group rows by ts. Each cycle ts → {target: {ok, latency_ms}}."""
    by_ts: dict[int, dict[str, dict]] = defaultdict(dict)
    for r in rows:
        by_ts[r["ts"]][r["target"]] = {"ok": bool(r["ok"]), "latency_ms": r["latency_ms"]}
    return by_ts


def detect_outages(
    settings: Settings,
    window_sec: int,
    min_consecutive_failures: int = 2,
) -> list[Outage]:
    """An outage = >= min_consecutive_failures cycles where ALL external targets failed.

    Classification looks at gateway behavior across the failed window.
    """
    since = int(time.time()) - window_sec
    rows = db.fetch_since(settings.db_path, since)
    if not rows:
        return []

    external_names = {t.name for t in settings.targets if t.is_external}
    has_gateway = any(not t.is_external for t in settings.targets)
    by_ts = _group_by_cycle(rows)
    timestamps = sorted(by_ts.keys())

    outages: list[Outage] = []
    current_run: list[int] = []

    def flush() -> None:
        if len(current_run) < min_consecutive_failures:
            current_run.clear()
            return
        start = current_run[0]
        end = current_run[-1]
        # Classify: examine gateway across the run
        if has_gateway:
            gateway_results = []
            partial = False
            for ts in current_run:
                cycle = by_ts[ts]
                if "gateway" in cycle:
                    gateway_results.append(cycle["gateway"]["ok"])
                # detect partial: at least one external responded in any failed cycle
                ext_ok = [cycle.get(n, {}).get("ok", False) for n in external_names]
                if any(ext_ok):
                    partial = True
            if partial:
                classification = "partial"
            elif gateway_results and all(gateway_results):
                classification = "isp"
            elif gateway_results and not any(gateway_results):
                classification = "local"
            else:
                classification = "isp"  # mixed gateway state — treat as ISP/WAN
        else:
            classification = "isp"
        outages.append(
            Outage(
                start=start,
                end=end,
                duration_sec=end - start + settings.probe_interval_sec,
                classification=classification,
            )
        )
        current_run.clear()

    for ts in timestamps:
        cycle = by_ts[ts]
        ext_results = [cycle.get(n, {}).get("ok", True) for n in external_names]
        all_external_failed = ext_results and not any(ext_results)
        if all_external_failed:
            current_run.append(ts)
        else:
            flush()
    flush()

    return outages


def latency_series(
    settings: Settings, window_sec: int, bucket_sec: int = 60
) -> dict[str, list[tuple[int, float | None]]]:
    """Time-bucketed mean latency per target. Failed probes contribute None to the bucket;
    bucket value is mean of successful latencies, or None if all failed."""
    since = int(time.time()) - window_sec
    rows = db.fetch_since(settings.db_path, since)
    buckets: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    seen_buckets: dict[str, set[int]] = defaultdict(set)
    for r in rows:
        bucket_ts = (r["ts"] // bucket_sec) * bucket_sec
        seen_buckets[r["target"]].add(bucket_ts)
        if r["ok"] and r["latency_ms"] is not None:
            buckets[r["target"]][bucket_ts].append(r["latency_ms"])

    out: dict[str, list[tuple[int, float | None]]] = {}
    for target, bucket_set in seen_buckets.items():
        series = []
        for bucket_ts in sorted(bucket_set):
            samples = buckets[target].get(bucket_ts, [])
            mean = sum(samples) / len(samples) if samples else None
            series.append((bucket_ts, mean))
        out[target] = series
    return out


def outage_heatmap(
    settings: Settings, window_sec: int, tz_name: str = "UTC"
) -> list[list[float]]:
    """7x24 matrix of outage minutes by (day_of_week, hour_of_day) in local time.
    Monday=0, Sunday=6.
    """
    tz = ZoneInfo(tz_name)
    matrix = [[0.0 for _ in range(24)] for _ in range(7)]
    for outage in detect_outages(settings, window_sec):
        # Spread the outage across hour buckets it touches (in local time).
        cur = outage.start
        end = outage.end + settings.probe_interval_sec
        while cur < end:
            dt = datetime.fromtimestamp(cur, tz=tz)
            hour_end_dt = dt.replace(minute=0, second=0, microsecond=0)
            hour_end = int(hour_end_dt.timestamp()) + 3600
            chunk_end = min(end, hour_end)
            seconds_in_hour = chunk_end - cur
            matrix[dt.weekday()][dt.hour] += seconds_in_hour / 60.0
            cur = chunk_end
    return matrix
