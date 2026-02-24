from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ifc_agent.parser import TrustParser


class TrustParserTests(unittest.TestCase):
    def test_score_to_label_thresholds(self) -> None:
        parser = TrustParser()
        self.assertEqual(parser.map_score_to_label(0.80).level, "Public")
        self.assertEqual(parser.map_score_to_label(0.50).level, "Internal")
        low = parser.map_score_to_label(0.49)
        self.assertEqual(low.level, "Confidential")
        self.assertIn("Untrusted", low.categories)

    def test_assess_trusted_https_content_is_high(self) -> None:
        parser = TrustParser(trusted_domains=["example.com"])
        clean_text = "By Alice at Acme Inc. See http://ref1 and http://ref2."
        raw_html = "<meta name='author' content='Alice'><time datetime='2025-01-01'>"
        assessment = parser.assess("https://example.com/page", clean_text, raw_html)
        self.assertGreaterEqual(assessment.score, 0.8)
        self.assertEqual(assessment.label.level, "Public")


if __name__ == "__main__":
    unittest.main()
