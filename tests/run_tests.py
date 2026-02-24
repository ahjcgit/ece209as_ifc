from __future__ import annotations

import argparse
import json
import sys
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class JsonTestResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._start_time = time.time()
        self._all_tests: list[unittest.case.TestCase] = []

    def startTest(self, test) -> None:
        self._all_tests.append(test)
        super().startTest(test)

    def get_report(self) -> dict:
        duration_s = time.time() - self._start_time

        def _case_to_dict(test, status: str, err=None) -> dict:
            data = {
                "id": test.id(),
                "status": status,
            }
            if err:
                data["error"] = self._exc_info_to_string(err, test)
            return data

        report = {
            "summary": {
                "total": self.testsRun,
                "failures": len(self.failures),
                "errors": len(self.errors),
                "skipped": len(self.skipped),
                "expected_failures": len(self.expectedFailures),
                "unexpected_successes": len(self.unexpectedSuccesses),
                "duration_seconds": round(duration_s, 6),
            },
            "tests": [],
        }

        failed = {t.id(): err for t, err in self.failures}
        errored = {t.id(): err for t, err in self.errors}
        skipped = {t.id(): reason for t, reason in self.skipped}
        xfail = {t.id(): err for t, err in self.expectedFailures}
        xpass = {t.id(): None for t in self.unexpectedSuccesses}

        for test in self._all_tests:
            test_id = test.id()
            if test_id in failed:
                report["tests"].append(_case_to_dict(test, "failed", failed[test_id]))
            elif test_id in errored:
                report["tests"].append(_case_to_dict(test, "error", errored[test_id]))
            elif test_id in skipped:
                report["tests"].append({"id": test_id, "status": "skipped", "reason": skipped[test_id]})
            elif test_id in xfail:
                report["tests"].append(_case_to_dict(test, "expected_failure", xfail[test_id]))
            elif test_id in xpass:
                report["tests"].append({"id": test_id, "status": "unexpected_success"})
            else:
                report["tests"].append({"id": test_id, "status": "passed"})

        return report


class JsonTestRunner(unittest.TextTestRunner):
    resultclass = JsonTestResult


def _load_suite(start_dir: Path) -> unittest.TestSuite:
    loader = unittest.TestLoader()
    return loader.discover(str(start_dir), pattern="test_*.py")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--json-path",
        default=str(PROJECT_ROOT / "test_results.json"),
        help="Where to write the JSON report.",
    )
    parser.add_argument("--verbosity", type=int, default=2, help="Verbosity for stdout.")
    args = parser.parse_args()

    suite = _load_suite(PROJECT_ROOT / "tests")
    runner = JsonTestRunner(verbosity=args.verbosity)
    result: JsonTestResult = runner.run(suite)  # type: ignore[assignment]

    report = result.get_report()
    with Path(args.json_path).open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
