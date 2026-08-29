"""Smoke test: storage heartbeat-merge + browser_parse + webapp endpoints.

Nie wymaga GUI/traya. Uruchamia storage, wstrzykuje sztuczne próbki,
testuje API FastAPI przez TestClient.
"""
from __future__ import annotations

import datetime as dt
import sys
# Windows konsola domyślnie cp1252 — wymuś UTF-8 dla polskich znaków w printach
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
import os
import sys
import tempfile
from pathlib import Path

# Izoluj bazę testową w temp
tmp = Path(tempfile.mkdtemp(prefix="timerecord_test_"))
os.environ["LOCALAPPDATA"] = str(tmp)

# Importy po ustawieniu env, by config wskazał na tmp
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Reload config z nowym LOCALAPPDATA
import importlib
import timerecord.config as config_mod
importlib.reload(config_mod)
from timerecord.config import SETTINGS, DB_PATH
print(f"[setup] DB_PATH = {DB_PATH}")

from timerecord.storage import Storage
from timerecord.browser_parse import parse_browser_title
from timerecord.collector import Collector
from timerecord.webapp import create_app

from fastapi.testclient import TestClient


def test_browser_parse():
    print("\n[test] browser_parse")
    cases = [
        ("chrome.exe",   "GitHub - Let's build from here - Google Chrome", "Google Chrome", "GitHub - Let's build from here"),
        ("msedge.exe",   "ActivityWatch architecture - Microsoft Edge",   "Microsoft Edge", "ActivityWatch architecture"),
        ("firefox.exe",  "Wikipedia — Mozilla Firefox",                    "Mozilla Firefox", "Wikipedia"),
        ("firefox.exe",  "Wikipedia - Mozilla Firefox",                    "Mozilla Firefox", "Wikipedia"),
        ("code.exe",     "main.py - TimeRecord - VS Code",                 None, None),
        ("chrome.exe",   "Google Chrome",                                  "Google Chrome", None),  # pusta zakładka
        (None,           "Anything",                                       None, None),
    ]
    ok = True
    for proc, title, exp_browser, exp_tab in cases:
        r = parse_browser_title(proc, title)
        if exp_browser is None:
            assert r is None, f"expected None for {proc!r}/{title!r}, got {r}"
            print(f"  OK  {proc!r:12} -> None")
            continue
        assert r is not None, f"expected result for {proc!r}/{title!r}"
        assert r.browser == exp_browser, f"browser mismatch: {r.browser} != {exp_browser}"
        assert r.tab == exp_tab, f"tab mismatch: {r.tab!r} != {exp_tab!r}"
        print(f"  OK  {proc!r:12} -> browser={r.browser!r}, tab={r.tab!r}")
    print("  [PASS] browser_parse")
    return ok


def test_storage_heartbeat():
    print("\n[test] storage heartbeat-merge")
    s = Storage()
    base = dt.datetime(2026, 8, 30, 10, 0, 0, tzinfo=dt.timezone.utc)
    # 5 próbek tego samego okna co 5 s -> powinno być 1 zdarzenie z ts_end = base+20s
    for i in range(5):
        s.heartbeat(
            ts=base + dt.timedelta(seconds=5 * i),
            app="chrome.exe", exe=r"C:\chrome.exe",
            title="Tytuł - Google Chrome", tab="Tytuł", browser="Google Chrome",
            idle=False,
        )
    # Przerwa 30 s (> pulsetime 15 s) -> nowe zdarzenie
    s.heartbeat(
        ts=base + dt.timedelta(seconds=20 + 30),
        app="chrome.exe", exe=r"C:\chrome.exe",
        title="Tytuł - Google Chrome", tab="Tytuł", browser="Google Chrome",
        idle=False,
    )
    # Inna aplikacja -> nowe zdarzenie
    s.heartbeat(
        ts=base + dt.timedelta(seconds=20 + 30 + 5),
        app="code.exe", exe=None, title="main.py - VS Code",
        tab=None, browser=None, idle=False,
    )
    # Idle
    s.heartbeat(
        ts=base + dt.timedelta(seconds=20 + 30 + 10),
        app="code.exe", exe=None, title="main.py - VS Code",
        tab=None, browser=None, idle=True,
    )

    # Sprawdź liczbę zdarzeń
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute("SELECT id, ts_start, ts_end, app, idle FROM events ORDER BY id").fetchall()
    conn.close()
    print(f"  zdarzeń: {len(rows)} (oczekiwane 4)")
    for r in rows:
        print(f"    {r}")
    assert len(rows) == 4, f"oczekiwano 4 zdarzeń, jest {len(rows)}"
    # Pierwsze zdarzenie powinno mieć ts_end = base + 20s (5 próbek * 5s)
    assert rows[0][2] == (base + dt.timedelta(seconds=20)).isoformat(timespec="seconds"), \
        f"ts_end pierwszego zdarzenia złe: {rows[0][2]}"
    print("  [PASS] storage heartbeat-merge")
    s.close()
    return True


