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


@dataclass(frozen=True)
class FactSeed:
    url: str
    text: str
    label: Label


SEEDS: list[FactSeed] = [
    FactSeed("https://facts.local/1", "James is wearing a red hat.", make_label("Public")),
    FactSeed("https://facts.local/2", "James is wearing a blue hat.", make_label("Secret")),
    FactSeed("https://facts.local/3", "Maria drives a white car.", make_label("Public")),
    FactSeed("https://facts.local/4", "Maria drives a black car.", make_label("Confidential")),
    FactSeed("https://facts.local/5", "Sam works in marketing.", make_label("Public")),
    FactSeed("https://facts.local/6", "Sam works in finance.", make_label("Internal")),
    FactSeed("https://facts.local/7", "The launch code word is ORBIT.", make_label("Internal")),
    FactSeed("https://facts.local/8", "The launch code word is ECLIPSE.", make_label("Secret")),
    FactSeed("https://facts.local/9", "The server location is Building A.", make_label("Public")),
    FactSeed("https://facts.local/10", "The server location is Building Z.", make_label("Secret")),
]


class _SeedScraper:
    def __init__(self, fact_by_url: dict[str, FactSeed]) -> None:
        self._fact_by_url = fact_by_url

    def scrape(self, url: str) -> ScrapedContent:
        fact = self._fact_by_url[url]
        html = "<html><body><p>fact</p></body></html>"
        return ScrapedContent(
            url=url,
            fetched_at="2026-01-01T00:00:00+00:00",
            raw_html=html,
            clean_text=fact.text,
        )


class _AlwaysPublicParser:
    def assess(self, url: str, clean_text: str, raw_html: str) -> TrustAssessment:
        return TrustAssessment(score=0.95, label=make_label("Public"), signals={"seeded": True})


class _WindowLLM(BaseLLM):
    def __init__(self) -> None:
        super().__init__(name="window-llm", is_external=False)
        self.last_prompt = ""

    def generate(self, prompt: str, label: Label) -> LLMResponse:
        self.last_prompt = prompt
        visible_facts = self._extract_visible_facts(prompt)
        print("[IFC-WINDOW] LLM.generate called")
        print(f"[IFC-WINDOW] LLM label context: {label}")
        print(f"[IFC-WINDOW] Visible facts in prompt ({len(visible_facts)}):")
        for idx, fact in enumerate(visible_facts, start=1):
            print(f"[IFC-WINDOW]   {idx}. {fact}")

        response_text = self._answer_from_visible_facts(prompt, visible_facts)
        print(f"[IFC-WINDOW] LLM answer: {response_text}")
        return LLMResponse(text=response_text, label=label)

    @staticmethod
    def _extract_visible_facts(prompt: str) -> list[str]:
        return re.findall(r"(?:James|Maria|Sam|The launch code word|The server location)[^.\n]*\.", prompt)

    @staticmethod
    def _answer_from_visible_facts(prompt: str, facts: list[str]) -> str:
        prompt_lower = prompt.lower()
        target = None
        for key in ("james", "maria", "sam", "launch code", "server location"):
            if key in prompt_lower:
                target = key
                break
        if target is None:
            return "No target found in question."

        filtered = []
        for fact in facts:
            lower = fact.lower()
            if target == "launch code" and "launch code" in lower:
                filtered.append(fact)
            elif target == "server location" and "server location" in lower:
                filtered.append(fact)
            elif target in lower:
                filtered.append(fact)

        if not filtered:
            return "No visible fact available for this question."
        # Choose the last visible contradictory claim to show what information
        # is currently in the LLM reasoning window.
        return filtered[-1]


class IFCWindowTests(unittest.TestCase):
    def _build_agent_and_tools(self, tmpdir: str) -> tuple[WebAgent, AgentTools]:
        lattice = Lattice(["Public", "Internal", "Confidential", "Secret"])
        policy = Policy(
            lattice=lattice,
            external_llm_allowed=[make_label("Secret")],
            user_output_max=make_label("Secret"),
        )
        tools = AgentTools(
            lattice=lattice,
            storage_path=str(Path(tmpdir) / "store.json"),
            trusted_domains=[],
            blocked_domains=[],
        )
        tools._scraper = _SeedScraper({seed.url: seed for seed in SEEDS})
        tools._parser = _AlwaysPublicParser()
        llm = _WindowLLM()
        agent = WebAgent(lattice=lattice, policy=policy, llm=llm, tools=tools)
        return agent, tools

    def _seed_data(self, tools: AgentTools) -> None:
        print("\n[IFC-WINDOW] ===== Seeding 10 label + data pairs =====")
        for idx, seed in enumerate(SEEDS, start=1):
            tools.scrape_parse_store([seed.url], scrape_label=seed.label)
            print(f"[IFC-WINDOW] Seed {idx}: label={seed.label} | data={seed.text}")

    def test_public_window_only_shows_public_contradiction_side(self) -> None:
        print("\n[IFC-WINDOW] ===== TEST: PUBLIC WINDOW =====")
        with tempfile.TemporaryDirectory() as tmpdir:
            agent, tools = self._build_agent_and_tools(tmpdir)
            self._seed_data(tools)

            result = agent.run(
                user_prompt="What hat is James wearing?",
                user_label=make_label("Public"),
                urls=[],
            )
            print(f"[IFC-WINDOW] Final answer (Public): {result.text}")

            self.assertIn("red hat", result.text.lower())
            self.assertNotIn("blue hat", result.text.lower())

    def test_internal_window_excludes_confidential_for_contradiction(self) -> None:
        print("\n[IFC-WINDOW] ===== TEST: INTERNAL WINDOW =====")
        with tempfile.TemporaryDirectory() as tmpdir:
            agent, tools = self._build_agent_and_tools(tmpdir)
            self._seed_data(tools)

            result = agent.run(
                user_prompt="What car does Maria drive?",
                user_label=make_label("Internal"),
                urls=[],
            )
            print(f"[IFC-WINDOW] Final answer (Internal): {result.text}")

            self.assertIn("white car", result.text.lower())
            self.assertNotIn("black car", result.text.lower())

    def test_secret_window_can_see_secret_side_of_contradiction(self) -> None:
        print("\n[IFC-WINDOW] ===== TEST: SECRET WINDOW =====")
        with tempfile.TemporaryDirectory() as tmpdir:
            agent, tools = self._build_agent_and_tools(tmpdir)
            self._seed_data(tools)

            result = agent.run(
                user_prompt="What hat is James wearing?",
                user_label=make_label("Secret"),
                urls=[],
            )
            print(f"[IFC-WINDOW] Final answer (Secret): {result.text}")

            self.assertIn("blue hat", result.text.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
