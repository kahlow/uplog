from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import db
from .config import load_settings
from .routes import router
from .scheduler import build_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    db.init_db(settings.db_path)
    log.info("loaded %d targets: %s", len(settings.targets),
             ", ".join(f"{t.name}={t.address}" for t in settings.targets))
    log.info("probe interval: %ds, retention: %dd, db: %s",
             settings.probe_interval_sec, settings.retention_days, settings.db_path)

    app.state.settings = settings
    scheduler = build_scheduler(settings)
    scheduler.start()
    log.info("scheduler started")
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        log.info("scheduler stopped")


app = FastAPI(title="Home Internet Tester", lifespan=lifespan)
app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).parent / "static")),
    name="static",
)
app.include_router(router)
