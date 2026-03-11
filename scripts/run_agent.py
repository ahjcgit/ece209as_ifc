from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

# Ensure local package import works when running as a script.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ifc_agent.agent import WebAgent
from ifc_agent.labels import Lattice, make_label
from ifc_agent.llm import OllamaLLM, OpenAICompatibleLLM
from ifc_agent.policy import Policy
from ifc_agent.tools import AgentTools


def _load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _build_policy(config: dict) -> tuple[Lattice, Policy]:
    lattice = Lattice(config["lattice"])
    user_output_max = make_label(
        config["user_output_max"]["level"],
        config["user_output_max"].get("categories", []),
    )
    external_allowed = [
        make_label(item["level"], item.get("categories", []))
        for item in config["external_llm_allowed"]
    ]
    policy = Policy(lattice, external_allowed, user_output_max)
    return lattice, policy


def _check_ollama_available(base_url: str) -> None:
    tags_url = f"{base_url.rstrip('/')}/api/tags"
    req = urllib.request.Request(tags_url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5):
            return
    except urllib.error.URLError as exc:
        raise RuntimeError(
            "Local LLM backend selected, but Ollama is unreachable. "
            f"Start Ollama and verify connectivity at {tags_url}."
        ) from exc


def _build_llm(config: dict, backend_mode: str):
    effective_mode = backend_mode
    if backend_mode == "auto":
        effective_mode = "external" if os.getenv("OPENAI_API_KEY") else "local"

    if effective_mode == "external":
        params = config["openai_compatible"]
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError(
                "External backend selected but OPENAI_API_KEY is not set."
            )
        return OpenAICompatibleLLM(
            model=params["model"],
            base_url=params["base_url"],
        ), "external"

    params = config["ollama"]
    _check_ollama_available(params["base_url"])
    return OllamaLLM(model=params["model"], base_url=params["base_url"]), "local"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run IFC web agent on one or more URLs.")
    parser.add_argument("config_path", help="Path to config.json")
    parser.add_argument("urls", nargs="+", help="One or more URLs to scrape")
    parser.add_argument(
        "--prompt",
        default="Summarize the main points.",
        help="User prompt sent to the agent.",
    )
    parser.add_argument(
        "--user-level",
        default="Secret",
        help="User clearance level label (for example: Public/Internal/Confidential/Secret).",
    )
    parser.add_argument(
        "--user-categories",
        default="",
        help="Comma-separated user label categories (for example: PII,Untrusted).",
    )
    parser.add_argument(
        "--llm-backend",
        choices=("local", "external", "auto"),
        default=None,
        help=(
            "LLM backend selection override. "
            "'local' is recommended and default, 'external' requires OPENAI_API_KEY, "
            "'auto' picks external if a key is available."
        ),
    )
    parser.add_argument(
        "--audit-json-path",
        default="",
        help="Optional path to write run audit metadata as JSON.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    config_path = Path(args.config_path)
    urls = args.urls

    for url in urls:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            print(f"[ERROR] Invalid URL format: {url}")
            return 1

    config = _load_config(config_path)
    lattice, policy = _build_policy(config)
    backend_mode = args.llm_backend or config.get("llm_backend", "local")
    llm, resolved_backend = _build_llm(config, backend_mode)
    tool_cfg = config.get("tools", {})

    tools = AgentTools(
        lattice=lattice,
        storage_path=tool_cfg.get("storage_path", "data/store.json"),
        trusted_domains=tool_cfg.get("trusted_domains", []),
        blocked_domains=tool_cfg.get("blocked_domains", []),
        user_agent=tool_cfg.get("user_agent", "IFC-Agent/0.2"),
    )
    
    agent = WebAgent(lattice=lattice, policy=policy, llm=llm, tools=tools)
 
    user_prompt = args.prompt
    categories = [item.strip() for item in args.user_categories.split(",") if item.strip()]
    user_label = make_label(args.user_level, categories)


    try:
        result = agent.run(user_prompt, user_label, urls)
        print(f"[INFO] LLM backend: {resolved_backend} ({llm.name})")
        print(result.text)
        if args.audit_json_path:
            audit_path = Path(args.audit_json_path)
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "backend_mode": resolved_backend,
                "llm_name": llm.name,
                "result_label": str(result.label),
                "result_text": result.text,
                "audit": result.audit or {},
            }
            with audit_path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
            print(f"[INFO] Wrote audit log: {audit_path}")
    except Exception as e:
        print(f"[ERROR] {e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
