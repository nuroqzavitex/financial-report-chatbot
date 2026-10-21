"""Shippable index artefacts (spec §4.3): JSONL/JSON/Parquet files under ``index/``.

Chunks and facts are written with ``model_dump(mode="json")`` (Decimal values stay exact strings) and
read back as plain dicts; loaders validate them into domain models where they need to.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import BaseModel

from ircb.domain.models import Chunk, Fact, PageInfo

CHUNKS = "chunks.jsonl"
FACTS = "facts.jsonl"
GLOSSARY = "glossary.json"
PAGE_MAP = "page_map.json"
VECTORS = "vectors.parquet"
MANIFEST = "manifest.json"
REPORT = "ingest_report.json"


class Manifest(BaseModel):
    index_version: str
    doc_id: str
    pdf_sha256: str
    embed_provider: str
    embed_model: str
    embed_dimensions: int
    tokenizer_version: str
    periods_seen: list[str]
    # years strictly inside a printed range ("2026–2030" -> 2027..2029); [] in older manifests
    periods_in_ranges: list[str] = []
    n_chunks: int
    n_facts: int
    created_at: str


@dataclass
class VectorRecord:
    id: str
    kind: Literal["chunk", "fact"]
    dense: list[float]
    sparse_indices: list[int]
    sparse_values: list[float]


# ---------------------------------------------------------------- generic


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- typed artefacts


def write_chunks(out_dir: Path, chunks: list[Chunk]) -> None:
    write_jsonl(out_dir / CHUNKS, (c.model_dump(mode="json") for c in chunks))


def read_chunks(out_dir: Path) -> list[dict[str, Any]]:
    return read_jsonl(out_dir / CHUNKS)


def write_facts(out_dir: Path, facts: list[Fact]) -> None:
    write_jsonl(out_dir / FACTS, (f.model_dump(mode="json") for f in facts))


def read_facts(out_dir: Path) -> list[dict[str, Any]]:
    return read_jsonl(out_dir / FACTS)


def write_glossary(out_dir: Path, glossary: dict[str, Any]) -> None:
    write_json(out_dir / GLOSSARY, glossary)


def read_glossary(out_dir: Path) -> dict[str, Any]:
    data: dict[str, Any] = read_json(out_dir / GLOSSARY)
    return data


def write_page_map(out_dir: Path, pages: list[PageInfo]) -> None:
    write_json(out_dir / PAGE_MAP, [p.model_dump(mode="json") for p in pages])


def read_page_map(out_dir: Path) -> list[PageInfo]:
    return [PageInfo.model_validate(p) for p in read_json(out_dir / PAGE_MAP)]


def write_manifest(out_dir: Path, manifest: Manifest) -> None:
    write_json(out_dir / MANIFEST, manifest.model_dump(mode="json"))


def read_manifest(out_dir: Path) -> Manifest:
    return Manifest.model_validate(read_json(out_dir / MANIFEST))


def write_report(out_dir: Path, report: dict[str, Any]) -> None:
    write_json(out_dir / REPORT, report)


def read_report(out_dir: Path) -> dict[str, Any]:
    data: dict[str, Any] = read_json(out_dir / REPORT)
    return data


# ---------------------------------------------------------------- vectors


def _schema(dims: int) -> pa.Schema:
    return pa.schema(
        [
            ("id", pa.string()),
            ("kind", pa.string()),
            ("dense", pa.list_(pa.float32(), dims)),
            ("sparse_indices", pa.list_(pa.uint32())),
            ("sparse_values", pa.list_(pa.float32())),
        ]
    )


def write_vectors(out_dir: Path, records: list[VectorRecord]) -> None:
    dims = len(records[0].dense) if records else 0
    if any(len(r.dense) != dims for r in records):
        raise ValueError("dense vectors differ in dimension")
    table = pa.table(
        {
            "id": [r.id for r in records],
            "kind": [r.kind for r in records],
            "dense": [r.dense for r in records],
            "sparse_indices": [r.sparse_indices for r in records],
            "sparse_values": [r.sparse_values for r in records],
        },
        schema=_schema(dims),
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out_dir / VECTORS)


def read_vectors(out_dir: Path) -> list[VectorRecord]:
    rows = pq.read_table(out_dir / VECTORS).to_pylist()
    return [
        VectorRecord(
            r["id"], r["kind"], list(r["dense"]), list(r["sparse_indices"]), list(r["sparse_values"])
        )
        for r in rows
    ]
