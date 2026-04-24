from __future__ import annotations

import logging
import time

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

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


def build_scheduler(settings: Settings) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        _run_probe_cycle,
        trigger=IntervalTrigger(seconds=settings.probe_interval_sec),
        kwargs={"settings": settings},
        id="probe_cycle",
        max_instances=1,
        coalesce=True,
        next_run_time=None,  # first run scheduled immediately by start()
    )
    scheduler.add_job(
        _run_archive,
        trigger=CronTrigger(hour=3, minute=0),
        kwargs={"settings": settings},
        id="archive_daily",
        max_instances=1,
        coalesce=True,
    )
    return scheduler
