"""Parsowanie tytułów okien przeglądarek -> (browser, tab_title).

Mockup: wyciągamy tytuł zakładki z tytułu okna przeglądarki.
URL nie jest dostępny z samego tytułu okna (to wymagałoby rozszerzenia).

Konwencje tytułów:
  Chrome/Edge/Brave/Opera/Vivaldi:  "<tab> - <BrowserName>"
  Firefox:                          "<tab> — Mozilla Firefox"  (em-dash) lub "<tab> - Mozilla Firefox"
  IE/Starsze:                       "<tab> - Windows Internet Explorer"
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


# (browser_name, sufiks tytułu okna - regex kotwiczony na końcu)
_BROWSER_SUFFIXES: list[tuple[str, re.Pattern]] = [
    ("Google Chrome",            re.compile(r"\s-\sGoogle Chrome(?:$|\s)")),
    ("Microsoft Edge",           re.compile(r"\s-\sMicrosoft\s?\u200b?Edge(?:$|\s)")),
    ("Brave",                    re.compile(r"\s-\sBrave(?:$|\s)")),
    ("Opera",                    re.compile(r"\s-\sOpera(?:$|\s)")),
    ("Vivaldi",                  re.compile(r"\s-\sVivaldi(?:$|\s)")),
    ("Mozilla Firefox",          re.compile(r"\s[-\u2014]\sMozilla Firefox(?:$|\s)")),
    ("Internet Explorer",        re.compile(r"\s-\s(?:Windows Internet Explorer|Internet Explorer)(?:$|\s)")),
    ("Tor Browser",              re.compile(r"\s-\sTor Browser(?:$|\s)")),
    ("Chromium",                 re.compile(r"\s-\sChromium(?:$|\s)")),
    ("Arc",                      re.compile(r"\s-\sArc(?:$|\s)")),
    ("Orbitum",                  re.compile(r"\s-\sOrbitum(?:$|\s)")),
    ("CocCoc",                   re.compile(r"\s-\sC\u00f4c C\u00f4c(?:$|\s)")),
    ("Yandex",                   re.compile(r"\s-\sYandex(?:$|\s)")),
    ("Maxthon",                  re.compile(r"\s-\sMaxthon(?:$|\s)")),
    ("Sogou Explorer",           re.compile(r"\s-\sSogou(?:$|\s)")),
    ("QQ Browser",               re.compile(r"\s-\sQQBrowser(?:$|\s)")),
]

# Nazwy procesów przeglądarek (do szybkiego odrzucenia nie-przeglądarek)
_BROWSER_PROCESSES = {
    "chrome.exe", "msedge.exe", "brave.exe", "opera.exe", "vivaldi.exe",
    "firefox.exe", "iexplore.exe", "tor-browser.exe", "chromium.exe",
    "arc.exe", "orbitum.exe", "coccoc.exe", "browser.exe", "maxthon.exe",
    "qqbrowser.exe", "yandex.exe", "sogouexplorer.exe",
}


@dataclass(frozen=True)
class ParsedBrowser:
    browser: str
    tab: str


def parse_browser_title(process_name: Optional[str], window_title: Optional[str]) -> Optional[ParsedBrowser]:
    """Zwraca ParsedBrowser jeśli okno wygląda na przeglądarkę, inaczej None."""
    if not window_title:
        return None
    proc = (process_name or "").lower()
    # Szybki filtr: tylko jeśli proces to znana przeglądarka.
    if proc and proc not in _BROWSER_PROCESSES:
        return None
    title = window_title.strip()
    # Puste okna przeglądarek (np. "Google Chrome" bez zakładki)
    for browser, pat in _BROWSER_SUFFIXES:
        m = pat.search(title)
        if m:
            tab = title[: m.start()].strip()
            # Jeśli tab jest puste, to okno bez załadowanej zakładki
            return ParsedBrowser(browser=browser, tab=tab or None)
    # Jeżeli proces to przeglądarka ale nie dopasowaliśmy sufiksu,
    # traktujemy całość jako tytuł zakładki (np. about:blank, ustawienia).
    # Wyjątek: tytuł == sama nazwa przeglądarki -> pusta zakładka (tab=None).
    if proc in _BROWSER_PROCESSES:
        browser_name = _process_to_browser_name(proc)
        if title == browser_name or title.lower() == browser_name.lower():
            return ParsedBrowser(browser=browser_name, tab=None)
        return ParsedBrowser(browser=browser_name, tab=title or None)
    return None


def _process_to_browser_name(proc: str) -> str:
    mapping = {
        "chrome.exe": "Google Chrome",
        "msedge.exe": "Microsoft Edge",
        "brave.exe": "Brave",
        "opera.exe": "Opera",
        "vivaldi.exe": "Vivaldi",
        "firefox.exe": "Mozilla Firefox",
        "iexplore.exe": "Internet Explorer",
        "tor-browser.exe": "Tor Browser",
        "chromium.exe": "Chromium",
        "arc.exe": "Arc",
        "orbitum.exe": "Orbitum",
        "coccoc.exe": "CocCoc",
        "browser.exe": "Browser",
        "maxthon.exe": "Maxthon",
        "qqbrowser.exe": "QQ Browser",
        "yandex.exe": "Yandex",
        "sogouexplorer.exe": "Sogou Explorer",
    }
    return mapping.get(proc, "Browser")
