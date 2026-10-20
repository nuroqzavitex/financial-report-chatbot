import json
from decimal import Decimal
from typing import Any

import litellm
import pytest
from ircb.domain.models import GeneratorOutput
from ircb.llm import client
from ircb.llm.client import LLMClient, LLMError
from ircb.settings import Settings
from pydantic import BaseModel


@pytest.fixture
def settings() -> Settings:
    return Settings(llm_model="openai/m", _env_file=None)  # type: ignore[call-arg]


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client, "_sleep", lambda s: None)


def valid_generator_json() -> str:
    return json.dumps(
        {
            "status": "answered",
            "claims": [],
            "calcs": [],
            "conflict": {"kind": None, "note": ""},
            "need_fact": None,
        }
    )


def make_resp(content: str, pt: int = 10, ct: int = 5) -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": pt, "completion_tokens": ct},
    }


def always_raise(exc: Exception):
    def fn(**kwargs: Any) -> Any:
        raise exc

    return fn


def sequence(items: list[str], calls: list[dict[str, Any]] | None = None):
    it = iter(items)

    def fn(**kwargs: Any) -> Any:
        if calls is not None:
            calls.append(kwargs)
        return make_resp(next(it))

    return fn


def test_complete_json_retries_then_raises_llm_error(settings: Settings) -> None:
    c = LLMClient(
        settings, completion_fn=always_raise(litellm.Timeout("t", model="m", llm_provider="openai"))
    )
    with pytest.raises(LLMError):
        c.complete_json("openai/m", [], GeneratorOutput)
    assert c._attempts == 3


def test_non_retryable_error_fails_fast(settings: Settings) -> None:
    c = LLMClient(settings, completion_fn=always_raise(ValueError("boom")))
    with pytest.raises(LLMError):
        c.complete_json("openai/m", [], GeneratorOutput)
    assert c._attempts == 1


def test_schema_retry_then_ok(settings: Settings) -> None:
    calls: list[dict[str, Any]] = []
    c = LLMClient(settings, completion_fn=sequence(['{"bad":1}', valid_generator_json()], calls))
    out, usage = c.complete_json("openai/m", [{"role": "user", "content": "q"}], GeneratorOutput)
    assert isinstance(out, GeneratorOutput) and out.status == "answered"
    assert c._attempts == 2
    assert usage.prompt_tokens == 20 and usage.completion_tokens == 10
    retry_msg = calls[1]["messages"][-1]
    assert retry_msg["role"] == "user" and "validation" in retry_msg["content"].lower()


def test_schema_error_twice_raises(settings: Settings) -> None:
    c = LLMClient(settings, completion_fn=sequence(['{"bad":1}', "not json"]))
    with pytest.raises(LLMError):
        c.complete_json("openai/m", [], GeneratorOutput)
    assert c._attempts == 2


@pytest.mark.parametrize("fence", ["```json\n{}\n```", "```\n{}\n```", "\n```JSON\n{}```\n"])
def test_reply_wrapped_in_a_markdown_fence_is_unwrapped(settings: Settings, fence: str) -> None:
    c = LLMClient(settings, completion_fn=sequence([fence.replace("{}", valid_generator_json())]))
    out, _ = c.complete_json("ollama_chat/gemma4:31b", [], GeneratorOutput)
    assert isinstance(out, GeneratorOutput) and c._attempts == 1


def test_fence_with_text_around_it_still_fails_validation(settings: Settings) -> None:
    text = f"Here it is:\n```json\n{valid_generator_json()}\n```"
    c = LLMClient(settings, completion_fn=sequence([text, text]))
    with pytest.raises(LLMError):
        c.complete_json("openai/m", [], GeneratorOutput)


def capture_kwargs(settings: Settings, model: str = "openai/m") -> dict[str, Any]:
    calls: list[dict[str, Any]] = []
    c = LLMClient(settings, completion_fn=sequence([valid_generator_json()], calls))
    c.complete_json(model, [], GeneratorOutput)
    return calls[0]


def test_seed_when_no_temperature(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client, "_supports_temperature", lambda m: False)
    kwargs = capture_kwargs(settings)
    assert kwargs["seed"] == 42 and "temperature" not in kwargs


def test_temperature_zero_when_supported(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client, "_supports_temperature", lambda m: True)
    kwargs = capture_kwargs(settings)
    assert kwargs["temperature"] == 0 and "seed" not in kwargs
    assert kwargs["timeout"] == settings.llm_timeout_s == 60


