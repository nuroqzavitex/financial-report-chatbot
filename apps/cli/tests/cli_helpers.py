import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from ircb.domain.models import Answer, Chunk, Citation, TurnState
from ircb.storage import artefacts
from ircb.storage.artefacts import Manifest, VectorRecord


def write_input(tmp_path: Path, rows: list[Any], jsonl: bool = False) -> Path:
    p = tmp_path / ("in.jsonl" if jsonl else "in.json")
    if jsonl:
        p.write_text("\n".join(r if isinstance(r, str) else json.dumps(r) for r in rows), encoding="utf-8")
    else:
        p.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return p


def read_jsonl(p: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def make_answer(status: str = "answered", text: str = "Tổng tài sản 1.192 nghìn tỷ đồng [tr. 5]") -> Answer:
    cits = [Citation.for_pages([5])] if status == "answered" else []
    return Answer(
        status=status,  # type: ignore[arg-type]
        text=text,
        claims=[],
        calcs=[],
        citations=cits,
        conflict=None,
        state=TurnState(metrics=["tổng tài sản"], periods=["2025"], entity=None),
        trace_id="t1",
        latency_ms={"total": 12},
        cost_usd=Decimal("0.0012"),
    )


class FakeService:
    def __init__(self, status: str = "answered", boom: Exception | None = None) -> None:
        self.status, self.boom = status, boom
        self.prev_states: list[TurnState | None] = []
        self.histories: list[list[tuple[str, str]]] = []
        self.questions: list[str] = []

    def ask(
        self, message: str, prev_state: TurnState | None = None, history: list[tuple[str, str]] | None = None
    ) -> Answer:
        if self.boom is not None and "boom" in message:
            raise self.boom
        self.questions.append(message)
        self.prev_states.append(prev_state)
        self.histories.append(list(history or []))
        return make_answer(self.status)


class Backend:
    def __init__(self, dim: int) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.25] * self.dim for _ in texts]


def build_mini_index(d: Path, dim: int, version: str = "v1") -> Path:
    chunks = [
        Chunk(
            chunk_id=f"c{i}",
            doc_id="tcb-ar-2025",
            pdf_page=1,
            half="L",
            printed_pages=[i + 1],
            chapter=None,
            statement=None,
            note_no=None,
            content_type="prose",
            unit=None,
            text=f"đoạn {i}",
            fact_ids=[],
            bbox=[0.0, 0.0, 1.0, 1.0],
        )
        for i in range(2)
    ]
    artefacts.write_chunks(d, chunks)
    artefacts.write_facts(d, [])
    artefacts.write_glossary(d, {"entries": [], "extra": {}})
    vec = [0.5] * dim
    artefacts.write_vectors(d, [VectorRecord(c.chunk_id, "chunk", vec, [1], [1.0]) for c in chunks])
    artefacts.write_manifest(
        d,
        Manifest(
            index_version=version,
            doc_id="tcb-ar-2025",
            pdf_sha256="0",
            embed_provider="openai",
            embed_model="openai/text-embedding-3-large",
            embed_dimensions=dim,
            tokenizer_version="t1",
            periods_seen=["2025"],
            n_chunks=2,
            n_facts=0,
            created_at="2026-01-01T00:00:00Z",
        ),
    )
    return d
