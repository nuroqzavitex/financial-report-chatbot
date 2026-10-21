def test_report_pdf_is_served_inline(client):
    r = client.get("/v1/report.pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content[:5] == b"%PDF-"
    assert r.headers["content-disposition"].startswith("inline")


def test_report_pdf_missing_is_503(client_no_pdf):
    r = client_no_pdf.get("/v1/report.pdf")
    assert r.status_code == 503 and r.json()["code"] == "pdf_missing"
