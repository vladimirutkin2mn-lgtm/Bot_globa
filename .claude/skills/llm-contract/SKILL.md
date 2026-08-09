---
name: llm-contract
description: LLM provider work — the LLMClient interface, OpenAI adapter, strict structured output, repair retries, prompt packs and versioning, cost/latency telemetry. Use when editing app/providers/llm/, app/prompts/, reading_generation, or when a model call, schema validation or repair-retry behavior needs changing.
---

# LLM contract

Provider-neutral by design: `app/providers/llm/base.py` defines `LLMClient`; adapters are
`openai.py` and the deterministic `stub.py`, selected by `factory.py` from `LLM_PROVIDER`.
Local and CI always run `stub` — no test may make a billed call.

## Structured output, not "generate JSON"

- The response schema is a Pydantic model. Before the call it is deterministically reduced to
  OpenAI's strict subset (all object fields required, unsupported validation keywords
  removed); after the call the **full** strict Pydantic contract is re-validated.
- Evidence/symbol references are checked against the real source (message IDs, drawn cards,
  calculated chart facts).
- Only a fully valid result is persisted. An invalid first response is not stored.

## Retries and failure codes

- Transport/server failures retry up to `LLM_MAX_TRANSPORT_ATTEMPTS` (1–5).
  Auth and bad-request errors do **not** retry.
- An invalid result gets at most `LLM_MAX_REPAIR_ATTEMPTS` (0–1) controlled repair.
- If the repaired response is still invalid, the **second** response's category decides the
  failure code: semantic reference errors → `invalid_evidence_refs`, everything else →
  `invalid_model_output`.
- Failures surface to the user as safe messages — never internal codes, prompts, or content.

## Versioning and telemetry

Persist with every result: provider, model, prompt version, schema version, attempt count,
tokens, latency, and a safe request ID. Prompt packs live in `app/prompts/` and are
versioned (`analysis_v1`, `followup_v1`, persona packs). Changing a prompt = a new version,
not an in-place edit — stored readings must stay reproducible.

Cost and quality telemetry (`app/observability/oracle_quality.py`) is a release gate:
`make gate-quality-observability`. Spend caps and rate limits live in
`ORACLE_DAILY_SPEND_CAP_MICROUSD`, `ORACLE_MAX_RESERVED_COST_MICROUSD_PER_READING`,
`ORACLE_GENERATION_RATE_LIMIT` — reservations are conservative and denominated in microusd.

## Never in a prompt

Raw untrusted data is passed as clearly separated JSON, never merged into instructions.
Memory in particular is untrusted (`test_reading_generation_memory.py`). Prompts, invalid
responses and API keys never reach logs, analytics or failure metadata.

## Manual smoke (costs real money)

`python -m app.cli.smoke_openai` uses a fictional dialogue and prints only safe metadata.
It never runs in CI; the Bash guard hook blocks it unless you intend the spend.

Client lifecycle: one client per dispatcher lifetime, closed on shutdown. Always set a
timeout (`LLM_TIMEOUT_SECONDS`).
