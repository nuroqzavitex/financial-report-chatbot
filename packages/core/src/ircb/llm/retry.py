"""Shared retry predicate for transport-level LLM/embedding errors."""


def retryable(exc: Exception) -> bool:
    """True for timeouts, rate limits (429) and 5xx/408 responses."""
    name = type(exc).__name__.lower()
    if isinstance(exc, TimeoutError) or "timeout" in name or "ratelimit" in name:
        return True
    code = getattr(exc, "status_code", None)
    return isinstance(code, int) and (code in (408, 429) or code >= 500)
