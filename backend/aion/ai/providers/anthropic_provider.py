"""Claude via the official Anthropic Python SDK."""
from __future__ import annotations

from typing import Any

import anthropic

from aion.ai.providers.base import LLMError, LLMResponse


class AnthropicProvider:
    def __init__(self, model: str, effort: str = "high", timeout: float = 300.0, api_key: str | None = None):
        self.model = model
        self.effort = effort
        self.name = f"anthropic:{model}"
        # The key comes from the dashboard (decrypted at runtime) or, if None, the SDK resolves
        # credentials itself (ANTHROPIC_API_KEY). Never hard-coded.
        self.client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=2) if api_key \
            else anthropic.Anthropic(timeout=timeout, max_retries=2)

    def complete_json(self, system: str, user: str, schema: dict[str, Any], schema_name: str,
                      max_tokens: int) -> LLMResponse:
        try:
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                thinking={"type": "adaptive"},
                # Structured outputs: the reply is constrained to our JSON schema.
                output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
                # If a safety classifier declines, the API retries on a fallback model.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.AuthenticationError as exc:
            raise LLMError(f"Anthropic authentication failed - check ANTHROPIC_API_KEY ({exc})") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError(f"Anthropic rate limit hit: {exc}") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Anthropic API error {exc.status_code}: {exc}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError(f"Could not reach the Anthropic API: {exc}") from exc

        if response.stop_reason == "refusal":
            raise LLMError("The model declined this request (stop_reason=refusal)")
        if response.stop_reason == "max_tokens":
            raise LLMError("The model ran out of output tokens before finishing")
        text = "".join(b.text for b in response.content if b.type == "text")
        usage = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "model": response.model,
        }
        return LLMResponse(text=text, usage=usage)
