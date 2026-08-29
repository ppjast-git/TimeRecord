# TimeRecord

Lekki, **lokalny** tracker czasu pracy na Windows 10. Rejestruje aktywne okno
(nazwę procesu, tytuł okna, tytuł zakładki przeglądarki), wykrywa idle (AFK) i
prezentuje podsumowania w dashboardzie webowym. Dane tylko w lokalnym SQLite.

## Architektura

Jeden proces Pythona, trzy warstwy:

```
┌──────────────────────────────────────────────────────────────────┐
│  proces TimeRecord (pythonw.exe run.py)                          │
│                                                                  │
│  ┌────────────┐   ┌──────────────┐   ┌────────────────────────┐  │
│  │ Collector  │──▶│   Storage    │◀──│  FastAPI dashboard     │  │
│  │ (wątek)    │   │  (SQLite)    │   │  http://127.0.0.1:7231 │  │
│  │ co 5 s     │   │  heartbeat   │   │  + REST API            │  │
│  │ GetForegr. │   │  merge       │   │                        │  │
│  └────────────┘   └──────────────┘   └────────────────────────┘  │
│         ▲                                       ▲                 │
│         └──────────── pystray (tray) ───────────┘                 │
└──────────────────────────────────────────────────────────────────┘
                       ▼
            %LOCALAPPDATA%\TimeRecord\time.db
```

- **Collector** — co `sample_interval` (5 s) pobiera aktywne okno przez
  `win32gui.GetForegroundWindow`, nazwę procesu przez `psutil`, idle przez
  `GetLastInputInfo`. Parsuje tytuł okna przeglądarki → tytuł zakładki.
- **Storage** — SQLite z **heartbeat-merge**: sąsiadujące próbki o tych samych
  danych (app/title/tab/browser/idle) i przerwie ≤ `pulsetime` (15 s) są łączone
  w jedno zdarzenie (rozszerzenie `ts_end`). Insiprowane ActivityWatch.
- **Webapp** — FastAPI serwuje dashboard HTML + REST API na `127.0.0.1:7231`.
- **Tray** — `pystray` ikona z menu: *Otwórz dashboard*, *Pauza/Wznów*, *Wyjdź*.
  Tooltip pokazuje dzisiejszy łączny czas pracy.

## Instalacja

```powershell
cd D:\PJ\TimeRecord
pip install -r requirements.txt
python -m timerecord.tray        # lub: python run.py
```

W trayu pojawi się ikona zegara. Klik prawy → *Otwórz dashboard* (lub dwuklik).

## Autostart z systemem

```powershell
python install_startup.py install     # tworzy skrót w shell:startup
python install_startup.py status      # sprawdza
python install_startup.py uninstall   # usuwa
```

Skrót uruchamia `pythonw.exe run.py` zminimalizowany (bez okna konsoli).

## REST API

| Endpoint                  | Opis                                   |
|---------------------------|----------------------------------------|
| `GET /`                   | Dashboard HTML                         |
| `GET /api/today`          | Suma dzisiaj + per-app                 |
| `GET /api/day/YYYY-MM-DD` | Suma dla wskazanego dnia               |
| `GET /api/week`           | Ostatnie 7 dni                         |
| `GET /api/events?date=`   | Ostatnie zdarzenia dnia                |
| `GET /api/now`            | Aktualna próbka + stan pauzy           |
| `POST /api/pause`         | Pauza collectora                       |
| `POST /api/resume`        | Wznowienie collectora                  |

## Konfiguracja

Edytuj `timerecord/config.py` (`Settings`):

- `sample_interval` — interwał próbkowania (s)
- `pulsetime` — okno łączenia heartbeats (s)
- `idle_threshold` — próg AFK (s)
- `web_host`, `web_port` — adres dashboardu

## Schemat bazy

```sql
events(id, ts_start, ts_end, app, exe, title, tab, browser, host, idle)
```

`ts_start`/`ts_end` w UTC (ISO8601). `idle=1` oznacza okres nieaktywności.

## Inspiracje

- [ActivityWatch](https://github.com/ActivityWatch/activitywatch) — heartbeat-merge, modularność
- [HafidIdrissi/Time-Tracker](https://github.com/HafidIdrissi/Time-Tracker) — parsowanie tytułów przeglądarek
- [vinistoisr/timewarp](https://github.com/vinistoisr/timewarp) — GetForegroundWindow co 1 s + SQLite
- [yuki-katakami/worktracker](https://github.com/yuki-katakami/worktracker) — minimalizm stdlib

## Roadmap (dalszy rozwój)

- rozszerzenie przeglądarki → dokładny URL (jak `aw-watcher-web`)
- kategorie/reguły dla aplikacji (praca/prywatne)
- wykresy godzinowe, heatmapa aktywności
- eksport CSV/JSON
- notyfikacje po N godzin pracy
