# Platform invariants for the oracle migration

This document defines the production-sensitive behavior inherited from the HeartSignal baseline. The new oracle and `Reading` domain may call these capabilities through adapters, but must not silently change their semantics.

## 1. Credit ledger

- The balance is derived from immutable `credit_transactions`; it is never maintained as an independently mutable counter.
- One paid artifact can create at most one successful spend transaction.
- Concurrent spends cannot make a user balance negative.
- A retry of the same spend returns the existing outcome instead of writing another debit.
- A refund reverses one exact spend and is itself exactly once.
- A refunded spend cannot later grant full access.
- Ownership is checked for spend, unlock and refund operations; identifiers from another user reveal no transaction or artifact details.
- Purchased credits never expire. Credits granted by a subscription period lapse once that period has closed, through a compensating `expiry` transaction rather than any deletion, so the balance stays a plain sum of immutable rows.
- Spending is charged against lapsing subscription credits before purchased ones, an expiry never removes more than its own period granted, and it can never drive a balance negative.
- Settling a closed period is exactly once and is recorded on the period itself, so a period that had nothing left to expire is not swept again.

## 2. Access and delivery

- A paid unlock and a refund are mutually exclusive under concurrency.
- Replaying an already generated result does not call the LLM and does not charge again.
- Technical delivery failure must not create a second entitlement or second debit.
- Existing ready content remains accessible after worker or webhook retries.

## 3. Included follow-up

- One eligible paid artifact has one follow-up entitlement.
- Concurrent submissions consume the entitlement once and make at most one LLM call.
- Replays return the original completed follow-up rather than accepting a different second question.
- A technical generation failure releases the entitlement for a safe retry.
- Preview-only, deleted or unauthorized artifacts cannot use the follow-up.

## 4. Privacy and deletion

- Sensitive source content and generated private content remain encrypted at rest.
- Deleting an artifact purges its private content and encrypted follow-up history.
- Account deletion may race with payment completion without resurrecting personal data or duplicating ledger entries.
- Immutable financial records required for reconciliation remain, but personal fields are tombstoned or detached according to the existing deletion contract.
- Deletion and retention operations must not affect another user’s records.

## 5. Database and provider compatibility

- Existing Alembic revision identifiers are immutable. New oracle tables and columns require new revisions.
- Existing payment provider event identifiers, idempotency keys and reconciliation paths remain valid.
- Existing historical SKU codes may remain in ledger and provider snapshots even after the public catalog changes.
- A domain migration must use adapters around the ledger, payment, privacy and delivery services rather than rewriting those systems inside `Reading` services.

## CI enforcement

`bash scripts/run_platform_invariants.sh` executes the explicit PostgreSQL characterization suite. The main CI runs this gate before the complete test suite, so a future domain change fails early when it alters a protected invariant.

Adding an invariant requires all three changes:

1. add or identify a deterministic regression test;
2. add its exact pytest node ID to the script;
3. document the protected behavior here.

Removing or weakening an invariant requires an explicit architecture decision in the pull request description.
