"""LLM providers for agents. Configured by LLM_PROVIDER: anthropic (hosted) | ollama | fake.

Agents only ever get text back from here. Providers have no tools: they cannot fetch URLs,
touch the database or call the API.
"""

from functools import lru_cache
from typing import Protocol

import anthropic
import httpx

from blackmamba.core.config import Settings, get_settings


class LLMError(RuntimeError):
    pass


class LLMRefusalError(LLMError):
    pass


class LLMClient(Protocol):
    @property
    def model_name(self) -> str: ...

    async def complete(self, system: str, prompt: str) -> str: ...


class AnthropicLLM:
    """Claude via the official SDK, with server-side refusal fallback enabled."""

    def __init__(self, settings: Settings) -> None:
        if settings.llm_api_key is None:
            raise LLMError("LLM_API_KEY is required for LLM_PROVIDER=anthropic")
        self._client = anthropic.AsyncAnthropic(
            api_key=settings.llm_api_key.get_secret_value(),
            timeout=float(settings.llm_timeout_seconds),
            max_retries=2,
        )
        self._model = settings.llm_model
        self._served_by = settings.llm_model

    @property
    def model_name(self) -> str:
        return self._served_by

    async def complete(self, system: str, prompt: str) -> str:
        try:
            response = await self._client.beta.messages.create(
                model=self._model,
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_config={"effort": "medium"},
                # On a safety decline the API retries on a fallback model in the same call.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.RateLimitError as exc:
            raise LLMError("LLM provider rate limit reached, try again shortly") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"LLM provider error ({exc.status_code})") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("cannot reach the LLM provider") from exc
        if response.stop_reason == "refusal":
            raise LLMRefusalError("the model declined this request")
        self._served_by = response.model
        text = "".join(block.text for block in response.content if block.type == "text")
        if not text.strip():
            raise LLMError("the model returned no text")
        return text.strip()


class OllamaLLM:
    """Self-hosted models via Ollama's /api/chat (no data leaves your infrastructure)."""

    def __init__(self, settings: Settings) -> None:
        self._base = (settings.llm_base_url or "http://localhost:11434").rstrip("/")
        self._model = settings.llm_model
        self._timeout = settings.llm_timeout_seconds

    @property
    def model_name(self) -> str:
        return f"ollama:{self._model}"

    async def complete(self, system: str, prompt: str) -> str:
        payload = {
            "model": self._model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(f"{self._base}/api/chat", json=payload)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMError(f"Ollama request failed: {exc}") from exc
        text = str(data.get("message", {}).get("content", "")).strip()
        if not text:
            raise LLMError("the model returned no text")
        return text


class FakeLLM:
    """Deterministic offline provider for tests and demos."""

    def __init__(self, reply: str | None = None) -> None:
        self.reply = reply
        self.calls: list[tuple[str, str]] = []

    @property
    def model_name(self) -> str:
        return "fake"

    async def complete(self, system: str, prompt: str) -> str:
        self.calls.append((system, prompt))
        if self.reply is not None:
            return self.reply
        first_line = prompt.strip().splitlines()[0] if prompt.strip() else ""
        return f"[offline draft] {first_line[:200]}"


@lru_cache
def get_llm() -> LLMClient:
    settings = get_settings()
    if settings.llm_provider == "anthropic":
        return AnthropicLLM(settings)
    if settings.llm_provider == "ollama":
        return OllamaLLM(settings)
    return FakeLLM()
