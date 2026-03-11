from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ifc_agent.scraper import WebScraper

TEST_LANE = "integration"


def _playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
    except ModuleNotFoundError:
        return False
    return True


@unittest.skipUnless(
    _playwright_available(),
    "Integration scraper tests require Playwright (`pip install playwright`).",
)
class WebScraperIntegrationTests(unittest.TestCase):
    def test_scrape_data_url_returns_expected_content(self) -> None:
        scraper = WebScraper(user_agent="IFC-Agent/IntegrationTest")
        content = scraper.scrape("data:text/html,<html><body><h1>Hello</h1><p>world</p></body></html>")

        self.assertTrue(content.raw_html)
        self.assertTrue(content.clean_text)
        self.assertIn("Hello", content.clean_text)
        # Must be parseable ISO timestamp.
        dt.datetime.fromisoformat(content.fetched_at)

    def test_scrape_invalid_url_wraps_error(self) -> None:
        scraper = WebScraper()
        with self.assertRaises(RuntimeError) as exc:
            scraper.scrape("://not-a-valid-url")
        self.assertIn("Failed to scrape", str(exc.exception))


if __name__ == "__main__":
    unittest.main()
