# IFC Web Agent (Tool-First)

This project is a minimal Python web agent with Information Flow Control (IFC).
It is now tool-first: scrape/parse/store/retrieve are explicit tools, while IFC
policy enforcement stays in the main agent.

## Features
- Simple IFC lattice + labels + join operation
- Policy gate for external LLM egress and user output
- Tool contracts:
  - `scrape_parse_store(urls, scrape_label?)`
  - `retrieve_by_query(query, label_cap?)`
- Deterministic trust parser (score + auditable signals)
- JSON storage backend for documents and trust assessments
- Local LLM via Ollama (default)
- Optional OpenAI-compatible API usage via API key

## Setup (Local LLM)
1) Install Ollama and pull a model:
   - `ollama pull qwen2.5:7b-instruct`
2) Edit `config.json` (already present in repo).
3) Run:
   - `python scripts/run_agent.py config.json https://example.com`

## Setup (API LLM)
1) Set API key:
   - `export OPENAI_API_KEY=...`
2) Update `config.json` `openai_compatible.base_url` if needed.
3) Run the same script; it will use the API automatically.

## Policy Defaults
- External LLMs only receive `Public` or `Internal` labels.
- User output limited to `Confidential+PII` by default.

Adjust `config.json` to match your security policy.

## Data Stored (JSON MVP)
- `documents`: `id`, `url`, `fetched_at`, `raw_html`, `clean_text`
- `trust_assessments`: `document_id`, `score`, `label`, `signals`

Default storage file is `data/store.json` (configured under `tools.storage_path`).
