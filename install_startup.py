"""Tworzy/usuwa skrót do TimeRecord w folderze Autostart (shell:startup).

Użycie:
  python install_startup.py install   # tworzy skrót
  python install_startup.py uninstall # usuwa skrót
  python install_startup.py status    # sprawdza obecność

Skrót uruchamia `pythonw.exe run.py` z katalogu projektu, z oknem ukrytym.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# shell:startup -> %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
STARTUP_DIR = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
SHORTCUT_NAME = "TimeRecord.lnk"
PROJECT_DIR = Path(__file__).resolve().parent
RUN_PY = PROJECT_DIR / "run.py"


def _startup_path() -> Path:
    return STARTUP_DIR / SHORTCUT_NAME


def _pythonw() -> str:
    """Pełna ścieżka do pythonw.exe (bez okna konsoli)."""
    base = Path(sys.executable).parent
    cand = base / "pythonw.exe"
    if cand.exists():
        return str(cand)
    # fallback na python.exe
    return sys.executable


def install() -> int:
    if not STARTUP_DIR.exists():
        print(f"Błąd: folder Autostart nie istnieje: {STARTUP_DIR}", file=sys.stderr)
        return 1
    try:
        import win32com.client  # pywin32
    except ImportError:
        print("Błąd: pywin32 nie zainstalowane. Uruchom: pip install pywin32", file=sys.stderr)
        return 1

    shortcut_path = _startup_path()
    shell = win32com.client.Dispatch("WScript.Shell")
    sc = shell.CreateShortcut(str(shortcut_path))
    sc.TargetPath = _pythonw()
    sc.Arguments = f'"{RUN_PY}"'
    sc.WorkingDirectory = str(PROJECT_DIR)
    sc.WindowStyle = 7  # 7 = zminimalizowane
    sc.Description = "TimeRecord - tracker czasu pracy"
    sc.IconLocation = _pythonw() + ",0"
    sc.Save()
    print(f"OK: skrót utworzony w {shortcut_path}")
    print(f"     target: {_pythonw()} \"{RUN_PY}\"")
    return 0


def uninstall() -> int:
    p = _startup_path()
    if p.exists():
        p.unlink()
        print(f"OK: skrót usunięty ({p})")
    else:
        print("Skrót nie istniał.")
    return 0


def status() -> int:
    p = _startup_path()
    if p.exists():
        print(f"Zainstalowany: {p}")
        return 0
    print("Nie zainstalowany.")
    return 1


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in {"install", "uninstall", "status"}:
        print(__doc__)
        return 2
    return {"install": install, "uninstall": uninstall, "status": status}[argv[1]]()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
