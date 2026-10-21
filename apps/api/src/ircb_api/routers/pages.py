"""GET /v1/pages/{printed}/image: a printed half page as PNG, evidence highlighted."""

from __future__ import annotations

import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response
from ircb.pages import PageNotFound, PdfMissing

from ircb_api.errors import ApiError
from ircb_api.state import AppState, get_state

router = APIRouter()

_FACT = "fact:"
_CHUNK = "chunk:"


def _source_rect(st: AppState, source: str | None, printed: int) -> list[float] | None:
    """Bbox of the source, only if the source lives on this printed page; else None."""
    if not source:
        return None
    pages: list[int] = []
    bbox: list[float] | None = None
    if source.startswith(_FACT):
        fid = source.removeprefix(_FACT)
        f = st.facts.get_many([fid]).get(fid)
        if f is not None:
            pages, bbox = f.printed_pages, f.bbox
    elif source.startswith(_CHUNK):
        ch = st.chunks.get(source.removeprefix(_CHUNK))
        if ch is not None:
            pages, bbox = ch.printed_pages, ch.bbox
    if bbox is None or len(bbox) != 4 or printed not in pages:
        return None
    return bbox


@router.get(
    "/pages/{printed}/image", response_class=Response, responses={200: {"content": {"image/png": {}}}}
)
def page_image(
    printed: int,
    st: Annotated[AppState, Depends(get_state)],
    source: str | None = None,
    evidence: Annotated[str | None, Query(max_length=500)] = None,
    if_none_match: Annotated[str | None, Header()] = None,
) -> Response:
    rect = _source_rect(st, source, printed)
    try:
        png = st.renderer.render(printed, rect=rect, evidence=evidence)
    except PageNotFound:
        raise ApiError(404, "page_not_found", "Không có trang này trong báo cáo.") from None
    except PdfMissing:
        raise ApiError(503, "pdf_missing", "Không có tệp PDF gốc trên máy chủ.") from None
    # revalidated on every view (304 when unchanged): a new highlight style must not hide behind a
    # browser cache of the same URL, as a one-day max-age did when boxes became red text
    etag = f'"{hashlib.sha256(png).hexdigest()[:32]}"'
    headers = {"Cache-Control": "no-cache", "ETag": etag}
    if if_none_match == etag:
        return Response(status_code=304, headers=headers)
    return Response(png, media_type="image/png", headers=headers)
