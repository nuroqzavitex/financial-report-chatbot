"""Glossary-based query expansion (spec §5.8). Applied to sparse text only, never to dense text."""

from __future__ import annotations

import re
from typing import Any


def expand_query(text: str, glossary: dict[str, list[str]]) -> str:
    """Append glossary expansions for every term occurring as a whole word (case-insensitive)."""
    extra: list[str] = []
    for term, expansions in glossary.items():
        if not term.strip():
            continue
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, re.IGNORECASE):
            extra.extend(e for e in expansions if e and e not in extra)
    return " ".join([text, *extra]) if extra else text


def build_glossary(artefact: dict[str, Any]) -> dict[str, list[str]]:
    """Merge ``index/glossary.json`` (``entries`` + ``extra`` aliases) into one term -> expansions map."""
    merged: dict[str, list[str]] = {}
    for e in artefact.get("entries", []):
        term, definition = str(e.get("term", "")).strip(), str(e.get("definition", "")).strip()
        if term and definition:
            merged.setdefault(term, []).append(definition)
    for term, vals in artefact.get("extra", {}).items():
        merged.setdefault(str(term), []).extend(str(v) for v in vals)
    return merged
