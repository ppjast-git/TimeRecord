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
    # wstaw zdarzenie w "dziś" (przerwy <= pulsetime, by heartbeats się scalały
    # i zdarzenia miały niezerowy czas trwania — jak w produkcji)
    now = dt.datetime.now(dt.timezone.utc)
    s.heartbeat(ts=now - dt.timedelta(seconds=120), app="chrome.exe", exe=None,
                title="T - Google Chrome", tab="T", browser="Google Chrome", idle=False)
    s.heartbeat(ts=now - dt.timedelta(seconds=115), app="chrome.exe", exe=None,
                title="T - Google Chrome", tab="T", browser="Google Chrome", idle=False)
    s.heartbeat(ts=now - dt.timedelta(seconds=30), app="code.exe", exe=None,
                title="main.py - VS Code", tab=None, browser=None, idle=False)
    s.heartbeat(ts=now - dt.timedelta(seconds=25), app="code.exe", exe=None,
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


def test_top_titles_and_export():
    print("\n[test] top-titles + export.xlsx")
    s = Storage()
    # Reguły użytkownika w testowej DB (produkcyjnie: seed z DATA_DIR/rules_seed.json
    # albo ręczne z dashboardu). Testują silnik reguł end-to-end.
    from timerecord.rules import Rule
    s.add_rule(Rule(pattern=r"Item\s*:?\s*([A-Za-z0-9-]+)(?:,\s*(.*))?",
                    app_match="geoapp", entity_tmpl="Element {1}",
                    category="Elementy", detail_group=2, priority=11))
    s.add_rule(Rule(pattern=r"overview", app_match="geoapp", match_type="contains",
                    entity_tmpl="Przegląd (Overview)",
                    category="Narzędzia", priority=16))
    s.add_rule(Rule(pattern=r"(?:Compressing|Extracting)\s*(?:.*[/\\])?([^/\\]+)$",
                    app_match="pack", entity_tmpl="Archiwum: {1}",
                    category="Archiwizacja", priority=10))
    now = dt.datetime.now(dt.timezone.utc)
    # dwa scalone heartbeats (gap 5s <= pulsetime) -> zdarzenie z niezerowym czasem
    for off in (120, 115):
        s.heartbeat(ts=now - dt.timedelta(seconds=off), app="chrome.exe", exe=None,
                    title="T - Google Chrome", tab="T", browser="Google Chrome", idle=False)
    # geoapp.exe: ten sam element, różne warianty (filtry) -> skleją się po regule
    # każdy wariant dostaje 2 scalone heartbeats (5s), by miał niezerowy czas
    for off, t in ((90, "GeoApp - Item T0930783, Statistics"),
                   (80, "GeoApp - Item T0930783, Statistics [Filter ON 5, 12, 35, 60]"),
                   (70, "GeoApp - Overview")):
        s.heartbeat(ts=now - dt.timedelta(seconds=off), app="geoapp.exe", exe=None,
                    title=t, tab=None, browser=None, idle=False)
        s.heartbeat(ts=now - dt.timedelta(seconds=off - 5), app="geoapp.exe", exe=None,
                    title=t, tab=None, browser=None, idle=False)
    # pack.exe: zmienność na POCZĄTKU tytułu (postęp %) -> też musi się skleić
    for off, t in ((60, "12% Compressing D:\\data\\x\\file.zip"),
                   (55, "87% Compressing D:\\data\\x\\file.zip")):
        s.heartbeat(ts=now - dt.timedelta(seconds=off), app="pack.exe", exe=None,
                    title=t, tab=None, browser=None, idle=False)
        s.heartbeat(ts=now - dt.timedelta(seconds=off - 5), app="pack.exe", exe=None,
                    title=t, tab=None, browser=None, idle=False)

    class MockCollector:
        is_paused = False
        last_sample = None
        def pause(self): self.is_paused = True
        def resume(self): self.is_paused = False

    app = create_app(s, MockCollector())
    client = TestClient(app)
    today = dt.datetime.now().astimezone().date().isoformat()

    r = client.get(f"/api/day/{today}/app/chrome.exe/top-titles?limit=5")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["items"], "brak pozycji top-titles"
    assert j["items"][0]["key"] == "T"
    assert j["items"][0]["dur_seconds"] > 0
    print(f"  OK  GET top-titles -> {[ (i['key'], i['dur_seconds']) for i in j['items'] ]}")

    # Semantyczna agregacja obiektów i zadań:
    # - geoapp.exe: oba warianty elementu (bez i z filtrem) sklejają się w "Element T0930783" = 10s (2 warianty)
    # - geoapp.exe: "GeoApp - Overview" staje się czystym "Przegląd (Overview)" = 5s
    # - suma czasów obiektów (10s + 5s = 15s) strictly równa się czasowi aplikacji geoapp.exe
    r = client.get(f"/api/day/{today}/app/geoapp.exe/entities")
    assert r.status_code == 200, r.text
    ents = r.json()["entities"]
    assert len(ents) == 2, f"oczekiwano 2 obiektów, jest: {ents}"
    e_line = next((e for e in ents if e["entity"] == "Element T0930783"), None)
    assert e_line, f"brak encji Element T0930783: {ents}"
    assert e_line["dur_seconds"] == 10.0 and e_line["n_variants"] == 2
    assert len(e_line["variants"]) == 2
    e_map = next((e for e in ents if e["entity"] == "Przegląd (Overview)"), None)
    assert e_map, f"brak encji Przegląd: {ents}"
    assert e_map["dur_seconds"] == 5.0
    assert sum(e["dur_seconds"] for e in ents) == 15.0, "suma obiektów != suma aplikacji"
    print(f"  OK  GET entities (geoapp.exe) -> {[e['entity'] for e in ents]}")

    # pack.exe: zmienność na początku (12% i 87%) skleja się w jedno archiwum "Archiwum: file.zip" = 10s
    r = client.get(f"/api/day/{today}/app/pack.exe/entities")
    assert r.status_code == 200, r.text
    ents_p = r.json()["entities"]
    assert len(ents_p) == 1 and ents_p[0]["entity"] == "Archiwum: file.zip"
    assert ents_p[0]["dur_seconds"] == 10.0 and ents_p[0]["n_variants"] == 2
    print(f"  OK  GET entities (pack.exe) -> {ents_p[0]['entity']} ({ents_p[0]['dur_seconds']}s, {ents_p[0]['n_variants']} war.)")

    # endpoint projektów: /api/day/{today}/projects
    r = client.get(f"/api/day/{today}/projects")
    assert r.status_code == 200, r.text
    print(f"  OK  GET projects -> {r.json()['projects']}")

    r = client.get(f"/api/day/{today}/export.xlsx")
    assert r.status_code == 200, r.text
    ct = r.headers.get("content-type", "")
    assert ct.startswith("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"), ct
    assert "attachment" in r.headers.get("content-disposition", "")
    body = r.content
    assert body[:4] == b"PK\x03\x04", "plik nie wygląda na xlsx (brak sygnatury ZIP)"
    assert len(body) > 1000

    # Weryfikacja arkuszy w XLSX
    from io import BytesIO
    from openpyxl import load_workbook
    wb = load_workbook(BytesIO(body))
    expected_sheets = ["Aplikacje", "Zdarzenia", "Obiekty i zadania", "Projekty (zbiorczo)", "Wszystkie tytuły (szczegóły)"]
    assert wb.sheetnames == expected_sheets, f"złe arkusze: {wb.sheetnames} != {expected_sheets}"
    ws_apps, ws_ev, ws_obj, ws_proj, ws_titles = (wb[s] for s in expected_sheets)
    assert ws_apps.cell(row=2, column=2).value, "brak wierszy aplikacji"
    assert isinstance(ws_apps.cell(row=2, column=2).value, int), "Czas (s) w Aplikacje nie jest int"
    assert ws_ev.max_row >= 2, "brak zdarzeń w arkuszu"
    start = ws_ev.cell(row=2, column=1).value
    assert isinstance(start, str) and len(start) == 19 and "T" not in start, \
        f"Start nie jest w formacie czasu lokalnego: {start!r}"
    assert isinstance(ws_ev.cell(row=2, column=8).value, int), "Czas (s) w Zdarzenia nie jest int"

    # arkusz "Obiekty i zadania": Element T0930783 ma być zagregowana z czasem 10s i 2 wariantami
    rows_obj = [(r[0], r[1], r[2], r[4], r[7]) for r in ws_obj.iter_rows(min_row=2, values_only=True)]
    assert any(r[0] == "geoapp.exe" and r[1] == "Element T0930783" and r[3] == 10 and r[4] == 2 for r in rows_obj), \
        f"brak Element T0930783 (10s, 2 war.) w arkuszu obiektów: {rows_obj}"
    print(f"  OK  export.xlsx: {len(body)} bytes, ct={ct}, start={start!r}, obiekty={len(rows_obj)}")

    # kalendarz: /api/month
    r = client.get(f"/api/month/{dt.datetime.now().year}/{dt.datetime.now().month}")
    assert r.status_code == 200, r.text
    jm = r.json()
    assert len(jm["days"]) >= 28
    assert any(x["total_seconds"] > 0 for x in jm["days"])
    print(f"  OK  GET /api/month -> {len(jm['days'])} dni")

    print("  [PASS] top-titles + export.xlsx")
    s.close()
    return True


if __name__ == "__main__":
    failures = 0
    for t in (test_browser_parse, test_storage_heartbeat, test_webapp_api, test_top_titles_and_export):
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
