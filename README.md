# TimeRecord

[![Version](https://img.shields.io/github/v/release/ppjast-git/TimeRecord)](https://github.com/ppjast-git/TimeRecord/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Lekki, **lokalny** tracker czasu pracy na Windows. Rejestruje aktywne okno
(nazwę procesu, tytuł okna, tytuł zakładki przeglądarki), wykrywa idle (AFK)
i prezentuje podsumowania w dashboardzie webowym. **Dane tylko w lokalnym
SQLite — nic nie jest wysyłane do chmury ani żadnego serwera.**

## Funkcje

- **Automatyczne śledzenie** — próbkowanie aktywnego okna co 5 s (nazwa procesu, tytuł, zakładka przeglądarki)
- **Detekcja AFK** — idle powyżej 3 min oznaczane osobno, nie wlicza się do czasu pracy
- **Reguły klasyfikacji** — normalizacja tytułów w sensowne **obiekty i zadania** z kategoriami i projektami; własne reguły + wbudowane presety
- **Asystent reguł** — analizuje tytuły aplikacji i proponuje gotowe grupowania („57 tytułów zawiera «X» — zgrupuj po wartości"), bez pisania regexów
- **Dashboard webowy** — podsumowanie dzienne, per-aplikacja, drilldown obiektów, projekty, kalendarz, ostatnie zdarzenia
- **Eksport XLSX** — raport wybranego dnia jednym kliknięciem (aplikacje, zdarzenia, obiekty, projekty)
- **REST API** — wszystkie dane dostępne przez HTTP na localhost (dla integracji/eksportu)
- **Ikona w trayu** — tooltip z dzisiejszym czasem pracy, pauza/wznowienie, dashboard
- **Autostart z systemem** — uruchamia się automatycznie po logowaniu
- **Auto-aktualizacja** — sprawdza GitHub Releases, cichy upgrade z menu traya
- **Prywatność** — dane wyłącznie lokalne (SQLite), brak telemetrii, brak konta

## Reguły klasyfikacji

Surowe tytuły okien są normalizowane **przy odczycie** (nie przy zapisie) —
zmiana reguły przelicza także dane historyczne.

- **Encja** — semantyczny obiekt wyciągnięty z tytułu (np. `Dokument T12345`
  zamiast `GeoApp - Item T0930783, Statistics [Filter ON ...]`)
- **Kategoria** — grupa encji (np. „Dokumenty", „Poczta", „Programowanie")
- **Projekt** — reguły-deklaracje wykrywają aktywny projekt aplikacji
  (np. nazwa pliku/projektu z tytułu), inne encje dziedziczą go

Wszystko zarządzane z dashboardu → **⚙ Ustawienia**:

- **Asystent** — wybierasz aplikację, system analizuje jej tytuły z ostatnich
  dni i proponuje gotowe reguły w języku naturalnym; klikasz „Użyj" i gotowe
- **Edytor** — pełna kontrola (regex/contains, szablon encji `{1}`…`{9}`,
  kategoria, projekt), z podglądem na żywo i testem pokrycia na danych dnia
- **Zarządzanie zbiorcze** — eksport/import reguł jako JSON, wyczyść
  z automatyczną archiwizacją
- **Presety wbudowane** — 24 generyczne reguły (przeglądarki, edytory,
  Office, dialogi plików, multimedia, komunikatory)

## Wymagania

- Windows 10/11 (x64)
- ~25 MB wolnego miejsca na dysku
- **Python nie wymagany** — instalator zawiera wszystko

## Pobranie i instalacja

1. Pobierz instalator z [**Latest Release**](https://github.com/ppjast-git/TimeRecord/releases/latest)
2. Uruchom `TimeRecord-Setup-vX.Y.Z.exe` — instaluje się do `%LOCALAPPDATA%\Programs\TimeRecord` (bez uprawnień administratora)
3. Po instalacji: ikona zegara w trayu, dashboard na `http://127.0.0.1:7231/`
4. Autostart z systemem jest włączony domyślnie (można odznaczyć w kreatorze)

## Prywatność

TimeRecord jest zaprojektowany z naciskiem na prywatność:

- **Dane wyłącznie lokalne** — wszystkie zdarzenia w `%LOCALAPPDATA%\TimeRecord\time.db` (SQLite). Nigdy nie opuszczają Twojego komputera.
- **Brak telemetrii** — aplikacja nie wysyła żadnych danych do żadnego serwera.
- **Brak konta** — nie wymaga logowania, rejestracji, ani połączenia z internetem.
- **Jedyna komunikacja sieciowa** — sprawdzanie aktualizacji przez GitHub API (publiczne API, anonimowe, można wyłączyć w `config.py`).
- **Dashboard tylko na localhost** — `127.0.0.1:7231`, niedostępny z innych komputerów.
- **Open source** — pełny kod dostępny w tym repo, możesz zweryfikować samodzielnie.

## REST API

Dashboard dostępny na `http://127.0.0.1:7231/`. Endpointy:

| Endpoint                  | Opis                                   |
|---------------------------|----------------------------------------|
| `GET /`                   | Dashboard HTML                         |
| `GET /api/today`          | Suma dzisiaj + per-app                 |
| `GET /api/day/YYYY-MM-DD` | Suma dla wskazanego dnia               |
| `GET /api/day/…/app/X/entities` | Obiekty/zadania aplikacji (po regułach) |
| `GET /api/day/…/app/X/top-titles` | Top tytuły aplikacji              |
| `GET /api/day/…/projects` | Wykryte projekty dnia                     |
| `GET /api/day/…/export.xlsx` | Eksport dnia do XLSX                   |
| `GET /api/week`           | Ostatnie 7 dni                         |
| `GET /api/month/YYYY/M`   | Kalendarz miesiąca                       |
| `GET /api/events?date=`   | Ostatnie zdarzenia dnia                |
| `GET /api/suggestions`    | Nieklasyfikowane encje (kandydaci)     |
| `GET/POST/PUT/DELETE /api/rules` | CRUD reguł użytkownika         |
| `POST /api/rules/test`    | Podgląd draftu reguły vs tytuł         |
| `POST /api/rules/test-coverage` | Pokrycie reguły na danych dnia   |
| `POST /api/rules/suggest` | Asystent — propozycje reguł dla appki  |
| `GET /api/rules/export` `POST /api/rules/import` `POST /api/rules/clear` | Backup/import/reset reguł |
| `GET /api/now`            | Aktualna próbka + stan pauzy           |
| `POST /api/pause`         | Pauza collectora                       |
| `POST /api/resume`        | Wznowienie collectora                  |

## Architektura

Jeden proces Pythona, trzy warstwy:

```
┌──────────────────────────────────────────────────────────────────┐
│  proces TimeRecord                                               │
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

- **Collector** — co 5 s pobiera aktywne okno przez `win32gui.GetForegroundWindow`, nazwę procesu przez `psutil`, idle przez `GetLastInputInfo`. Parsuje tytuł okna przeglądarki → tytuł zakładki.
- **Storage** — SQLite z **heartbeat-merge**: sąsiadujące próbki o tych samych danych i przerwie ≤ 15 s są łączone w jedno zdarzenie. Inspiracja: [ActivityWatch](https://github.com/ActivityWatch/activitywatch).
- **RuleEngine** (`rules.py`) — przy odczycie normalizuje surowe tytuły w encje/kategorie/projekty: reguły użytkownika z DB → presety wbudowane → generyczny fallback.
- **Webapp** — FastAPI serwuje dashboard HTML + REST API na `127.0.0.1:7231`.
- **Tray** — `pystray` ikona z menu: *Otwórz dashboard*, *Pauza/Wznów*, *Sprawdź aktualizacje*, *Wyjdź*.

## Aktualizacje

Aplikacja sprawdza GitHub Releases API przy starcie (co 24 h) oraz ręcznie z menu traya → **„Sprawdź aktualizacje"**. Jeśli jest nowsza wersja:

- **„Aktualizuj automatycznie → vX.Y.Z"** — pobiera instalator w tle i uruchamia cichy upgrade (instalator zabija stary proces, instaluje nową wersję, uruchamia ją automatycznie; baza danych jest zachowywana)
- **„Pobierz ręcznie (przeglądarka)"** — otwiera URL instalatora w przeglądarce

## Konfiguracja

Edytuj `timerecord/config.py` (`Settings`):

| Parametr | Domyślnie | Opis |
|---|---|---|
| `sample_interval` | 5.0 s | interwał próbkowania |
| `pulsetime` | 15.0 s | okno łączenia heartbeats |
| `idle_threshold` | 180.0 s | próg AFK (3 min) |
| `web_host` | `127.0.0.1` | adres dashboardu |
| `web_port` | `7231` | port dashboardu |
| `github_repo` | `ppjast-git/TimeRecord` | repo do sprawdzania aktualizacji |
| `update_check_interval_hours` | 24.0 | co ile godzin auto-sprawdzać |

## Schemat bazy

```sql
events(id, ts_start, ts_end, app, exe, title, tab, browser, host, idle)
rules(id, enabled, priority, app_match, match_type, pattern,
      entity_tmpl, category, project_mode, project, project_group,
      is_decl, detail_group, note)
```

`ts_start`/`ts_end` w UTC (ISO8601). `idle=1` oznacza okres nieaktywności.
Reguły wbudowane nie są w DB — mieszkają w kodzie (`timerecord/rules.py`).

## Development

### Uruchomienie ze źródeł

```powershell
git clone https://github.com/ppjast-git/TimeRecord.git
cd TimeRecord
pip install -r requirements.txt
python run.py
```

### Build instalatora

Wymagania: [PyInstaller](https://pypi.org/project/pyinstaller/) + [Inno Setup 6](https://jrsoftware.org/isdl.php)

```powershell
pip install pyinstaller
python scripts/build.py          # pełny build: ikona → PyInstaller → Inno Setup
```

Wynik: `dist/TimeRecord-Setup-vX.Y.Z.exe` (~22 MB) — samodzielny instalator Windows.

### Publikacja nowej wersji

```powershell
# 1. Zaktualizuj wersję w timerecord/__init__.py
# 2. Build
python scripts/build.py
# 3. Commit + tag + push
git tag -a vX.Y.Z -m "vX.Y.Z — opis"
git push origin master
git push origin vX.Y.Z
# 4. Utwórz release na GitHub z dist/TimeRecord-Setup-vX.Y.Z.exe jako asset
```

## Inspiracje

- [ActivityWatch](https://github.com/ActivityWatch/activitywatch) — heartbeat-merge, modularność
- [HafidIdrissi/Time-Tracker](https://github.com/HafidIdrissi/Time-Tracker) — parsowanie tytułów przeglądarek
- [vinistoisr/timewarp](https://github.com/vinistoisr/timewarp) — GetForegroundWindow + SQLite
- [yuki-katakami/worktracker](https://github.com/yuki-katakami/worktracker) — minimalizm stdlib

## Roadmap

- [x] reguły klasyfikacji: kategorie, encje, projekty (v0.3.0)
- [x] asystent reguł — auto-propozycje grupowania tytułów (v0.3.0)
- [x] eksport XLSX (v0.3.0)
- [ ] rozszerzenie przeglądarki → dokładny URL (jak `aw-watcher-web`)
- [ ] wykresy godzinowe, heatmapa aktywności
- [ ] eksport CSV/JSON
- [ ] notyfikacje po N godzin pracy

## Licencja

MIT — zobacz [LICENSE](LICENSE).
