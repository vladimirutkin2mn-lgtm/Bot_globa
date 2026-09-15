# Paid follow-up question

A completed paid full report includes exactly one contextual follow-up question.

## Correctness model

- Eligibility is tied to an owned `completed` analysis with `report_access=full`, a positive
  paid cost, and the original full-access ledger transaction.
- Reservation locks the analysis first and creates at most one claim-fenced entitlement row.
- Provider I/O happens outside the database transaction.
- A live lease returns `processing`; an expired lease can be reclaimed with a new claim ID.
- Only the current claim can complete or release the entitlement.
- Success stores the encrypted question and answer and consumes the entitlement exactly once.
- Technical failure clears private question/answer content and returns the entitlement to
  `available`.
- Replayed callbacks return the stored answer without a second LLM call.

## Privacy and safety

The follow-up prompt receives only the validated structured report and a bounded question. It
never receives the normalized source conversation. Question and answer history are encrypted
with separate purpose-derived keys. Analytics and logs contain only identifiers, status,
prompt version, attempt counts, and safe failure categories.

The answer can reference only existing structured report sections. It cannot weaken a high-risk
safety signal from the primary report. Soft-deleting the analysis removes the encrypted follow-up
row through a database trigger.

## Operations

A reserved row with an expired lease is safe to reclaim. A completed row is immutable through the
public service boundary. Corrupted encrypted history is not retried automatically; it is surfaced
as support-required. Migration `20260805_15` refuses downgrade while any entitlement state exists.

## OpenAI staging acceptance checklist

This checklist is the live procedure for the `openai_followup_staging` release gate. Run it only
against the exact staging release being attested, with a real staging OpenAI key and configured
staging model. Mock/fake provider results and CI are not acceptance evidence.

1. Confirm the staging release identity is current and `/admin/release-readiness` reports
   `app_env=staging`, the expected code SHA/schema/checklist tuple, and this gate as `missing` or a
   prior result as `stale`.
2. Complete a paid full report that is eligible for one contextual follow-up and verify exactly one
   follow-up entitlement is `available` before provider I/O begins.
3. Submit a normal bounded follow-up question and exercise the real configured OpenAI model. Verify
   a valid answer is stored and the entitlement becomes consumed exactly once.
4. Replay the same callback/request after success and verify the stored answer is returned without
   a second provider call or a second entitlement consumption.
5. Verify the provider context boundary using privacy-safe observability: only the validated
   structured report plus the bounded follow-up question may enter the follow-up prompt. The
   normalized source conversation and unrelated private state must not be added to the provider
   context. Do not record the private question, answer or prompt body as gate evidence.
6. Exercise the configured structured-response repair path by causing a response that requires
   validation/repair. Verify the bounded repair path either produces a valid answer or fails
   safely, and does not consume an additional entitlement.
7. Exercise the safety rejection/fallback path. Verify the follow-up cannot weaken a high-risk
   safety signal from the primary report and that the user receives the configured safe outcome.
8. Force a transient/technical provider failure before successful completion. Verify private
   partial content is not retained, the entitlement returns to `available`, and a later retry can
   succeed and consume it exactly once.
9. Verify an expired processing lease can be reclaimed without two successful completions, and
   that only the current claim may finalize or release the entitlement.
10. Inspect staging logs/analytics for the procedure. They may contain identifiers, status, prompt
    version, attempt counts and safe failure categories, but must not contain the private question,
    answer, normalized source conversation, provider credentials or raw provider payloads.
11. Only after all scenarios above pass on the real staging provider, append a `passed` attestation
    for `openai_followup_staging` with a non-secret `evidence_ref`. Record `failed` instead if a
    live scenario exposes a defect, fix it in a narrow PR, and repeat the affected live procedure
    before appending a later pass.
