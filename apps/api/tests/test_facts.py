def test_fact_search_endpoint(client):
    rows = client.get("/v1/facts", params={"q": "tổng tài sản", "period": "FY2025"}).json()
    assert rows and rows[0]["value"] == "1192344137" and isinstance(rows[0]["value"], str)
    assert rows[0]["unit"] == "triệu đồng" and rows[0]["printed_pages"] == [297]
    assert client.get("/v1/facts", params={"limit": 0}).status_code == 422
    assert client.get("/v1/facts", params={"limit": 201}).status_code == 422
