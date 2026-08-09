---
name: privacy-encryption
description: Handling user content in this repo — encryption at rest, consent, oracle memory, birth profiles, deletion and retention, and keeping private data out of logs/analytics/errors. Use when touching app/repositories/private_content.py, app/services/oracle_memory*, birth_profile, data_deletion, retention, sensitive_content, analytics events, or any code that stores or logs what a user wrote.
---

# Privacy and encryption

Reference: `heartsignal/docs/privacy-deletion-retention.md`,
`heartsignal/docs/analytics-admin-observability.md`.

## Encrypt at rest

Question text, free-form context, birth data and full generated results are encrypted
(`CONTENT_ENCRYPTION_KEY`). Ciphertext lives in the private-content tables; the domain row
holds only non-sensitive state. Never add a plaintext column for "convenience" or debugging.

## Consent gates storage

- Long-term oracle memory exists **only** with explicit consent. Revoking consent purges
  every value and blocks new writes.
- A birth profile requires its own consent; revoking purges the ciphertext and blocks reuse.
- Model speculation is never stored as a biographical fact. Provenance
  (`user_stated` vs `model_inferred`) and confidence are part of the record; user-stated
  values supersede equal model inferences.
- User content is never used for training by default.

## Deletion and retention

- The user can delete: one reading, one memory item, the birth profile, or everything.
- Deleting an artifact purges its private content **and** encrypted follow-up history.
- Account deletion may race with payment completion — it must not resurrect personal data
  nor duplicate ledger entries.
- Immutable financial records required for reconciliation survive deletion; personal fields
  are tombstoned or detached per the existing deletion contract.
- Deletion and retention never touch another user's rows.
- `RAW_CONTENT_RETENTION_DAYS` drives the maintenance worker cleanup.

## Never leaves the system

Out of logs, analytics events, error metadata, failure reasons, callback data and receipts:

conversation/question text, names, goals, report bodies, birth data, Telegram identity,
receipt contact, checkout URLs/tokens, provider signatures, prompts, invalid model output,
encryption keys, stack traces with content.

Analytics uses a strict event allow-list with idempotent transition keys. HTTP correlation
uses a short `X-Correlation-ID`; Telegram correlation uses only `update_id` — never user or
chat identity.

## Proof

```bash
make gate-invariants     # includes encryption round-trip + deletion race tests
pytest tests/test_privacy_logging.py tests/test_sensitive_content.py
```

When adding a new field, answer explicitly in the PR: is it sensitive? encrypted? deleted on
account deletion? excluded from analytics and logs? A "no" to any of these needs a reason.
