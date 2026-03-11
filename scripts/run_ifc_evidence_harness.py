from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
import urllib.error
import urllib.request

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ifc_agent.agent import WebAgent
from ifc_agent.evidence_harness import (
    HarnessCase,
    StoreBackedTools,
    build_default_cases,
    build_retrieval_snapshot,
    expected_outcome_for_case,
    load_seeded_documents,
    parse_evaluator_verdict,
)
from ifc_agent.labels import Label, Lattice, make_label
from ifc_agent.llm import BaseLLM, LLMResponse, OllamaLLM, OpenAICompatibleLLM
from ifc_agent.policy import Policy


class ForceLabelLLM(BaseLLM):
    def __init__(self, backend: BaseLLM, forced_label: Label) -> None:
        super().__init__(name=f"forced-label->{backend.name}", is_external=backend.is_external)
        self._backend = backend
        self._forced_label = forced_label
        self.calls = 0

    def generate(self, prompt: str, label: Label) -> LLMResponse:
        self.calls += 1
        response = self._backend.generate(prompt, label)
        return LLMResponse(text=response.text, label=self._forced_label)


def _load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _build_policy(config: dict) -> tuple[Lattice, Policy]:
    lattice = Lattice(config["lattice"])
    external_allowed = [
        make_label(item["level"], item.get("categories", []))
        for item in config["external_llm_allowed"]
    ]
    user_output_max = make_label(
        config["user_output_max"]["level"],
        config["user_output_max"].get("categories", []),
    )
    return lattice, Policy(lattice, external_allowed, user_output_max)


def _base_answer_llm(config: dict) -> BaseLLM:
    params = config["ollama"]
    return OllamaLLM(
        model=params["model"],
        base_url=params.get("base_url", "http://127.0.0.1:11434"),
    )


def _external_answer_llm(config: dict) -> BaseLLM:
    params = config["openai_compatible"]
    return OpenAICompatibleLLM(model=params["model"], base_url=params["base_url"])


def _build_case_llm(base_llm: BaseLLM, case: HarnessCase) -> BaseLLM:
    llm: BaseLLM = base_llm
    if case.forced_response_label is not None:
        llm = ForceLabelLLM(llm, case.forced_response_label)
    return llm


def _actual_outcome(result_text: str, blocked_reason: str, error_text: str) -> str:
    if error_text:
        return "error"
    if blocked_reason:
        lower = blocked_reason.lower()
        if "external llm policy" in lower:
            return "blocked_external"
        if "user clearance" in lower:
            return "blocked_user"
        return "blocked_other"
    if result_text.startswith("No relevant or authorized documents"):
        return "no_docs"
    return "allowed"


def _evaluate_case_with_llm(
    evaluator: BaseLLM | None,
    case_payload: dict[str, object],
) -> dict[str, object]:
    if evaluator is None:
        return {
            "status": "skipped",
            "raw_response": "",
            "verdict": "",
            "confidence": 0.0,
            "rationale": "Evaluator skipped (missing OPENAI_API_KEY or disabled).",
            "mismatch": "",
            "error": "",
        }
    prompt = (
        "You are an IFC policy auditor. Decide whether enforcement outcome matches expectation.\n"
        "Return ONLY JSON with keys: verdict, confidence, rationale, mismatch.\n"
        "verdict must be pass or fail. confidence must be 0..1.\n\n"
        f"CASE:\n{json.dumps(case_payload, indent=2)}\n"
    )
    try:
        response = evaluator.generate(prompt, make_label("Public"))
        raw = response.text
    except Exception as exc:
        return {
            "status": "error",
            "raw_response": "",
            "verdict": "",
            "confidence": 0.0,
            "rationale": "",
            "mismatch": "",
            "error": str(exc),
        }
    try:
        verdict = parse_evaluator_verdict(raw)
        return {
            "status": "ok",
            "raw_response": raw,
            "verdict": verdict.verdict,
            "confidence": verdict.confidence,
            "rationale": verdict.rationale,
            "mismatch": verdict.mismatch,
            "error": "",
        }
    except Exception as exc:
        return {
            "status": "parse_error",
            "raw_response": raw,
            "verdict": "",
            "confidence": 0.0,
            "rationale": "",
            "mismatch": "",
            "error": str(exc),
        }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run IFC evidence harness on store.json examples with LLM evaluator."
    )
    parser.add_argument("--config-path", default="config.json")
    parser.add_argument("--store-path", default="data/store.json")
    parser.add_argument(
        "--answer-backends",
        default="local,external",
        help="Comma-separated real answer backends to run: local,external",
    )
    parser.add_argument(
        "--output-json-path",
        default="artifacts/ifc_evidence_harness.json",
    )
    parser.add_argument(
        "--output-md-path",
        default="artifacts/ifc_evidence_harness.md",
    )
    parser.add_argument(
        "--evaluator-backend",
        choices=("local", "external"),
        default="local",
        help="Evaluator backend to use. 'local' uses Ollama, 'external' uses OpenAI-compatible API.",
    )
    parser.add_argument(
        "--evaluator-model",
        default="",
        help=(
            "Evaluator model name. "
            "For local backend this should be an Ollama model; for external backend an OpenAI-compatible model."
        ),
    )
    parser.add_argument(
        "--skip-evaluator",
        action="store_true",
        help="Skip LLM evaluator pass/fail judgement and only record raw harness outcomes.",
    )
    parser.add_argument(
        "--strict-exit",
        action="store_true",
        help="Exit non-zero when enforcement mismatches exist.",
    )
    parser.add_argument(
        "--allow-missing-backends",
        action="store_true",
        help="If set, mark unavailable answer backends as skipped instead of failing the run.",
    )
    return parser.parse_args()


