from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from ircb_api.schemas import HealthOut
from ircb_api.state import AppState, get_state

router = APIRouter()


@router.get("/health", response_model=HealthOut)
def health(st: Annotated[AppState, Depends(get_state)]) -> HealthOut:
    return HealthOut(
        status="ok",
        index_version=st.manifest.index_version,
        doc_id=st.manifest.doc_id,
        n_chunks=st.manifest.n_chunks,
        n_facts=st.manifest.n_facts,
        llm_model=st.settings.llm_model,
        embed_model=st.settings.embed_model,
        pdf_available=st.renderer.pdf_available,
    )
