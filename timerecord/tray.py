"""Ikona w trayu + główny entry point aplikacji TimeRecord.

Uruchamia:
  - Storage (SQLite)
  - Collector (wątek próbkujący)
  - FastAPI dashboard w wątku (uvicorn.Server)
  - pystray ikonę w wątku głównym (zatrzymuje całość po 'Wyjdź')
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import threading
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

from .collector import Collector
from .config import SETTINGS
from .storage import Storage
from .webapp import create_app

log = logging.getLogger(__name__)


def _make_icon_image():
    """Prosta ikona zegara generowana w PIL (bez plików zewnętrznych)."""
    from PIL import Image, ImageDraw
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # tarcza
    d.ellipse([4, 4, size - 4, size - 4], fill=(79, 156, 249, 255))
    d.ellipse([10, 10, size - 10, size - 10], fill=(15, 17, 21, 255))
    # wskazówki (12 -> 2)
    cx = cy = size // 2
    d.line([cx, cy, cx, 14], fill=(230, 233, 239, 255), width=3)      # do góry
    d.line([cx, cy, size - 18, cy], fill=(110, 231, 183, 255), width=3)  # w prawo
    d.ellipse([cx - 3, cy - 3, cx + 3, cy + 3], fill=(230, 233, 239, 255))
    return img


def _fmt_seconds(s: float) -> str:
    s = int(round(s))
    h, s = divmod(s, 3600)
    m, _ = divmod(s, 60)
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m"


def _today_total_seconds(storage: Storage) -> float:
    s = storage.daily_summary()
    return s.get("total_seconds") or 0.0


def _open_dashboard():
    url = f"http://{SETTINGS.web_host}:{SETTINGS.web_port}/"
    try:
        webbrowser.open(url)
    except Exception as e:
        log.warning("nie otwarto przeglądarki: %s", e)


def _ensure_stdio() -> None:
    """Pod pythonw.exe sys.stdout/stderr są None — uvicorn/pystray tego nie znoszą.
    Podstawiamy no-op streamy (zapis do pliku logu obsługuje logging osobno).
    """
    class _NullStream:
        def write(self, *a, **k): pass
        def flush(self, *a, **k): pass
        def isatty(self): return False
        def fileno(self): raise OSError("no fileno")
        def close(self): pass
    if sys.stdout is None:
        sys.stdout = _NullStream()  # type: ignore[assignment]
    if sys.stderr is None:
        sys.stderr = _NullStream()  # type: ignore[assignment]


def _setup_logging() -> None:
    """Konfiguruj logowanie — do pliku (zawsze) + do stderr (gdy jest konsola)."""
    from .config import DATA_DIR
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log_file = DATA_DIR / "timerecord.log"
    handlers: list[logging.Handler] = [
        logging.handlers.RotatingFileHandler(
            log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        ),
    ]
    # stderr tylko gdy realnie jest konsola (pythonw.exe jej nie ma -> fileno() rzuci)
    try:
        sys.stderr.fileno()
        handlers.append(logging.StreamHandler(sys.stderr))
    except (AttributeError, OSError, ValueError):
        pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def run() -> int:
    _ensure_stdio()
    _setup_logging()
    log.info("TimeRecord start (host=%s, port=%s, pid=%s)",
             SETTINGS.web_host, SETTINGS.web_port, os.getpid())

    try:
        return _run_inner()
    except Exception:
        log.exception("FATAL: nieprzechwycony wyjatek w run()")
        return 1


def _run_inner() -> int:
    storage = Storage()
    collector = Collector(storage)
    collector.start()

    # --- serwer webowy w wątku ------------------------------------------------
    import uvicorn
    app = create_app(storage, collector)
    config = uvicorn.Config(
        app,
        host=SETTINGS.web_host,
        port=SETTINGS.web_port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=server.run, name="TimeRecordWeb", daemon=True)
    server_thread.start()
    log.info("dashboard: http://%s:%s/", SETTINGS.web_host, SETTINGS.web_port)

    # --- ikona w trayu --------------------------------------------------------
    try:
        import pystray
        from PIL import Image
    except ImportError as e:
        log.error("pystray/Pillow niedostępny: %s. Uruchamiam bez traya (tylko web).", e)
        # czekaj aż Ctrl-C
        try:
            server_thread.join()
        except KeyboardInterrupt:
            pass
        collector.stop()
        storage.close()
        return 0

    image = _make_icon_image()

    # --- update checker -------------------------------------------------------
    from . import __version__
    from .updater import check_for_update

    _update_info = None  # cache ostatniego wyniku sprawdzenia

    def on_check_update(icon, item):
        """Ręczne sprawdzenie aktualizacji z menu traya."""
        icon.notify("Sprawdzam aktualizacje...", "TimeRecord")
        info = check_for_update(force=True)
        nonlocal _update_info
        _update_info = info
        if info is None:
            icon.notify(f"Masz najnowszą wersję ({__version__})", "TimeRecord")
        else:
            msg = f"Nowa wersja {info.latest_version} dostępna!\nObecna: {info.current_version}"
            if info.download_url:
                msg += "\n\nKliknij aby pobrać instalator."
            else:
                msg += "\n\nKliknij aby otworzyć stronę release."
            icon.notify(msg, "TimeRecord — aktualizacja")

    def on_update_download(icon, item):
        """Otwórz URL pobierania/release w przeglądarce."""
        if _update_info and _update_info.download_url:
            webbrowser.open(_update_info.download_url)
        elif _update_info and _update_info.html_url:
            webbrowser.open(_update_info.html_url)
        else:
            # Fallback: otwórz releases page
            from .config import SETTINGS
            if SETTINGS.github_repo:
                webbrowser.open(f"https://github.com/{SETTINGS.github_repo}/releases/latest")

    def _auto_check_update():
        """Automatyczne sprawdzenie przy starcie (z cache 24h)."""
        try:
            info = check_for_update(force=False)
            nonlocal _update_info
            _update_info = info
            if info:
                log.info("aktualizacja dostępna: %s -> %s", info.current_version, info.latest_version)
                msg = f"Nowa wersja {info.latest_version} dostępna!"
                icon.notify(msg, "TimeRecord — aktualizacja")
        except Exception as e:
            log.debug("auto update check failed: %s", e)

    def _refresh_tooltip(icon):
        try:
            total = _today_total_seconds(storage)
            state = "pauza" if collector.is_paused else "live"
            icon.title = f"TimeRecord — dziś: {_fmt_seconds(total)}  ({state})"
        except Exception as e:
            log.debug("tooltip err: %s", e)

    def on_open(icon, item):
        _open_dashboard()

    def on_pause(icon, item):
        if collector.is_paused:
            collector.resume()
        else:
            collector.pause()
        _refresh_tooltip(icon)

    def on_quit(icon, item):
        log.info("quit requested")
        icon.stop()
        server.should_exit = True
        collector.stop()
        try:
            storage.touch_last()
        except Exception:
            pass
        storage.close()

    # Dynamiczne menu — aktualizacje pokazują się tylko gdy dostępne
    def _menu_items():
        items = [
            pystray.MenuItem("Otwórz dashboard", on_open, default=True),
            pystray.MenuItem("Pauza / Wznów", on_pause),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Sprawdź aktualizacje", on_check_update),
        ]
        if _update_info:
            label = f"Pobierz v{_update_info.latest_version}"
            items.append(pystray.MenuItem(label, on_update_download))
        items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem(f"Wersja {__version__}", None, enabled=False))
        items.append(pystray.MenuItem("Wyjdź", on_quit))
        return items

    menu = pystray.Menu(lambda: _menu_items())
    icon = pystray.Icon("TimeRecord", image, "TimeRecord", menu)

    # odświeżanie tooltipa co 30 s (pystray nie wystawia sygnału zakończenia -> Timer)
    def _periodic_tooltip():
        _refresh_tooltip(icon)
        if icon.visible:
            threading.Timer(30, _periodic_tooltip).start()

    _refresh_tooltip(icon)
    threading.Timer(30, _periodic_tooltip).start()

    # Automatyczne sprawdzenie aktualizacji 5s po starcie (w tle)
    threading.Timer(5, _auto_check_update).start()

    try:
        icon.run()
    finally:
        server.should_exit = True
        collector.stop()
        try:
            storage.touch_last()
        except Exception:
            pass
        storage.close()
    return 0


if __name__ == "__main__":
    sys.exit(run())
