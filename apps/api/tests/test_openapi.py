import json

from ircb_api.openapi import main as main_openapi


def test_openapi_export_has_chat_and_pages(tmp_path):
    out = tmp_path / "o.json"
    main_openapi([str(out)])
    text = out.read_text(encoding="utf-8")
    spec = json.loads(text)
    assert {"/v1/chat", "/v1/pages/{printed}/image", "/v1/facts", "/v1/health"} <= spec["paths"].keys()
    assert {"ChatAnswerOut", "StatusOut", "ErrorOut"} <= spec["components"]["schemas"].keys()
    assert (
        text.endswith("\n") and text == json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )
