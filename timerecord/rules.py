"""Silnik reguł normalizacji tytułów okien.

Reguła = dane (wiersz w tabeli `rules` albo wbudowany preset), nie kod.
Każda reguła dopasowuje tytuł okna do wzorca (regex/substring) i produkuje
ustrukturyzowaną encję: nazwę obiektu, kategorię, opcjonalnie projekt.

Priorytety:
  - reguły użytkownika z DB: priority < 1000 (domyślnie 100)
  - presety wbudowane (BUILTIN_RULES): priority >= 1000
  - fallback (normalizer.py): gdy żadna reguła nie pasuje

Szablon encji: "{0}" = cały dopasowany tekst (dla 'contains' = cały tytuł),
"{1}".."{9}" = grupy przechwytujące regexa.

Projekt (project_mode):
  - "inherit" — dziedzicz aktywny projekt aplikacji (Koncepcja A)
  - "none"    — wymuś brak projektu
  - "fixed"   — stała nazwa (pole project)
  - "group"   — wartość grupy regex numer project_group

Reguła z is_decl=1 nie produkuje encji — deklaruje aktywny projekt
aplikacji (używana przez detect_project_declaration).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .normalizer import NormalizedEntity


@dataclass
class Rule:
    """Pojedyncza reguła normalizacji (z DB lub wbudowana)."""
    pattern: str
    id: Optional[int] = None
    enabled: bool = True
    priority: int = 100
    app_match: str = ""              # substring (lower) w nazwie app; "" = wszystkie
    match_type: str = "regex"        # 'regex' | 'contains'
    entity_tmpl: str = "{0}"         # {0}=dopasowanie/tytuł, {n}=grupa regex
    category: str = "Inne"
    project_mode: str = "inherit"    # 'inherit'|'none'|'fixed'|'group'
    project: Optional[str] = None    # nazwa dla project_mode='fixed'
    project_group: Optional[int] = None  # nr grupy dla 'group'/'decl'
    is_decl: bool = False            # 1 = deklaracja projektu (nie encja)
    detail_group: Optional[int] = None   # nr grupy -> detail; None = raw title
    note: Optional[str] = None       # notatka użytkownika
    builtin: bool = False            # True dla presetów (nie z DB)

    def app_matches(self, app_low: str) -> bool:
        """app_match: substring, lista oddzielona '|', albo '' = wszystkie."""
        if not self.app_match:
            return True
        return any(p.strip() in app_low
                   for p in self.app_match.lower().split("|") if p.strip())

    def match(self, raw: str) -> Optional[re.Match]:
        """Zwraca re.Match dla regex, syntetyczny match dla contains, lub None."""
        if self.match_type == "contains":
            if self.pattern.lower() in raw.lower():
                # syntetyczny "match": group(0) = cały tytuł
                return re.search(r"^(.*)$", raw, re.S)
            return None
        try:
            return re.search(self.pattern, raw, re.I)
        except re.error:
            return None

    def _render(self, tmpl: str, m: re.Match, raw: str) -> str:
        """Podstaw {0},{1}..{9} w szablonie."""
        def _grp(n: int) -> str:
            if n == 0:
                return m.group(0) if self.match_type == "regex" else raw
            try:
                return m.group(n) or ""
            except IndexError:
                return ""
        out = tmpl
        for n in range(9, -1, -1):  # {9}..{1}, potem {0}
            out = out.replace("{" + str(n) + "}", _grp(n).strip())
        return out.strip()


class RuleEngine:
    """Aplikuje listę reguł (user + builtin) do tytułów okien."""

    def __init__(self, rules: list[Rule]):
        self.rules = sorted((r for r in rules if r.enabled),
                            key=lambda r: r.priority)

    def detect_project(self, app: str, title: Optional[str], tab: Optional[str]) -> Optional[str]:
        """Zwraca nazwę projektu jeśli jakaś reguła deklarująca pasuje."""
        raw = (tab or title or "").strip()
        if not raw:
            return None
        app_low = (app or "").lower()
        for r in self.rules:
            if not r.is_decl or not r.app_matches(app_low):
                continue
            m = r.match(raw)
            if m is None:
                continue
            if r.project_mode == "fixed" and r.project:
                return r.project
            grp = r.project_group if r.project_group is not None else 1
            try:
                val = m.group(grp)
                if val:
                    return val.strip()
            except IndexError:
                continue
        return None

    def apply(self, app: str, title: Optional[str], tab: Optional[str],
              active_project: Optional[str] = None) -> Optional[NormalizedEntity]:
        """Pierwsza pasująca reguła produkuje encję; None gdy brak trafienia."""
        raw = (tab or title or "").strip()
        app_low = (app or "").lower()
        for r in self.rules:
            if r.is_decl or not r.app_matches(app_low):
                continue
            m = r.match(raw)
            if m is None:
                continue
            entity = r._render(r.entity_tmpl, m, raw) or raw or app or "Aplikacja"
            project = self._project_of(r, m, raw, active_project)
            detail = None
            if r.detail_group is not None:
                try:
                    detail = (m.group(r.detail_group) or "").strip() or None
                except IndexError:
                    detail = None
            if detail is None:
                detail = raw
            return NormalizedEntity(entity=entity, category=r.category,
                                    project=project, detail=detail)
        return None

    def _project_of(self, r: Rule, m: re.Match, raw: str,
                    active_project: Optional[str]) -> Optional[str]:
        if r.project_mode == "none":
            return None
        if r.project_mode == "fixed":
            return r.project
        if r.project_mode == "group" and r.project_group is not None:
            try:
                v = m.group(r.project_group)
                return v.strip() if v else active_project
            except IndexError:
                return active_project
        return active_project


# =============================================================================
# Presety generyczne — uniwersalne wzorce, bez danych specyficznych użytkownika.
# Priorytet >= 1000 (użytkownik może nadpisać regułą z niższym priority).
# =============================================================================

BUILTIN_RULES: list[Rule] = [
    # --- deklaracje projektu (Koncepcja A) ---
    Rule(pattern=r"^(.+?)\s*[-–—]\s*(.+?)\s*[-–—]\s*Visual Studio Code\s*$",
         app_match="code",
         is_decl=True, project_mode="group", project_group=2, priority=1000, builtin=True),
    Rule(pattern=r"^([A-Za-z0-9_.-]+)\s*[-–—]\s*Devin(?:\s*[-–—]\s*.*)?$", app_match="devin",
         is_decl=True, project_mode="group", project_group=1, priority=1000, builtin=True),

    # --- przeglądarki ---
    Rule(pattern=r"^(.+?)\s*[-–—]\s*[^@\s]+@[^@\s]+\s*[-–—]\s*Gmail\s*$",
         app_match="chrome|edge|firefox|brave|browser",
         entity_tmpl="Poczta: {1}", category="Poczta", project_mode="none",
         priority=1010, builtin=True),
    Rule(pattern=r"^(?:Odebrane|Wysłane|Wszystkie|Spam|Kosze?|Kosz)(?:\s*\(\d+\))?\s*[-–—].*Gmail",
         app_match="chrome|edge|firefox|brave|browser",
         entity_tmpl="Poczta: {0}", category="Poczta", project_mode="none",
         priority=1011, builtin=True),
    Rule(pattern=r"^(.+?)\s*[-–—]\s*(?:Szukaj w Google|Google Search)\s*$",
         app_match="chrome|edge|firefox|brave|browser",
         entity_tmpl="Szukaj: {1}", category="Wyszukiwanie w Google", project_mode="none",
         priority=1012, builtin=True),
    Rule(pattern=r"^(.*?)\s*[-–—]\s*(?:Google Chrome|Microsoft Edge|Mozilla Firefox|Brave|Opera)\s*$",
         app_match="chrome|edge|firefox|brave|opera|browser",
         entity_tmpl="{1}", category="Przeglądarka internetowa", project_mode="none",
         detail_group=None, priority=1090, builtin=True),

    # --- edytory kodu ---
    Rule(pattern=r"^(.+?)\s*[-–—]\s*(.+?)\s*[-–—]\s*Visual Studio Code\s*$",
         app_match="code",
         entity_tmpl="{2}: {1}", category="Programowanie",
         project_mode="group", project_group=2, priority=1020, builtin=True),
    Rule(pattern=r"^([A-Za-z0-9_.-]+)\s*[-–—]\s*Devin\s*[-–—]\s*(.*)$",
         app_match="devin",
         entity_tmpl="{1}: {2}", category="Programowanie",
         project_mode="group", project_group=1, priority=1020, builtin=True),
    Rule(pattern=r"^(.+?)\s*[-–—]\s*Cursor\s*$", app_match="cursor",
         entity_tmpl="{1}", category="Programowanie", priority=1020, builtin=True),

    # --- dokumenty / arkusze ---
    Rule(pattern=r"^(.*?)\s*[-–—]\s*LibreOffice\s+(?:Calc|Impress|Writer|Draw|Base).*$",
         app_match="soffice",
         entity_tmpl="{1}", category="Dokumenty i arkusze", priority=1030, builtin=True),
    Rule(pattern=r"^(.*?)\s*[-–—]\s*(?:Microsoft\s+)?(?:Word|Excel|PowerPoint)\s*$",
         app_match="winword|excel|powerpnt",
         entity_tmpl="{1}", category="Dokumenty i arkusze", priority=1030, builtin=True),
    Rule(pattern=r"^(.*?)\s*[-–—]\s*(?:Notepad\+\+|Notatnik|Notepad)\s*$",
         app_match="notepad",
         entity_tmpl="{1}", category="Edytor tekstu", priority=1030, builtin=True),
    Rule(pattern=r"^(.*?)\s*[-–—]\s*Adobe Acrobat.*$", app_match="acrobat|acrord32",
         entity_tmpl="{1}", category="PDF", priority=1030, builtin=True),

    # --- okna dialogowe plików (Open/Save) ---
    Rule(pattern=r"^(?:Otwieranie|Zapisywanie(?:\s+jako)?|Open|Save(?:\s+As)?)\s*[:—-]?\s*(.+)$",
         app_match="",
         entity_tmpl="Plik: {1}", category="Operacje na plikach", priority=1040, builtin=True),

    # --- komunikatory ---
    Rule(pattern=r"^(.+?)\s*[-–—|]\s*(?:Microsoft\s+)?Teams\s*$", app_match="teams|msedgewebview2",
         entity_tmpl="Teams: {1}", category="Komunikator", project_mode="none",
         priority=1040, builtin=True),
    Rule(pattern=r"^(.*?)\s*[-–—]\s*Outlook\s*$", app_match="outlook",
         entity_tmpl="{1}", category="Poczta", project_mode="none", priority=1040, builtin=True),
    Rule(pattern=r"^(.*)$", app_match="slack",
         entity_tmpl="Slack: {0}", category="Komunikator", project_mode="none",
         priority=1040, builtin=True),

    # --- multimedia / podgląd plików ---
    Rule(pattern=r"(\d{4})-\d{2}-\d{2}.*\.(?:mp4|3gp|mov|avi|mkv)$",
         app_match="photo|dllhost|vlc|mpv|wmplayer",
         entity_tmpl="Wideo z archiwum ({1})", category="Multimedia / Archiwum",
         project_mode="none", priority=1050, builtin=True),
    Rule(pattern=r"(\d{4})-\d{2}-\d{2}.*\.(?:jpg|jpeg|png|heic|raw|cr2)$",
         app_match="photo|dllhost",
         entity_tmpl="Zdjęcia z archiwum ({1})", category="Multimedia / Archiwum",
         project_mode="none", priority=1051, builtin=True),
    Rule(pattern=r"IMG_\d+", app_match="photo|dllhost",
         entity_tmpl="Zdjęcia z aparatu (IMG)", category="Multimedia / Archiwum",
         project_mode="none", priority=1052, builtin=True),

    # --- eksplorator / archiwa ---
    Rule(pattern=r"^(Program Manager|This PC|Ten komputer)$", app_match="explorer",
         entity_tmpl="Pulpit / Mój komputer", category="System", project_mode="none",
         priority=1060, builtin=True),
    Rule(pattern=r"^(.*)$", app_match="explorer",
         entity_tmpl="Folder: {0}", category="Eksplorator plików",
         detail_group=None, priority=1061, builtin=True),
    Rule(pattern=r"(?:Compressing|Extracting|Kompresowanie|Wypakowywanie)\s*(?:.*[/\\])?([^/\\]+)$",
         app_match="7z|rar|zip|pack|winrar",
         entity_tmpl="Archiwum: {1}", category="Archiwizacja", priority=1070, builtin=True),

    # --- GIS ---
    Rule(pattern=r"^\*?([^\s—-]+)\s*[-–—]\s*QGIS", app_match="qgis",
         entity_tmpl="Projekt GIS: {1}", category="GIS i Mapy", priority=1080, builtin=True),
]


def make_engine(user_rules: list[Rule]) -> RuleEngine:
    """Engine z regułami użytkownika (DB) + presety wbudowane."""
    return RuleEngine(list(user_rules) + list(BUILTIN_RULES))


# =============================================================================
# Asystent reguł — analiza powtarzalnych fragmentów w tytułach aplikacji.
# Nie wymaga od użytkownika znajomości regexów: proponuje gotowe kandydatury
# w postaci «kotwica + zmienna część» albo «stały fragment = jedna pozycja».
# =============================================================================

_ANCHOR_MAX_TOKENS = 6
_VAR_CLASS = r"[^,\[\]\(\)\|:;—–]"      # znaki dozwolone w zmiennej części
_VAR_RE = _VAR_CLASS + r"+?"
_SEP = r"[-–—:]"                         # separatory między kotwicą a zmienną


def suggest_for_app(titles: list[str], *, max_out: int = 10) -> list[dict]:
    """Analizuje tytuły okien i proponuje kandydatów na reguły.

    Zwraca listę słowników:
      kind          'extract' (grupuj po zmiennej) | 'constant' (jedna pozycja)
      anchor        powtarzalny fragment tytułu
      support       liczba tytułów zawierających kotwicę
      match_type    'regex' | 'contains'
      pattern       gotowy wzorzec reguły
      entity_tmpl   '{1}' dla extract / stały tekst dla constant
      name_hint     propozycja nazwy grupy (ostatnie słowo kotwicy)
      sample_values przykładowe wydobyte wartości (dla extract)
      sample_titles przykładowe tytuły
    """
    uniq = sorted({t.strip() for t in titles if t and t.strip()})
    if not uniq:
        return []
    token_lists = [re.findall(r"\S+", t) for t in uniq]

    # --- support n-gramów: ile różnych tytułów zawiera daną frazę ---
    support: dict[str, int] = {}
    for tl in token_lists:
        seen: set[str] = set()
        for n in range(1, min(_ANCHOR_MAX_TOKENS, len(tl)) + 1):
            for i in range(len(tl) - n + 1):
                seen.add(" ".join(tl[i:i + n]))
        for a in seen:
            support[a] = support.get(a, 0) + 1

    _STOPWORDS = {"and", "or", "the", "of", "for", "in", "on", "a", "an", "to",
                  "with", "is", "at", "by", "i", "w", "z", "na", "do", "po",
                  "o", "u", "lub", "oraz", "nie", "się", "dla"}

    def _anchor_ok(a: str) -> bool:
        if len(a) < 3 or not re.search(r"[A-Za-zÀ-ž]", a):
            return False
        if a.lower().strip(" -–—:.,()[]") in _STOPWORDS:
            return False
        return support[a] >= 2 or len(uniq) <= 3

    def _clean_anchor(a: str) -> str:
        """Utnij wiodące/końcowe tokeny-czystą-interpunkcję ('MyApp -' -> 'MyApp')."""
        toks = a.split()
        while toks and not re.search(r"[A-Za-zÀ-ž0-9]", toks[-1]):
            toks.pop()
        while toks and not re.search(r"[A-Za-zÀ-ž0-9]", toks[0]):
            toks.pop(0)
        return " ".join(toks)

    # --- pruning: kotwica wchłonięta przez dłuższą o tym samym support ---
    def _titles_with(anchor: str) -> list[str]:
        al = anchor.lower()
        return [t for t in uniq if f" {al} " in f" {t.lower()} "]

    kept: list[tuple[str, list[str]]] = []
    for a0 in sorted((a for a in support if _anchor_ok(a)),
                     key=lambda x: (-support[x], -len(x))):
        a = _clean_anchor(a0)
        if not a or len(a) < 3:
            continue
        group = _titles_with(a)
        if not group:
            continue
        if any(a == b or (a in b and len(group) == len(g)) for b, g in kept):
            continue
        kept.append((a, group))

    def _extract_after(anchor: str, group: list[str]) -> list[str]:
        rx = re.compile(re.escape(anchor) + r"\s*" + _SEP + r"?\s*"
                        + r"(" + _VAR_CLASS + r"+?)\s*(?=[,:\[\(\|;—–]|$)", re.I)
        out = []
        for t in group:
            m = rx.search(t)
            out.append(m.group(1).strip() if m else "")
        return out

    def _extract_before(anchor: str, group: list[str]) -> list[str]:
        rx = re.compile(r"(" + _VAR_CLASS + r"+?)\s*" + _SEP + r"?\s*"
                        + re.escape(anchor), re.I)
        out = []
        for t in group:
            m = rx.search(t)
            out.append(m.group(1).strip() if m else "")
        return out

    def _name_hint(anchor: str) -> str:
        words = re.findall(r"[A-Za-zÀ-ž0-9]+", anchor)
        return words[-1].capitalize() if words else anchor.strip()

    candidates: list[dict] = []
    for a, group in kept[:40]:
        base = {"anchor": a, "support": len(group),
                "sample_titles": group[:5]}
        # 1) zmienna PO kotwicy:  «Line : T0920783, …»  →  grupuj po T0920783
        vals = _extract_after(a, group)
        filled = [v for v in vals if v]
        if len(filled) >= max(2, len(group) * 0.6) and len(set(filled)) >= 2:
            candidates.append({**base, "kind": "extract", "match_type": "regex",
                "pattern": re.escape(a) + r"\s*" + _SEP + r"?\s*(" + _VAR_CLASS
                           + r"+?)\s*(?=[,:\[\(\|;—–]|$)",
                "entity_tmpl": "{1}", "name_hint": _name_hint(a),
                "sample_values": sorted(set(filled))[:6],
                "_values": set(filled)})
            continue
        # 2) zmienna PRZED kotwicą:  «DOC-42 - Szczegóły»  →  grupuj po DOC-42
        vals = _extract_before(a, group)
        filled = [v for v in vals if v]
        if len(filled) >= max(2, len(group) * 0.6) and len(set(filled)) >= 2:
            candidates.append({**base, "kind": "extract", "match_type": "regex",
                "pattern": r"(" + _VAR_CLASS + r"+?)\s*" + _SEP + r"?\s*" + re.escape(a),
                "entity_tmpl": "{1}", "name_hint": _name_hint(a),
                "sample_values": sorted(set(filled))[:6],
                "_values": set(filled)})
            continue
        # 3) stały fragment — wszystkie tytuły to jedna pozycja
        candidates.append({**base, "kind": "constant", "match_type": "contains",
                           "pattern": a, "entity_tmpl": a.strip(" -–—:"),
                           "name_hint": a.strip(" -–—:"), "sample_values": [],
                           "_values": set()})

    # deduplikacja: extract z identycznym zbiorem wartości co inny (dłuższa kotwica wygrywa)
    deduped: list[dict] = []
    for c in candidates:
        if c["kind"] == "extract" and any(
                o["kind"] == "extract" and c["_values"] == o["_values"]
                and c["anchor"] != o["anchor"] and c["anchor"] in o["anchor"]
                for o in candidates):
            continue
        deduped.append(c)

    def _score(c: dict) -> float:
        if c["kind"] == "extract":
            vals = list(c["_values"])
            digit_ratio = sum(1 for v in vals if re.search(r"\d", v)) / max(1, len(vals))
            return c["support"] * (0.6 + digit_ratio)
        return c["support"] * 0.5

    deduped.sort(key=_score, reverse=True)
    for c in deduped:
        c.pop("_values", None)
    return deduped[:max_out]
