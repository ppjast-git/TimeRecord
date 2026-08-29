"""Instalator autostartu TimeRecord na Windows.

Dwie metody (można użyć obu — Task Scheduler jest niezawodniejszy):

  1. Skrót w shell:startup  — prosty, łatwy do usunięcia, ale Fast Startup
     w Win10 czasem go pomija.
  2. Task Scheduler         — trigger "At logon", uruchamia się zawsze,
     działa nawet przy Fast Startup / hibernacji.

Użycie:
  python install_startup.py install          # tworzy skrót + zadanie (domyślnie)
  python install_startup.py install shortcut # tylko skrót w shell:startup
  python install_startup.py install task     # tylko Task Scheduler
  python install_startup.py uninstall        # usuwa oba
  python install_startup.py status           # sprawdza obecność

Skrót uruchamia `pythonw.exe run.py` z katalogu projektu, z oknem ukrytym.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# shell:startup -> %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
STARTUP_DIR = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
SHORTCUT_NAME = "TimeRecord.lnk"
TASK_NAME = "TimeRecord_Autostart"
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


# --- metoda 1: skrót w shell:startup ----------------------------------------
def install_shortcut() -> int:
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


def uninstall_shortcut() -> int:
    p = _startup_path()
    if p.exists():
        p.unlink()
        print(f"OK: skrót usunięty ({p})")
        return 0
    print("Skrót nie istniał.")
    return 0


# --- metoda 2: Task Scheduler (At logon) — przez schtasks.exe ---------------
def install_task() -> int:
    import subprocess
    # /Create /TN name /TR "command" /SC ONLOGON /RL LIMITED /F
    # /RL LIMITED = bez uprawnień admina; /F = nadpisz jeśli istnieje
    cmd = [
        "schtasks.exe", "/Create",
        "/TN", TASK_NAME,
        "/TR", f'"{_pythonw()}" "{RUN_PY}"',
        "/SC", "ONLOGON",      # trigger przy logowaniu
        "/RL", "LIMITED",      # uprawnienia zwykłego użytkownika
        "/F",                  # nadpisz jeśli istnieje
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"Błąd schtasks: {r.stderr.strip() or r.stdout.strip()}", file=sys.stderr)
        return 1
    print(f"OK: zadanie '{TASK_NAME}' zarejestrowane (trigger: ONLOGON)")
    print(f"     target: {_pythonw()} \"{RUN_PY}\"")
    return 0


def uninstall_task() -> int:
    import subprocess
    r = subprocess.run(
        ["schtasks.exe", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True, text=True,
    )
    if r.returncode == 0:
        print(f"OK: zadanie '{TASK_NAME}' usunięte")
    else:
        print("Zadanie nie istniało.")
    return 0


# --- composite --------------------------------------------------------------
def install() -> int:
    rc1 = install_shortcut()
    rc2 = install_task()
    return rc1 or rc2


def uninstall() -> int:
    uninstall_shortcut()
    uninstall_task()
    return 0


def status() -> int:
    import subprocess
    p = _startup_path()
    found = False
    if p.exists():
        print(f"Skrót: ZAINSTALOWANY ({p})")
        found = True
    else:
        print("Skrót: brak")
    # Sprawdź zadanie przez schtasks /Query
    r = subprocess.run(
        ["schtasks.exe", "/Query", "/TN", TASK_NAME, "/FO", "LIST"],
        capture_output=True, text=True,
    )
    if r.returncode == 0:
        print(f"Zadanie: ZAINSTALOWANE ('{TASK_NAME}')")
        found = True
    else:
        print("Zadanie: brak")
    return 0 if found else 1


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in {"install", "uninstall", "status"}:
        print(__doc__)
        return 2
    cmd = argv[1]
    method = argv[2] if len(argv) > 2 else None
    if cmd == "install":
        if method == "shortcut":
            return install_shortcut()
        elif method == "task":
            return install_task()
        else:
            return install()
    elif cmd == "uninstall":
        return uninstall()
    elif cmd == "status":
        return status()
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
