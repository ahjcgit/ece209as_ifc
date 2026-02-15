from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .labels import Label, make_label
from .parser import TrustAssessment
from .scraper import ScrapedContent


@dataclass(frozen=True)
class Document:
    id: str
    url: str
    fetched_at: str
    raw_html: str
    clean_text: str


@dataclass(frozen=True)
class StoredTrustAssessment:
    document_id: str
    score: float
    label: Label
    signals: dict[str, float | str | bool | int]


class JSONStorage:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._ensure_file()

    def store_document(self, content: ScrapedContent, assessment: TrustAssessment) -> tuple[Document, StoredTrustAssessment]:
        payload = self._load()
        document = Document(
            id=str(uuid4()),
            url=content.url,
            fetched_at=content.fetched_at,
            raw_html=content.raw_html,
            clean_text=content.clean_text,
        )
        trust = StoredTrustAssessment(
            document_id=document.id,
            score=assessment.score,
            label=assessment.label,
            signals=assessment.signals,
        )
        payload["documents"].append(
            {
                "id": document.id,
                "url": document.url,
                "fetched_at": document.fetched_at,
                "raw_html": document.raw_html,
                "clean_text": document.clean_text,
            }
        )
        payload["trust_assessments"].append(
            {
                "document_id": trust.document_id,
                "score": trust.score,
                "label": {"level": trust.label.level, "categories": sorted(trust.label.categories)},
                "signals": trust.signals,
            }
        )
        self._save(payload)
        return document, trust

    def load_documents(self) -> list[Document]:
        payload = self._load()
        return [
            Document(
                id=item["id"],
                url=item["url"],
                fetched_at=item["fetched_at"],
                raw_html=item["raw_html"],
                clean_text=item["clean_text"],
            )
            for item in payload["documents"]
        ]

    def load_trust_assessments(self) -> list[StoredTrustAssessment]:
        payload = self._load()
        assessments: list[StoredTrustAssessment] = []
        for item in payload["trust_assessments"]:
            label_obj = item["label"]
            assessments.append(
                StoredTrustAssessment(
                    document_id=item["document_id"],
                    score=float(item["score"]),
                    label=make_label(label_obj["level"], label_obj.get("categories", [])),
                    signals=item.get("signals", {}),
                )
            )
        return assessments

    def _ensure_file(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._save({"documents": [], "trust_assessments": []})

    def _load(self) -> dict:
        with self._path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _save(self, payload: dict) -> None:
        with self._path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
