from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import db
from .config import Settings

log = logging.getLogger(__name__)


def _row_to_dict(row) -> dict:
    return {
        "ts": row["ts"],
        "iso": datetime.fromtimestamp(row["ts"], tz=timezone.utc).isoformat(),
        "target": row["target"],
        "address": row["address"],
        "ok": bool(row["ok"]),
        "latency_ms": row["latency_ms"],
        "method": row["method"],
        "error": row["error"],
    }


def _merge_into_file(path: Path, new_rows: list[dict]) -> None:
    if path.exists():
        try:
            existing = json.loads(path.read_text())
            if not isinstance(existing, list):
                existing = []
        except json.JSONDecodeError:
            log.warning("archive file %s was malformed; overwriting", path)
            existing = []
    else:
        existing = []
    combined = existing + new_rows
    combined.sort(key=lambda r: (r["ts"], r["target"]))
    path.write_text(json.dumps(combined, indent=2))


def archive_older_than(settings: Settings, days: int) -> int:
    cutoff = int(time.time()) - days * 86400
    rows = db.fetch_older_than(settings.db_path, cutoff)
    if not rows:
        return 0

    by_day: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        date_str = datetime.fromtimestamp(r["ts"], tz=timezone.utc).strftime("%Y-%m-%d")
        by_day[date_str].append(_row_to_dict(r))

    for date_str, day_rows in by_day.items():
        path = settings.archive_dir / f"probes-{date_str}.json"
        _merge_into_file(path, day_rows)

    return db.delete_older_than(settings.db_path, cutoff)
