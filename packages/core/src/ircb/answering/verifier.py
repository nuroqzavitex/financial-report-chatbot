"""Per-claim deterministic verifier (spec §5.12) — the last gate before the analyst.

Rules run in spec order; ``failed_rule`` is the first one that fails:

1. ``source_missing``: every source (``fact:<id>`` / ``chunk:<id>``, plus the operand facts
   of the claim's calcs) exists in the context.
2. ``evidence_not_substring``: a claim citing a chunk quotes evidence that is a substring of
   one of its chunks (whitespace-normalised).
3. ``number_mismatch``: every hand-written number (outside placeholders) matches a reference
   number by value and unit, within half of the claim's last displayed digit. Precision
   (final-review ruling I2): in the source's own unit the claim may not be rounded more coarsely
   than the source (claim decimals >= source decimals: "ROA 2%" never matches 1,5%); across a
   scale conversion ("1.192 nghìn tỷ đồng" vs 1.192.344.137 triệu đồng) a rounded claim needs at
   least 3 significant digits (an exact conversion such as "1,5 tỷ đồng" for 1.500 triệu passes).
4. ``direction_near_placeholder`` / ``direction_mismatch`` / ``direction_unknown``.
5. ``calc_failed``: no placeholder may survive ``fill_placeholders``.
6. ``printed_pages`` = union of the sources' and operand facts' printed pages.

Units of a number come from the words right after it: ``%`` / ``phần trăm``, ``điểm %``,
``lần``, ``đồng`` / ``đ`` / ``VND``, and a scale word with or without ``đồng`` (``tỷ``/``tỉ`` →
``tỷ đồng``, ``triệu``/``tr`` → ``triệu đồng``, ``nghìn tỷ`` → ``nghìn tỷ đồng``, ``nghìn`` →
``nghìn đồng``; ``trăm``/``chục`` multiply the scale). After a scale word the next word must be
``đồng``/``đ``/``VND``/``VNĐ``, punctuation / end of line, or a connective (và, so, với, …);
anything else (``nghìn tỷ nhân dân tệ``, ``triệu khách hàng``) fails closed. A foreign currency
right before the number (``USD 1.192``) never matches either.

Reference numbers for rule 3:
- numbers with a unit: numbers in the *verified* evidence (only when rule 2 checked it against
  a chunk; bare evidence numbers take that chunk's unit) and the source facts' values. Text of a
  chunk outside the quoted evidence is never a reference, so a neighbouring KPI tile cannot
  vouch for a wrong number.
- unitless numbers (fail closed): only *unitless* numbers in the verified evidence, unitless fact
  values and non-date numbers in the source facts' descriptive fields. Full chunk text vouches
  only for 4-digit years 1900–2100 and identifier tokens containing letters (``COVID-19``),
  matched as a whole word.
Narrow exemptions: parts of a ``d/m/yyyy`` date that also occurs in the sources, and
parenthesised 1–2 digit footnote markers such as ``(1)``. A source fact's period vouches for
its year and closing date (``FY2025`` → 2025, 31/12/2025). A parenthesised cash outflow whose
label names a payment (trả, chi, nộp, mua: "Cổ tức trả cho cổ đông (7.084.911)") also vouches
for its magnitude. A cited chunk's own SQL facts (``Context.chunk_facts``) count as sources.

Direction (rule 4): direction words are tăng, giảm, đi lên, đi xuống, suy giảm, tăng trưởng
("tăng cường" is not one; "mạnh"/"nhẹ" only matter next to one). Each direction word in the
claim is checked against its subject S: the content words of its clause (text since the last
``, ; : .`` / newline; a clause with only numbers and units takes the previous clause across
``,``/``:``), stopwords, numbers and comparative period phrases ("so với năm trước") removed,
NFC-lowercased without accent folding. "không"/"chưa"/"chẳng"/"không hề"
right before it fails closed. Signals for that word:
- a cited fact's up/down direction when label words ⊆ S ⊆ words of the fact's label,
  parent_label, table_title, chapter and statement;
- a non-negated evidence direction word whose own clause subject equals S, with |S| >= 2;
- a bound fact's direction is its KPI arrow, else the explicit sign of a ``%`` / ``điểm %``
  change ("+18,16%" up, "-0,5%" down) in its raw text;
- a word that governs no number (none within 3 words after it) and sits in a 5-word window
  (2 words before, 2 after) quoted verbatim from a cited chunk ("bứt phá tăng trưởng và").
Calc results never supply signals. A direction word needs a signal; contradictory signals fail
closed; a bound fact with ``direction="unknown"`` gives ``direction_unknown``.

All comparisons are ``Decimal``; nothing is compared through ``str(Decimal)``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from decimal import Decimal

from ircb.answering.calc import fill_placeholders, operand_facts, period_key
from ircb.domain.models import CalcResult, Chunk, ClaimOut, Fact, VerifiedClaim
from ircb.domain.numbers_vn import find_numbers, normalize_chars
from ircb.domain.units import UNIT_SCALE, normalize_unit, to_vnd
from ircb.retrieval.hybrid import Context

DIRECTION_WORDS = ("tăng", "giảm", "mạnh", "nhẹ", "đi xuống", "đi lên")
# Direction detection (controller ruling): tăng, giảm, đi lên, đi xuống, suy giảm, tăng trưởng.
# "tăng cường" (strengthen) and "tăng trưởng kép" (CAGR, a metric name) are not directions;
# "mạnh"/"nhẹ" only matter next to a direction word, so they never trigger on their own.
_UP_RE = re.compile(
    r"(?<!\w)(?:tăng(?!\w)(?!\s+cường(?!\w))(?!\s+trưởng\s+kép(?!\w))|đi\s+lên(?!\w))", re.IGNORECASE
)
_DOWN_RE = re.compile(r"(?<!\w)(?:giảm|đi\s+xuống)(?!\w)", re.IGNORECASE)
_DIR_RE = re.compile(f"{_UP_RE.pattern}|{_DOWN_RE.pattern}", re.IGNORECASE)
NEAR_WINDOW = 3  # words before a placeholder
_NEGATIONS = frozenset({"không", "chưa", "chẳng", "hề"})  # "hề" covers "không hề"
# Subject binding (round-4 ruling). Clause breaks: soft , : / hard . ; newline.
_SOFT_BREAKS, _HARD_BREAKS = ",:", ".;\n"
# Function words dropped from a clause's subject. Deliberately NOT stopwords: "cho" (cho vay),
# "có" (tài sản có rủi ro), "trước"/"sau" (lợi nhuận trước/sau thuế), "ngân"/"hàng"
# (khách hàng, Khối Ngân hàng Bán lẻ), "con" (công ty con), "không" (negation), "tỷ" (tỷ lệ).
_STOPWORDS = frozenset(
    {
        *("của", "và", "so", "với", "năm", "là", "đạt", "được", "này", "đó", "các", "những"),
        *("trong", "tại", "từ", "đến", "đã", "đang", "vẫn", "cũng", "đều", "ở", "vào", "kỳ", "cùng"),
        *("suy", "mạnh", "nhẹ"),  # "suy giảm"; degree words
    }
)
# period phrases are dropped only after "so với" / "cùng" (round-5 ruling)
_PERIOD = r"(?:năm\s+trước|kỳ\s+trước|năm\s+ngoái)"
_COMPARATIVE_PERIOD_RE = re.compile(
    rf"(?<!\w)(?:so\s+với\s+(?:cùng\s+kỳ(?:\s+{_PERIOD})?|{_PERIOD})|cùng\s+(?:kỳ(?:\s+{_PERIOD})?|{_PERIOD}))(?!\w)"
)
_LETTERS_RE = re.compile(r"[^\W\d_]+")
# a number together with its unit words ("1.192 nghìn tỷ đồng", "21,8%", "0,2 điểm %")
_NUM_UNIT_RE = re.compile(
    r"\d[\d.,]*(?:\s*%|\s+(?:phần\s+trăm|điểm\s*%|điểm\s+phần\s+trăm|lần"
    r"|(?:(?:trăm|chục)\s+)?(?:(?:nghìn|ngàn)\s+(?:tỷ|tỉ)|tỷ|tỉ|triệu|tr|nghìn|ngàn)"
    r"(?:\s+(?:đồng|đ|vnd|vnđ)(?!\w))?(?!\w)|(?:đồng|đ|vnd|vnđ)(?!\w)))?",
    re.IGNORECASE,
)

_PLACEHOLDER_RE = re.compile(r"\{[^{}]*\}")
_CALC_REF_RE = re.compile(r"\{(c\d+)\}")
_DATE_RE = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{4})(?!\d)")
_FOOTNOTE_RE = re.compile(r"^\(\d{1,2}\)$")
_DECIMALS_RE = re.compile(r",(\d+)")
_WS_RE = re.compile(r"\s+")
_HALF = Decimal("0.5")
MIN_SIGNIFICANT = 3  # significant digits a claim needs when its unit differs from the source's
GOVERN_WINDOW = 3  # words after a direction word within which it governs a number
QUOTE_BEFORE, QUOTE_AFTER = 2, 2  # words around a direction word quoted verbatim from a chunk
_PAYMENT_WORDS = frozenset({"trả", "chi", "nộp", "mua"})  # labels of outflows shown as (x)
_FOREIGN = "foreign"  # unit marker for non-VND currencies: never matches
_SCALES = {"tỷ": "tỷ", "tỉ": "tỷ", "triệu": "triệu", "tr": "triệu", "nghìn": "nghìn", "ngàn": "nghìn"}
_SCALE_VALUE = {"nghìn tỷ": 10**12, "tỷ": 10**9, "triệu": 10**6, "nghìn": 10**3}
_MULTIPLIERS = {"trăm": 100, "chục": 10}
_MONEY_SCALE: dict[str, int] = {
    **UNIT_SCALE,
    "nghìn đồng": 10**3,
    **{f"{m} {s} đồng": k * v for m, k in _MULTIPLIERS.items() for s, v in _SCALE_VALUE.items()},
}
_CURRENCIES = frozenset(
    {
        *("usd", "us$", "$", "đô", "đô-la", "đôla", "dollar", "eur", "euro", "€", "jpy", "yên", "yen", "¥"),
        *("gbp", "£", "cny", "rmb", "ndt", "tệ", "sgd", "krw", "won", "thb", "baht", "aud", "chf"),
        *("hkd", "rúp", "rub", "inr", "rupee", "twd", "myr", "idr", "kip", "riel"),
    }
)
_FOREIGN_PHRASES = (("nhân", "dân", "tệ"), ("bảng", "anh"), ("mỹ", "kim"))
# after a scale word the next word must be a VND word, punctuation / end, or one of these
_CONNECTIVES = frozenset(
    {"và", "so", "với", "tăng", "giảm", "trong", "của", "là", "năm", "tại", "cho", "từ", "đến"}
)
_VND_WORDS = frozenset({"đồng", "đ", "vnd", "vnđ"})
_STRIP = " ,.;:()"


@dataclass(frozen=True)
class _Num:
    value: Decimal
    unit: str | None  # normalised unit or None
    vnd: Decimal | None
    decimals: int = 0
    raw: str = ""
    span: tuple[int, int] = (0, 0)


def _norm(s: str) -> str:
    return _WS_RE.sub(" ", normalize_chars(s)).strip()


def _line_after(text: str, end: int) -> list[str]:
    return text[end:].split("\n", 1)[0].split()


def _unit_after(text: str, end: int) -> str | None:
    """Unit from the words immediately following a number (same line); never the whole sentence."""
    raw = _line_after(text, end)[:6]
    words = [w.lower().strip(_STRIP) for w in raw]
    if not words:
        return None
    w0, w1, w2 = (words + ["", "", ""])[:3]
    if w0 == "%" or (w0, w1) == ("phần", "trăm"):
        return "%"
    if w0 == "điểm" and (w1 == "%" or (w1, w2) == ("phần", "trăm")):
        return "điểm %"
    if w0 == "lần":
        return "lần"
    if w0 in _VND_WORDS:
        return "đồng"
    if _is_currency(words):
        return _FOREIGN
    mult, k = "", 0
    if w0 in _MULTIPLIERS:  # "trăm tỷ", "chục triệu"
        mult, k = f"{w0} ", 1
    a, b = (words[k:] + ["", ""])[:2]
    if _SCALES.get(a) == "nghìn" and _SCALES.get(b) == "tỷ":
        scale, k = "nghìn tỷ", k + 2
    elif a in _SCALES:
        scale, k = _SCALES[a], k + 1
    else:
        return None
    # fail closed: after the scale only a VND word, punctuation / end, or a connective
    if raw[k - 1].lower().strip(_STRIP) != raw[k - 1].lower():  # "tỷ," / "tỷ."
        return f"{mult}{scale} đồng"
    nxt = words[k] if k < len(words) else ""
    if nxt == "" or nxt in _VND_WORDS or nxt in _CONNECTIVES:
        return f"{mult}{scale} đồng"
    return _FOREIGN


def _is_currency(words: list[str]) -> bool:
    return bool(words) and (
        words[0] in _CURRENCIES or any(tuple(words[: len(p)]) == p for p in _FOREIGN_PHRASES)
    )


def _currency_before(text: str, start: int) -> bool:
    """A foreign currency written right before the number ("USD 1.192", "$1.192")."""
    before = text[:start].split()
    if not before:
        return False
    prev = before[-1].lower().strip(_STRIP)
    return prev in _CURRENCIES or prev.endswith(("$", "€", "£", "¥"))


def _followed_by_word(text: str, end: int) -> bool:
    nxt = _line_after(text, end)[:1]
    return bool(nxt) and nxt[0][:1].isalpha()


def _money_vnd(value: Decimal, unit: str | None) -> Decimal | None:
    return value * _MONEY_SCALE[unit] if unit in _MONEY_SCALE else None


def _numbers(text: str, default_unit: str | None = None) -> list[_Num]:
    text = normalize_chars(text)
    out: list[_Num] = []
    for p in find_numbers(text, skip_years=False):
        if _currency_before(text, p.span[0]):
            unit: str | None = _FOREIGN
        else:
            unit = "%" if p.is_percent else _unit_after(text, p.span[1])
            if unit is None and default_unit and not _followed_by_word(text, p.span[1]):
                unit = default_unit  # bare table value takes the chunk unit; "302 chi nhánh" does not
        m = _DECIMALS_RE.search(p.raw)
        vnd = _money_vnd(p.value, unit)
        out.append(_Num(p.value, unit, vnd, len(m.group(1)) if m else 0, p.raw, p.span))
    return out


def _value_decimals(value: Decimal) -> int:
    exp = value.normalize().as_tuple().exponent
    return max(0, -exp) if isinstance(exp, int) else 0


def _fact_ref(f: Fact) -> _Num:
    unit = normalize_unit(f.unit)
    vnd = f.value_vnd if f.value_vnd is not None else (to_vnd(f.value, unit) if unit else None)
    m = _DECIMALS_RE.search(f.raw) if f.raw else None
    decimals = len(m.group(1)) if m else (0 if f.raw else _value_decimals(f.value))
    return _Num(f.value, unit, vnd, decimals)


def _significant(raw: str) -> int:
    return len("".join(c for c in raw if c.isdigit()).lstrip("0"))


def _fact_text(f: Fact) -> str:
    fields = (f.label, f.parent_label, f.period, f.col_path, f.table_title, f.raw, f.change_basis)
    return "\n".join(x for x in fields if x)


def _matches(n: _Num, refs: list[_Num]) -> bool:
    """Value within half of the claim's last displayed digit, at no coarser precision than the source.

    Same unit as the reference: claim decimals >= reference decimals. Different (money) unit, i.e.
    a scale conversion: an exact value, or at least ``MIN_SIGNIFICANT`` significant digits.
    """
    tol = _HALF * Decimal(10) ** -n.decimals  # half of the last displayed digit, claim's unit
    if n.unit == _FOREIGN:
        return False
    for r in refs:
        if r.unit == n.unit:
            if n.decimals >= r.decimals and abs(r.value - n.value) <= tol:
                return True
        elif n.unit in _MONEY_SCALE and r.vnd is not None:
            scale = Decimal(_MONEY_SCALE[n.unit])
            diff = abs(r.vnd - n.value * scale)
            if diff == 0:  # lossless conversion ("1,5 tỷ đồng" for 1.500 triệu đồng) is not rounding
                return True
            if _significant(n.raw) >= MIN_SIGNIFICANT and diff <= tol * scale:
                return True
    return False


def _word_at(text: str, pos: int) -> str:
    start = text.rfind(" ", 0, pos) + 1
    end = text.find(" ", pos)
    return text[start : end if end >= 0 else len(text)].strip(_STRIP)


def _words(text: str) -> set[str]:
    return {w.strip(_STRIP) for w in normalize_chars(text).split()}


def _is_year(n: _Num) -> bool:
    return n.raw.isdigit() and len(n.raw) == 4 and 1900 <= n.value <= 2100


def _dates(text: str) -> set[tuple[int, int, int]]:
    return {(int(d), int(m), int(y)) for d, m, y in _DATE_RE.findall(normalize_chars(text))}


def _blank_placeholders(text: str) -> str:
    return _PLACEHOLDER_RE.sub(lambda m: " " * len(m.group(0)), text)


@dataclass
class _Sources:
    ids: list[str]
    facts: list[Fact]
    chunks: list[Chunk]
    missing: bool


def _resolve(claim: ClaimOut, ctx: Context, calcs: dict[str, CalcResult]) -> _Sources:
    ids = list(claim.sources)
    for cid in dict.fromkeys(_CALC_REF_RE.findall(claim.text)):
        ids += [f"fact:{fid}" for fid in operand_facts(cid, calcs)]
    ids = list(dict.fromkeys(ids))
    facts = {f.fact_id: f for f in ctx.facts}
    chunks = {c.chunk_id: c for c in ctx.chunks}
    own = {f.fact_id: f for f in ctx.chunk_facts}
    out = _Sources(ids, [], [], missing=not ids)
    for sid in ids:
        kind, _, raw = sid.partition(":")
        if kind == "fact" and raw in facts:
            out.facts.append(facts[raw])
        elif kind == "chunk" and raw in chunks:
            out.chunks.append(chunks[raw])
        else:
            out.missing = True
    # a cited chunk vouches with its own SQL facts too (KPI period and arrow direction)
    seen = {f.fact_id for f in out.facts}
    for c in out.chunks:
        for fid in c.fact_ids:
            if fid in own and fid not in seen:
                out.facts.append(own[fid])
                seen.add(fid)
    return out


def _check_numbers(text: str, src: _Sources, evidence_chunk: Chunk | None, evidence: str) -> bool:
    fact_texts = [_fact_text(f) for f in src.facts]
    evidence_nums = _numbers(evidence, normalize_unit(evidence_chunk.unit or "")) if evidence_chunk else []
    trusted_texts = fact_texts + ([evidence] if evidence_chunk else [])
    all_texts = trusted_texts + [c.text for c in src.chunks]

    fact_refs = [_fact_ref(f) for f in src.facts]
    outflows = [_magnitude(r) for f, r in zip(src.facts, fact_refs, strict=True) if _is_outflow(f, r)]
    refs = fact_refs + outflows + evidence_nums  # numbers with a unit
    # unitless claim numbers: only unitless references (fail closed on unknown unit words);
    # parts of a date never vouch for a count ("31 chi nhánh" vs period 31/12/2025)
    plain_refs = [
        n
        for n in evidence_nums + fact_refs + [n for t in fact_texts for n in _undated_numbers(t)]
        if n.unit is None
    ]
    # a fact's period vouches for its year and closing date ("FY2025" -> 2025, 31/12/2025)
    periods = [k for k in (period_key(f.period) for f in src.facts) if k is not None]
    years = [n for t in all_texts for n in _numbers(t) if _is_year(n)]
    years += [_Num(Decimal(y), None, None, 0, str(y)) for y, _, _ in periods]
    source_words = set().union(*(_words(t) for t in all_texts)) if all_texts else set()
    source_dates = set().union(*(_dates(t) for t in all_texts)) if all_texts else set()
    source_dates |= {(d, m, y) for y, m, d in periods}
    date_spans = [m.span() for m in _DATE_RE.finditer(text) if _dates(m.group(0)) <= source_dates]

    for n in _numbers(text):
        if _FOOTNOTE_RE.match(n.raw.strip()):
            continue
        if any(s <= n.span[0] and n.span[1] <= e for s, e in date_spans):
            continue
        if n.unit is not None:
            ok = _matches(n, refs)
        else:
            word = _word_at(text, n.span[0])
            ok = (
                (any(c.isalpha() for c in word) and word in source_words)
                or (_is_year(n) and _matches(n, years))
                or _matches(n, plain_refs)
            )
        if not ok:
            return False
    return True


def _magnitude(n: _Num) -> _Num:
    return replace(n, value=abs(n.value), vnd=abs(n.vnd) if n.vnd is not None else None)


def _is_outflow(f: Fact, ref: _Num) -> bool:
    """A payment shown in parentheses ("Cổ tức trả cho cổ đông (7.084.911)"); never a loss row."""
    words = {w.strip(_STRIP) for w in normalize_chars(f.label).lower().split()}
    return ref.value < 0 and (f.raw or "").strip().startswith("(") and bool(words & _PAYMENT_WORDS)


def _undated_numbers(text: str) -> list[_Num]:
    spans = [m.span() for m in _DATE_RE.finditer(normalize_chars(text))]
    return [n for n in _numbers(text) if not any(s <= n.span[0] and n.span[1] <= e for s, e in spans)]


def _content(text: str) -> set[str]:
    """Content words of a clause, NFC-lowercased and NOT accent-folded ("thuê" ≠ "thuế").

    Removed: numbers with their unit words, stopwords, and a comparative period phrase
    ("so với năm trước", "so với cùng kỳ năm trước", "cùng kỳ", …). A bare period phrase
    ("Tổng tài sản năm trước tăng") keeps "trước"/"ngoái" in the subject, so it only binds
    when the evidence clause or fact vocabulary has it too."""
    s = unicodedata.normalize("NFC", normalize_chars(text)).lower()
    s = _COMPARATIVE_PERIOD_RE.sub(" ", _NUM_UNIT_RE.sub(" ", s))
    return {w for w in _LETTERS_RE.findall(s) if w not in _STOPWORDS}


def _is_break(text: str, i: int) -> bool:
    c = text[i]
    if c not in _SOFT_BREAKS and c not in _HARD_BREAKS:
        return False
    # "1.192" / "21,8": separators inside a number do not end a clause
    return not (c in ",." and 0 < i < len(text) - 1 and text[i - 1].isdigit() and text[i + 1].isdigit())


def _subject(text: str, pos: int) -> set[str]:
    """Content words of the clause before ``pos`` (since the last , ; : . newline or start).

    A clause with no content words ("…: 1.192 nghìn tỷ đồng, tăng 21,8%") takes the subject
    of the clause before it, back across ``,`` / ``:`` only — the elided subject of the real
    KPI sentences. It never crosses ``.`` / ``;`` / a newline."""
    end = pos
    while True:
        i = end - 1
        while i >= 0 and not _is_break(text, i):
            i -= 1
        words = _content(text[i + 1 : end])
        if words or i < 0 or text[i] in _HARD_BREAKS:
            return words
        end = i


def _direction_hits(text: str) -> list[tuple[str, int, bool]]:
    """(direction, start, negated) for every direction word; negated = "không"/"chưa"/… before it."""
    out: list[tuple[str, int, bool]] = []
    for m in _DIR_RE.finditer(text):
        d = "up" if _UP_RE.match(m.group(0)) else "down"
        before = text[: m.start()].split()
        negated = bool(before) and before[-1].lower().strip(_STRIP) in _NEGATIONS
        out.append((d, m.start(), negated))
    return out


def _fact_binds(subject: set[str], f: Fact) -> bool:
    """label words ⊆ subject ⊆ words of the fact's label and descriptive context."""
    label = _content(f.label)
    fields = (f.label, f.parent_label, f.table_title, f.chapter, f.statement)
    vocab = set().union(*(_content(x) for x in fields if x))
    return bool(label) and label <= subject <= vocab


