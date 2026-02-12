# IFC Web Agent (Small-Scale)

This is a minimal Python web agent with Information Flow Control (IFC) that runs
on local hardware by default and can switch to an API-backed LLM by setting an
API key.

## Features
- Simple IFC lattice + labels + join operation
- Policy gate for external LLM egress and user output
- Local LLM via Ollama (default)
- Optional OpenAI-compatible API usage via API key
- Lightweight web fetching (stdlib only)

## Hardware Fit
Your GPUs (RTX 4080 16GB, 1070 Ti 8GB) can run 3–8B models locally. Use the
4080 for a 7–8B model; use a 3–4B model on the 1070 Ti if needed.

## Setup (Local LLM)
1) Install Ollama and pull a model:
   - `ollama pull qwen2.5:7b-instruct`
2) Copy and edit config:
   - `cp config.example.json config.json`
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

