"""Docker-free sanity checks of the synthetic fixture: no tied scores that could flip tie-breaking."""

import math
import uuid
from pathlib import Path

from ircb.storage import artefacts
from modes_support import QUERIES, HashEmbedder, build_mini_index

GAP = 1e-6


def _cos(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True)) / (math.hypot(*a) * math.hypot(*b))


def test_synthetic_vectors_distinct_and_scores_untied(tmp_path: Path) -> None:
    d = build_mini_index(tmp_path, "v", uuid.uuid4().hex[:8])
    recs = artefacts.read_vectors(d)
    dense = [tuple(r.dense) for r in recs]
    assert len(set(dense)) == len(dense)
    assert len({(tuple(r.sparse_indices), tuple(r.sparse_values)) for r in recs}) == len(recs)
    embedder = HashEmbedder()
    for kind in ("chunk", "fact"):
        vecs = [r.dense for r in recs if r.kind == kind]
        for rw in QUERIES:
            for q in embedder.embed([rw.standalone_query, *rw.metrics]):
                scores = sorted((_cos(q, v) for v in vecs), reverse=True)
                assert all(a - b > GAP for a, b in zip(scores, scores[1:], strict=False)), rw
