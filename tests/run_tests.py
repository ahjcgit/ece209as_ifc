from __future__ import annotations

import argparse
import json
import sys
import time
import unittest
from pathlib import Path
from typing import Iterable

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

        def _normalize_error_text(test, err) -> str:
            # unittest loader/import failures can surface as strings instead of
            # exc_info tuples; normalize both shapes.
            if isinstance(err, tuple) and len(err) == 3:
                return self._exc_info_to_string(err, test)
            return str(err)

        def _case_to_dict(test, status: str, err=None) -> dict:
            data = {
                "id": test.id(),
                "status": status,
            }
            if err:
                data["error"] = _normalize_error_text(test, err)
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


LANES = ("unit", "integration", "live")


def _iter_tests(suite: unittest.TestSuite) -> Iterable[unittest.case.TestCase]:
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _iter_tests(item)
        else:
            yield item


def _test_lane(test: unittest.case.TestCase) -> str:
    method = getattr(test, test._testMethodName, None)
    if method is not None:
        lane = getattr(method, "TEST_LANE", None)
        if lane in LANES:
            return lane

    lane = getattr(test.__class__, "TEST_LANE", None)
    if lane in LANES:
        return lane

    module_obj = sys.modules.get(test.__class__.__module__)
    if module_obj is not None:
        lane = getattr(module_obj, "TEST_LANE", None)
        if lane in LANES:
            return lane

    return "unit"


def _suite_for_lane(discovered: unittest.TestSuite, lane: str) -> unittest.TestSuite:
    selected = unittest.TestSuite()
    for test in _iter_tests(discovered):
        if _test_lane(test) == lane:
            selected.addTest(test)
    return selected


def _run_lane(
    *,
    lane: str,
    discovered: unittest.TestSuite,
    verbosity: int,
) -> dict:
    suite = _suite_for_lane(discovered, lane)
    runner = JsonTestRunner(verbosity=verbosity)
    result: JsonTestResult = runner.run(suite)  # type: ignore[assignment]
    report = result.get_report()
    report["lane"] = lane
    return report


def _write_summary_markdown(report: dict, target_path: Path) -> None:
    lines: list[str] = []
    lines.append("# IFC Evaluation Summary")
    lines.append("")
    lines.append("## Overall")
    lines.append("")
    summary = report["summary"]
    lines.append(f"- Total tests: {summary['total']}")
    lines.append(f"- Failures: {summary['failures']}")
    lines.append(f"- Errors: {summary['errors']}")
    lines.append(f"- Skipped: {summary['skipped']}")
    lines.append(f"- Duration (s): {summary['duration_seconds']}")
    lines.append("")
    lines.append("## Lane Breakdown")
    lines.append("")
    for lane_name in report["meta"]["lanes_run"]:
        lane_report = report["lanes"][lane_name]
        lane_summary = lane_report["summary"]
        lines.append(
            f"- `{lane_name}`: total={lane_summary['total']}, "
            f"failures={lane_summary['failures']}, errors={lane_summary['errors']}, "
            f"skipped={lane_summary['skipped']}, duration={lane_summary['duration_seconds']}s"
        )
    lines.append("")
    lines.append("## IFC Critical Checks")
    lines.append("")
    critical_patterns = (
        "test_agent.WebAgentTests.test_run_blocks_external_llm_on_high_combined_label",
        "test_agent.WebAgentTests.test_run_blocks_user_output_above_user_max",
        "test_tools_pipeline.AgentToolsTests.test_retrieve_respects_label_cap",
        "test_ifc_window_with_logs.IFCWindowTests.test_public_window_only_shows_public_contradiction_side",
        "test_ifc_window_with_logs.IFCWindowTests.test_internal_window_excludes_confidential_for_contradiction",
        "test_ifc_window_with_logs.IFCWindowTests.test_secret_window_can_see_secret_side_of_contradiction",
    )
    all_tests: list[dict] = []
    for lane in report["lanes"].values():
        all_tests.extend(lane.get("tests", []))
    by_id = {item["id"]: item for item in all_tests}
    for test_id in critical_patterns:
        status = by_id.get(test_id, {}).get("status", "missing")
        lines.append(f"- `{test_id}`: {status}")
    lines.append("")
    lines.append("## Residual Gaps")
    lines.append("")
    lines.append("- Live lane may contain zero tests unless explicitly authored and enabled.")
    lines.append("- Local-model answer quality is not benchmarked by these deterministic checks.")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--json-path",
        default=str(PROJECT_ROOT / "test_results.json"),
        help="Where to write the JSON report.",
    )
    parser.add_argument("--verbosity", type=int, default=2, help="Verbosity for stdout.")
    parser.add_argument(
        "--lane",
        choices=("unit", "integration", "live", "all"),
        default="unit",
        help="Test lane to execute. Default keeps evaluation offline/deterministic.",
    )
    parser.add_argument(
        "--summary-md-path",
        default="",
        help="Optional path to write a markdown summary of lane and IFC-critical results.",
    )
    args = parser.parse_args()

    suite = _load_suite(PROJECT_ROOT / "tests")
    lanes_to_run = list(LANES) if args.lane == "all" else [args.lane]

    lane_reports: dict[str, dict] = {}
    was_successful = True
    for lane in lanes_to_run:
        lane_report = _run_lane(
            lane=lane,
            discovered=suite,
            verbosity=args.verbosity,
        )
        lane_reports[lane] = lane_report
        lane_failed = lane_report["summary"]["failures"] + lane_report["summary"]["errors"]
        if lane_failed > 0:
            was_successful = False

    total_summary = {
        "total": sum(lane_reports[item]["summary"]["total"] for item in lanes_to_run),
        "failures": sum(lane_reports[item]["summary"]["failures"] for item in lanes_to_run),
        "errors": sum(lane_reports[item]["summary"]["errors"] for item in lanes_to_run),
        "skipped": sum(lane_reports[item]["summary"]["skipped"] for item in lanes_to_run),
        "expected_failures": sum(
            lane_reports[item]["summary"]["expected_failures"] for item in lanes_to_run
        ),
        "unexpected_successes": sum(
            lane_reports[item]["summary"]["unexpected_successes"] for item in lanes_to_run
        ),
        "duration_seconds": round(
            sum(lane_reports[item]["summary"]["duration_seconds"] for item in lanes_to_run),
            6,
        ),
    }

    report = {
        "meta": {
            "selected_lane": args.lane,
            "lanes_run": lanes_to_run,
            "available_lanes": list(LANES),
        },
        "summary": total_summary,
        "lanes": lane_reports,
    }
    with Path(args.json_path).open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
    if args.summary_md_path:
        _write_summary_markdown(report, Path(args.summary_md_path))

    return 0 if was_successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
