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

-- Reguły normalizacji (użytkownika) — zobacz timerecord/rules.py
CREATE TABLE IF NOT EXISTS rules (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    enabled       INTEGER NOT NULL DEFAULT 1,
    priority      INTEGER NOT NULL DEFAULT 100,   -- niższy = wcześniej
    app_match     TEXT NOT NULL DEFAULT '',       -- substring w nazwie app; '' = wszystkie
    match_type    TEXT NOT NULL DEFAULT 'regex',  -- 'regex' | 'contains'
    pattern       TEXT NOT NULL,
    entity_tmpl   TEXT NOT NULL DEFAULT '{0}',    -- {0}=tytuł/match, {n}=grupa regex
    category      TEXT NOT NULL DEFAULT 'Inne',
    project_mode  TEXT NOT NULL DEFAULT 'inherit',-- inherit|none|fixed|group
    project       TEXT,                           -- nazwa dla project_mode='fixed'
    project_group INTEGER,                        -- nr grupy dla 'group'/deklaracji
    is_decl       INTEGER NOT NULL DEFAULT 0,     -- 1 = reguła deklaruje projekt
    detail_group  INTEGER,                        -- nr grupy -> detail; NULL = raw
    note          TEXT,
    created_at    TEXT NOT NULL
);
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
        self._seed_rules()

    def _seed_rules(self) -> None:
        """Importuj reguły z rules_seed.json w DATA_DIR gdy tabela rules jest pusta.

        Plik seed jest lokalny (poza repo) — użytkownik może tam trzymać
        swoje prywatne paczki reguł, np. branżowe.
        """
        import json as _json
        seed = DATA_DIR / "rules_seed.json"
        with self._cursor() as (_, cur):
            n = cur.execute("SELECT COUNT(*) AS c FROM rules").fetchone()["c"]
        if n > 0 or not seed.exists():
            return
        try:
            data = _json.loads(seed.read_text(encoding="utf-8"))
            if isinstance(data, list):
                imported = self.import_rules(data)
                if imported:
                    import logging
                    logging.getLogger(__name__).info(
                        "zaimportowano %d reguł z %s", imported, seed)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("seed reguł nie powiódł się")

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

    # --- reguły normalizacji (CRUD) ------------------------------------------
    def _row_to_rule(self, r: sqlite3.Row):
        from .rules import Rule
        return Rule(
            id=r["id"], enabled=bool(r["enabled"]), priority=r["priority"],
            app_match=r["app_match"] or "", match_type=r["match_type"],
            pattern=r["pattern"], entity_tmpl=r["entity_tmpl"],
            category=r["category"], project_mode=r["project_mode"],
            project=r["project"], project_group=r["project_group"],
            is_decl=bool(r["is_decl"]), detail_group=r["detail_group"],
            builtin=False,
        )

    def list_rules(self) -> list:
        """Wszystkie reguły użytkownika (włącznie z disabled), posortowane."""
        with self._cursor() as (_, cur):
            rows = cur.execute(
                "SELECT * FROM rules ORDER BY priority ASC, id ASC"
            ).fetchall()
        return [self._row_to_rule(r) for r in rows]

    def rules_enabled(self) -> list:
        """Aktywne reguły użytkownika — do silnika normalizacji."""
        return [r for r in self.list_rules() if r.enabled]

    def add_rule(self, rule) -> int:
        """Dodaj regułę. Zwraca id."""
        with self._cursor() as (conn, cur):
            cur.execute(
                """INSERT INTO rules
                   (enabled, priority, app_match, match_type, pattern,
                    entity_tmpl, category, project_mode, project, project_group,
                    is_decl, detail_group, note, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (int(rule.enabled), rule.priority, rule.app_match, rule.match_type,
                 rule.pattern, rule.entity_tmpl, rule.category, rule.project_mode,
                 rule.project, rule.project_group, int(rule.is_decl),
                 rule.detail_group, getattr(rule, "note", None), utcnow_iso()),
            )
            conn.commit()
            return cur.lastrowid

    def update_rule(self, rule_id: int, **fields) -> bool:
        """Aktualizuj wybrane pola reguły. Zwraca True gdy reguła istniała."""
        allowed = {"enabled", "priority", "app_match", "match_type", "pattern",
                   "entity_tmpl", "category", "project_mode", "project",
                   "project_group", "is_decl", "detail_group", "note"}
        sets, params = [], []
        for k, v in fields.items():
            if k not in allowed:
                continue
            sets.append(f"{k}=?")
            if k in ("enabled", "is_decl"):
                v = int(bool(v))
            params.append(v)
        if not sets:
            return False
        params.append(rule_id)
        with self._cursor() as (conn, cur):
            cur.execute(f"UPDATE rules SET {', '.join(sets)} WHERE id=?", params)
            conn.commit()
            return cur.rowcount > 0

    def delete_rule(self, rule_id: int) -> bool:
        with self._cursor() as (conn, cur):
            cur.execute("DELETE FROM rules WHERE id=?", (rule_id,))
            conn.commit()
            return cur.rowcount > 0

    def import_rules(self, rules: list) -> int:
        """Importuj listę reguł (Rule lub dict). Zwraca liczbę dodanych."""
        from .rules import Rule
        n = 0
        for r in rules:
            if isinstance(r, dict):
                r = Rule(**{k: v for k, v in r.items()
                            if k in {"pattern", "enabled", "priority", "app_match",
                                     "match_type", "entity_tmpl", "category",
                                     "project_mode", "project", "project_group",
                                     "is_decl", "detail_group", "note"}})
            self.add_rule(r)
            n += 1
        return n

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

    # --- top breakdown for dashboard hover ---------------------------------
    def top_titles_for_day_and_app(
        self,
        *,
        day: Optional[datetime],
        app: str,
        limit: int = 8,
    ) -> list[dict]:
        """Zwraca top encji/obiektów dla dnia i aplikacji (do szybkiego podglądu w tooltipie)."""
        ents = self.entities_for_day(day=day, app=app, limit=limit)
        return [
            {
                "key": e["entity"],
                "category": e["category"],
                "project": e["project"],
                "dur_seconds": e["dur_seconds"],
                "n_events": e["n_events"],
                "n_variants": e["n_variants"],
            }
            for e in ents
        ]

    def all_titles_for_day(self, day: Optional[datetime] = None) -> list[dict]:
        """Wszystkie zagregowane tytuły (tab/title) per aplikacja dla danego dnia.

        Jak top_titles_for_day_and_app, ale bez limitu i dla wszystkich aplikacji
        naraz (jedno zapytanie, GROUP BY app + klucz).
        """
        day = day or datetime.now().astimezone()
        start_utc, end_utc = self._day_bounds_utc(day)
        s_iso = start_utc.isoformat(timespec="seconds")
        e_iso = end_utc.isoformat(timespec="seconds")
        with self._cursor() as (_, cur):
            rows = cur.execute(
                """
                SELECT
                  app,
                  COALESCE(NULLIF(tab, ''), title) AS key,
                  SUM(
                    (julianday(MIN(ts_end, ?)) - julianday(MAX(ts_start, ?))) * 86400.0
                  ) AS dur_seconds,
                  COUNT(*) AS n_events
                FROM events
                WHERE ts_end > ? AND ts_start < ?
                  AND idle = 0
                  AND COALESCE(NULLIF(tab, ''), title) IS NOT NULL
                GROUP BY app, key
                ORDER BY app ASC, dur_seconds DESC
                """,
                (e_iso, s_iso, s_iso, e_iso),
            ).fetchall()
        return [
            {
                "app": r["app"],
                "key": r["key"],
                "dur_seconds": round(r["dur_seconds"] or 0, 1),
                "n_events": r["n_events"],
            }
            for r in rows
        ]

    # --- semantyczna agregacja encji i projektów ----------------------------
    def entities_for_day(
        self,
        day: Optional[datetime] = None,
        app: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """Zwraca obiekty biznesowe z agregacją wariantów.

        Używa silnika reguł (reguły użytkownika z DB + presety wbudowane),
        potem generycznego fallbacku z `timerecord.normalizer`.
        Suma czasów encji dla aplikacji == czas całkowity aplikacji.
        """
        from .rules import make_engine
        from .normalizer import normalize_title

        engine = make_engine(self.rules_enabled())

        day = day or datetime.now().astimezone()
        start_utc, end_utc = self._day_bounds_utc(day)
        s_iso = start_utc.isoformat(timespec="seconds")
        e_iso = end_utc.isoformat(timespec="seconds")

        # Stan aktywnego projektu per app sprzed początku dnia (Koncepcja A):
        # skanujemy ostatnie zdarzenia sprzed dnia i przepuszczamy przez
        # reguły deklarujące projekt.
        active_project: dict[str, str] = {}
        with self._cursor() as (_, cur):
            prior_rows = cur.execute(
                """SELECT app, title, tab FROM events
                   WHERE ts_start <= ? AND idle = 0
                   ORDER BY ts_start DESC LIMIT 200""",
                (s_iso,),
            ).fetchall()
            for pr in prior_rows:
                p_app = pr["app"]
                if p_app not in active_project:
                    decl = engine.detect_project(p_app, pr["title"], pr["tab"])
                    if decl:
                        active_project[p_app] = decl

            query = """
                SELECT app, title, tab,
                       (julianday(MIN(ts_end, ?)) - julianday(MAX(ts_start, ?))) * 86400.0 AS dur
                FROM events
                WHERE ts_end > ? AND ts_start < ?
                  AND idle = 0
            """
            params = [e_iso, s_iso, s_iso, e_iso]
            if app:
                query += " AND app = ?"
                params.append(app)
            query += " ORDER BY ts_start ASC"
            rows = cur.execute(query, params).fetchall()

        groups: dict[tuple[str, str], dict] = {}
        for r in rows:
            dur = r["dur"] or 0.0
            r_app = r["app"]
            decl = engine.detect_project(r_app, r["title"], r["tab"])
            if decl:
                active_project[r_app] = decl

            curr_proj = active_project.get(r_app)
            norm = engine.apply(r_app, r["title"], r["tab"], active_project=curr_proj)
            if norm is None:
                norm = normalize_title(r_app, r["title"], r["tab"], active_project=curr_proj)
            gk = (r_app, norm.entity)
            if gk not in groups:
                groups[gk] = {
                    "app": r_app,
                    "entity": norm.entity,
                    "category": norm.category,
                    "project": norm.project,
                    "dur_seconds": 0.0,
                    "n_events": 0,
                    "variants": {},
                }
            g = groups[gk]
            g["dur_seconds"] += dur
            g["n_events"] += 1
            raw_key = (r["tab"] or r["title"] or "").strip() or norm.entity
            v = g["variants"].setdefault(raw_key, {"title": raw_key, "dur_seconds": 0.0, "n_events": 0})
            v["dur_seconds"] += dur
            v["n_events"] += 1

        out = []
        for g in groups.values():
            var_list = sorted(g["variants"].values(), key=lambda x: x["dur_seconds"], reverse=True)
            out.append({
                "app": g["app"],
                "entity": g["entity"],
                "category": g["category"],
                "project": g["project"],
                "dur_seconds": round(g["dur_seconds"], 1),
                "n_events": g["n_events"],
                "n_variants": len(var_list),
                "variants": [
                    {
                        "title": v["title"],
                        "dur_seconds": round(v["dur_seconds"], 1),
                        "n_events": v["n_events"],
                    }
                    for v in var_list
                ],
            })

        out.sort(key=lambda x: x["dur_seconds"], reverse=True)
        return out[:limit]

    def unclassified_for_day(self, day: Optional[datetime] = None,
                             limit: int = 30) -> list[dict]:
        """Top encje z kategorii "Inne"/"Ogólne" — kandydaci do reguł użytkownika.

        Zwraca wiersze z `suggestion`: propozycja app_match + przykładowy tytuł.
        """
        ents = self.entities_for_day(day=day, limit=500)
        out = []
        for e in ents:
            if e["category"] not in ("Inne", "Ogólne"):
                continue
            top_variant = e["variants"][0]["title"] if e.get("variants") else e["entity"]
            out.append({
                "app": e["app"],
                "entity": e["entity"],
                "dur_seconds": e["dur_seconds"],
                "n_events": e["n_events"],
                "n_variants": e["n_variants"],
                "sample_title": top_variant,
            })
            if len(out) >= limit:
                break
        return out

    def projects_for_day(self, day: Optional[datetime] = None) -> list[dict]:
        """Zwraca zagregowany czas per projekt (przenikający różne aplikacje)."""
        all_entities = self.entities_for_day(day=day, limit=500)
        proj_map: dict[str, dict] = {}
        for e in all_entities:
            p = e.get("project")
            if not p:
                continue
            if p not in proj_map:
                proj_map[p] = {
                    "project": p,
                    "dur_seconds": 0.0,
                    "n_events": 0,
                    "apps": set(),
                    "entities": {},
                }
            slot = proj_map[p]
            slot["dur_seconds"] += e["dur_seconds"]
            slot["n_events"] += e["n_events"]
            slot["apps"].add(e["app"])
            slot["entities"][e["entity"]] = slot["entities"].get(e["entity"], 0.0) + e["dur_seconds"]

        out = []
        for p, d in proj_map.items():
            top_ents = sorted(d["entities"].items(), key=lambda x: x[1], reverse=True)[:5]
            out.append({
                "project": p,
                "dur_seconds": round(d["dur_seconds"], 1),
                "n_events": d["n_events"],
                "apps": sorted(list(d["apps"])),
                "top_entities": [{"entity": k, "dur_seconds": round(v, 1)} for k, v in top_ents],
            })
        out.sort(key=lambda x: x["dur_seconds"], reverse=True)
        return out

    def month_summary(self, year: int, month: int) -> list[dict]:
        """Sumy dobowe dla każdego dnia danego miesiąca (do widoku kalendarza)."""
        import calendar as _cal

        n_days = _cal.monthrange(year, month)[1]
        return [
            self.daily_summary(datetime(year, month, dd).astimezone())
            for dd in range(1, n_days + 1)
        ]

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
