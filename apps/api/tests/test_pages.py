def test_page_png_with_chunk_highlight(client):
    r = client.get("/v1/pages/2/image", params={"source": "chunk:c1", "evidence": "Tổng tài sản 1.192"})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert r.headers["cache-control"] == "no-cache" and r.headers["etag"]
    again = client.get(
        "/v1/pages/2/image",
        params={"source": "chunk:c1", "evidence": "Tổng tài sản 1.192"},
        headers={"If-None-Match": r.headers["etag"]},
    )
    assert again.status_code == 304 and again.content == b""


def test_page_bounds_and_unknown_source(client):
    assert client.get("/v1/pages/0/image").json()["code"] == "page_not_found"
    assert client.get("/v1/pages/999/image").status_code == 404
    ok = client.get("/v1/pages/2/image", params={"source": "fact:missing", "evidence": 'a"b\nc'})
    assert ok.status_code == 200
    assert client.get("/v1/pages/2/image", params={"source": "garbage"}).status_code == 200


def test_rect_only_used_when_source_covers_page(client):
    hit = client.get("/v1/pages/2/image", params={"source": "chunk:c1"}).content
    miss = client.get("/v1/pages/3/image", params={"source": "chunk:c1"}).content
    plain = client.get("/v1/pages/2/image").content
    assert hit != plain  # c1 covers page 2: rect highlighted
    assert miss == client.get("/v1/pages/3/image").content  # c1 does not cover page 3


def test_evidence_too_long_is_422(client):
    assert client.get("/v1/pages/2/image", params={"evidence": "x" * 501}).status_code == 422


def test_pdf_missing_is_503(client_no_pdf):
    r = client_no_pdf.get("/v1/pages/2/image")
    assert r.status_code == 503 and r.json()["code"] == "pdf_missing"
