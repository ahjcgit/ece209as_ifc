# Mock Websites for IFC Pipeline Simulation

This folder contains local HTML pages you can host with a simple static server
to simulate mixed trust and sensitivity inputs for the web agent.

## Start a local website server

From repository root:

- PowerShell:
  - `python -m http.server 8000 --directory mock_web`
- Bash/macOS/Linux:
  - `python -m http.server 8000 --directory mock_web`

Base URL:

- `http://localhost:8000`

## Suggested pipeline run

Use multiple URLs at once so retrieval has conflicting and mixed-sensitivity
sources:

`python scripts/run_agent.py config.json http://localhost:8000/01_public_research.html http://localhost:8000/02_internal_ops_update.html http://localhost:8000/03_confidential_hr_incident.html http://localhost:8000/04_low_trust_rumor_blog.html --llm-backend local --prompt "Summarize the current incident status and key actions." --user-level Internal --audit-json-path artifacts/mock_web_pipeline_audit.json`

## Page set and intent

- `01_public_research.html`
  - High-structure, citation-heavy, author/date metadata.
  - Intended to score as relatively more trustworthy.

- `02_internal_ops_update.html`
  - Internal operations update with partially sensitive context.

- `03_confidential_hr_incident.html`
  - Contains explicit confidential and PII-like fields (employee IDs, phone).

- `04_low_trust_rumor_blog.html`
  - Rumor-heavy content with weak sourcing and boilerplate/spam text.
  - Intended to score as lower trust.

- `05_conflicting_public_claim.html`
  - Public claim for contradiction testing.

- `06_conflicting_secret_claim.html`
  - Higher-sensitivity contradictory claim for IFC window tests.

- `07_vendor_security_advisory.html`
  - Structured advisory with refs and mitigation actions.

- `08_phishing_forum_post.html`
  - Adversarial-style page with suspicious instructions.

## Optional config tweak for trust simulation

For local hosting on `localhost`, you can treat it as trusted during simulation
to produce a wider score spread:

```json
"tools": {
  "trusted_domains": ["localhost", "127.0.0.1"],
  "blocked_domains": []
}
```
