"""Orkiestracja build: PyInstaller → Inno Setup → instalator .exe.

Kroki:
  1. (opcjonalnie) Generuj ikonę: python scripts/make_icon.py
  2. PyInstaller: pyinstaller timerecord.spec --noconfirm
  3. Inno Setup: ISCC.exe installer.iss
  4. Wynik: dist/TimeRecord-Setup-vX.Y.Z.exe

Użycie:
  python scripts/build.py              # pełny build
  python scripts/build.py --skip-icon  # pomiń generowanie ikony
  python scripts/build.py --pyinstaller-only  # tylko PyInstaller (bez instalatora)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ISCC_PATHS = [
    str(Path.home() / "AppData" / "Local" / "Programs" / "Inno Setup 6" / "ISCC.exe"),
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
]


def _find_iscc() -> str | None:
    """Znajdź kompilator Inno Setup."""
    for p in ISCC_PATHS:
        if Path(p).exists():
            return p
    # Spróbuj PATH
    import shutil
    return shutil.which("ISCC.exe")


def _run(cmd: list[str], cwd: Path = ROOT) -> int:
    """Uruchom komendę i streamuj output."""
    print(f"\n>>> {' '.join(cmd)}")
    r = subprocess.run(cmd, cwd=str(cwd))
    return r.returncode


def _read_version() -> str:
    """Wczytaj wersję z timerecord/__init__.py."""
    init = (ROOT / "timerecord" / "__init__.py").read_text(encoding="utf-8")
    for line in init.splitlines():
        if "__version__" in line and "=" in line:
            return line.split("=")[1].strip().strip('"').strip("'")
    return "0.0.0"


def main(argv: list[str]) -> int:
    skip_icon = "--skip-icon" in argv
    pyinstaller_only = "--pyinstaller-only" in argv

    version = _read_version()
    print(f"=== TimeRecord build v{version} ===")

    # 1. Ikona
    if not skip_icon:
        print("\n--- Krok 1: generowanie ikony ---")
        rc = _run([sys.executable, str(ROOT / "scripts" / "make_icon.py")])
        if rc != 0:
            print("BŁĄD: generowanie ikony nie powiodło się", file=sys.stderr)
            return rc
    else:
        print("\n--- Krok 1: pominięto generowanie ikony (--skip-icon) ---")

    # 2. PyInstaller
    print("\n--- Krok 2: PyInstaller ---")
    rc = _run([sys.executable, "-m", "PyInstaller", "timerecord.spec", "--noconfirm"])
    if rc != 0:
        print("BŁĄD: PyInstaller nie powiódł się", file=sys.stderr)
        return rc
    print(f"OK: dist/TimeRecord/ (zbudowane)")

    if pyinstaller_only:
        print("\n--pyinstaller-only: pomijam Inno Setup")
        return 0

    # 3. Inno Setup
    print("\n--- Krok 3: Inno Setup ---")
    iscc = _find_iscc()
    if not iscc:
        print("BŁĄD: Inno Setup (ISCC.exe) nie znaleziony.", file=sys.stderr)
        print("Zainstaluj: https://jrsoftware.org/isdl.php", file=sys.stderr)
        print("Lub uruchom z --pyinstaller-only aby pominąć instalator.", file=sys.stderr)
        return 1

    # Zaktualizuj wersję w installer.iss (jeśli różna)
    iss = ROOT / "installer.iss"
    content = iss.read_text(encoding="utf-8")
    import re
    content_new = re.sub(
        r'#define MyAppVersion "[^"]*"',
        f'#define MyAppVersion "{version}"',
        content,
    )
    if content != content_new:
        iss.write_text(content_new, encoding="utf-8")
        print(f"Zaktualizowano wersję w installer.iss -> {version}")

    rc = _run([iscc, str(iss)])
    if rc != 0:
        print("BŁĄD: Inno Setup nie powiódł się", file=sys.stderr)
        return rc

    installer = ROOT / "dist" / f"TimeRecord-Setup-v{version}.exe"
    if installer.exists():
        size_mb = installer.stat().st_size / (1024 * 1024)
        print(f"\n=== GOTOWE ===")
        print(f"Instalator: {installer}")
        print(f"Rozmiar: {size_mb:.1f} MB")
        print(f"\nOpublikuj na GitHub Releases:")
        print(f"  gh release create v{version} \"{installer}\" --title \"v{version}\" --notes \"...\"")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
