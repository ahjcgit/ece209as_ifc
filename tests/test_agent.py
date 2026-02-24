from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ifc_agent.agent import WebAgent
from ifc_agent.labels import Label, Lattice, make_label
from ifc_agent.llm import BaseLLM, LLMResponse
from ifc_agent.policy import Policy
from ifc_agent.retrieval import RetrievedDocument
from ifc_agent.tools import RetrieveResult


class _FakeLLM(BaseLLM):
    def __init__(self, is_external: bool, response_label: Label) -> None:
        super().__init__(name="fake", is_external=is_external)
        self._response_label = response_label

    def generate(self, prompt: str, label: Label) -> LLMResponse:
        return LLMResponse(text="ok", label=self._response_label)


class _FakeTools:
    def __init__(self, docs: list[RetrievedDocument]) -> None:
        self._docs = docs
        self.scrape_calls = 0

    def scrape_parse_store(self, urls, scrape_label=None):
        self.scrape_calls += 1
        return []

    def retrieve_by_query(self, query: str, label_cap=None, top_k: int = 3) -> RetrieveResult:
        return RetrieveResult(documents=self._docs)


class WebAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lattice = Lattice(["Public", "Internal", "Confidential", "Secret"])
        self.policy = Policy(
            lattice=self.lattice,
            external_llm_allowed=[make_label("Internal")],
            user_output_max=make_label("Confidential", ["PII"]),
        )

    def test_run_blocks_external_llm_on_high_combined_label(self) -> None:
        docs = [
            RetrievedDocument(
                id="1",
                url="https://x",
                text_snippet="s",
                label=make_label("Confidential", ["Untrusted"]),
                score=0.3,
            )
        ]
        tools = _FakeTools(docs)
        llm = _FakeLLM(is_external=True, response_label=make_label("Internal"))
        agent = WebAgent(self.lattice, self.policy, llm, tools)

        with self.assertRaises(PermissionError):
            agent.run("q", make_label("Internal"), ["https://x"])

    def test_run_success_for_local_llm(self) -> None:
        docs = [
            RetrievedDocument(
                id="1",
                url="https://x",
                text_snippet="snippet",
                label=make_label("Public"),
                score=0.9,
            )
        ]
        tools = _FakeTools(docs)
        llm = _FakeLLM(is_external=False, response_label=make_label("Internal"))
        agent = WebAgent(self.lattice, self.policy, llm, tools)

        result = agent.run("summarize", make_label("Internal"), ["https://x"])
        self.assertEqual(result.text, "ok")
        self.assertEqual(result.label.level, "Internal")
        self.assertEqual(tools.scrape_calls, 1)

    def test_run_blocks_user_output_above_user_max(self) -> None:
        docs = [
            RetrievedDocument(
                id="1",
                url="https://x",
                text_snippet="snippet",
                label=make_label("Public"),
                score=0.9,
            )
        ]
        tools = _FakeTools(docs)
        llm = _FakeLLM(is_external=False, response_label=make_label("Secret"))
        agent = WebAgent(self.lattice, self.policy, llm, tools)

        with self.assertRaises(PermissionError):
            agent.run("summarize", make_label("Internal"), ["https://x"])


if __name__ == "__main__":
    unittest.main()
