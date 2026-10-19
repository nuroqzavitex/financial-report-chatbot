"""Default-suite end to end on real storage (no Docker, no network).

Real artefact writers and the real embed stage (fake embedding backend) build a mini index;
``AnswerService.from_settings`` loads it through ``ensure_loaded`` into embedded Qdrant + SQLite;
a scripted fake LLM plays rewriter and generator. This is the chain that hand-built ``Hit``
payloads in the other service tests cannot cover (final review C1 / I8).
"""

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from factories import fact
from ircb import service as service_mod
from ircb.domain.models import (
    CalcSpec,
    Chunk,
    ClaimOut,
    Conflict,
    GeneratorOutput,
    RewriteResult,
)
from ircb.ingestion.pipeline import run_embed
from ircb.llm.client import Usage
from ircb.retrieval.embed import Embedder
from ircb.service import AnswerService
from ircb.settings import Settings
from ircb.storage import artefacts
from ircb.storage.artefacts import Manifest
from pydantic import BaseModel

DIM = 16
KPI_TEXT = "Tổng tài sản: 1.192 nghìn tỷ đồng, tăng 21,8% so với năm trước"


class HashBackend:
    def __init__(self, *_: Any) -> None:
        pass

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            h = hashlib.sha256(t.encode("utf-8")).digest()
            out.append([h[i % 32] / 255.0 + 0.01 for i in range(DIM)])
        return out


def _chunk(chunk_id: str, printed: int, content_type: str, text: str, **kw: Any) -> Chunk:
    base: dict[str, Any] = {
        "chunk_id": chunk_id,
        "doc_id": "tcb-ar-2025",
        "pdf_page": printed // 2 + 1,
        "half": "R",
        "printed_pages": [printed],
        "chapter": None,
        "statement": None,
        "note_no": None,
        "content_type": content_type,
        "unit": None,
        "text": text,
        "fact_ids": [],
        "bbox": [0.0, 0.0, 10.0, 10.0],
    }
    base.update(kw)
    return Chunk(**base)


def _money(fid: str, value: str, period: str, col: str) -> Any:
    v = Decimal(value)
    return fact(
        fact_id=fid,
        label="Tổng tài sản",
        label_norm="tong tai san",
        value=v,
        unit="triệu đồng",
        value_vnd=v * 10**6,
        period=period,
        col_path=col,
        raw=f"{int(v):,}".replace(",", "."),
        printed_pages=[297],
        pdf_page=149,
        statement="B02/TCTD-HN",
        table_title="Báo cáo tình hình tài chính hợp nhất",
    )


def build_index(d: Path) -> Path:
    kpi_fact = fact(
        fact_id="p3R_k01",
        label="Tổng tài sản",
        label_norm="tong tai san",
        value=Decimal("1192"),
        unit="nghìn tỷ đồng",
        raw="1.192",
        source="kpi",
        printed_pages=[5],
        pdf_page=3,
    )
    facts = [
        kpi_fact,
        _money("p149R_t02_r20_c0", "1192344137", "2025-12-31", "31/12/2025"),
        _money("p149R_t02_r20_c1", "978800000", "2024-12-31", "31/12/2024"),
    ]
    chunks = [
        _chunk("p3R_k", 5, "kpi", KPI_TEXT, fact_ids=["p3R_k01"]),
        _chunk("p10R_p01", 19, "prose", "Ngân hàng mở rộng dịch vụ số cho khách hàng cá nhân."),
        _chunk(
            "p149R_t02",
            297,
            "table",
            "Báo cáo tình hình tài chính hợp nhất\nTổng tài sản 1.192.344.137 978.800.000",
            unit="triệu đồng",
            statement="B02/TCTD-HN",
            fact_ids=["p149R_t02_r20_c0", "p149R_t02_r20_c1"],
        ),
    ]
    artefacts.write_chunks(d, chunks)
    artefacts.write_facts(d, facts)
    artefacts.write_glossary(d, {"entries": [], "extra": {}})
    run_embed(d, Embedder(HashBackend(), d.parent / "build_cache", "openai/text-embedding-3-large", DIM))
    artefacts.write_manifest(
        d,
        Manifest(
            index_version="e2e-v1",
            doc_id="tcb-ar-2025",
            pdf_sha256="0",
            embed_provider="openai",
            embed_model="openai/text-embedding-3-large",
            embed_dimensions=DIM,
            tokenizer_version="t1",
            periods_seen=["2024", "2025"],
            n_chunks=len(chunks),
            n_facts=len(facts),
            created_at="2026-01-01T00:00:00Z",
        ),
    )
    return d


