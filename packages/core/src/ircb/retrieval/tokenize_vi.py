"""Vietnamese tokenizer shared by indexing and querying."""

import hashlib
import re
import unicodedata

TOKENIZER_VERSION = "vi-1"

_CODE = re.compile(r"\w[\w./-]*[/-][\w./-]*\w|\w+/\w+")
_WORD = re.compile(r"\w+", re.UNICODE)
_EDGE = ".,;:!?()[]{}\"'“”‘’…-–—"


def strip_accents(s: str) -> str:
    s = s.replace("đ", "d").replace("Đ", "D")
    nfd = unicodedata.normalize("NFD", s)
    return unicodedata.normalize("NFC", "".join(c for c in nfd if not unicodedata.combining(c)))


def _is_code(raw: str) -> bool:
    return bool(_CODE.fullmatch(raw))


def tokenize(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text)
    out: list[str] = []
    prev: str | None = None  # previous accented syllable in an unbroken run
    prev_plain: str | None = None
    for raw in text.split():
        raw = raw.strip(_EDGE)
        if not raw:
            prev = prev_plain = None
            continue
        low = raw.lower()
        for syl in [low] if _is_code(raw) else _WORD.findall(low):
            plain = strip_accents(syl)
            out.append(syl)
            if plain != syl:
                out.append(plain)
            if prev is not None and prev_plain is not None:
                out.append(f"{prev}_{syl}")
                if (prev, syl) != (prev_plain, plain):
                    out.append(f"{prev_plain}_{plain}")
            prev, prev_plain = syl, plain
    return out


def term_id(token: str) -> int:
    return int.from_bytes(hashlib.blake2b(token.encode("utf-8"), digest_size=4).digest(), "big")
