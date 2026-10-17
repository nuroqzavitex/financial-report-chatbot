"""Synthetic mini index, fake embedder and fixed queries for the cross-mode equality tests."""

import hashlib
from pathlib import Path
from typing import Any

from factories import fact
from ircb.domain.models import Chunk, RewriteResult
from ircb.storage import artefacts
from ircb.storage.artefacts import Manifest, VectorRecord

MINI_DOC = "it-mini-doc"  # never the real doc_id
DIM = 32
N = 30
CONTENT_TYPES = ("prose", "table", "glossary")


def hashed_vector(seed: str, dim: int = DIM) -> list[float]:
    """Deterministic, distinct-per-seed vector of ``dim`` floats in (-1, 1)."""
    out: list[float] = []
    counter = 0
    while len(out) < dim:
        digest = hashlib.sha256(f"{seed}#{counter}".encode()).digest()
        out.extend(b / 127.5 - 1.0 for b in digest)
        counter += 1
    return out[:dim]


class HashEmbedder:
    """Deterministic fake embedder: same text -> same vector."""

    def __init__(self, dim: int = DIM) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [hashed_vector(f"query:{t}", self.dim) for t in texts]


def build_mini_index(d: Path, version: str, tag: str) -> Path:
    chunks = [
        Chunk(
            chunk_id=f"{tag}-c{i}",
            doc_id=MINI_DOC,
            pdf_page=1,
            half="L",
            printed_pages=[i + 1],
            chapter="Ch1",
            statement=None,
            note_no=None,
            content_type=CONTENT_TYPES[i % 3],  # type: ignore[arg-type]
            unit=None,
            text=f"đoạn {i} từ khóa{i}",
            fact_ids=[],
            bbox=[0.0, 0.0, 1.0, 1.0],
        )
        for i in range(N)
    ]
    facts = [
        fact(fact_id=f"{tag}-f{i}", doc_id=MINI_DOC, label=f"chỉ tiêu {i}", period="2025") for i in range(N)
    ]
    artefacts.write_chunks(d, chunks)
    artefacts.write_facts(d, facts)
    recs = [
        VectorRecord(c.chunk_id, "chunk", hashed_vector(f"chunk{i}"), [i, i + 100], [1.0 + i / 100, 0.5])
        for i, c in enumerate(chunks)
    ]
    recs += [
        VectorRecord(f.fact_id, "fact", hashed_vector(f"fact{i}"), [i, i + 200], [2.0 + i / 100, 0.5])
        for i, f in enumerate(facts)
    ]
    artefacts.write_vectors(d, recs)
    artefacts.write_manifest(
        d,
        Manifest(
            index_version=version,
            doc_id=MINI_DOC,
            pdf_sha256="0",
            embed_provider="openai",
            embed_model="openai/text-embedding-3-large",
            embed_dimensions=DIM,
            tokenizer_version="t1",
            periods_seen=["2025"],
            n_chunks=N,
            n_facts=N,
            created_at="2026-01-01T00:00:00Z",
        ),
    )
    return d


def rw_for(q: str, **kw: Any) -> RewriteResult:
    base: dict[str, Any] = {
        "standalone_query": q,
        "metrics": [],
        "periods": [],
        "entity": None,
        "needs_comparison": False,
        "needs_calc": False,
        "is_forecast": False,
    }
    base.update(kw)
    return RewriteResult(**base)


QUERIES = [
    rw_for("đoạn 3"),
    rw_for("đoạn 12 bảng", needs_calc=True),
    rw_for("thuật ngữ viết tắt là gì", metrics=["chỉ tiêu 4"], periods=["2025"]),
    rw_for("so sánh", needs_comparison=True, metrics=["chỉ tiêu 7", "chỉ tiêu 9"], periods=["2025", "2024"]),
    rw_for("câu hỏi không liên quan"),
]
