# ORA-306 memory quality invariants

This milestone improves memory quality without treating topic as an eligibility or deletion rule.

## Exact deduplication

- Exact identity is a keyed HMAC over the normalized value and memory kind.
- Fingerprints are computed transiently only after consent has been checked and ciphertext has been authenticated.
- Neither plaintext nor the fingerprint is stored in operational metadata.
- Every quality-managed write reconciles legacy duplicates under the existing per-user database lock.

## Supersession

- A user correction retires the previous item and creates a new `user_stated` item.
- An exact `user_stated` value retires an equal `model_inferred` value instead of rewriting its provenance in place.
- A model inference is never presented as though it had always been user-provided.

## Staleness

- Staleness is a deterministic age policy, not deletion and not a topic filter.
- A stale item may still be retrieved when relevant, but receives a ranking penalty.
- Stable categories such as birth profile do not expire automatically.

## Quality metrics

- Metrics contain only counts and timestamps, never decrypted values or fingerprints.
- Counts distinguish active, stale, user-stated, model-inferred, corrected and duplicate groups.

## Privacy

- Revocation, reconciliation and deletion continue to purge ciphertext.
- Fingerprints are purpose-separated keyed HMAC values, not public hashes.
- High-stakes medical, legal, financial, gambling, abuse, self-harm or crisis content is neither suppressed nor preferentially retained solely because of topic.
