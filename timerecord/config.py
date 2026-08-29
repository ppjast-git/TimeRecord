"""Konfiguracja TimeRecord."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _appdata_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "TimeRecord"


DATA_DIR: Path = _appdata_dir()
DB_PATH: Path = DATA_DIR / "time.db"


@dataclass(frozen=True)
class Settings:
    # Próbkowanie aktywnego okna
    sample_interval: float = 5.0          # sekundy
    # Heartbeat: łącz sąsiadujące zdarzenia o tych samych danych, jeśli przerwa < pulsetime
    pulsetime: float = 15.0               # sekundy (>= 2x sample_interval)
    # Próg idle (brak inputu klawiatury/myszy) - powyżej tego uznajemy AFK
    idle_threshold: float = 180.0         # 3 minuty
    # Dashboard webowy
    web_host: str = "127.0.0.1"
    web_port: int = 7231
    # Nazwa hosta do zapisu w bazie
    hostname: str = os.environ.get("COMPUTERNAME") or "localhost"
    # Repo GitHub do sprawdzania aktualizacji (format: "owner/repo").
    # Ustaw na własne repo po pushu na GitHub. Puste = nie sprawdzaj.
    github_repo: str = ""  # np. "ppjast/TimeRecord"
    # Co ile godzin sprawdzać aktualizacje automatycznie (0 = tylko ręcznie z menu)
    update_check_interval_hours: float = 24.0


SETTINGS = Settings()
