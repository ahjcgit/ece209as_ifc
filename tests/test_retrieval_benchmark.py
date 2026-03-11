from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ifc_agent.labels import Label, Lattice, make_label
from ifc_agent.retrieval import Retriever
from ifc_agent.storage import Document, StoredTrustAssessment


@dataclass(frozen=True)
class RetrievalCase:
    query: str
    label_cap: Label
    expected_ids: set[str]
    top_k: int = 3


class RetrievalBenchmarkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lattice = Lattice(["Public", "Internal", "Confidential", "Secret"])
        self.retriever = Retriever(self.lattice)
        self.documents = [
            Document("d1", "https://facts.local/1", "2026-01-01T00:00:00+00:00", "<html></html>", "James is wearing a red hat."),
            Document("d2", "https://facts.local/2", "2026-01-01T00:00:00+00:00", "<html></html>", "James is wearing a blue hat."),
            Document("d3", "https://facts.local/3", "2026-01-01T00:00:00+00:00", "<html></html>", "Maria drives a white car."),
            Document("d4", "https://facts.local/4", "2026-01-01T00:00:00+00:00", "<html></html>", "The launch code word is ORBIT."),
            Document("d5", "https://facts.local/5", "2026-01-01T00:00:00+00:00", "<html></html>", "The server location is Building A."),
        ]
        self.assessments = [
            StoredTrustAssessment("d1", 0.95, make_label("Public"), {}),
            StoredTrustAssessment("d2", 0.95, make_label("Secret"), {}),
            StoredTrustAssessment("d3", 0.95, make_label("Public"), {}),
            StoredTrustAssessment("d4", 0.90, make_label("Internal"), {}),
            StoredTrustAssessment("d5", 0.95, make_label("Public"), {}),
        ]

    def test_benchmark_precision_and_hit_rate(self) -> None:
        cases = [
            RetrievalCase(
                query="james red hat",
                label_cap=make_label("Public"),
                expected_ids={"d1"},
            ),
            RetrievalCase(
                query="launch code word",
                label_cap=make_label("Public"),
                expected_ids=set(),
            ),
            RetrievalCase(
                query="launch code word",
                label_cap=make_label("Internal"),
                expected_ids={"d4"},
            ),
            RetrievalCase(
                query="server location building",
                label_cap=make_label("Public"),
                expected_ids={"d5"},
            ),
            RetrievalCase(
                query="james hat",
                label_cap=make_label("Secret"),
                expected_ids={"d1", "d2"},
            ),
        ]

        precision_scores: list[float] = []
        hit_count = 0

        for case in cases:
            retrieved = self.retriever.retrieve(
                query=case.query,
                documents=self.documents,
                assessments=self.assessments,
                label_cap=case.label_cap,
                top_k=case.top_k,
            )
            retrieved_ids = {doc.id for doc in retrieved}

            # IFC benchmark constraint: all returned labels must flow to caller cap.
            for item in retrieved:
                self.assertTrue(
                    self.lattice.can_flow(item.label, case.label_cap),
                    f"Doc {item.id} exceeded cap {case.label_cap}",
                )

            if not case.expected_ids:
                case_precision = 1.0 if not retrieved else 0.0
                hit = not retrieved
            else:
                relevant = len(retrieved_ids.intersection(case.expected_ids))
                case_precision = relevant / max(1, len(retrieved_ids))
                hit = relevant > 0

            precision_scores.append(case_precision)
            if hit:
                hit_count += 1

        precision_at_k = sum(precision_scores) / len(precision_scores)
        hit_rate = hit_count / len(cases)

        # Conservative targets for current token-overlap retriever.
        self.assertGreaterEqual(precision_at_k, 0.60)
        self.assertGreaterEqual(hit_rate, 0.80)


if __name__ == "__main__":
    unittest.main()
