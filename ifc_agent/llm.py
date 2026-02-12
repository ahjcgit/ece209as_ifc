from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from typing import Any

from .labels import Label


@dataclass(frozen=True)
class LLMResponse:
    text: str
    label: Label


class BaseLLM:
    def __init__(self, name: str, is_external: bool) -> None:
        self.name = name
        self.is_external = is_external

    def generate(self, prompt: str, label: Label) -> LLMResponse:
        raise NotImplementedError


class OllamaLLM(BaseLLM):
    """
    Local LLM via Ollama API.
    Requires Ollama running on localhost (default: http://127.0.0.1:11434).
    """

    def __init__(self, model: str, base_url: str = "http://127.0.0.1:11434") -> None:
        super().__init__(name=f"ollama:{model}", is_external=False)
        self._model = model
        self._base_url = base_url.rstrip("/")

    def generate(self, prompt: str, label: Label) -> LLMResponse:
        payload = {"model": self._model, "prompt": prompt, "stream": False}
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self._base_url}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return LLMResponse(text=body.get("response", ""), label=label)


class OpenAICompatibleLLM(BaseLLM):
    """
    External LLM with OpenAI-compatible API.
    Uses the OPENAI_API_KEY env var by default.
    """

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key_env: str = "OPENAI_API_KEY",
    ) -> None:
        super().__init__(name=f"openai:{model}", is_external=True)
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._api_key = os.getenv(api_key_env, "")

    def generate(self, prompt: str, label: Label) -> LLMResponse:
        if not self._api_key:
            raise RuntimeError("Missing API key for external LLM.")
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self._base_url}/v1/chat/completions",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        return LLMResponse(text=content, label=label)