def _check_ollama_available(base_url: str) -> bool:
    tags_url = f"{base_url.rstrip('/')}/api/tags"
    req = urllib.request.Request(tags_url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5):
            return True
    except urllib.error.URLError:
        return False


def _normalize_backends(raw: str) -> list[str]:
    items = [item.strip() for item in raw.split(",") if item.strip()]
    valid = {"local", "external"}
    if not items or any(item not in valid for item in items):
        raise ValueError("--answer-backends must contain one or both of: local,external")
    deduped: list[str] = []
    for item in items:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _write_markdown_report(report: dict, target_path: Path) -> None:
    lines: list[str] = []
    summary = report["summary"]
    lines.append("# IFC Evidence Harness Report")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Run timestamp: {report['meta']['ran_at_utc']}")
    lines.append(f"- Cases total: {summary['total_cases']}")
    lines.append(f"- Cases executed: {summary['executed_cases']}")
    lines.append(f"- Cases skipped (backend unavailable): {summary['skipped_cases']}")
    lines.append(f"- Backends requested: {', '.join(report['meta']['answer_backends_requested'])}")
    lines.append(f"- Backends executed: {', '.join(report['meta']['answer_backends_executed'])}")
    lines.append(f"- Enforcement matches expected: {summary['enforcement_match_count']}")
    lines.append(f"- Enforcement mismatches: {summary['enforcement_mismatch_count']}")
    lines.append(f"- Blocked (external): {summary['blocked_external_cases']}")
    lines.append(f"- Blocked (user): {summary['blocked_user_cases']}")
    lines.append(f"- No docs due to IFC window: {summary['no_docs_cases']}")
    lines.append(f"- Allowed responses: {summary['allowed_cases']}")
    lines.append(f"- Errors: {summary['error_cases']}")
    lines.append("")
    lines.append("## Evaluator")
    lines.append("")
    lines.append(f"- Evaluator status: {summary['evaluator_status']}")
    lines.append(f"- Evaluator pass verdicts: {summary['evaluator_pass_count']}")
    lines.append(f"- Evaluator fail verdicts: {summary['evaluator_fail_count']}")
    lines.append(f"- Evaluator parse errors: {summary['evaluator_parse_error_count']}")
    lines.append("")
    lines.append("## Backend Health")
    lines.append("")
    lines.append(f"- Local backend available: {report['meta']['local_backend_available']}")
    lines.append(f"- External backend available: {report['meta']['external_backend_available']}")
    lines.append("")
    lines.append("## IFC Verdict")
    lines.append("")
    lines.append(f"- Final enforcement verdict: {summary['final_ifc_verdict']}")
    lines.append(f"- Reason: {summary['final_ifc_reason']}")
    lines.append("")
    lines.append("## Case Results")
    lines.append("")
    for case in report["cases"]:
        lines.append(
            f"- `{case['name']}[{case['answer_backend']}]` | expected={case['expected_outcome']} | actual={case['actual_outcome']} "
            f"| match={case['enforcement_match']} | evaluator={case['evaluator']['verdict'] or case['evaluator']['status']}"
        )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = _parse_args()
    requested_backends = _normalize_backends(args.answer_backends)
    config = _load_config(Path(args.config_path))
    lattice, policy = _build_policy(config)
    local_backend_available = _check_ollama_available(config["ollama"]["base_url"])
    external_backend_available = bool(os.getenv("OPENAI_API_KEY"))
    available_by_name = {
        "local": local_backend_available,
        "external": external_backend_available,
    }
    unavailable = [name for name in requested_backends if not available_by_name[name]]
    if unavailable and not args.allow_missing_backends:
        print(
            "[ERROR] Required real answer backend(s) unavailable:",
            ",".join(unavailable),
            "| use --allow-missing-backends to continue with skips.",
        )
        return 1

    answer_llms: dict[str, BaseLLM] = {}
    if "local" in requested_backends and local_backend_available:
        answer_llms["local"] = _base_answer_llm(config)
    if "external" in requested_backends and external_backend_available:
        answer_llms["external"] = _external_answer_llm(config)

    seeded_docs = load_seeded_documents(args.store_path)
    cases = build_default_cases(seeded_docs)

    evaluator: BaseLLM | None = None
    evaluator_status = "disabled"
    if not args.skip_evaluator:
        if args.evaluator_backend == "local":
            if local_backend_available:
                evaluator_cfg = config.get("ollama", {})
                evaluator_model = args.evaluator_model or evaluator_cfg.get(
                    "model", "qwen2.5:7b-instruct"
                )
                evaluator = OllamaLLM(
                    model=evaluator_model,
                    base_url=evaluator_cfg.get("base_url", "http://127.0.0.1:11434"),
                )
                evaluator_status = f"enabled:{evaluator.name}"
            else:
                evaluator_status = "skipped_local_evaluator_backend_unavailable"
        else:
            if config.get("openai_compatible") and os.getenv("OPENAI_API_KEY"):
                evaluator_cfg = config["openai_compatible"]
                evaluator_model = args.evaluator_model or evaluator_cfg.get(
                    "model", "gpt-4o-mini"
                )
                evaluator = OpenAICompatibleLLM(
                    model=evaluator_model,
                    base_url=evaluator_cfg["base_url"],
                )
                evaluator_status = f"enabled:{evaluator.name}"
            else:
                evaluator_status = "skipped_missing_api_key"

    rows: list[dict[str, object]] = []
    for case in cases:
        for backend_name in requested_backends:
            if backend_name not in case.target_backends:
                continue
            if backend_name not in answer_llms:
                rows.append(
                    {
                        "name": case.name,
                        "description": case.description,
                        "answer_backend": backend_name,
                        "prompt": case.prompt,
                        "user_label": str(case.user_label),
                        "target_backends": list(case.target_backends),
                        "forced_response_label": str(case.forced_response_label)
                        if case.forced_response_label is not None
                        else "",
                        "expected_outcome": expected_outcome_for_case(case),
                        "actual_outcome": "skipped_backend_unavailable",
                        "enforcement_match": False,
                        "blocked_reason": "",
                        "error_text": "",
                        "result_label": "",
                        "result_text": "",
                        "audit": {},
                        "evaluator": {
                            "status": "skipped",
                            "raw_response": "",
                            "verdict": "",
                            "confidence": 0.0,
                            "rationale": "Case skipped because requested real backend is unavailable.",
                            "mismatch": "",
                            "error": "",
                        },
                    }
                )
                continue

            tools = StoreBackedTools(
                lattice=lattice,
                storage_path=args.store_path,
                allowed_document_ids=case.document_ids,
            )
            llm = _build_case_llm(answer_llms[backend_name], case)
            agent = WebAgent(lattice=lattice, policy=policy, llm=llm, tools=tools)

            result_text = ""
            result_label = ""
            blocked_reason = ""
            error_text = ""
            audit: dict[str, object] = {}
            try:
                result = agent.run(case.prompt, case.user_label, urls=[])
                result_text = result.text
                result_label = str(result.label)
                audit = result.audit or {}
            except PermissionError as exc:
                blocked_reason = str(exc)
            except Exception as exc:
                error_text = str(exc)

            actual = _actual_outcome(result_text, blocked_reason, error_text)
            expected = expected_outcome_for_case(case)
            enforcement_match = actual == expected
            case_payload = {
                "case_name": case.name,
                "answer_backend": backend_name,
                "case_description": case.description,
                "prompt": case.prompt,
                "user_label": str(case.user_label),
                "candidate_docs": build_retrieval_snapshot(seeded_docs, case.document_ids),
                "expected_outcome": expected,
                "actual_outcome": actual,
                "blocked_reason": blocked_reason,
                "error_text": error_text,
                "result_label": result_label,
                "result_text_preview": result_text[:320],
                "audit": audit,
                "policy": {
                    "external_llm_allowed": [
                        str(make_label(item["level"], item.get("categories", [])))
                        for item in config["external_llm_allowed"]
                    ],
                    "user_output_max": str(
                        make_label(
                            config["user_output_max"]["level"],
                            config["user_output_max"].get("categories", []),
                        )
                    ),
                },
                "enforcement_match": enforcement_match,
            }
            evaluator_row = _evaluate_case_with_llm(evaluator, case_payload)
            rows.append(
                {
                    "name": case.name,
                    "description": case.description,
                    "answer_backend": backend_name,
                    "prompt": case.prompt,
                    "user_label": str(case.user_label),
                    "target_backends": list(case.target_backends),
                    "forced_response_label": str(case.forced_response_label)
                    if case.forced_response_label is not None
                    else "",
                    "expected_outcome": expected,
                    "actual_outcome": actual,
                    "enforcement_match": enforcement_match,
                    "blocked_reason": blocked_reason,
                    "error_text": error_text,
                    "result_label": result_label,
                    "result_text": result_text,
                    "audit": audit,
                    "evaluator": evaluator_row,
                }
            )

    executed_cases = [
        item for item in rows if item["actual_outcome"] != "skipped_backend_unavailable"
    ]
    summary = {
        "total_cases": len(rows),
        "executed_cases": len(executed_cases),
        "enforcement_match_count": sum(1 for item in executed_cases if item["enforcement_match"]),
        "enforcement_mismatch_count": sum(
            1 for item in executed_cases if not item["enforcement_match"]
        ),
        "skipped_cases": sum(
            1 for item in rows if item["actual_outcome"] == "skipped_backend_unavailable"
        ),
        "blocked_external_cases": sum(1 for item in rows if item["actual_outcome"] == "blocked_external"),
        "blocked_user_cases": sum(1 for item in rows if item["actual_outcome"] == "blocked_user"),
        "no_docs_cases": sum(1 for item in rows if item["actual_outcome"] == "no_docs"),
        "allowed_cases": sum(1 for item in rows if item["actual_outcome"] == "allowed"),
        "error_cases": sum(1 for item in rows if item["actual_outcome"] == "error"),
        "evaluator_status": evaluator_status,
        "evaluator_pass_count": sum(
            1 for item in rows if item["evaluator"].get("verdict") == "pass"
        ),
        "evaluator_fail_count": sum(
            1 for item in rows if item["evaluator"].get("verdict") == "fail"
        ),
        "evaluator_parse_error_count": sum(
            1 for item in rows if item["evaluator"].get("status") == "parse_error"
        ),
    }
    if summary["executed_cases"] == 0:
        final_verdict = "INCONCLUSIVE"
        final_reason = "No cases executed due to unavailable requested answer backends."
    elif summary["enforcement_mismatch_count"] == 0 and summary["error_cases"] == 0:
        final_verdict = "PASS"
        final_reason = "All executed cases matched expected IFC outcomes without runtime errors."
    elif summary["enforcement_mismatch_count"] > 0:
        final_verdict = "FAIL"
        final_reason = "One or more executed cases deviated from expected IFC enforcement outcomes."
    else:
        final_verdict = "INCONCLUSIVE"
        final_reason = "No mismatches, but runtime errors occurred."
    summary["final_ifc_verdict"] = final_verdict
    summary["final_ifc_reason"] = final_reason
    by_backend: dict[str, dict[str, int]] = {}
    for backend_name in requested_backends:
        subset = [item for item in rows if item["answer_backend"] == backend_name]
        by_backend[backend_name] = {
            "total": len(subset),
            "executed": sum(
                1 for item in subset if item["actual_outcome"] != "skipped_backend_unavailable"
            ),
            "matches": sum(
                1
                for item in subset
                if item["actual_outcome"] != "skipped_backend_unavailable"
                and item["enforcement_match"]
            ),
            "mismatches": sum(
                1
                for item in subset
                if item["actual_outcome"] != "skipped_backend_unavailable"
                and not item["enforcement_match"]
            ),
            "skipped": sum(
                1 for item in subset if item["actual_outcome"] == "skipped_backend_unavailable"
            ),
            "errors": sum(1 for item in subset if item["actual_outcome"] == "error"),
        }
    summary["by_backend"] = by_backend
    report = {
        "meta": {
            "ran_at_utc": datetime.now(timezone.utc).isoformat(),
            "config_path": args.config_path,
            "store_path": args.store_path,
            "answer_backends_requested": requested_backends,
            "answer_backends_executed": sorted(answer_llms.keys()),
            "local_backend_available": local_backend_available,
            "external_backend_available": external_backend_available,
            "evaluator_backend": args.evaluator_backend,
            "evaluator_model": args.evaluator_model,
            "evaluator_status": evaluator_status,
        },
        "summary": summary,
        "cases": rows,
    }

    output_json = Path(args.output_json_path)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    with output_json.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)

    output_md = Path(args.output_md_path)
    _write_markdown_report(report, output_md)

    print(f"[INFO] Wrote evidence JSON: {output_json}")
    print(f"[INFO] Wrote evidence markdown: {output_md}")
    print(
        "[INFO] Cases:",
        summary["total_cases"],
        "| matches:",
        summary["enforcement_match_count"],
        "| mismatches:",
        summary["enforcement_mismatch_count"],
        "| final:",
        summary["final_ifc_verdict"],
    )
    if args.strict_exit and summary["final_ifc_verdict"] != "PASS":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

