from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta

from . import archive, db, probes
from .config import Settings

log = logging.getLogger(__name__)


async def _run_probe_cycle(settings: Settings) -> None:
    results = await probes.probe_all(settings.targets, settings.probe_timeout_sec)
    ts = int(time.time())
    rows = [
        (ts, r.target, r.address, 1 if r.ok else 0, r.latency_ms, r.method, r.error)
        for r in results
    ]
    db.insert_probes(settings.db_path, rows)
    failed = [r.target for r in results if not r.ok]
    if failed:
        log.info("probe cycle: %d/%d failed (%s)", len(failed), len(results), ",".join(failed))


def _run_archive(settings: Settings) -> None:
    try:
        n = archive.archive_older_than(settings, settings.retention_days)
        log.info("archive: moved %d rows older than %d days", n, settings.retention_days)
    except Exception:
        log.exception("archive job failed")


async def probe_loop(settings: Settings) -> None:
    """Fire a probe cycle every PROBE_INTERVAL_SEC, forever."""
    log.info("probe loop started, interval=%ds", settings.probe_interval_sec)
    while True:
        try:
            await _run_probe_cycle(settings)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("probe cycle failed")
        try:
            await asyncio.sleep(settings.probe_interval_sec)
        except asyncio.CancelledError:
            raise


async def archive_loop(settings: Settings) -> None:
    """Run the archive job once per day at ~03:00 local time."""
    log.info("archive loop started, retention=%dd", settings.retention_days)
    while True:
        now = datetime.now()
        next_run = now.replace(hour=3, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        sleep_sec = (next_run - now).total_seconds()
        try:
            await asyncio.sleep(sleep_sec)
        except asyncio.CancelledError:
            raise
        # Archive is sync (DB ops); off-load to a thread so we don't block probes.
        try:
            await asyncio.to_thread(_run_archive, settings)
        except Exception:
            log.exception("archive failed")
