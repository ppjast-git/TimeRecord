"""Collector: wątek próbkujący aktywne okno co `sample_interval` sekund.

Wykorzystuje Win32 API:
  - win32gui.GetForegroundWindow / GetWindowText
  - win32process.GetWindowThreadProcessId -> PID -> psutil.Process.name()/exe()
  - win32api.GetLastInputInfo + GetTickCount do detekcji idle (AFK)

Idle: jeżeli czas od ostatniego inputu > idle_threshold, zapisujemy zdarzenie
z idle=1 (aplikacja zostaje zapamiętana, ale czas liczy się jako nieaktywny).
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Optional

import psutil

from .browser_parse import parse_browser_title
from .config import SETTINGS
from .storage import Storage

log = logging.getLogger(__name__)


# --- Win32 importy (łagodny fallback, jeśli pywin32 niepełny) -----------------
try:
    import win32gui
    import win32process
    import win32api
    import win32con
    _WIN32_OK = True
except ImportError as e:  # pragma: no cover
    _WIN32_OK = False
    log.error("pywin32 niedostępny: %s. Collector nie będzie działał.", e)


def _idle_seconds() -> float:
    """Sekundy od ostatniego inputu (klawiatura/myszka)."""
    if not _WIN32_OK:
        return 0.0
    try:
        # GetLastInputInfo zwraca strukturę; w pywin32 wywołujemy bez argumentów
        last = win32api.GetLastInputInfo()
        now = win32api.GetTickCount()
        # GetTickCount zawija się co ~49 dni; obsługa:
        if now < last:
            return 0.0
        return (now - last) / 1000.0
    except Exception as e:
        log.debug("idle_seconds failed: %s", e)
        return 0.0


def _foreground_window_info() -> Optional[dict]:
    """Zwraca {app, exe, title, pid} dla okna na pierwszym planie lub None."""
    if not _WIN32_OK:
        return None
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return None
        title = win32gui.GetWindowText(hwnd)
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        try:
            p = psutil.Process(pid)
            app = p.name()
            try:
                exe = p.exe()
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                exe = None
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            app = "unknown.exe"
            exe = None
        return {"app": app or "unknown.exe", "exe": exe, "title": title or None, "pid": pid}
    except Exception as e:
        log.debug("foreground_window_info failed: %s", e)
        return None


class Collector(threading.Thread):
    """Wątek demon; co `sample_interval` zapisuje heartbeat do Storage."""

    def __init__(self, storage: Storage, *, paused_event: Optional[threading.Event] = None) -> None:
        super().__init__(name="TimeRecordCollector", daemon=True)
        self._storage = storage
        self._stop = threading.Event()
        self._paused = paused_event or threading.Event()  # set = działa, clear = pauza
        self._paused.set()
        self._last_sample: Optional[dict] = None

    def stop(self) -> None:
        self._stop.set()

    def pause(self) -> None:
        self._paused.clear()
        # Odcięcie ostatniego zdarzenia, by pauza nie "przedłużała" aktywności
        try:
            self._storage.touch_last()
        except Exception as e:
            log.debug("touch_last on pause failed: %s", e)

    def resume(self) -> None:
        self._paused.set()

    @property
    def is_paused(self) -> bool:
        return not self._paused.is_set()

    def run(self) -> None:
        log.info("Collector start (interval=%.1fs, idle_threshold=%.0fs)",
                 SETTINGS.sample_interval, SETTINGS.idle_threshold)
        while not self._stop.is_set():
            # Czekamy na interwał, ale responsywnie reagujemy na stop
            if self._stop.wait(SETTINGS.sample_interval):
                break
            if not self._paused.is_set():
                continue
            try:
                self._sample_once()
            except Exception as e:
                log.exception("sample failed: %s", e)

    def _sample_once(self) -> None:
        now = datetime.now(timezone.utc)
        idle_s = _idle_seconds()
        is_idle = idle_s >= SETTINGS.idle_threshold

        info = _foreground_window_info()
        if info is None:
            # Brak okna (np. zablokowana sesja, ekran logowania) -> idle
            app, exe, title = "no-window", None, None
        else:
            app, exe, title = info["app"], info["exe"], info["title"]

        # Parsowanie przeglądarki (tylko gdy nie idle - przy idle zostawiamy jak jest)
        browser = None
        tab = None
        if not is_idle:
            parsed = parse_browser_title(app, title)
            if parsed is not None:
                browser = parsed.browser
                tab = parsed.tab

        self._storage.heartbeat(
            ts=now,
            app=app,
            exe=exe,
            title=title,
            tab=tab,
            browser=browser,
            idle=is_idle,
        )
        self._last_sample = {
            "app": app, "title": title, "tab": tab, "browser": browser,
            "idle": is_idle, "ts": now.isoformat(timespec="seconds"),
        }

    @property
    def last_sample(self) -> Optional[dict]:
        return self._last_sample