def _governed(text: str, pos: int) -> _Num | None:
    """The number a direction word at ``pos`` governs: the first one within GOVERN_WINDOW words."""
    for n in _numbers(text):
        if n.span[0] > pos:
            return n if len(text[pos : n.span[0]].split()) <= GOVERN_WINDOW + 1 else None
    return None


def _fact_direction(f: Fact) -> str | None:
    """KPI arrow, else the explicit sign of a % change cell ("+18,16%"); never a bare value."""
    if f.direction is not None:
        return f.direction
    raw = (f.raw or "").strip()
    if normalize_unit(f.unit) not in ("%", "điểm %") or not raw:
        return None
    if raw.startswith("+") and f.value > 0:
        return "up"
    if raw.startswith(("-", "(")) and f.value < 0:
        return "down"
    return None


def _quoted(text: str, pos: int, chunks: list[Chunk]) -> bool:
    """The direction word with QUOTE_BEFORE words before and QUOTE_AFTER after is in a cited chunk."""
    before = text[:pos].split()[-QUOTE_BEFORE:]
    after = text[pos:].split()[: QUOTE_AFTER + 1]
    if len(before) < QUOTE_BEFORE or len(after) < QUOTE_AFTER + 1:
        return False

    def words(t: str) -> str:
        return " ".join(w.strip(_STRIP) for w in _norm(t).lower().split())

    window = words(" ".join(before + after))
    return any(window in words(c.text) for c in chunks)


