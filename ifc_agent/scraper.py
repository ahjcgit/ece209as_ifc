from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class ScrapedContent:
    url: str
    fetched_at: str
    raw_html: str
    clean_text: str


def strip_html(html: str) -> str:
    text = re.sub(r"<script.*?>.*?</script>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<style.*?>.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


class WebScraper:
    def __init__(self, user_agent: str = "IFC-Agent/0.2") -> None:
        self._user_agent = user_agent

    def scrape(self, url: str) -> ScrapedContent:
        req = urllib.request.Request(url, headers={"User-Agent": self._user_agent})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw_html = resp.read().decode("utf-8", errors="replace")
        return ScrapedContent(
            url=url,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            raw_html=raw_html,
            clean_text=strip_html(raw_html),
        )
