"""LiteLLM client: strict structured output, retries, cost accounting."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ValidationError

from ircb.llm.retry import retryable
from ircb.retrieval.embed import LiteLLMEmbedBackend
from ircb.settings import Settings

TRANSPORT_RETRIES = 2
_PER_MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int
    completion_tokens: int
    cost_usd: Decimal


class LLMError(Exception):
    pass


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _supports_temperature(model: str) -> bool:
    try:
        import litellm

        params = litellm.get_supported_openai_params(model=model)
    except Exception:
        return True
    if params is None:
        return True
    return "temperature" in params


def _check_strict(node: Any, path: str = "$") -> None:
    if isinstance(node, dict):
        if node.get("type") == "object" or "properties" in node:
            props = node.get("properties", {})
            if node.get("additionalProperties") is not False:
                raise LLMError(f"schema is not strict: additionalProperties != false at {path}")
            if set(node.get("required", [])) != set(props):
                raise LLMError(f"schema is not strict: not all properties required at {path}")
        for k, v in node.items():
            _check_strict(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _check_strict(v, f"{path}[{i}]")


def _response_format(schema: type[BaseModel]) -> dict[str, Any]:
    js = schema.model_json_schema()
    _check_strict(js)
    return {
        "type": "json_schema",
        "json_schema": {"name": schema.__name__, "schema": js, "strict": True},
    }


def _get(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


class LLMClient:
    def __init__(
        self,
        settings: Settings,
        completion_fn: Callable[..., Any] | None = None,
        embedding_fn: Callable[..., Any] | None = None,
    ) -> None:
        self.settings = settings
        self._completion_fn = completion_fn
        self._embedding_fn = embedding_fn
        self._attempts = 0

    def _completion(self) -> Callable[..., Any]:
        if self._completion_fn is None:
            import litellm

            self._completion_fn = litellm.completion
        return self._completion_fn

    def _cost(self, resp: Any, pt: int, ct: int) -> Decimal:
        s = self.settings
        if s.llm_price_in is not None and s.llm_price_out is not None:
            return (
                Decimal(pt) * Decimal(str(s.llm_price_in)) / _PER_MILLION
                + Decimal(ct) * Decimal(str(s.llm_price_out)) / _PER_MILLION
            )
        try:
            import litellm

            # litellm sums float prices; 10 decimals of USD drop the binary noise (…500000000003)
            return Decimal(str(round(litellm.completion_cost(completion_response=resp), 10)))
        except Exception:
            return Decimal(0)

    def _call(self, kwargs: dict[str, Any]) -> Any:
        fn = self._completion()
        for retry in range(TRANSPORT_RETRIES + 1):
            self._attempts += 1
            try:
                return fn(**kwargs)
            except Exception as exc:
                if retry == TRANSPORT_RETRIES or not retryable(exc):
                    raise LLMError(f"LLM call failed: {exc}") from exc
                _sleep(2**retry)
        raise LLMError("unreachable")

    def complete_json(
        self, model: str, messages: list[dict[str, Any]], schema: type[BaseModel]
    ) -> tuple[BaseModel, Usage]:
        self._attempts = 0
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": list(messages),
            "response_format": _response_format(schema),
            "timeout": self.settings.llm_timeout_s,
        }
        if model.startswith(("ollama/", "ollama_chat/")):
            # local Ollama (or ollama.com); a signed-in local Ollama also serves the "*-cloud" models
            kwargs["api_base"] = self.settings.ollama_api_base
            if self.settings.ollama_api_key:
                kwargs["api_key"] = self.settings.ollama_api_key
        if _supports_temperature(model):
            kwargs["temperature"] = 0
        else:
            kwargs["seed"] = self.settings.llm_seed

        pt = ct = 0
        cost = Decimal(0)
        error: Exception | None = None
        for schema_try in range(2):
            resp = self._call(kwargs)
            try:
                usage = _get(resp, "usage")
                rpt = int(_get(usage, "prompt_tokens") or 0)
                rct = int(_get(usage, "completion_tokens") or 0)
                content = _get(_get(_get(resp, "choices")[0], "message"), "content") or ""
            except (TypeError, ValueError, IndexError, KeyError, AttributeError) as exc:
                raise LLMError(f"malformed provider response: {exc!r}") from exc
            if not isinstance(content, str):
                raise LLMError("malformed provider response: content is not a string")
            pt += rpt
            ct += rct
            cost += self._cost(resp, rpt, rct)
            try:
                out = schema.model_validate_json(content)
                return out, Usage(pt, ct, cost)
            except ValidationError as exc:
                error = exc
                if schema_try == 0:
                    kwargs["messages"] = [
                        *messages,
                        {
                            "role": "user",
                            "content": "Your previous reply failed JSON schema validation. "
                            f"Fix it and answer again.\nValidation error: {exc}",
                        },
                    ]
        raise LLMError(f"response failed schema validation: {error}") from error

    def embed(self, texts: list[str]) -> list[list[float]]:
        return LiteLLMEmbedBackend(self.settings).embed(texts)
