"""Any server that speaks the OpenAI Chat Completions protocol.

Covers local models (LM Studio, Ollama, llama.cpp server, vLLM) and hosted
providers (OpenAI, Groq, OpenRouter, ...) with one small adapter.
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from aion.ai.providers.base import LLMError, LLMResponse


class OpenAICompatProvider:
    def __init__(self, base_url: str, model: str, api_key: str = "", timeout: float = 300.0,
                 max_output_tokens: int = 4096):
        if not base_url or not model:
            raise ValueError("AION_OPENAI_BASE_URL and AION_OPENAI_MODEL must both be set")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        # Local models have small context windows; a huge output budget would crowd out the prompt.
        self.max_output_tokens = max_output_tokens
        self.name = f"openai_compat:{model}"
        # Not every server supports json_schema; degrade to json_object, then to prompt-only.
        self._format_modes = ["json_schema", "json_object", "none"]

    def complete_json(self, system: str, user: str, schema: dict[str, Any], schema_name: str,
                      max_tokens: int) -> LLMResponse:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        system_with_schema = (f"{system}\n\nRespond with a single JSON object matching this JSON schema:\n"
                              f"{json.dumps(schema)}")
        last_error = ""
        for mode in list(self._format_modes):
            body: dict[str, Any] = {
                "model": self.model,
                "messages": [{"role": "system", "content": system_with_schema}, {"role": "user", "content": user}],
                "max_tokens": min(max_tokens, self.max_output_tokens),
                "temperature": 0.1,
            }
            if mode == "json_schema":
                body["response_format"] = {"type": "json_schema",
                                           "json_schema": {"name": schema_name, "schema": schema, "strict": True}}
            elif mode == "json_object":
                body["response_format"] = {"type": "json_object"}
            try:
                r = httpx.post(f"{self.base_url}/chat/completions", json=body, headers=headers, timeout=self.timeout)
            except httpx.HTTPError as exc:
                raise LLMError(f"Could not reach LLM server at {self.base_url}: {exc}") from exc
            if r.status_code == 400 and mode != "none":
                last_error = r.text[:500]
                self._format_modes.remove(mode)  # remember: this server lacks that mode
                continue
            if r.status_code >= 400:
                raise LLMError(f"LLM server returned {r.status_code}: {r.text[:500]}")
            data = r.json()
            choice = data["choices"][0]
            if choice.get("finish_reason") == "length":
                raise LLMError("The model ran out of output tokens before finishing")
            usage = data.get("usage") or {}
            return LLMResponse(
                text=choice["message"].get("content") or "",
                usage={"input_tokens": usage.get("prompt_tokens", 0),
                       "output_tokens": usage.get("completion_tokens", 0), "model": self.model},
            )
        raise LLMError(f"LLM server rejected every response format: {last_error}")
