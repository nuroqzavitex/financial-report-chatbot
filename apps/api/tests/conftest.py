from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pymupdf as fitz
import pytest
from fastapi.testclient import TestClient
from ircb.domain.models import Answer, CalcResult, Chunk, Conflict, Fact, PageInfo, TurnState, VerifiedClaim
from ircb.pages import PageRenderer
from ircb.settings import Settings
from ircb.storage.artefacts import Manifest
from ircb.storage.db import make_engine, upgrade_db
from ircb.storage.fact_repo import SqlFactStore
from ircb.storage.session_repo import SessionRepo
from ircb_api.main import create_app
from ircb_api.state import AppState

ALL_STEPS = [
    "period_guard",
    "rewrite",
    "post_rewrite_guard",
    "prefetch",
    "gate",
    "generate",
    "calc",
    "verify",
    "render",
]


def make_answer(text: str = "Xin chào", status: str = "answered", state: TurnState | None = None) -> Answer:
    return Answer.model_validate(
        {
            "status": status,
            "text": text,
            "claims": [],
            "calcs": [],
            "citations": [],
            "conflict": None,
            "state": state.model_dump() if state else None,
            "trace_id": "t-1",
            "latency_ms": {},
            "cost_usd": "0",
        }
    )


def ok_claim(
    text: str,
    pages: list[int] | None = None,
    sources: list[str] | None = None,
    calc_ids: list[str] | None = None,
) -> VerifiedClaim:
    """A passed claim; a trailing ``[tr. N]`` label in ``text`` is stripped (the renderer adds it)."""
    return VerifiedClaim(
        text=text.split(" [tr.")[0],
        sources=sources if sources is not None else ["fact:f25", "chunk:c1"],
        printed_pages=pages if pages is not None else [5],
        ok=True,
        failed_rule=None,
        evidence="Tong tai san 1.192",
        calc_ids=calc_ids or [],
    )


def answer_with(
    claims: list[VerifiedClaim],
    text: str,
    calcs: list[CalcResult] | None = None,
    status: str = "answered",
    state: TurnState | None = None,
    cost_usd: str = "0.0012",
    conflict: Conflict | None = None,
) -> Answer:
    return Answer.model_validate(
        {
            "status": status,
            "text": text,
            "claims": [c.model_dump() for c in claims],
            "calcs": [c.model_dump() for c in calcs or []],
            "citations": [],
            "conflict": conflict.model_dump() if conflict else None,
            "state": state.model_dump() if state else None,
            "trace_id": "t-1",
            "latency_ms": {"total": 12},
            "cost_usd": cost_usd,
        }
    )


STATE_2025 = TurnState(metrics=["tổng tài sản"], periods=["2025"], entity=None)


def default_answer() -> Answer:
    return answer_with(
        claims=[ok_claim("Tổng tài sản đạt 1.192 nghìn tỷ đồng [tr. 5]")],
        text="Tổng tài sản đạt 1.192 nghìn tỷ đồng [tr. 5]",
        state=STATE_2025,
    )


class FakeService:
    """Scripted ServiceLike: returns queued answers, records calls and peak concurrency, replays steps."""

    def __init__(
        self,
        answers: list[Answer] | None = None,
        delay: float = 0.0,
        steps: list[str] | None = None,
        exc: Exception | None = None,
    ) -> None:
        self.answers = list(answers or [make_answer()])
        self.delay = delay
        self.steps = steps or []
        self.exc = exc
        self.calls: list[tuple[str, TurnState | None, list[tuple[str, str]] | None]] = []
        self.max_concurrent = 0
        self._active = 0
        self._guard = threading.Lock()

    def ask(
        self,
        message: str,
        prev_state: TurnState | None = None,
        history: list[tuple[str, str]] | None = None,
        on_step: Callable[[str], None] | None = None,
    ) -> Answer:
        with self._guard:
            self._active += 1
            self.max_concurrent = max(self.max_concurrent, self._active)
        try:
            self.calls.append((message, prev_state, history))
            if on_step:
                for s in self.steps:
                    on_step(s)
            if self.delay:
                time.sleep(self.delay)
            if self.exc is not None:
                raise self.exc
            return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        finally:
            with self._guard:
                self._active -= 1


