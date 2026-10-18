"""GET /v1/traces/{trace_id}: one stored trace (dev only)."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from ircb_api.errors import ApiError
from ircb_api.state import AppState, get_state

router = APIRouter()


@router.get("/traces/{trace_id}")
def get_trace(trace_id: str, st: Annotated[AppState, Depends(get_state)]) -> dict[str, Any]:
    if st.settings.app_env != "dev":
        raise ApiError(404, "not_found", "Không tìm thấy.")
    trace_dir = st.settings.trace_dir
    if trace_dir.is_dir():
        for path in sorted(trace_dir.glob("*.jsonl"), reverse=True):
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    if trace_id not in line:
                        continue
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(obj, dict) and obj.get("trace_id") == trace_id:
                        return obj
    raise ApiError(404, "trace_not_found", "Không tìm thấy trace.")
