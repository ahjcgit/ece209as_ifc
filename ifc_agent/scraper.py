from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright


@dataclass(frozen=True)
class ScrapedContent:
    url: str
    fetched_at: str
    raw_html: str
    clean_text: str

class WebScraper:
    def __init__(self, user_agent: str = "IFC-Agent/0.2") -> None:
        self._user_agent = user_agent

    def scrape(self, url: str) -> ScrapedContent:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False)
                context = browser.new_context(user_agent=self._user_agent)
                page = context.new_page()

                page.goto(url, timeout=60000)
                page.wait_for_load_state("networkidle")

                raw_html = page.content()
                clean_text = page.inner_text("body")

                browser.close()

        except Exception as e:
            raise RuntimeError(f"Failed to scrape {url}: {e}")

        return ScrapedContent(
            url=url,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            raw_html=raw_html,
            clean_text=clean_text.strip(),
        )
