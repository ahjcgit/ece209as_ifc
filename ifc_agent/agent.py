from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .labels import Label, Lattice, join_labels, make_label
from .llm import BaseLLM, LLMResponse
from .policy import Policy
from .tools import ToolResult, WebFetcher


@dataclass(frozen=True)
class AgentResult:
    text: str
    label: Label


class WebAgent:
    def __init__(
        self,
        lattice: Lattice,
        policy: Policy,
        llm: BaseLLM,
        fetcher: WebFetcher | None = None,
    ) -> None:
        self._lattice = lattice
        self._policy = policy
        self._llm = llm
        self._fetcher = fetcher or WebFetcher()

    def run(
        self,
        user_prompt: str,
        user_label: Label,
        urls: Iterable[str],
        scrape_label: Label | None = None,
    ) -> AgentResult:
        scrape_label = scrape_label or make_label(user_label.level, user_label.categories)

        tool_results: list[ToolResult] = []
        for url in urls:
            tool_results.append(self._fetcher.fetch(url, scrape_label))

        combined_label = join_labels(
            self._lattice, [user_label] + [res.label for res in tool_results]
        )
        summary_prompt = self._build_prompt(user_prompt, tool_results)

        if self._llm.is_external:
            decision = self._policy.can_send_to_external_llm(combined_label)
            if not decision.allowed:
                raise PermissionError(decision.reason)

        llm_response: LLMResponse = self._llm.generate(summary_prompt, combined_label)

        decision = self._policy.can_send_to_user(llm_response.label)
        if not decision.allowed:
            raise PermissionError(decision.reason)

        return AgentResult(text=llm_response.text, label=llm_response.label)

    @staticmethod
    def _build_prompt(user_prompt: str, tool_results: Iterable[ToolResult]) -> str:
        snippets = "\n\n".join(
            f"[Source {idx + 1}]\n{result.text[:2000]}"
            for idx, result in enumerate(tool_results)
        )
        return (
            "You are a cautious web agent. Use only the provided sources.\n\n"
            f"User request:\n{user_prompt}\n\n"
            f"Sources:\n{snippets}\n\n"
            "Provide a concise answer and cite sources by number."
        )

