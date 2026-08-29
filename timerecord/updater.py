"""Sprawdzanie aktualizacji przez GitHub Releases API.

Sprawdza najnowszy release na GitHub, porównuje wersje i zwraca info
o dostępnej aktualizacji (wersja, URL pobrania instalatora, URL strony release).

Nie pobiera ani nie instaluje automatycznie — tylko powiadamia użytkownika
(zgodnie z wybranym trybem "tylko sprawdzanie").
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .config import DATA_DIR, SETTINGS

log = logging.getLogger(__name__)

_CACHE_FILE = DATA_DIR / "update_check.json"


@dataclass
class UpdateInfo:
    """Info o dostępnej aktualizacji."""
    current_version: str
    latest_version: str
    download_url: str | None      # URL instalatora .exe (lub None jeśli nie znaleziono)
    html_url: str                 # URL strony release w przeglądarce
    release_notes: str            # opis release (body)


def _compare_versions(a: str, b: str) -> int:
    """Porównaj wersje semver (np. '0.2.0' vs '0.1.0'). Zwraca >0 jeśli a>b."""
    pa = [int(x) for x in a.split(".") if x.isdigit()]
    pb = [int(x) for x in b.split(".") if x.isdigit()]
    for i in range(max(len(pa), len(pb))):
        va = pa[i] if i < len(pa) else 0
        vb = pb[i] if i < len(pb) else 0
        if va != vb:
            return va - vb
    return 0


def _fetch_latest_release(repo: str) -> dict | None:
    """Pobierz najnowszy release z GitHub API. Zwraca JSON lub None przy błędzie."""
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urllib.request.Request(url, headers={
        "User-Agent": "TimeRecord",
        "Accept": "application/vnd.github+json",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        log.warning("GitHub API błąd: %s", e)
        return None


def _find_installer_asset(release: dict) -> str | None:
    """Znajdź asset instalatora (.exe) w release. Zwraca URL lub None."""
    for asset in release.get("assets", []):
        name = asset.get("name", "").lower()
        if name.endswith(".exe") and ("setup" in name or "install" in name or "timerecord" in name):
            return asset.get("browser_download_url")
    # Fallback: pierwszy .exe
    for asset in release.get("assets", []):
        if asset.get("name", "").lower().endswith(".exe"):
            return asset.get("browser_download_url")
    return None


def _should_auto_check() -> bool:
    """Czy automatyczne sprawdzanie jest włączone i czy czas to zrobić?"""
    if SETTINGS.update_check_interval_hours <= 0:
        return False
    if not SETTINGS.github_repo:
        return False
    try:
        if _CACHE_FILE.exists():
            data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
            last = datetime.fromisoformat(data["last_check"])
            elapsed = (datetime.now(timezone.utc) - last).total_seconds() / 3600
            return elapsed >= SETTINGS.update_check_interval_hours
    except Exception:
        pass
    return True


def _save_check_time() -> None:
    """Zapisz czas ostatniego sprawdzenia do cache."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(
            json.dumps({"last_check": datetime.now(timezone.utc).isoformat()}),
            encoding="utf-8",
        )
    except Exception as e:
        log.debug("nie zapisano cache: %s", e)


def check_for_update(*, force: bool = False) -> UpdateInfo | None:
    """Sprawdź czy jest nowsza wersja na GitHub.

    Args:
        force: pomiń cache i sprawdź natychmiast (np. z menu "Sprawdź aktualizacje")

    Returns:
        UpdateInfo jeśli jest nowsza wersja, None jeśli aktualne lub błąd.
    """
    if not SETTINGS.github_repo:
        log.debug("github_repo nie ustawione — pomijam sprawdzanie aktualizacji")
        return None

    if not force and not _should_auto_check():
        return None

    release = _fetch_latest_release(SETTINGS.github_repo)
    if release is None:
        return None

    _save_check_time()

    latest = (release.get("tag_name") or "").lstrip("vV")
    current = __version__
    if not latest:
        return None

    if _compare_versions(latest, current) <= 0:
        log.info("wersja aktualna: %s (latest=%s)", current, latest)
        return None

    log.info("nowa wersja dostępna: %s -> %s", current, latest)
    return UpdateInfo(
        current_version=current,
        latest_version=latest,
        download_url=_find_installer_asset(release),
        html_url=release.get("html_url", ""),
        release_notes=(release.get("body") or "").strip(),
    )


def download_installer(url: str, progress_cb=None) -> Path:
    """Pobierz instalator do %TEMP%. Zwraca ścieżkę do pobranego pliku.

    Args:
        url: URL instalatora .exe (browser_download_url z GitHub)
        progress_cb: opcjonalny callback (downloaded_bytes, total_bytes)
    """
    tmp_dir = Path(tempfile.gettempdir())
    # Nazwa pliku z URL
    filename = url.rsplit("/", 1)[-1] or "TimeRecord-Setup.exe"
    dst = tmp_dir / filename
    log.info("pobieram instalator: %s -> %s", url, dst)

    req = urllib.request.Request(url, headers={"User-Agent": "TimeRecord"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        with open(dst, "wb") as f:
            downloaded = 0
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if progress_cb:
                    progress_cb(downloaded, total)
    log.info("pobrano: %s (%s bytes)", dst, dst.stat().st_size)
    return dst


def run_installer_silent(installer_path: Path) -> None:
    """Uruchom instalator w trybie cichym (upgrade).

    Inno Setup z /VERYSILENT /SUPPRESSMSGBOXES /NORESTART:
    - nie pokazuje kreatora
    - zabija działający TimeRecord.exe (InitializeSetup w installer.iss)
    - nadpisuje pliki w {app}
    - uruchamia nową wersję (postinstall, skipifsilent nie blokuje przy VERYSILENT)

    Ten proces (stara wersja) zostanie zabity przez instalator.
    """
    log.info("uruchamiam instalator (silent): %s", installer_path)
    # /VERYSILENT — brak UI
    # /SUPPRESSMSGBOXES — brak okienek dialogowych
    # /NORESTART — bez restartu systemu
    # /NOCANCEL — użytkownik nie może anulować
    subprocess.Popen(
        [str(installer_path), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/NOCANCEL"],
        cwd=str(installer_path.parent),
    )
    # Ten proces zaraz zostanie zabity przez taskkill w InitializeSetup instalatora.


def download_and_install(info: UpdateInfo, progress_cb=None) -> None:
    """Pobierz instalator i uruchom cichy upgrade.

    Po uruchomieniu instalatora ten proces (stara wersja) zostanie zabity.
    Nowa wersja wystartuje automatycznie (postinstall w installer.iss).
    """
    if not info.download_url:
        log.warning("brak URL instalatora — nie można auto-aktualizować")
        raise ValueError("Brak URL instalatora w release")
    installer = download_installer(info.download_url, progress_cb)
    run_installer_silent(installer)