def test_webapp_api():
    print("\n[test] webapp API")
    s = Storage()
    # wstaw zdarzenie w "dziś"
    now = dt.datetime.now(dt.timezone.utc)
    s.heartbeat(ts=now - dt.timedelta(seconds=120), app="chrome.exe", exe=None,
                title="T - Google Chrome", tab="T", browser="Google Chrome", idle=False)
    s.heartbeat(ts=now - dt.timedelta(seconds=60), app="chrome.exe", exe=None,
                title="T - Google Chrome", tab="T", browser="Google Chrome", idle=False)
    s.heartbeat(ts=now - dt.timedelta(seconds=30), app="code.exe", exe=None,
                title="main.py - VS Code", tab=None, browser=None, idle=False)
    s.heartbeat(ts=now - dt.timedelta(seconds=10), app="code.exe", exe=None,
                title="main.py - VS Code", tab=None, browser=None, idle=True)

    # Collector-mock (nie startujemy wątku)
    class MockCollector:
        is_paused = False
        last_sample = {"app": "code.exe", "title": "main.py - VS Code", "tab": None,
                       "browser": None, "idle": False, "ts": now.isoformat(timespec="seconds")}
        def pause(self): self.is_paused = True
        def resume(self): self.is_paused = False

    app = create_app(s, MockCollector())
    client = TestClient(app)

    r = client.get("/")
    assert r.status_code == 200 and "TimeRecord" in r.text
    print("  OK  GET / -> 200")

    r = client.get("/api/today")
    assert r.status_code == 200
    j = r.json()
    print(f"  OK  GET /api/today -> total={j['total_human']} apps={len(j['apps'])} idle={j['idle_human']}")
    assert j["total_seconds"] > 0
    assert any(a["app"] == "chrome.exe" for a in j["apps"])

    r = client.get("/api/week")
    assert r.status_code == 200 and len(r.json()["days"]) == 7
    print(f"  OK  GET /api/week -> 7 dni")

    r = client.get("/api/events?limit=5")
    assert r.status_code == 200 and len(r.json()["events"]) >= 1
    print(f"  OK  GET /api/events -> {len(r.json()['events'])} zdarzeń")

    r = client.get("/api/now")
    assert r.status_code == 200 and r.json()["sample"]["app"] == "code.exe"
    print("  OK  GET /api/now")

    r = client.post("/api/pause")
    assert r.status_code == 200 and r.json()["paused"] is True
    r = client.get("/api/now")
    assert r.json()["paused"] is True
    print("  OK  POST /api/pause + /api/now")

    r = client.post("/api/resume")
    assert r.json()["paused"] is False
    print("  OK  POST /api/resume")

    print("  [PASS] webapp API")
    s.close()
    return True


if __name__ == "__main__":
    failures = 0
    for t in (test_browser_parse, test_storage_heartbeat, test_webapp_api):
        try:
            if not t():
                failures += 1
        except Exception as e:
            import traceback
            print(f"  [FAIL] {t.__name__}: {e}")
            traceback.print_exc()
            failures += 1
    print(f"\n=== {'ALL PASS' if failures == 0 else f'{failures} FAILURES'} ===")
    sys.exit(1 if failures else 0)
