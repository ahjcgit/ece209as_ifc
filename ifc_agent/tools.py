from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .labels import Label, Lattice
from .parser import TrustAssessment, TrustParser
from .retrieval import RetrievedDocument, Retriever
from .scraper import WebScraper
from .storage import JSONStorage


@dataclass(frozen=True)
class ScrapeStoreResult:
    document_id: str
    url: str
    label: Label
    score: float
    signals: dict[str, float | str | bool | int]


@dataclass(frozen=True)
class RetrieveResult:
    documents: list[RetrievedDocument]


class AgentTools:
    def __init__(
        self,
        lattice: Lattice,
        storage_path: str,
        trusted_domains: Iterable[str] | None = None,
        blocked_domains: Iterable[str] | None = None,
        user_agent: str = "IFC-Agent/0.2",
    ) -> None:
        self._lattice = lattice
        self._scraper = WebScraper(user_agent=user_agent)
        self._parser = TrustParser(
            trusted_domains=trusted_domains,
            blocked_domains=blocked_domains,
        )
        self._storage = JSONStorage(storage_path)
        self._retriever = Retriever(lattice)

    def scrape_parse_store(
        self,
        urls: Iterable[str],
        scrape_label: Label | None = None,
    ) -> list[ScrapeStoreResult]:
        stored: list[ScrapeStoreResult] = []
        for url in urls:
            content = self._scraper.scrape(url)

            assessment = self._parser.assess(
                url,
                content.clean_text,
                content.raw_html,
            )

            final_level = assessment.label.level
            final_categories = set(assessment.label.categories)

            if scrape_label is not None:
                if scrape_label.level not in self._lattice._rank:
                    raise ValueError(f"Unknown scrape label level: {scrape_label.level}")

                final_level = self._lattice.join_level(
                    final_level,
                    scrape_label.level,
                )

                final_categories.update(scrape_label.categories)

            final_label = Label(
                level=final_level,
                categories=frozenset(final_categories),
            )

            safe_assessment = TrustAssessment(
                score=assessment.score,
                label=final_label,
                signals=assessment.signals,
            )

            document, trust = self._storage.store_document(
                content,
                safe_assessment,
            )

            stored.append(
                ScrapeStoreResult(
                    document_id=document.id,
                    url=document.url,
                    label=trust.label,
                    score=trust.score,
                    signals=trust.signals,
                )
            )
        return stored

    def retrieve_by_query(
        self,
        query: str,
        label_cap: Label | None = None,
        top_k: int = 3,
    ) -> RetrieveResult:
        documents = self._storage.load_documents()
        assessments = self._storage.load_trust_assessments()
        retrieved = self._retriever.retrieve(
            query=query,
            documents=documents,
            assessments=assessments,
            label_cap=label_cap,
            top_k=top_k,
        )
        return RetrieveResult(documents=retrieved)
