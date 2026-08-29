"""Warstwa trwała: SQLite z heartbeat-merge zdarzeń.

Schemat inspirowany ActivityWatch (jeden bucket = tabela events).
Heartbeat-merge: jeżeli nowa próbka ma te same dane (app/title/tab/browser/idle)
co ostatnie aktywne zdarzenie i przerwa <= pulsetime, przedłużamy ts_end;
w przeciwnym razie wstawiamy nowe zdarzenie.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

from .config import DB_PATH, DATA_DIR, SETTINGS


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_start  TEXT NOT NULL,        -- ISO8601 UTC
    ts_end    TEXT NOT NULL,        -- ISO8601 UTC
    app       TEXT NOT NULL,        -- nazwa procesu, np. chrome.exe
    exe       TEXT,                 -- pełna ścieżka do exe (jeśli znana)
    title     TEXT,                 -- pełny tytuł okna
    tab       TEXT,                 -- tytuł zakładki przeglądarki (lub NULL)
    browser   TEXT,                 -- nazwa przeglądarki (lub NULL)
    host      TEXT NOT NULL,        -- nazwa komputera
    idle      INTEGER NOT NULL DEFAULT 0  -- 1 = okres nieaktywności (AFK)
);
CREATE INDEX IF NOT EXISTS idx_events_start ON events(ts_start);
CREATE INDEX IF NOT EXISTS idx_events_end   ON events(ts_end);
CREATE INDEX IF NOT EXISTS idx_events_app   ON events(app);
CREATE INDEX IF NOT EXISTS idx_events_idle  ON events(idle);
"""


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s)


class Storage:
    """Wątkowo-bezpieczny wrapper nad sqlite3 (jeden connection na wątek)."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = str(db_path)
        self._local = threading.local()
        # Inicjalizacja schematu w wątku głównym
        with self._cursor() as (conn, cur):
            cur.executescript(SCHEMA)
            conn.commit()

    # --- connection management ------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path, timeout=30, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            self._local.conn = conn
        return conn

    @contextmanager
    def _cursor(self):
        conn = self._connect()
        cur = conn.cursor()
        try:
            yield conn, cur
        finally:
            cur.close()

    # --- heartbeat insert -----------------------------------------------------
    def heartbeat(
        self,
        *,
        ts: datetime,
        app: str,
        exe: Optional[str],
        title: Optional[str],
        tab: Optional[str],
        browser: Optional[str],
        idle: bool,
    ) -> None:
        """Wstaw/rozszerz zdarzenie wg zasady heartbeat-merge."""
        ts_iso = ts.astimezone(timezone.utc).isoformat(timespec="seconds")
        idle_flag = 1 if idle else 0
        with self._cursor() as (conn, cur):
            row = cur.execute(
                """SELECT id, ts_end, app, title, tab, browser, idle
                   FROM events ORDER BY id DESC LIMIT 1"""
            ).fetchone()
            if row is not None:
                same_payload = (
                    row["app"] == app
                    and (row["title"] or None) == (title or None)
                    and (row["tab"] or None) == (tab or None)
                    and (row["browser"] or None) == (browser or None)
                    and row["idle"] == idle_flag
                )
                if same_payload:
                    last_end = parse_iso(row["ts_end"])
                    gap = (ts - last_end).total_seconds()
                    if 0 <= gap <= SETTINGS.pulsetime:
                        cur.execute(
                            "UPDATE events SET ts_end=? WHERE id=?",
                            (ts_iso, row["id"]),
                        )
                        conn.commit()
                        return
            cur.execute(
                """INSERT INTO events
                   (ts_start, ts_end, app, exe, title, tab, browser, host, idle)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (ts_iso, ts_iso, app, exe, title, tab, browser, SETTINGS.hostname, idle_flag),
            )
            conn.commit()

    # --- zamyknięcie niezakończonego zdarzenia (przy pauzie/wyjściu) ----------
    def touch_last(self, ts: Optional[datetime] = None) -> None:
        """Wymuszone odcięcie ostatniego zdarzenia (nowe ts_end = teraz)."""
        ts = ts or datetime.now(timezone.utc)
        ts_iso = ts.astimezone(timezone.utc).isoformat(timespec="seconds")
        with self._cursor() as (conn, cur):
            cur.execute(
                "UPDATE events SET ts_end=? WHERE id=(SELECT MAX(id) FROM events)",
                (ts_iso,),
            )
            conn.commit()

    # --- zapytania do dashboardu ---------------------------------------------
    def _day_bounds_utc(self, d: datetime) -> tuple[datetime, datetime]:
        """Zwraca początek/koniec dnia lokalnego przeliczony na UTC."""
        start_local = d.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = start_local + timedelta(days=1)
        # Konwersja naiwnego czasu lokalnego -> UTC
        return (
            start_local.astimezone(timezone.utc),
            end_local.astimezone(timezone.utc),
        )

    def daily_summary(self, day: Optional[datetime] = None) -> dict:
        """Suma czasu per aplikacja dla danego dnia (używa julianday)."""
        day = day or datetime.now().astimezone()
        start_utc, end_utc = self._day_bounds_utc(day)
        s_iso = start_utc.isoformat(timespec="seconds")
        e_iso = end_utc.isoformat(timespec="seconds")
        with self._cursor() as (_, cur):
            rows = cur.execute(
                """SELECT app,
                          SUM(
                            (julianday(MIN(ts_end, ?)) -
                             julianday(MAX(ts_start, ?))) * 86400.0
                          ) AS dur_seconds,
                          COUNT(*) AS n_events
                   FROM events
                   WHERE ts_end > ? AND ts_start < ?
                     AND idle = 0
                   GROUP BY app
                   ORDER BY dur_seconds DESC""",
                (e_iso, s_iso, s_iso, e_iso),
            ).fetchall()
            idle_row = cur.execute(
                """SELECT SUM(
                     (julianday(MIN(ts_end, ?)) -
                      julianday(MAX(ts_start, ?))) * 86400.0
                   ) AS dur_seconds
                   FROM events
                   WHERE ts_end > ? AND ts_start < ?
                     AND idle = 1""",
                (e_iso, s_iso, s_iso, e_iso),
            ).fetchone()
        apps = [
            {"app": r["app"], "dur_seconds": round(r["dur_seconds"] or 0, 1),
             "n_events": r["n_events"]}
            for r in rows
        ]
        total = sum(a["dur_seconds"] for a in apps)
        idle_seconds = round((idle_row["dur_seconds"] if idle_row else 0) or 0, 1)
        return {
            "day": day.date().isoformat(),
            "total_seconds": round(total, 1),
            "idle_seconds": idle_seconds,
            "apps": apps,
        }

    def recent_events(self, day: Optional[datetime] = None, limit: int = 50) -> list:
        day = day or datetime.now().astimezone()
        start_utc, end_utc = self._day_bounds_utc(day)
        s_iso = start_utc.isoformat(timespec="seconds")
        e_iso = end_utc.isoformat(timespec="seconds")
        with self._cursor() as (_, cur):
            rows = cur.execute(
                """SELECT ts_start, ts_end, app, title, tab, browser, idle,
                          (julianday(ts_end) - julianday(ts_start)) * 86400.0 AS dur_seconds
                   FROM events
                   WHERE ts_end > ? AND ts_start < ?
                   ORDER BY ts_start DESC
                   LIMIT ?""",
                (s_iso, e_iso, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def week_summary(self, today: Optional[datetime] = None) -> list:
        today = today or datetime.now().astimezone()
        out = []
        for i in range(6, -1, -1):
            d = today - timedelta(days=i)
            out.append(self.daily_summary(d))
        return out

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None
