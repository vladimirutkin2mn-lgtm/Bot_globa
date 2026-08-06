# ORA-306 memory quality invariants

This milestone improves memory quality without treating topic as an eligibility or deletion rule.

## Exact deduplication

- Exact identity is a keyed HMAC over the normalized value and memory kind.
- The plaintext value is never stored in operational metadata.
- One user may have at most one active item with the same fingerprint.
- Existing active rows receive fingerprints lazily only after consent has been checked and their ciphertext has been authenticated.

## Supersession

- A user correction retires the previous item and creates a new `user_stated` item.
- The replacement points to the retired item through non-secret UUID metadata.
- A model inference is never rewritten in place as though it had always been user-provided.

## Staleness

- Staleness is metadata, not deletion and not a topic filter.
- A stale item may still be retrieved when relevant, but receives a deterministic ranking penalty.
- Stable categories such as birth profile do not expire automatically.

## Quality metrics

- Metrics contain only counts and timestamps, never decrypted values or fingerprints.
- Counts distinguish active, stale, user-stated, model-inferred and superseded items.

## Privacy

- Revocation and deletion continue to purge ciphertext.
- Fingerprints are purpose-separated keyed HMAC values, not public hashes.
- High-stakes medical, legal, financial, gambling, abuse, self-harm or crisis content is neither suppressed nor preferentially retained solely because of topic.
