# Conversion funnel v1

## Goal

Measure whether the grounded preview hook increases paid value delivery without collecting
private question text, birth data, Telegram identifiers, or model output in analytics.

## Funnel

The launch funnel uses existing durable events:

1. `reading_preview_ready` — a reading has a validated preview;
2. `checkout_started` — the user starts a top-up/payment checkout when needed;
3. `purchase_completed` — the payment is durably credited;
4. `reading_full_unlocked` — paid reading value is actually delivered.

Users who already hold credits may legitimately move from preview directly to full unlock,
so checkout conversion and unlock conversion must be reported separately.

## Cohort identity

Reading analytics already use the internal user UUID as `subject_id`. Billing projection now
resolves `payment_orders.user_id` and writes the same internal UUID into billing analytics.
This is an application UUID, not a Telegram ID, and no free-form content is added.

## A/B/C assignment

Experiment key: `conversion_hook_v1`.

For the first release, Tarot, Love Oracle, and Mystical Psychologist use three stable arms:

- A — scenario first, then withheld conditions/alternative, then paid value;
- B — paid value first, then the grounded scenario;
- C — scenario/alternative first, paid value second, withheld conditions last.

All arms contain the same validated scenario and the same application-owned promises; only
the order of emphasis changes. The assignment is `internal_user_uuid.bytes[-1] % 3`, so the
same user remains in the same arm without an experiment-assignment table.

The Astrologer remains on the existing grounded control hook in this first slice. Its birth
profile flow has a separate rendering boundary; it should only enter the split when the
variant can be passed explicitly without mixing experimentation with calculated facts.

## Analysis rules

Cohort by `subject_id`, never by Telegram ID. For oracle reading events, filter persona when
comparing hook variants. Billing events are linked by the same subject and can therefore be
aggregated alongside reading events without storing private content.

Primary metrics:

- full unlocks / preview-ready users;
- checkout starts / preview-ready users;
- purchases / checkout starts;
- full unlocks / purchases;
- each metric split by A/B/C arm and persona where applicable.