def _direction_rule(
    claim_text: str, handwritten: str, src: _Sources, trusted_evidence: str | None
) -> str | None:
    for m in _PLACEHOLDER_RE.finditer(claim_text):
        window = " ".join(claim_text[: m.start()].split()[-NEAR_WINDOW:])
        if _DIR_RE.search(window):
            return "direction_near_placeholder"

    hits = _direction_hits(handwritten)
    if any(neg for _, _, neg in hits):
        return "direction_mismatch"  # "không tăng" is never vouched for
    # evidence direction words (not negated) with the subject of their own clause
    evidence = (
        [(d, _subject(trusted_evidence, p)) for d, p, neg in _direction_hits(trusted_evidence) if not neg]
        if trusted_evidence
        else []
    )
    # calc results never supply signals: the code renders their direction inside the placeholder
    per_word: list[tuple[str, set[str], bool]] = []
    for d, pos, _ in hits:
        subject = _subject(handwritten, pos)
        bound = [f for f in src.facts if _fact_binds(subject, f)]
        signals: set[str] = {d for d in map(_fact_direction, bound) if d in ("up", "down")}
        if len(subject) >= 2:
            signals |= {ed for ed, ev_subject in evidence if ev_subject == subject}
        if _governed(handwritten, pos) is None and _quoted(handwritten, pos, src.chunks):
            signals.add(d)
        per_word.append((d, signals, any(f.direction == "unknown" for f in bound)))

    # contradictory signals ({up, down}) fail closed
    if any(sig and (len(sig) > 1 or d not in sig) for d, sig, _ in per_word):
        return "direction_mismatch"
    if any(unknown for _, _, unknown in per_word):
        return "direction_unknown"
    if any(not sig for _, sig, _ in per_word):  # no supporting signal is not a match
        return "direction_mismatch"
    return None


