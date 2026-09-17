"""Minimal OpenAI-compatible chat client. Works with both OpenAI and OpenRouter."""

from __future__ import annotations

import json
from collections.abc import Iterator
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

    def _body(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float,
        stream: bool,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.settings.llm_model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if stream:
            body["stream"] = True
        return body

    def _transport_error(self, exc: httpx.HTTPError) -> LLMError:
        if isinstance(exc, httpx.ProxyError):
            return LLMError(
                f"A network proxy blocked the request to {self.settings.llm_base_url} ({exc})."
                " This is a network restriction, not an API key problem."
                " Try another provider or a network without the proxy."
            )
        return LLMError(f"Could not reach the LLM provider: {exc}")

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        """Return the assistant message from one completion call."""
        url = f"{self.settings.llm_base_url}/chat/completions"
        try:
            response = httpx.post(
                url,
                json=self._body(messages, tools, temperature, stream=False),
                headers=self._headers(),
                timeout=self.settings.llm_timeout,
            )
        except httpx.HTTPError as exc:
            raise self._transport_error(exc) from exc

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

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
    ) -> Iterator[dict[str, Any]]:
        """Yield {'type': 'delta'} events, then one {'type': 'message'} with the full result."""
        url = f"{self.settings.llm_base_url}/chat/completions"
        content: list[str] = []
        partial_calls: dict[int, dict[str, Any]] = {}

        try:
            with httpx.stream(
                "POST",
                url,
                json=self._body(messages, tools, temperature, stream=True),
                headers=self._headers(),
                timeout=self.settings.llm_timeout,
            ) as response:
                if response.status_code >= 400:
                    response.read()
                    raise LLMError(
                        f"LLM request failed ({response.status_code}): {response.text[:500]}"
                    )

                for line in response.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue

                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}

                    if piece := delta.get("content"):
                        content.append(piece)
                        yield {"type": "delta", "content": piece}

                    for fragment in delta.get("tool_calls") or []:
                        _merge_tool_call(partial_calls, fragment)
        except httpx.HTTPError as exc:
            raise self._transport_error(exc) from exc

        yield {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": "".join(content),
                "tool_calls": [partial_calls[key] for key in sorted(partial_calls)],
            },
        }


def _merge_tool_call(calls: dict[int, dict[str, Any]], fragment: dict[str, Any]) -> None:
    """Tool calls arrive split across chunks and keyed by index."""
    slot = calls.setdefault(
        fragment.get("index", 0),
        {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
    )
    if identifier := fragment.get("id"):
        slot["id"] = identifier
    function = fragment.get("function") or {}
    if name := function.get("name"):
        slot["function"]["name"] += name
    if arguments := function.get("arguments"):
        slot["function"]["arguments"] += arguments
