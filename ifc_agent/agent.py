from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .labels import Label, Lattice, join_labels, make_label
from .llm import BaseLLM, LLMResponse
from .policy import Policy
from .tools import AgentTools, RetrieveResult


@dataclass(frozen=True)
class AgentResult:
    text: str
    label: Label
    audit: dict[str, object] | None = None


class WebAgent:
    def __init__(
        self,
        lattice: Lattice,
        policy: Policy,
        llm: BaseLLM,
        tools: AgentTools,
    ) -> None:
        self._lattice = lattice
        self._policy = policy
        self._llm = llm
        self._tools = tools

    def run(
        self,
        user_prompt: str,
        user_label: Label,
        urls: Iterable[str],
        scrape_label: Label | None = None,
    ) -> AgentResult:
        audit: dict[str, object] = {
            "user_prompt": user_prompt,
            "user_label": str(user_label),
            "input_urls": list(urls),
        }

        scrape_label = scrape_label or make_label(user_label.level, user_label.categories)
        audit["scrape_label"] = str(scrape_label)

        self._tools.scrape_parse_store(
            urls=audit["input_urls"],
            scrape_label=scrape_label,
        )

        retrieved: RetrieveResult = self._tools.retrieve_by_query(
            query=user_prompt,
            label_cap=user_label,
        )
        audit["retrieved_documents"] = [
            {
                "id": doc.id,
                "url": doc.url,
                "label": str(doc.label),
                "score": doc.score,
            }
            for doc in retrieved.documents
        ]

        if not retrieved.documents:
            return AgentResult(
                text="No relevant or authorized documents were found for this query.",
                label=user_label,
                audit=audit,
            )

        combined_label = join_labels(
            self._lattice,
            [user_label] + [doc.label for doc in retrieved.documents],
        )
        audit["combined_label"] = str(combined_label)
        summary_prompt = self._build_prompt(user_prompt, retrieved)

        if self._llm.is_external:
            decision = self._policy.can_send_to_external_llm(combined_label)
            audit["external_llm_decision"] = {
                "allowed": decision.allowed,
                "reason": decision.reason,
            }
            if not decision.allowed:
                raise PermissionError(decision.reason)
        llm_response: LLMResponse = self._llm.generate(summary_prompt, combined_label)
        audit["llm_backend"] = self._llm.name
        audit["llm_response_label"] = str(llm_response.label)

        decision = self._policy.can_send_to_user(llm_response.label)
        audit["user_output_decision"] = {
            "allowed": decision.allowed,
            "reason": decision.reason,
        }
        if not decision.allowed:
            raise PermissionError(decision.reason)

        return AgentResult(text=llm_response.text, label=llm_response.label, audit=audit)

    @staticmethod
    def _build_prompt(user_prompt: str, retrieved: RetrieveResult) -> str:
        snippets = "\n\n".join(
            f"[Source {idx + 1}] ({document.url})\n{document.text_snippet[:2000]}"
            for idx, document in enumerate(retrieved.documents)
        )
        return (
            "You are a cautious web agent. Use only the provided sources.\n\n"
            f"User request:\n{user_prompt}\n\n"
            f"Sources:\n{snippets}\n\n"
            "Provide a concise answer and cite sources by number."
        )