def test_response_format_strict(settings: Settings) -> None:
    rf = capture_kwargs(settings)["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["name"] == "GeneratorOutput" and rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["schema"]["additionalProperties"] is False


def test_non_strict_schema_rejected(settings: Settings) -> None:
    class Loose(BaseModel):
        a: int = 1

    c = LLMClient(settings, completion_fn=sequence(["{}"]))
    with pytest.raises(LLMError, match="strict"):
        c.complete_json("openai/m", [], Loose)
    assert c._attempts == 0


def test_cost_from_prices(settings: Settings) -> None:
    s = settings.model_copy(update={"llm_price_in": 2.0, "llm_price_out": 8.0})
    c = LLMClient(s, completion_fn=sequence([valid_generator_json()]))
    _, usage = c.complete_json("openai/m", [], GeneratorOutput)
    assert usage.cost_usd == Decimal(10) * Decimal(2.0) / 1_000_000 + Decimal(5) * Decimal(8.0) / 1_000_000


def test_cost_falls_back_to_litellm(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(litellm, "completion_cost", lambda completion_response: 0.25)
    c = LLMClient(settings, completion_fn=sequence([valid_generator_json()]))
    _, usage = c.complete_json("openai/m", [], GeneratorOutput)
    assert usage.cost_usd == Decimal("0.25")


def test_cost_zero_when_litellm_raises(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(completion_response: Any) -> float:
        raise RuntimeError("no price")

    monkeypatch.setattr(litellm, "completion_cost", boom)
    c = LLMClient(settings, completion_fn=sequence([valid_generator_json()]))
    _, usage = c.complete_json("openai/m", [], GeneratorOutput)
    assert usage.cost_usd == Decimal(0)


def test_embed_delegates(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    class Fake:
        def __init__(self, s: Settings) -> None: ...

        def embed(self, texts: list[str]) -> list[list[float]]:
            return [[1.0] for _ in texts]

    monkeypatch.setattr(client, "LiteLLMEmbedBackend", Fake)
    assert LLMClient(settings).embed(["a", "b"]) == [[1.0], [1.0]]


@pytest.mark.parametrize(
    "resp",
    [
        {"choices": None, "usage": {"prompt_tokens": 1, "completion_tokens": 1}},
        {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1}},
        {"choices": [{}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}},
        {"choices": [{"message": None}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}},
        {
            "choices": [{"message": {"content": "{}"}}],
            "usage": {"prompt_tokens": "x", "completion_tokens": 1},
        },
        {
            "choices": [{"message": {"content": "{}"}}],
            "usage": {"prompt_tokens": [1], "completion_tokens": 1},
        },
    ],
)
def test_malformed_response_raises_llm_error(settings: Settings, resp: dict[str, Any]) -> None:
    c = LLMClient(settings, completion_fn=lambda **kw: resp)
    with pytest.raises(LLMError):
        c.complete_json("openai/m", [], GeneratorOutput)


def test_cost_uses_decimal_of_str_not_float(settings: Settings) -> None:
    s = settings.model_copy(update={"llm_price_in": 0.15, "llm_price_out": 0.6})
    c = LLMClient(s, completion_fn=sequence([valid_generator_json()]))
    _, usage = c.complete_json("openai/m", [], GeneratorOutput)
    assert (
        usage.cost_usd == Decimal(10) * Decimal("0.15") / 1_000_000 + Decimal(5) * Decimal("0.6") / 1_000_000
    )


def test_litellm_float_cost_drops_binary_noise(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """Real run: litellm summed float prices into 0.017802500000000003 and batch printed every digit."""
    monkeypatch.setattr(litellm, "completion_cost", lambda completion_response: 0.017802500000000003)
    c = LLMClient(settings, completion_fn=sequence([valid_generator_json()]))
    _, usage = c.complete_json("openai/m", [], GeneratorOutput)
    assert usage.cost_usd == Decimal("0.0178025")


def test_ollama_models_get_the_configured_base_and_key(settings: Settings) -> None:
    s = settings.model_copy(
        update={"ollama_api_base": "http://host.docker.internal:11434", "ollama_api_key": "k"}
    )
    kwargs = capture_kwargs(s, model="ollama_chat/gpt-oss:120b-cloud")
    assert kwargs["api_base"] == "http://host.docker.internal:11434" and kwargs["api_key"] == "k"


def test_other_providers_get_no_ollama_base(settings: Settings) -> None:
    kwargs = capture_kwargs(settings)
    assert "api_base" not in kwargs and "api_key" not in kwargs
