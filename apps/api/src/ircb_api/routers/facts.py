"""GET /v1/facts: label search over the extracted facts."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from ircb_api.mapping import to_fact_out
from ircb_api.schemas import FactOut
from ircb_api.state import AppState, get_state

router = APIRouter()


@router.get("/facts", response_model=list[FactOut])
def search_facts(
    st: Annotated[AppState, Depends(get_state)],
    q: str = "",
    period: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[FactOut]:
    return [to_fact_out(f) for f in st.facts.search(q, period=period, limit=limit)]
