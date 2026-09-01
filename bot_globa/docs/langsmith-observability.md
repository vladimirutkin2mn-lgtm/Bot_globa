# LangSmith observability v1

Numa can export privacy-safe LLM traces to LangSmith without replacing the existing
provider-neutral `LLMClient`, structured-output validation, Oracle memory or safety layers.

## Why this integration is narrow

LangSmith is used only as an external observability/evaluation surface. Numa remains the
source of truth for orchestration, encrypted memory, retries, validation, billing and
release controls.

The first version uses LangSmith's documented REST run API through the project's existing
`httpx` dependency. This deliberately avoids pulling LangChain orchestration into the
runtime merely to gain tracing.

## Privacy contract

Every LangSmith LLM run contains only operational data:

- application environment;
- persona code, when already available as safe telemetry;
- prompt version, but never prompt text;
- primary vs repair attempt;
- provider and model;
- input/output token counts;
- provider latency;
- a bounded internal failure code;
- project and privacy-safe tags.

The integration MUST NOT send:

- system or user prompts;
- user questions or optional context;
- schemas;
- memory values;
- Telegram/user IDs;
- reading/message IDs;
- participant labels or names;
- provider request IDs;
- generated model payloads;
- exception messages or tracebacks.

These exclusions are regression-tested in `tests/test_langsmith_observability.py`.

## Failure isolation

Trace submission is best-effort and happens in background tasks after the model call. A
LangSmith timeout, HTTP error or outage must never fail or delay a reading.

At process shutdown the wrapper waits for pending trace tasks before closing its HTTP
client. If the in-memory pending limit is reached, new traces are dropped and only a
content-free warning is logged.

## Configuration

Tracing is disabled by default.

```env
LANGSMITH_ENABLED=false
LANGSMITH_API_KEY=
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_PROJECT=numa-oracle
LANGSMITH_WORKSPACE_ID=
LANGSMITH_TRACE_TIMEOUT_SECONDS=2
LANGSMITH_MAX_PENDING_TRACES=100
```

For an EU LangSmith workspace, use
`https://eu.api.smith.langchain.com`. The endpoint must be HTTPS in production.

If an API key is scoped to multiple workspaces, set `LANGSMITH_WORKSPACE_ID`; it is sent
as LangSmith's documented `x-tenant-id` header.

## Runtime coverage

The wrapper is attached to:

1. Telegram Oracle runtime: Tarot, Love Oracle, Mystical Psychologist, Horoscope and
   follow-up model calls;
2. durable Oracle memory extraction worker.

The existing PostgreSQL analytics and `OracleQualityObserver` remain enabled in parallel.
LangSmith is additive, not a replacement.

## Next step

Once enough traces exist, create versioned LangSmith datasets from deliberately curated
non-private fixtures and use them for prompt/model experiments. Production user text must
not be copied into datasets by default.
