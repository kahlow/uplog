from __future__ import annotations

import csv
import io
import json
import os
import time
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates

from . import analytics, db
from .config import Settings

router = APIRouter()

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    settings = get_settings(request)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "targets": [{"name": t.name, "address": t.address} for t in settings.targets],
            "tz": os.environ.get("TZ", "UTC"),
            "probe_interval_sec": settings.probe_interval_sec,
        },
    )


@router.get("/api/status")
async def api_status(request: Request):
    settings = get_settings(request)
    statuses = analytics.current_status(settings)
    up_24 = analytics.uptime_pct(settings, 24 * 3600)
    up_7d = analytics.uptime_pct(settings, 7 * 86400)

    # "Up for" — time since the most recent outage end (or since first probe).
    outages_7d = analytics.detect_outages(settings, 7 * 86400)
    if outages_7d:
        last_outage = max(outages_7d, key=lambda o: o.end)
        up_for_sec = max(0, int(time.time()) - (last_outage.end + settings.probe_interval_sec))
    else:
        # No outage in window — use earliest probe in 7d as the "up since" anchor.
        rows = db.fetch_since(settings.db_path, int(time.time()) - 7 * 86400)
        if rows:
            up_for_sec = int(time.time()) - rows[0]["ts"]
        else:
            up_for_sec = 0

    return {
        "now": int(time.time()),
        "targets": [asdict(s) for s in statuses],
        "uptime_24h": up_24,
        "uptime_7d": up_7d,
        "up_for_sec": up_for_sec,
    }


@router.get("/api/history")
async def api_history(request: Request, hours: int = Query(24, ge=1, le=24 * 14)):
    settings = get_settings(request)
    bucket = 60 if hours <= 24 else 300
    series = analytics.latency_series(settings, hours * 3600, bucket_sec=bucket)
    return {
        "bucket_sec": bucket,
        "series": {
            target: [{"ts": ts, "latency_ms": ms} for ts, ms in points]
            for target, points in series.items()
        },
    }


@router.get("/api/outages")
async def api_outages(request: Request, days: int = Query(7, ge=1, le=14)):
    settings = get_settings(request)
    outages = analytics.detect_outages(settings, days * 86400)
    return {"outages": [asdict(o) for o in outages]}


@router.get("/api/heatmap")
async def api_heatmap(request: Request, days: int = Query(7, ge=1, le=14)):
    settings = get_settings(request)
    tz = os.environ.get("TZ", "UTC")
    matrix = analytics.outage_heatmap(settings, days * 86400, tz_name=tz)
    return {"tz": tz, "matrix": matrix}


@router.get("/api/export.csv")
async def api_export_csv(request: Request, days: int = Query(7, ge=1, le=14)):
    settings = get_settings(request)
    since = int(time.time()) - days * 86400
    rows = db.fetch_since(settings.db_path, since)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["ts_utc", "target", "address", "ok", "latency_ms", "method", "error"])
    for r in rows:
        w.writerow(
            [r["ts"], r["target"], r["address"], r["ok"], r["latency_ms"], r["method"], r["error"]]
        )
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="probes-{days}d.csv"'},
    )


@router.get("/api/export.json")
async def api_export_json(request: Request, days: int = Query(7, ge=1, le=14)):
    settings = get_settings(request)
    since = int(time.time()) - days * 86400
    rows = db.fetch_since(settings.db_path, since)
    payload = [
        {
            "ts": r["ts"],
            "target": r["target"],
            "address": r["address"],
            "ok": bool(r["ok"]),
            "latency_ms": r["latency_ms"],
            "method": r["method"],
            "error": r["error"],
        }
        for r in rows
    ]
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": f'attachment; filename="probes-{days}d.json"'},
    )
