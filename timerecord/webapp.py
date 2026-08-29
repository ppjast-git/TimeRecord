"""FastAPI dashboard: przegląd czasu pracy w przeglądarce.

Endpointy:
  GET /                  -> strona HTML dashboardu
  GET /api/today         -> JSON: suma dzisiaj + per-app
  GET /api/day/{date}    -> JSON: suma dla dnia (YYYY-MM-DD)
  GET /api/week          -> JSON: ostatnie 7 dni
  GET /api/events?date=  -> JSON: ostatnie zdarzenia danego dnia
  GET /api/now           -> JSON: aktualna próbka z collectora
  POST /api/pause        -> pauza collectora
  POST /api/resume       -> wznowienie collectora
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .collector import Collector
from .config import SETTINGS
from .storage import Storage

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_STATIC_DIR = Path(__file__).parent.parent / "static"


def _fmt_duration(seconds: float) -> str:
    """Sekundy -> '1h 23m' / '12m 30s' / '45s'."""
    s = int(round(seconds))
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def create_app(storage: Storage, collector: Collector) -> FastAPI:
    app = FastAPI(title="TimeRecord", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        html = (_TEMPLATES_DIR / "dashboard.html").read_text(encoding="utf-8")
        return HTMLResponse(html)

    @app.get("/api/today")
    async def api_today() -> JSONResponse:
        return _enrich(storage.daily_summary())

    @app.get("/api/day/{date}")
    async def api_day(date: str) -> JSONResponse:
        try:
            d = _dt.datetime.fromisoformat(date).astimezone()
        except ValueError:
            raise HTTPException(400, "Niepoprawna data (użyj YYYY-MM-DD)")
        return _enrich(storage.daily_summary(d))

    @app.get("/api/week")
    async def api_week() -> JSONResponse:
        days = storage.week_summary()
        return JSONResponse({"days": [_enrich(d) for d in days]})

    @app.get("/api/events")
    async def api_events(date: Optional[str] = None, limit: int = 50) -> JSONResponse:
        if date:
            try:
                d = _dt.datetime.fromisoformat(date).astimezone()
            except ValueError:
                raise HTTPException(400, "Niepoprawna data")
        else:
            d = None
        events = storage.recent_events(d, limit=limit)
        for e in events:
            e["dur_human"] = _fmt_duration(e.get("dur_seconds") or 0)
        return JSONResponse({"events": events})

    @app.get("/api/now")
    async def api_now() -> JSONResponse:
        s = collector.last_sample
        return JSONResponse({
            "paused": collector.is_paused,
            "sample": s,
            "host": SETTINGS.hostname,
            "interval": SETTINGS.sample_interval,
        })

    @app.post("/api/pause")
    async def api_pause() -> JSONResponse:
        collector.pause()
        return JSONResponse({"paused": True})

    @app.post("/api/resume")
    async def api_resume() -> JSONResponse:
        collector.resume()
        return JSONResponse({"paused": False})

    def _enrich(summary: dict) -> dict:
        summary = dict(summary)
        summary["total_human"] = _fmt_duration(summary.get("total_seconds") or 0)
        summary["idle_human"] = _fmt_duration(summary.get("idle_seconds") or 0)
        for a in summary.get("apps", []):
            a["dur_human"] = _fmt_duration(a.get("dur_seconds") or 0)
        return summary

    return app
