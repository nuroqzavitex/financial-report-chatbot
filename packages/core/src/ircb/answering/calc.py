"""Declarative calc executor (spec §5.15).

The LLM declares calculations as ``CalcSpec`` JSON; this module executes them with
``Decimal`` and renders placeholders ``{cN}``. The model never sees the results.

Design notes:
- Operands are ``fact:<id>`` or ``calc:<id>``. Calc operands use the *unrounded*
  Decimal of the earlier result; only the rendered string is rounded.
- Nesting is limited to one level (a calc may consume calcs that only consume facts).
- ``ratio`` always yields the pure ratio with unit ``lần`` (also for ``%`` / ``%``).
- Formulas of calc operands are written with the operand calc id, e.g. ``c1 − c2``.
- growth / diff of two typed operands (facts, or ``convert`` results which keep their fact's
  metric and period) need the same metric, the same unit and ``period(a)`` strictly later than
  ``period(b)`` (``FY2025`` / ``2025-12-31`` / ``31/12/2025`` / ``2025`` compare by date), else
  ``period_order``: a swapped pair would render a confident, sign-flipped figure. Two derived
  calcs (``calc:`` growth/diff/ratio results) carry no period and skip these checks; a typed
  operand against a derived calc has no defined meaning and fails with ``operand_mix``.
- Never format with ``str(Decimal)``: scale differs between SQLite and Postgres,
  so everything goes through ``format_vn``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from ircb.domain.models import CalcResult, CalcSpec, Fact
from ircb.domain.numbers_vn import format_vn
from ircb.domain.units import UNIT_SCALE, UnitError, convert, normalize_unit, to_vnd

_TWO = Decimal("0.01")
_PLACEHOLDER_RE = re.compile(r"\{(c\d+)\}")
_FY_RE = re.compile(r"(?:FY)?(\d{4})")
_ISO_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_DMY_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


def period_key(period: str | None) -> tuple[int, int, int] | None:
    """Comparable (year, month, day); a fiscal year is its last day. None when not a period."""
    p = (period or "").strip()
    if m := _FY_RE.fullmatch(p):
        return int(m.group(1)), 12, 31
    if m := _ISO_RE.fullmatch(p):
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    if m := _DMY_RE.fullmatch(p):
        return int(m.group(3)), int(m.group(2)), int(m.group(1))
    return None


@dataclass
class _Operand:
    value: Decimal
    unit: str
    vnd: Decimal | None
    decimals: int
    fact_ids: list[str]
    text: str
    label_norm: str | None = None
    period: str | None = None
    is_fact: bool = True
    depth: int = 0
    typed: bool = True  # a fact or a convert of one: has a metric and a period


class _CalcError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _fmt(value: Decimal) -> str:
    return format_vn(value.normalize() if value != 0 else Decimal(0))


def _decimals(value: Decimal) -> int:
    exp = value.normalize().as_tuple().exponent
    return max(0, -exp) if isinstance(exp, int) else 0


def _q2(value: Decimal) -> Decimal:
    return value.quantize(_TWO, rounding=ROUND_HALF_UP)


def _dedup(ids: list[str]) -> list[str]:
    return list(dict.fromkeys(ids))


def _direction(x: Decimal, body: str) -> str:
    if x == 0:
        return "không đổi"
    return f"tăng {body}" if x > 0 else f"giảm {body}"


def _fail(spec_id: str, code: str) -> CalcResult:
    return CalcResult(
        id=spec_id,
        ok=False,
        value=None,
        unit=None,
        rendered=None,
        formula=None,
        operand_fact_ids=[],
        error=code,
    )


def _ok(cid: str, value: Decimal, unit: str, rendered: str, formula: str, ids: list[str]) -> CalcResult:
    return CalcResult(
        id=cid,
        ok=True,
        value=value,
        unit=unit,
        rendered=rendered,
        formula=formula,
        operand_fact_ids=ids,
        error=None,
    )


def _calc_deps(spec: CalcSpec) -> list[str]:
    return [o[5:] for o in (spec.a, spec.b) if o and o.startswith("calc:")]


def _find_cyclic(specs: dict[str, CalcSpec]) -> set[str]:
    cyclic: set[str] = set()
    for start in specs:
        seen: set[str] = set()
        stack = list(_calc_deps(specs[start]))
        while stack:
            n = stack.pop()
            if n == start:
                cyclic.add(start)
                break
            if n in seen or n not in specs:
                continue
            seen.add(n)
            stack.extend(_calc_deps(specs[n]))
    return cyclic


def execute_calcs(calcs: list[CalcSpec], facts: dict[str, Fact]) -> dict[str, CalcResult]:
    specs = {c.id: c for c in calcs}
    cyclic = _find_cyclic(specs)
    results: dict[str, CalcResult] = {}
    depths: dict[str, int] = {}
    typed: dict[str, _Operand] = {}  # convert results keep their operand's metric and period

    def run(cid: str) -> CalcResult:
        if cid in results:
            return results[cid]
        if cid in cyclic:
            res = _fail(cid, "cycle")
        else:
            try:
                res, depths[cid] = _execute(specs[cid])
            except _CalcError as e:
                res = _fail(cid, e.code)
        results[cid] = res
        return res

    def operand(ref: str | None) -> _Operand:
        if ref is None:
            raise _CalcError("unknown_operand")
        if ref.startswith("fact:"):
            f = facts.get(ref[5:])
            if f is None:
                raise _CalcError("unknown_operand")
            vnd = f.value_vnd if f.value_vnd is not None else to_vnd(f.value, f.unit)
            return _Operand(
                value=f.value,
                unit=f.unit,
                vnd=vnd,
                decimals=_decimals(f.value),
                fact_ids=[f.fact_id],
                text=_fmt(f.value),
                label_norm=f.label_norm,
                period=f.period,
            )
        if ref.startswith("calc:"):
            rid = ref[5:]
            if rid not in specs:
                raise _CalcError("unknown_operand")
            r = run(rid)
            if not r.ok or r.value is None or r.unit is None:
                raise _CalcError(r.error or "unknown_operand")
            src = typed.get(rid)
            return _Operand(
                value=r.value,
                unit=r.unit,
                vnd=to_vnd(r.value, r.unit),
                decimals=_decimals(r.value),
                fact_ids=r.operand_fact_ids,
                text=rid,
                label_norm=src.label_norm if src else None,
                period=src.period if src else None,
                is_fact=False,
                depth=depths[rid] + 1,
                typed=src is not None,
            )
        raise _CalcError("unknown_operand")

    def _convert(spec: CalcSpec, a: _Operand) -> CalcResult:
        target = normalize_unit(spec.to_unit) if spec.to_unit else None
        if target is None or target not in UNIT_SCALE or normalize_unit(a.unit) not in UNIT_SCALE:
            raise _CalcError("bad_convert")
        try:
            val = convert(a.value, a.unit, target)
        except UnitError as e:  # pragma: no cover - guarded above
            raise _CalcError("bad_convert") from e
        rendered = f"{format_vn(_q2(val), 2)} {target}"
        return _ok(spec.id, val, target, rendered, f"{a.text} {a.unit} → {target}", _dedup(a.fact_ids))

    def _execute(spec: CalcSpec) -> tuple[CalcResult, int]:
        a = operand(spec.a)
        if a.depth > 1:
            raise _CalcError("nesting_too_deep")
        if spec.op == "convert":
            res = _convert(spec, a)
            if a.typed:
                typed[spec.id] = a
            return res, a.depth
        b = operand(spec.b)
        depth = max(a.depth, b.depth)
        if depth > 1:
            raise _CalcError("nesting_too_deep")
        ids = _dedup(a.fact_ids + b.fact_ids)
        if spec.op in ("growth", "diff"):
            if a.typed != b.typed:
                raise _CalcError("operand_mix")
            if a.typed and a.label_norm != b.label_norm:
                raise _CalcError("metric_mismatch")
            if a.unit != b.unit:
                raise _CalcError("unit_mismatch")
            if a.typed and a.period == b.period:
                raise _CalcError("same_period")
            if a.typed:
                ka, kb = period_key(a.period), period_key(b.period)
                if ka is None or kb is None or ka <= kb:
                    raise _CalcError("period_order")
            if spec.op == "growth":
                if b.value <= 0:  # growth on a zero/negative base has no meaningful direction
                    raise _CalcError("non_positive_base")
                val = (a.value - b.value) / b.value * 100
                shown = _q2(val)
                body = format_vn(abs(shown), 2) + "%"
                formula = f"({a.text} − {b.text}) / {b.text}"
                return _ok(spec.id, val, "%", _direction(shown, body), formula, ids), depth
            val = a.value - b.value
            if a.unit in ("%", "điểm %", "lần"):
                unit = "điểm %" if a.unit == "%" else a.unit
                shown = _q2(val)
                body = f"{format_vn(abs(shown), 2)} {unit}"
            else:
                unit = a.unit
                d = max(a.decimals, b.decimals)
                shown = val.quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP)
                body = f"{format_vn(abs(shown), d)} {unit}"
            return _ok(spec.id, val, unit, _direction(shown, body), f"{a.text} − {b.text}", ids), depth
        # ratio
        if a.vnd is not None and b.vnd is not None:
            na, nb = a.vnd, b.vnd
        elif a.unit == b.unit and a.unit in ("%", "điểm %"):
            na, nb = a.value, b.value
        else:
            raise _CalcError("not_comparable")
        if nb == 0:
            raise _CalcError("division_by_zero")
        val = na / nb
        rendered = f"{format_vn(_q2(val), 2)} lần"
        return _ok(spec.id, val, "lần", rendered, f"{a.text} / {b.text}", ids), depth

    for cid in specs:
        run(cid)
    return results


def fill_placeholders(text: str, results: dict[str, CalcResult]) -> tuple[str, list[str]]:
    """Replace ``{cN}`` with rendered results; unresolved placeholders stay untouched."""
    missing: list[str] = []

    def sub(m: re.Match[str]) -> str:
        r = results.get(m.group(1))
        if r is None or not r.ok or r.rendered is None:
            if m.group(1) not in missing:
                missing.append(m.group(1))
            return m.group(0)
        return r.rendered

    return _PLACEHOLDER_RE.sub(sub, text), missing


def operand_facts(calc_id: str, results: dict[str, CalcResult]) -> list[str]:
    """Fact ids behind a calc, including facts reached through ``calc:`` operands."""
    r = results.get(calc_id)
    return list(r.operand_fact_ids) if r else []
