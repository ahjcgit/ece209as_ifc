from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlparse

from .labels import Label, make_label


@dataclass(frozen=True)
class TrustAssessment:
    score: float
    label: Label
    signals: dict[str, float | str | bool | int]


class TrustParser:
    def __init__(
        self,
        trusted_domains: Iterable[str] | None = None,
        blocked_domains: Iterable[str] | None = None,
    ) -> None:
        self._trusted_domains = {d.lower() for d in (trusted_domains or [])}
        self._blocked_domains = {d.lower() for d in (blocked_domains or [])}

    def assess(self, url: str, clean_text: str, raw_html: str) -> TrustAssessment:
        host = (urlparse(url).hostname or "").lower()
        https = url.lower().startswith("https://")

        html_lower = raw_html.lower()
        text_lower = clean_text.lower()
        author_present = ("author" in html_lower) or ("by " in text_lower)
        date_present = any(token in html_lower for token in ("datetime", "published", "date"))
        org_present = any(token in text_lower for token in ("inc", "corp", "university", "government"))
        refs = text_lower.count("http") + text_lower.count("www.")
        boilerplate_ratio = self._boilerplate_ratio(clean_text)

        domain_signal = 0.5
        if host in self._trusted_domains:
            domain_signal = 1.0
        elif host in self._blocked_domains:
            domain_signal = 0.0

        score = (
            0.3 * domain_signal
            + 0.15 * float(https)
            + 0.2 * float(author_present or date_present or org_present)
            + 0.2 * min(refs, 5) / 5.0
            + 0.15 * (1.0 - boilerplate_ratio)
        )
        score = max(0.0, min(1.0, score))

        label = self.map_score_to_label(score)
        return TrustAssessment(
            score=score,
            label=label,
            signals={
                "domain": host,
                "domain_signal": domain_signal,
                "https": https,
                "author_present": author_present,
                "date_present": date_present,
                "org_present": org_present,
                "reference_count": refs,
                "boilerplate_ratio": round(boilerplate_ratio, 4),
            },
        )

    @staticmethod
    def map_score_to_label(score: float) -> Label:
        if score >= 0.8:
            return make_label("Public")
        if score >= 0.5:
            return make_label("Internal")
        return make_label("Confidential", ["Untrusted"])

    @staticmethod
    def _boilerplate_ratio(text: str) -> float:
        if not text:
            return 1.0
        words = text.split()
        if not words:
            return 1.0
        boilerplate_tokens = {"cookie", "privacy", "terms", "subscribe", "advertisement", "login"}
        boilerplate_count = sum(1 for w in words if w.lower().strip(".,:;!?()[]{}") in boilerplate_tokens)
        return min(1.0, boilerplate_count / max(1, len(words)))
