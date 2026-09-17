"""Minimal OpenAI-compatible chat client. Works with both OpenAI and OpenRouter."""

from __future__ import annotations

from typing import Any

import httpx

from djin.config import Settings, get_settings


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.llm_api_key:
            raise LLMError(
                f"No API key for provider '{self.settings.llm_provider}'."
                " Set it in .env and restart."
            )

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.settings.llm_api_key}",
            "Content-Type": "application/json",
        }
        if self.settings.llm_provider == "openrouter":
            # Optional attribution headers used by OpenRouter's dashboard.
            headers["HTTP-Referer"] = "http://localhost"
            headers["X-Title"] = "Djin"
        return headers

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        """Return the assistant message from one completion call."""
        body: dict[str, Any] = {
            "model": self.settings.llm_model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        url = f"{self.settings.llm_base_url}/chat/completions"
        try:
            response = httpx.post(
                url, json=body, headers=self._headers(), timeout=self.settings.llm_timeout
            )
        except httpx.ProxyError as exc:
            raise LLMError(
                f"A network proxy blocked the request to {self.settings.llm_base_url} ({exc})."
                " This is a network restriction, not an API key problem."
                " Try another provider or a network without the proxy."
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"Could not reach the LLM provider: {exc}") from exc

        if response.status_code >= 400:
            raise LLMError(
                f"LLM request failed ({response.status_code}): {response.text[:500]}"
            )

        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise LLMError(f"LLM returned no choices: {str(data)[:500]}")

        message = choices[0].get("message") or {}
        return {
            "role": "assistant",
            "content": message.get("content") or "",
            "tool_calls": message.get("tool_calls") or [],
        }