REWRITE = RewriteResult(
    standalone_query="Tổng tài sản năm 2025 là bao nhiêu và tăng bao nhiêu so với năm 2024?",
    metrics=["tổng tài sản"],
    periods=["2025", "2024"],
    entity=None,
    topic=None,
    needs_comparison=True,
    needs_calc=True,
    is_forecast=False,
)
GENERATED = GeneratorOutput(
    status="answered",
    claims=[
        ClaimOut(
            text="Tổng tài sản đạt 1.192 nghìn tỷ đồng.",
            sources=["chunk:p3R_k"],
            evidence="Tổng tài sản: 1.192 nghìn tỷ đồng",
        ),
        ClaimOut(
            text="Tổng tài sản hợp nhất {c1} so với cuối năm trước.",
            sources=["fact:p149R_t02_r20_c0", "fact:p149R_t02_r20_c1"],
            evidence="",
        ),
    ],
    calcs=[
        CalcSpec(id="c1", op="growth", a="fact:p149R_t02_r20_c0", b="fact:p149R_t02_r20_c1", to_unit=None)
    ],
    conflict=Conflict(kind=None, note=""),
    need_fact=None,
)


class ScriptedLLM:
    def __init__(self, *_: Any) -> None:
        self.user_messages: list[str] = []

    def complete_json(
        self, model: str, messages: list[dict[str, Any]], schema: type[BaseModel]
    ) -> tuple[BaseModel, Usage]:
        self.user_messages.append(messages[-1]["content"])
        out: BaseModel = REWRITE if schema is RewriteResult else GENERATED
        return out, Usage(10, 5, Decimal("0.001"))


@pytest.fixture
def svc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    build_index(tmp_path / "index")
    monkeypatch.setattr(service_mod, "LiteLLMEmbedBackend", HashBackend)
    monkeypatch.setattr(service_mod, "LLMClient", ScriptedLLM)
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        llm_model="big",
        llm_model_small="small",
        embed_dimensions=DIM,
        index_dir=tmp_path / "index",
        qdrant_path=str(tmp_path / "var" / "qdrant"),
        database_url=f"sqlite:///{(tmp_path / 'var' / 'app.db').as_posix()}",
        trace_dir=tmp_path / "traces",
        embed_cache_dir=tmp_path / "var" / "embed_cache",
        page_cache_dir=tmp_path / "var" / "page_cache",
        qdrant_url=None,
    )
    s = AnswerService.from_settings(settings)  # auto-load: ensure_loaded into embedded Qdrant + SQLite
    yield s
    s.deps.store.close()  # type: ignore[attr-defined]


def test_ask_end_to_end_on_real_storage(svc: Any) -> None:
    a = svc.ask("Tổng tài sản năm 2025 là bao nhiêu, tăng bao nhiêu so với 2024?")
    assert a.status == "answered", a.text
    assert a.text == (
        "Tổng tài sản đạt 1.192 nghìn tỷ đồng. [tr. 5]\n"
        "Tổng tài sản hợp nhất tăng 21,82% so với cuối năm trước. [tr. 297]"
    )
    assert [c.label for c in a.citations] == ["[tr. 5]", "[tr. 297]"]
    assert [(c.ok, c.failed_rule) for c in a.claims] == [(True, None), (True, None)]
    assert a.claims[0].text == "Tổng tài sản đạt 1.192 nghìn tỷ đồng."
    assert a.calcs[0].ok and a.calcs[0].operand_fact_ids == ["p149R_t02_r20_c0", "p149R_t02_r20_c1"]

    # the generator saw chunks rebuilt from Qdrant payloads and facts read back from SQLite
    gen_user = svc.client.user_messages[-1]
    assert "[chunk:p3R_k] (tr. 5) " + KPI_TEXT in gen_user
    assert "[fact:p149R_t02_r20_c0]" in gen_user and "1.192.344.137 triệu đồng" in gen_user

    (trace_file,) = list(svc.trace_dir.glob("*.jsonl"))
    lines = [json.loads(x) for x in trace_file.read_text(encoding="utf-8").splitlines()]
    rec = next(x for x in lines if x["trace_id"] == a.trace_id)["records"]
    assert rec["status"] == "answered" and rec["gate"]["passed"] is True
    assert "p3R_k" in rec["retrieval"]["chunks"]
    assert set(rec["retrieval"]["facts"]) >= {"p149R_t02_r20_c0", "p149R_t02_r20_c1"}
    assert [v["failed_rule"] for v in rec["verifier"]] == [None, None]
