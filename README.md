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
- IFC contract and threat model documented in `IFC_CONTRACT.md`

## Setup (Local LLM)
1) Install Ollama and pull a model:
   - `ollama pull qwen2.5:7b-instruct`
2) Edit `config.json` (already present in repo).
3) Run:
   - `python scripts/run_agent.py config.json https://example.com`

## Setup (API LLM, explicit opt-in)
1) Set API key:
   - `export OPENAI_API_KEY=...`
2) Update `config.json` `openai_compatible.base_url` if needed.
3) Run with explicit backend selection:
   - `python scripts/run_agent.py config.json https://example.com --llm-backend external`

`local` is the default backend, even if `OPENAI_API_KEY` is present.

## Policy Defaults
- External LLMs only receive `Public` or `Internal` labels.
- User output limited to `Confidential+PII` by default.

Adjust `config.json` to match your security policy.

## Data Stored (JSON MVP)
- `documents`: `id`, `url`, `fetched_at`, `raw_html`, `clean_text`
- `trust_assessments`: `document_id`, `score`, `label`, `signals`

Default storage file is `data/store.json` (configured under `tools.storage_path`).

## IFC Contract

The enforcement contract and threat model are captured in `IFC_CONTRACT.md`.

Key invariants:
- retrieval must respect caller clearance (`label_cap`);
- external LLM egress must satisfy external policy;
- output to user must satisfy user-output policy;
- prompt label passed to the LLM is the join of user + retrieved document labels.

## Evaluation

The project has lane-based evaluation so you can run deterministic tests by default
and opt into environment-dependent checks only when needed.

### Test Lanes
- `unit` (default): offline and deterministic, no Playwright/LLM services required.
- `integration`: environment-backed tests (for example, real Playwright scraper path).
- `live`: optional tests intended for live service checks.
- `all`: runs all lanes and writes one combined JSON artifact.

### Run Commands
- Unit lane (recommended default):
  - `python tests/run_tests.py --lane unit --verbosity 2 --json-path test_results.json`
- Integration lane:
  - `python tests/run_tests.py --lane integration --verbosity 2 --json-path test_results.json`
- Live lane:
  - `python tests/run_tests.py --lane live --verbosity 2 --json-path test_results.json`
- Full evaluation:
  - `python tests/run_tests.py --lane all --verbosity 2 --json-path test_results.json`
- Full evaluation + markdown summary:
  - `python tests/run_tests.py --lane all --verbosity 2 --json-path artifacts/test_results.json --summary-md-path artifacts/test_results_analysis.md`

### Environment Requirements
- Integration scraper tests require Playwright:
  - `pip install playwright`
  - `playwright install chromium`
- Live external LLM checks require:
  - `OPENAI_API_KEY` exported in your shell

If lane prerequisites are not available, tests are skipped with explicit reasons and
those skip reasons are captured in the JSON artifact.

### Evaluation Artifact
`tests/run_tests.py` writes `test_results.json` with:
- top-level summary totals
- lane metadata (`selected_lane`, `lanes_run`, `available_lanes`)
- per-lane summaries
- per-test statuses (`passed`, `failed`, `error`, `skipped`, etc.)
- skip reasons and error trace text when applicable

If `--summary-md-path` is provided, a concise markdown summary is also written
containing lane totals and IFC-critical test statuses.

## Local Pipeline Audit Logging

To capture an auditable run from the local backend:

- `python scripts/run_agent.py config.json https://example.com --llm-backend local --audit-json-path artifacts/pipeline_audit.json`

The audit JSON includes retrieved document labels, combined label, backend used,
and output policy decision metadata.