def synthetic_pdf(path: Path) -> Path:
    d = fitz.open()  # type: ignore[no-untyped-call]
    p1 = d.new_page(width=300, height=400)  # type: ignore[no-untyped-call]
    p1.insert_text((50, 100), "Cover", fontsize=14)  # type: ignore[no-untyped-call]
    p2 = d.new_page(width=600, height=400)  # type: ignore[no-untyped-call]
    p2.insert_text((50, 60), "Tong tai san 1.192", fontsize=14)  # type: ignore[no-untyped-call]
    p2.insert_text((350, 60), "Du no vay 328,1", fontsize=14)  # type: ignore[no-untyped-call]
    d.save(path)  # type: ignore[no-untyped-call]
    d.close()
    return path


PAGE_MAP = [
    PageInfo(pdf_page=1, half="S", printed_page=1, chapter=None, is_divider=False),
    PageInfo(pdf_page=2, half="L", printed_page=2, chapter=None, is_divider=False),
    PageInfo(pdf_page=2, half="R", printed_page=3, chapter=None, is_divider=False),
]


def make_state(tmp_path: Path, answers: list[Answer] | None = None, **service_kwargs: object) -> AppState:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        llm_model="fake-llm",
        index_dir=tmp_path / "index",
        database_url=f"sqlite:///{(tmp_path / 'api.db').as_posix()}",
        pdf_path=tmp_path / "synthetic.pdf",
        page_cache_dir=tmp_path / "page_cache",
        trace_dir=tmp_path / "traces",
        cors_origins="http://localhost:3000",
        app_env="dev",
    )
    synthetic_pdf(settings.pdf_path)
    engine = make_engine(settings.database_url)
    upgrade_db(engine)
    chunk = Chunk(
        chunk_id="c1",
        doc_id="doc",
        pdf_page=2,
        half="L",
        printed_pages=[2],
        chapter=None,
        statement=None,
        note_no=None,
        content_type="prose",
        unit=None,
        text="Tong tai san 1.192",
        fact_ids=[],
        bbox=[0, 0, 300, 400],
    )
    manifest = Manifest(
        index_version="v-test",
        doc_id="doc",
        pdf_sha256="0" * 64,
        embed_provider="openai",
        embed_model="text-embedding-3-small",
        embed_dimensions=8,
        tokenizer_version="1",
        periods_seen=["2025"],
        n_chunks=1,
        n_facts=0,
        created_at="2026-01-01T00:00:00Z",
    )
    return AppState(
        settings=settings,
        service=FakeService(answers, **service_kwargs),  # type: ignore[arg-type]
        sessions=SessionRepo(engine),
        facts=SqlFactStore(engine),
        chunks={chunk.chunk_id: chunk},
        renderer=PageRenderer(settings.pdf_path, PAGE_MAP, settings.page_cache_dir),
        manifest=manifest,
        lock=threading.Lock(),
    )


def make_fact(fact_id: str, value: str, period: str, pages: list[int]) -> Fact:
    return Fact(
        fact_id=fact_id,
        doc_id="doc",
        printed_pages=pages,
        chapter=None,
        statement=None,
        note_no=None,
        table_title=None,
        label="Tổng tài sản",
        label_norm="tong tai san",
        parent_label=None,
        row_level=0,
        is_total=True,
        col_path=period,
        period=period,
        value=Decimal(value),
        unit="tỷ đồng",
        value_vnd=None,
        raw=value.replace(".", ","),
        source="table",
        pdf_page=3,
        bbox=[0, 0, 1, 1],
        direction=None,
        change_basis=None,
    )


