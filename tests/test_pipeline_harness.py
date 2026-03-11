from __future__ import annotations

import re
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ifc_agent.agent import WebAgent
from ifc_agent.labels import Label, Lattice, make_label
from ifc_agent.llm import BaseLLM, LLMResponse
from ifc_agent.parser import TrustAssessment
from ifc_agent.policy import Policy
from ifc_agent.scraper import ScrapedContent
from ifc_agent.tools import AgentTools

TEST_LANE = "unit"


@dataclass(frozen=True)
class Fact:
    url: str
    text: str
    label: Label


@dataclass(frozen=True)
class HarnessCase:
    name: str
    facts: list[Fact]
    prompt: str
    user_label: Label
    llm_external: bool = False
    llm_response_label: Label | None = None
    external_allowed: list[Label] | None = None
    user_output_max: Label | None = None
    expected_contains: str | None = None
    expected_not_contains: str | None = None
    expect_permission_error_substr: str | None = None
    expect_zero_llm_calls: bool = False


class _FactScraper:
    def __init__(self, by_url: dict[str, Fact]) -> None:
        self._by_url = by_url

    def scrape(self, url: str) -> ScrapedContent:
        fact = self._by_url[url]
        return ScrapedContent(
            url=url,
            fetched_at="2026-01-01T00:00:00+00:00",
            raw_html="<html><body>seed</body></html>",
            clean_text=fact.text,
        )


class _AlwaysPublicParser:
    def assess(self, url: str, clean_text: str, raw_html: str) -> TrustAssessment:
        return TrustAssessment(
            score=0.9,
            label=make_label("Public"),
            signals={"seeded": True},
        )


class _RuleLLM(BaseLLM):
    def __init__(self, is_external: bool, fixed_response_label: Label | None = None) -> None:
        super().__init__(name="harness-rule-llm", is_external=is_external)
        self._fixed_response_label = fixed_response_label
        self.calls = 0

    def generate(self, prompt: str, label: Label) -> LLMResponse:
        self.calls += 1
        visible = re.findall(
            r"(?:James|Maria|Sam|The launch code word|The server location)[^.\n]*\.",
            prompt,
        )
        answer = visible[-1] if visible else "No visible fact available."
        response_label = self._fixed_response_label or label
        print(f"[HARNESS] LLM call {self.calls} label={label} visible={len(visible)} answer={answer}")
        return LLMResponse(text=answer, label=response_label)


class PipelineHarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lattice = Lattice(["Public", "Internal", "Confidential", "Secret"])

    def _run_case(self, case: HarnessCase) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tools = AgentTools(
                lattice=self.lattice,
                storage_path=str(Path(tmpdir) / "store.json"),
            )
            tools._scraper = _FactScraper({fact.url: fact for fact in case.facts})
            tools._parser = _AlwaysPublicParser()

            llm = _RuleLLM(
                is_external=case.llm_external,
                fixed_response_label=case.llm_response_label,
            )
            policy = Policy(
                lattice=self.lattice,
                external_llm_allowed=case.external_allowed or [make_label("Internal")],
                user_output_max=case.user_output_max or make_label("Confidential", ["PII"]),
            )
            agent = WebAgent(self.lattice, policy, llm, tools)

            print(f"\n[HARNESS] Running case: {case.name}")
            print(f"[HARNESS] user_label={case.user_label} prompt={case.prompt}")
            for fact in case.facts:
                tools.scrape_parse_store([fact.url], scrape_label=fact.label)
                print(f"[HARNESS] seed {fact.url} label={fact.label} text={fact.text}")

            if case.expect_permission_error_substr:
                with self.assertRaises(PermissionError) as exc:
                    agent.run(case.prompt, case.user_label, [])
                self.assertIn(case.expect_permission_error_substr, str(exc.exception))
                if case.expect_zero_llm_calls:
                    self.assertEqual(llm.calls, 0)
                return

            result = agent.run(case.prompt, case.user_label, [])
            print(f"[HARNESS] result={result.text} label={result.label}")
            if case.expected_contains is not None:
                self.assertIn(case.expected_contains, result.text.lower())
            if case.expected_not_contains is not None:
                self.assertNotIn(case.expected_not_contains, result.text.lower())

    def test_harness_cases(self) -> None:
        cases = [
            HarnessCase(
                name="public_cannot_see_secret_contradiction",
                facts=[
                    Fact("https://facts/1", "James is wearing a red hat.", make_label("Public")),
                    Fact("https://facts/2", "James is wearing a blue hat.", make_label("Secret")),
                ],
                prompt="What hat is James wearing?",
                user_label=make_label("Public"),
                expected_contains="red hat",
                expected_not_contains="blue hat",
            ),
            HarnessCase(
                name="secret_can_see_secret_contradiction",
                facts=[
                    Fact("https://facts/1", "James is wearing a red hat.", make_label("Public")),
                    Fact("https://facts/2", "James is wearing a blue hat.", make_label("Secret")),
                ],
                prompt="What hat is James wearing?",
                user_label=make_label("Secret"),
                user_output_max=make_label("Secret"),
                expected_contains="blue hat",
            ),
            HarnessCase(
                name="internal_excludes_confidential_fact",
                facts=[
                    Fact("https://facts/3", "Maria drives a white car.", make_label("Public")),
                    Fact("https://facts/4", "Maria drives a black car.", make_label("Confidential")),
                ],
                prompt="What car does Maria drive?",
                user_label=make_label("Internal"),
                expected_contains="white car",
                expected_not_contains="black car",
            ),
            HarnessCase(
                name="external_egress_blocked_before_llm_call",
                facts=[
                    Fact("https://facts/5", "Sam works in finance.", make_label("Secret")),
                ],
                prompt="Where does Sam work?",
                user_label=make_label("Secret"),
                llm_external=True,
                expect_permission_error_substr="exceeds external LLM policy",
                expect_zero_llm_calls=True,
            ),
            HarnessCase(
                name="user_output_policy_blocks_secret_output",
                facts=[
                    Fact("https://facts/6", "The launch code word is ORBIT.", make_label("Internal")),
                ],
                prompt="What is the launch code word?",
                user_label=make_label("Internal"),
                llm_response_label=make_label("Secret"),
                expect_permission_error_substr="exceeds user clearance",
            ),
        ]
        for case in cases:
            with self.subTest(case=case.name):
                self._run_case(case)


if __name__ == "__main__":
    unittest.main(verbosity=2)
