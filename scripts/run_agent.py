from __future__ import annotations
from urllib.parse import urlparse

import json
import os
import sys
from pathlib import Path

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


def _build_llm(config: dict):
    if os.getenv("OPENAI_API_KEY"):
        params = config["openai_compatible"]
        return OpenAICompatibleLLM(
            model=params["model"],
            base_url=params["base_url"],
        )
    params = config["ollama"]
    return OllamaLLM(model=params["model"], base_url=params["base_url"])


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: python scripts/run_agent.py <config.json> <url> [url...]")
        return 1

    config_path = Path(sys.argv[1])
    urls = sys.argv[2:]

    from urllib.parse import urlparse
    for url in urls:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            print(f"[ERROR] Invalid URL format: {url}")
            return 1

    config = _load_config(config_path)
    lattice, policy = _build_policy(config)
    llm = _build_llm(config)
    tool_cfg = config.get("tools", {})

    tools = AgentTools(
        lattice=lattice,
        storage_path=tool_cfg.get("storage_path", "data/store.json"),
        trusted_domains=tool_cfg.get("trusted_domains", []),
        blocked_domains=tool_cfg.get("blocked_domains", []),
        user_agent=tool_cfg.get("user_agent", "IFC-Agent/0.2"),
    )

    agent = WebAgent(lattice=lattice, policy=policy, llm=llm, tools=tools)

    user_prompt = "Summarize the main points."
    # user_label = make_label("Confidential", ["PII"])
    # user_label = make_label("Public")
    # user_label = make_label("Internal")
    # user_label = make_label("Confidential")
    user_label = make_label("Secret")




    try:
        result = agent.run(user_prompt, user_label, urls)
        print(result.text)
    except Exception as e:
        print(f"[ERROR] {e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
