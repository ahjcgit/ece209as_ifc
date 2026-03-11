from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ifc_agent.agent import WebAgent
from ifc_agent.labels import Lattice, make_label
from ifc_agent.llm import BaseLLM, LLMResponse
from ifc_agent.scraper import ScrapedContent
from ifc_agent.tools import AgentTools


class _FakeScraper:
    def scrape(self, url: str) -> ScrapedContent:
        text = "alpha beta gamma by author http://ref1 http://ref2"
        html = "<html><meta name='author' content='A'><time datetime='2026-01-01'></time></html>"
        return ScrapedContent(
            url=url,
            fetched_at="2026-01-01T00:00:00+00:00",
            raw_html=html,
            clean_text=text,
        )


class _FakeLLM(BaseLLM):
    def __init__(self, response_label):
        super().__init__(name="fake-local", is_external=False)
        self._response_label = response_label

    def generate(self, prompt: str, label) -> LLMResponse:
        print("[PIPELINE] LLM.generate called")
        print(f"[PIPELINE] LLM received label: {label}")
        print(f"[PIPELINE] Prompt preview: {prompt[:120].replace(chr(10), ' ')}...")
        return LLMResponse(text="Synthetic summary answer.", label=self._response_label)


class PipelineWithLogsTests(unittest.TestCase):
    def _build_tools(self, tmpdir: str) -> AgentTools:
        lattice = Lattice(["Public", "Internal", "Confidential", "Secret"])
        tools = AgentTools(
            lattice=lattice,
            storage_path=str(Path(tmpdir) / "store.json"),
            trusted_domains=["example.com"],
            blocked_domains=[],
        )
        tools._scraper = _FakeScraper()
        return tools

    def test_pipeline_success_with_verbose_logs(self) -> None:
        print("\n[PIPELINE] ===== SUCCESS SCENARIO =====")
        lattice = Lattice(["Public", "Internal", "Confidential", "Secret"])
        from ifc_agent.policy import Policy

        policy = Policy(
            lattice=lattice,
            external_llm_allowed=[make_label("Internal")],
            user_output_max=make_label("Confidential", ["PII"]),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tools = self._build_tools(tmpdir)
            llm = _FakeLLM(response_label=make_label("Internal"))
            agent = WebAgent(lattice=lattice, policy=policy, llm=llm, tools=tools)

            urls = ["https://example.com/ok"]
            user_prompt = "Summarize alpha content."
            user_label = make_label("Internal")

            print(f"[PIPELINE] Input URLs: {urls}")
            print(f"[PIPELINE] User label: {user_label}")
            print("[PIPELINE] Running agent...")
            result = agent.run(user_prompt=user_prompt, user_label=user_label, urls=urls)
            print(f"[PIPELINE] Final result label: {result.label}")
            print(f"[PIPELINE] Final result text: {result.text}")
            print(f"[PIPELINE] Audit keys: {sorted((result.audit or {}).keys())}")

            docs = tools._storage.load_documents()
            trusts = tools._storage.load_trust_assessments()
            print(f"[PIPELINE] Stored documents: {len(docs)}")
            print(f"[PIPELINE] Stored trust rows: {len(trusts)}")
            if trusts:
                print(f"[PIPELINE] Stored trust label: {trusts[0].label}")
                print(f"[PIPELINE] Stored trust score: {trusts[0].score}")

            self.assertEqual(result.text, "Synthetic summary answer.")
            self.assertEqual(result.label.level, "Internal")
            self.assertIsNotNone(result.audit)
            self.assertEqual(result.audit.get("combined_label"), "Internal")
            self.assertIn("retrieved_documents", result.audit)
            self.assertEqual(result.audit.get("llm_backend"), "fake-local")
            self.assertEqual(len(docs), 1)
            self.assertEqual(len(trusts), 1)

    def test_pipeline_failure_policy_block_with_verbose_logs(self) -> None:
        print("\n[PIPELINE] ===== FAILURE SCENARIO (USER OUTPUT POLICY) =====")
        lattice = Lattice(["Public", "Internal", "Confidential", "Secret"])
        from ifc_agent.policy import Policy

        policy = Policy(
            lattice=lattice,
            external_llm_allowed=[make_label("Internal")],
            user_output_max=make_label("Confidential", ["PII"]),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tools = self._build_tools(tmpdir)
            llm = _FakeLLM(response_label=make_label("Secret"))
            agent = WebAgent(lattice=lattice, policy=policy, llm=llm, tools=tools)

            urls = ["https://example.com/fail"]
            user_prompt = "Summarize alpha content."
            user_label = make_label("Internal")

            print(f"[PIPELINE] Input URLs: {urls}")
            print(f"[PIPELINE] User label: {user_label}")
            print("[PIPELINE] Running agent and expecting PermissionError...")

            with self.assertRaises(PermissionError) as exc:
                agent.run(user_prompt=user_prompt, user_label=user_label, urls=urls)

            print(f"[PIPELINE] Expected failure captured: {exc.exception}")
            self.assertIn("exceeds user clearance", str(exc.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
