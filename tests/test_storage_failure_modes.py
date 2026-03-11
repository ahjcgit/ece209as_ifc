from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ifc_agent.labels import Lattice, make_label
from ifc_agent.parser import TrustAssessment, TrustParser
from ifc_agent.retrieval import Retriever
from ifc_agent.scraper import ScrapedContent, WebScraper
from ifc_agent.storage import Document, JSONStorage, StoredTrustAssessment


def _content(url: str, text: str, html: str = "<html><body>x</body></html>") -> ScrapedContent:
    return ScrapedContent(
        url=url,
        fetched_at="2026-01-01T00:00:00+00:00",
        raw_html=html,
        clean_text=text,
    )


def _assessment(level: str) -> TrustAssessment:
    return TrustAssessment(
        score=0.9,
        label=make_label(level),
        signals={"seeded": True},
    )


class JSONStorageSemanticsTests(unittest.TestCase):
    def test_store_document_updates_existing_row_by_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JSONStorage(Path(tmpdir) / "store.json")
            original_doc, _ = store.store_document(
                _content("https://example.com/a", "alpha"),
                _assessment("Public"),
            )
            updated_doc, updated_trust = store.store_document(
                _content("https://example.com/a", "alpha new"),
                _assessment("Internal"),
            )

            docs = store.load_documents()
            trusts = store.load_trust_assessments()

        self.assertEqual(len(docs), 1)
        self.assertEqual(len(trusts), 1)
        self.assertEqual(updated_doc.id, original_doc.id)
        self.assertEqual(docs[0].clean_text, "alpha new")
        self.assertEqual(updated_trust.label.level, "Internal")
        self.assertEqual(trusts[0].label.level, "Internal")

    def test_store_document_updates_existing_row_by_content_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JSONStorage(Path(tmpdir) / "store.json")
            original_doc, _ = store.store_document(
                _content("https://source-a.example/doc", "shared content"),
                _assessment("Public"),
            )
            updated_doc, _ = store.store_document(
                _content("https://source-b.example/doc", "shared content"),
                _assessment("Confidential"),
            )
            docs = store.load_documents()
            trusts = store.load_trust_assessments()

        self.assertEqual(len(docs), 1)
        self.assertEqual(len(trusts), 1)
        self.assertEqual(updated_doc.id, original_doc.id)
        self.assertEqual(docs[0].url, "https://source-b.example/doc")
        self.assertEqual(trusts[0].label.level, "Confidential")

    def test_store_document_inserts_new_rows_for_new_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JSONStorage(Path(tmpdir) / "store.json")
            store.store_document(_content("https://example.com/a", "alpha"), _assessment("Public"))
            store.store_document(_content("https://example.com/b", "beta"), _assessment("Internal"))
            docs = store.load_documents()
            trusts = store.load_trust_assessments()

        self.assertEqual(len(docs), 2)
        self.assertEqual(len(trusts), 2)
        self.assertEqual({doc.url for doc in docs}, {"https://example.com/a", "https://example.com/b"})
        self.assertEqual({trust.document_id for trust in trusts}, {doc.id for doc in docs})

    def test_load_raises_for_corrupted_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "store.json"
            path.write_text("{bad-json", encoding="utf-8")
            store = JSONStorage(path)
            with self.assertRaises(json.JSONDecodeError):
                store.load_documents()


class FailureModeTests(unittest.TestCase):
    def test_parser_empty_content_maps_to_confidential_untrusted(self) -> None:
        parser = TrustParser()
        assessment = parser.assess(
            url="http://unknown.example/path",
            clean_text="",
            raw_html="",
        )
        self.assertEqual(assessment.label.level, "Confidential")
        self.assertIn("Untrusted", assessment.label.categories)

    def test_retriever_ignores_documents_without_matching_assessment(self) -> None:
        lattice = Lattice(["Public", "Internal", "Confidential", "Secret"])
        retriever = Retriever(lattice)
        documents = [
            Document(
                id="doc-1",
                url="https://example.com/a",
                fetched_at="2026-01-01T00:00:00+00:00",
                raw_html="<html></html>",
                clean_text="alpha topic",
            )
        ]
        assessments = [
            StoredTrustAssessment(
                document_id="some-other-doc",
                score=0.95,
                label=make_label("Public"),
                signals={},
            )
        ]

        result = retriever.retrieve(query="alpha", documents=documents, assessments=assessments)
        self.assertEqual(result, [])

    def test_scraper_wraps_runtime_errors(self) -> None:
        fake_playwright_module = types.SimpleNamespace()

        class _RaisingContext:
            def __enter__(self):
                raise ValueError("network down")

            def __exit__(self, exc_type, exc, tb):
                return False

        fake_playwright_module.sync_playwright = lambda: _RaisingContext()

        with patch.dict(sys.modules, {"playwright.sync_api": fake_playwright_module}):
            scraper = WebScraper()
            with self.assertRaises(RuntimeError) as exc:
                scraper.scrape("https://example.com")

        self.assertIn("Failed to scrape https://example.com", str(exc.exception))
        self.assertIn("network down", str(exc.exception))


if __name__ == "__main__":
    unittest.main()