def sse_events(response: httpx.Response) -> list[tuple[str, Any]]:
    """Parse an SSE body into (event, decoded JSON data) pairs; comment frames (pings) are skipped."""
    assert response.status_code == 200, response.text
    out: list[tuple[str, Any]] = []
    for frame in response.text.replace("\r\n", "\n").split("\n\n"):
        event, data = "message", []
        for line in frame.split("\n"):
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].lstrip())
        if data:
            out.append((event, json.loads("\n".join(data))))
    return out


def wait_until(cond: Callable[[], bool], timeout: float = 5.0) -> None:
    """Poll ``cond`` until it holds; fail after ``timeout`` seconds."""
    deadline = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        time.sleep(0.02)


@pytest.fixture
def state(tmp_path: Path) -> AppState:
    st = make_state(tmp_path, [default_answer()], steps=ALL_STEPS)
    tts25 = make_fact("tts25", "1192344137", "FY2025", [297]).model_copy(update={"unit": "triệu đồng"})
    st.facts.upsert([make_fact("f25", "1192.3", "2025", [5]), make_fact("f24", "978.8", "2024", [6]), tts25])
    return st


@pytest.fixture
def fake_service(state: AppState) -> FakeService:
    assert isinstance(state.service, FakeService)
    return state.service


@pytest.fixture
def facts_store(state: AppState) -> SqlFactStore:
    return state.facts


@pytest.fixture
def chunks(state: AppState) -> dict[str, Chunk]:
    return state.chunks


def _client(state: AppState) -> Iterator[TestClient]:
    with TestClient(create_app(state)) as c:
        yield c


@pytest.fixture
def client(state: AppState) -> Iterator[TestClient]:
    yield from _client(state)


@pytest.fixture
def client_no_pdf(state: AppState) -> Iterator[TestClient]:
    state.settings.pdf_path.unlink()
    yield from _client(state)


@pytest.fixture
def client_prod(state: AppState) -> Iterator[TestClient]:
    prod = replace(state, settings=state.settings.model_copy(update={"app_env": "prod"}))
    yield from _client(prod)


@pytest.fixture
def trace_file(state: AppState) -> str:
    """Write a day file with two traces; return the id of the second."""
    d = state.settings.trace_dir
    d.mkdir(parents=True, exist_ok=True)
    lines = [{"trace_id": "other", "question": "a"}, {"trace_id": "tr-abc123", "question": "b"}]
    body = "\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n"
    (d / "2026-10-18.jsonl").write_text(body, encoding="utf-8")
    return "tr-abc123"


@pytest.fixture
def client_with_failed_claim(state: AppState, fake_service: FakeService) -> Iterator[TestClient]:
    failed = VerifiedClaim(
        text="SECRET 9.999 nghìn tỷ",
        sources=["fact:f25", "chunk:c1"],
        printed_pages=[7],
        ok=False,
        failed_rule="number_mismatch",
        evidence="SECRET 9.999",
    )
    fake_service.answers = [
        answer_with(
            claims=[ok_claim("Tổng tài sản đạt 1.192 nghìn tỷ đồng [tr. 5]"), failed],
            text="Tổng tài sản đạt 1.192 nghìn tỷ đồng [tr. 5]\n"
            "Chưa xác minh được một phần nội dung, xem [tr. 7].",
            status="partial",
            state=STATE_2025,
        )
    ]
    yield from _client(state)


@pytest.fixture
def client_error(state: AppState, fake_service: FakeService) -> Iterator[TestClient]:
    fake_service.answers = [make_answer("Lỗi khi gọi mô hình, vui lòng thử lại.", status="error")]
    yield from _client(state)


@pytest.fixture
def client_raising(state: AppState, fake_service: FakeService) -> Iterator[TestClient]:
    fake_service.exc = RuntimeError("boom")
    yield from _client(state)


@pytest.fixture
def slow_client(state: AppState, fake_service: FakeService) -> Iterator[TestClient]:
    fake_service.delay = 0.2
    yield from _client(state)
