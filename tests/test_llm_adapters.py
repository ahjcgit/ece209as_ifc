from __future__ import annotations

import io
import json
import os
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ifc_agent.labels import make_label
from ifc_agent.llm import OllamaLLM, OpenAICompatibleLLM


class _FakeHTTPResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class LLMAdaptersTests(unittest.TestCase):
    def test_ollama_generate_maps_response_text(self) -> None:
        captured: dict[str, object] = {}

        def _fake_urlopen(req, timeout=0):
            captured["url"] = req.full_url
            captured["method"] = req.get_method()
            captured["timeout"] = timeout
            captured["payload"] = json.loads(req.data.decode("utf-8"))
            return _FakeHTTPResponse({"response": "hello from ollama"})

        with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
            llm = OllamaLLM(model="qwen2.5:7b-instruct", base_url="http://127.0.0.1:11434")
            label = make_label("Internal")
            response = llm.generate("summarize", label)

        self.assertEqual(response.text, "hello from ollama")
        self.assertEqual(response.label, label)
        self.assertEqual(captured["url"], "http://127.0.0.1:11434/api/generate")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["timeout"], 120)
        self.assertEqual(captured["payload"], {"model": "qwen2.5:7b-instruct", "prompt": "summarize", "stream": False})

    def test_ollama_generate_surfaces_http_error_body(self) -> None:
        def _fake_urlopen(req, timeout=0):
            raise urllib.error.HTTPError(
                url=req.full_url,
                code=500,
                msg="Internal Server Error",
                hdrs=None,
                fp=io.BytesIO(b'{"error":"backend exploded"}'),
            )

        with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
            llm = OllamaLLM(model="qwen2.5:7b-instruct")
            with self.assertRaises(RuntimeError) as exc:
                llm.generate("ping", make_label("Public"))

        self.assertIn("Ollama API error: 500", str(exc.exception))
        self.assertIn("backend exploded", str(exc.exception))

    def test_openai_compatible_requires_api_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            llm = OpenAICompatibleLLM(model="gpt-4o-mini", base_url="https://api.openai.com")
            with self.assertRaises(RuntimeError) as exc:
                llm.generate("hello", make_label("Public"))
        self.assertIn("Missing API key", str(exc.exception))

    def test_openai_compatible_maps_chat_response(self) -> None:
        captured: dict[str, object] = {}

        def _fake_urlopen(req, timeout=0):
            captured["url"] = req.full_url
            captured["method"] = req.get_method()
            captured["auth"] = req.headers.get("Authorization")
            captured["payload"] = json.loads(req.data.decode("utf-8"))
            captured["timeout"] = timeout
            return _FakeHTTPResponse(
                {"choices": [{"message": {"content": "hello from api"}}]}
            )

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True):
            with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
                llm = OpenAICompatibleLLM(
                    model="gpt-4o-mini",
                    base_url="https://api.openai.com",
                )
                label = make_label("Internal")
                response = llm.generate("give summary", label)

        self.assertEqual(response.text, "hello from api")
        self.assertEqual(response.label, label)
        self.assertEqual(captured["url"], "https://api.openai.com/v1/chat/completions")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["auth"], "Bearer test-key")
        self.assertEqual(captured["timeout"], 120)
        self.assertEqual(
            captured["payload"],
            {
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "give summary"}],
            },
        )


if __name__ == "__main__":
    unittest.main()
