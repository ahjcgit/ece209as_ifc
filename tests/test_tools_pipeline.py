from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ifc_agent.labels import Lattice, make_label
from ifc_agent.scraper import ScrapedContent
from ifc_agent.tools import AgentTools


class _FakeScraper:
    def scrape(self, url: str) -> ScrapedContent:
        text = "alpha beta gamma by author http://ref"
        html = "<html><meta name='author' content='A'><time datetime='2025-01-01'></time></html>"
        return ScrapedContent(url=url, fetched_at="2026-01-01T00:00:00+00:00", raw_html=html, clean_text=text)


class AgentToolsTests(unittest.TestCase):
    def test_scrape_parse_store_then_retrieve(self) -> None:
        lattice = Lattice(["Public", "Internal", "Confidential", "Secret"])
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = str(Path(tmpdir) / "store.json")
            tools = AgentTools(lattice=lattice, storage_path=store_path, trusted_domains=["example.com"])
            tools._scraper = _FakeScraper()  # deterministic offline test

            stored = tools.scrape_parse_store(["https://example.com/a"])
            self.assertEqual(len(stored), 1)
            self.assertEqual(stored[0].label.level, "Public")

            retrieved = tools.retrieve_by_query("alpha", label_cap=make_label("Internal"))
            self.assertEqual(len(retrieved.documents), 1)
            self.assertEqual(retrieved.documents[0].url, "https://example.com/a")

    def test_retrieve_respects_label_cap(self) -> None:
        lattice = Lattice(["Public", "Internal", "Confidential", "Secret"])
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = str(Path(tmpdir) / "store.json")
            tools = AgentTools(lattice=lattice, storage_path=store_path)
            tools._scraper = _FakeScraper()

            tools.scrape_parse_store(["https://untrusted.example/a"], scrape_label=make_label("Confidential", ["Untrusted"]))
            retrieved = tools.retrieve_by_query("alpha", label_cap=make_label("Internal"))
            self.assertEqual(len(retrieved.documents), 0)


if __name__ == "__main__":
    unittest.main()
