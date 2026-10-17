"""BM25 sparse encoding (IDF is applied by Qdrant via modifier=IDF)."""

from collections import Counter
from dataclasses import dataclass

from ircb.retrieval.tokenize_vi import term_id


@dataclass
class SparseVec:
    indices: list[int]
    values: list[float]


def encode_doc(tokens: list[str], avg_len: float, k1: float = 1.2, b: float = 0.75) -> SparseVec:
    counts = Counter(term_id(t) for t in tokens)
    n = len(tokens)
    norm = k1 * (1 - b + b * n / avg_len) if avg_len > 0 else k1
    idx = sorted(counts)
    return SparseVec(idx, [counts[i] * (k1 + 1) / (counts[i] + norm) for i in idx])


def encode_query(tokens: list[str]) -> SparseVec:
    idx = sorted({term_id(t) for t in tokens})
    return SparseVec(idx, [1.0] * len(idx))
