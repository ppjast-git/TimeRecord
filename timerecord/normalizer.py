"""Minimalna normalizacja tytułów okien — ostateczny fallback.

Właściwa normalizacja dzieje się w `timerecord/rules.py` (silnik reguł:
reguły użytkownika z DB + presety generyczne). Ten moduł zawiera wyłącznie:

- `NormalizedEntity` — struktura wyniku
- `normalize_title()` — generyczny fallback gdy żadna reguła nie pasuje:
  zdejmuje sufiks nazwy aplikacji, procenty postępu, zbędne białe znaki.

UWAGA: w tym pliku NIE ma reguł specyficznych dla użytkownika
(aplikacje branżowe, nazwy projektów). Takie reguły są danymi —
tabela `rules` w lokalnej bazie, edytowalne z dashboardu.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class NormalizedEntity:
    entity: str             # Czysta nazwa obiektu/zadania
    category: str           # Kategoria (np. "Przeglądarka internetowa")
    project: Optional[str]  # Wykryty/aktywny projekt (albo None)
    detail: Optional[str]   # Wariant/szczegół (surowy tytuł lub fragment)


# Sufiksy nazw aplikacji do odcięcia z końca tytułu (generyczne, nie branżowe)
_APP_SUFFIXES = (
    "Google Chrome", "Microsoft Edge", "Mozilla Firefox", "Brave", "Opera",
    "Notepad++", "Notatnik", "Notepad",
    "Visual Studio Code", "Visual Studio",
)


def normalize_title(
    app: Optional[str],
    title: Optional[str],
    tab: Optional[str] = None,
    active_project: Optional[str] = None,
) -> NormalizedEntity:
    """Generyczny fallback — minimalne czyszczenie tytułu.

    Wywoływana TYLKO gdy żadna reguła (użytkownika ani wbudowana) nie pasuje.
    """
    raw = (tab or title or "").strip()
    if not raw:
        return NormalizedEntity(
            entity=f"({app or 'Aplikacja'})",
            category="Ogólne",
            project=active_project,
            detail=None,
        )

    clean = raw
    # odetnij znany sufiks aplikacji, np. "dokument.txt — Notepad++"
    for suf in _APP_SUFFIXES:
        clean = re.sub(rf"\s*[-–—]\s*{re.escape(suf)}\s*$", "", clean, flags=re.I).strip()
    # odetnij wiodący procent postępu, np. "87% Compressing..."
    clean = re.sub(r"^\d+\s*%\s*", "", clean).strip()

    return NormalizedEntity(
        entity=clean or raw or app or "Aplikacja",
        category="Inne",
        project=active_project,
        detail=None,
    )