def _verify(claim: ClaimOut, ctx: Context, calcs: dict[str, CalcResult]) -> VerifiedClaim:
    src = _resolve(claim, ctx, calcs)
    filled, _ = fill_placeholders(claim.text, calcs)
    pages = sorted(
        {p for f in src.facts for p in f.printed_pages} | {p for c in src.chunks for p in c.printed_pages}
    )

    def result(rule: str | None) -> VerifiedClaim:
        return VerifiedClaim(
            text=filled,
            sources=src.ids,
            printed_pages=pages,
            ok=rule is None,
            failed_rule=rule,
            evidence=claim.evidence,
            calc_ids=list(dict.fromkeys(_CALC_REF_RE.findall(claim.text))),
        )

    # 1. sources
    if src.missing:
        return result("source_missing")

    # 2. evidence is a substring of a cited chunk
    evidence = _norm(claim.evidence)
    evidence_chunk: Chunk | None = None
    if src.chunks:
        evidence_chunk = next((c for c in src.chunks if evidence and evidence in _norm(c.text)), None)
        if evidence_chunk is None:
            return result("evidence_not_substring")

    # 3. hand-written numbers
    handwritten = _blank_placeholders(normalize_chars(claim.text))
    if not _check_numbers(handwritten, src, evidence_chunk, evidence):
        return result("number_mismatch")

    # 4. direction words
    trusted = evidence if evidence_chunk is not None else None
    rule = _direction_rule(normalize_chars(claim.text), handwritten, src, trusted)
    if rule:
        return result(rule)

    # 5. calcs: any placeholder left after filling means a failed / undeclared calc
    if _PLACEHOLDER_RE.search(filled):
        return result("calc_failed")

    # 6. citation pages
    return result(None)


def verify_claims(claims: list[ClaimOut], ctx: Context, calcs: dict[str, CalcResult]) -> list[VerifiedClaim]:
    """Verify every claim independently; one ``VerifiedClaim`` per input, same order."""
    return [_verify(c, ctx, calcs) for c in claims]
