from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .labels import Label, Lattice
from .storage import Document, StoredTrustAssessment


@dataclass(frozen=True)
class RetrievedDocument:
    id: str
    url: str
    text_snippet: str
    label: Label
    score: float


class Retriever:
    def __init__(self, lattice: Lattice) -> None:
        self._lattice = lattice

    def retrieve(
        self,
        query: str,
        documents: Iterable[Document],
        assessments: Iterable[StoredTrustAssessment],
        label_cap: Label | None = None,
        top_k: int = 3,
    ) -> list[RetrievedDocument]:
        assessment_by_doc = {item.document_id: item for item in assessments}
        query_tokens = self._tokenize(query)

        scored: list[tuple[float, RetrievedDocument]] = []
        for doc in documents:
            assessment = assessment_by_doc.get(doc.id)
            if assessment is None:
                continue
            if label_cap is not None and not self._lattice.can_flow(assessment.label, label_cap):
                continue
            rank_score = self._rank(query_tokens, doc.clean_text)
            if rank_score <= 0:
                continue
            scored.append(
                (
                    rank_score,
                    RetrievedDocument(
                        id=doc.id,
                        url=doc.url,
                        text_snippet=doc.clean_text[:500],
                        label=assessment.label,
                        score=assessment.score,
                    ),
                )
            )
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored[:top_k]]

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", text.lower())

    @classmethod
    def _rank(cls, query_tokens: list[str], text: str) -> float:
        if not query_tokens:
            return 0.0
        doc_tokens = set(cls._tokenize(text))
        if not doc_tokens:
            return 0.0
        overlap = sum(1 for token in query_tokens if token in doc_tokens)
        return overlap / max(1, len(set(query_tokens)))
