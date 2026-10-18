def test_traces_dev_only(client, client_prod, trace_file):
    assert client.get(f"/v1/traces/{trace_file}").json()["trace_id"] == trace_file
    assert client.get("/v1/traces/none").json()["code"] == "trace_not_found"
    assert client_prod.get(f"/v1/traces/{trace_file}").status_code == 404
    assert client_prod.get(f"/v1/traces/{trace_file}").json()["code"] == "not_found"
