"""GET /v1/report.pdf: the whole annual report, shown inline by the browser's PDF viewer."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from ircb_api.errors import ApiError
from ircb_api.state import AppState, get_state

router = APIRouter()

REPORT_FILENAME = "techcombank-bao-cao-thuong-nien-2025.pdf"


@router.get(
    "/report.pdf",
    response_class=FileResponse,
    responses={200: {"content": {"application/pdf": {}}}},
)
def report_pdf(st: Annotated[AppState, Depends(get_state)]) -> FileResponse:
    if not st.renderer.pdf_available:
        raise ApiError(503, "pdf_missing", "Không có tệp PDF gốc trên máy chủ.")
    return FileResponse(
        st.settings.pdf_path,
        media_type="application/pdf",
        filename=REPORT_FILENAME,
        content_disposition_type="inline",  # open in the viewer, not as a download
    )
