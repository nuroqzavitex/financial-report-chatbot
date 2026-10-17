"""Render verified claims into the final Vietnamese answer, status and citations."""

from __future__ import annotations

from typing import Literal

from ircb.domain.models import CalcResult, Citation, Conflict, VerifiedClaim

REFUSED_TEXT = "Không tìm thấy thông tin này trong Báo cáo thường niên 2025."
UNVERIFIED_TEXT = "Chưa xác minh được một phần nội dung"
PARTIAL_TEXT = "Một phần câu hỏi không có thông tin trong Báo cáo thường niên 2025."
# The model's free-text conflict note is never shown (it is unverified): one fixed sentence per kind.
CONFLICT_TEXT = {
    "rounding": "Số liệu tổng quan đã được làm tròn từ số kiểm toán.",
    "definition": "Hai số liệu khác nhau do khác định nghĩa chỉ tiêu.",
    "genuine": "Hai nguồn trong báo cáo cho số liệu khác nhau — cần kiểm tra.",
}


def _cite(pages: list[int]) -> str:
    return Citation.for_pages(pages).label if pages else ""


def _sentence(c: VerifiedClaim) -> str:
    tag = _cite(c.printed_pages)
    return f"{c.text.rstrip()} {tag}" if tag else c.text.rstrip()


def _unverified(failed: list[VerifiedClaim]) -> str:
    """One fixed note for all failed claims: pages only, never claim text (zero-leak ruling C2)."""
    tag = _cite(sorted({p for c in failed for p in c.printed_pages}))
    return f"{UNVERIFIED_TEXT}, xem {tag}." if tag else f"{UNVERIFIED_TEXT}."


def render(
    verified: list[VerifiedClaim],
    calcs: dict[str, CalcResult],
    conflict: Conflict | None,
    gen_status: str,
    suggest_pages: list[int] | None = None,
) -> tuple[Literal["answered", "partial", "refused"], str, list[Citation]]:
    """Claim order is kept as the generator returned it (rounding conflicts: overview figure first).

    Only code-written text is added to verified claims: the conflict sentence for ``conflict.kind``,
    the unverified note (pages only) and, for a generator "partial", the missing-part note.
    """
    passed = [c for c in verified if c.ok]
    failed = [c for c in verified if not c.ok]
    if not passed or gen_status == "not_found":
        text = REFUSED_TEXT
        if suggest_pages:
            text += f" Có thể tham khảo {_cite(suggest_pages)}."
        return "refused", text, []
    lines = [_sentence(c) for c in passed]
    if conflict is not None and conflict.kind is not None:
        lines.append(CONFLICT_TEXT[conflict.kind])
    if failed:
        lines.append(_unverified(failed))
    partial = bool(failed) or gen_status == "partial"
    if gen_status == "partial":
        lines.append(PARTIAL_TEXT)
    citations: list[Citation] = []
    seen: set[str] = set()
    for c in passed:
        if not c.printed_pages:
            continue
        cit = Citation.for_pages(c.printed_pages)
        if cit.label not in seen:
            seen.add(cit.label)
            citations.append(cit)
    return ("partial" if partial else "answered"), "\n".join(lines), citations
