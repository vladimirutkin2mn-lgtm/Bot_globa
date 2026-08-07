# Oracle limited-release rollback runbook

This runbook covers ORA-604 operational controls for the four MVP oracle personas. It is intentionally separate from billing rollback: payments, refunds, subscriptions, reconciliation and webhook receipt have their own controls and must keep running unless the incident is billing-specific.

## Control surface

The application reads the following values at process startup:

- `ORACLE_ENABLED` — global oracle admission switch.
- `ORACLE_ROLLOUT_PERCENTAGE` — deterministic percentage of internal users admitted to new Readings.
- `ORACLE_ROLLOUT_SEED` — cohort seed. Keep it stable while changing only the percentage.
- `ORACLE_DISABLED_PERSONAS` — comma-separated persona codes, for example `astrologer,love_oracle`.
- `ORACLE_DISABLED_ENGINES` — comma-separated engine versions, for example `astrology-calculation-v1`.
- `ORACLE_GENERATION_RATE_LIMIT` and `ORACLE_GENERATION_RATE_WINDOW_SECONDS` — maximum new Readings per internal user in the configured window. `0` disables the rate limit.
- `ORACLE_DAILY_SPEND_CAP_MICROUSD` — conservative UTC-day LLM reservation cap. `0` disables the cap.
- `ORACLE_MAX_RESERVED_COST_MICROUSD_PER_READING` — worst-case reservation for one newly admitted Reading, including the allowed repair attempt.

Changes require redeploy/restart of the bot and Telegram worker processes that compose the oracle services. Do not rely on changing an environment variable without replacing the running processes.

## Safest rollback order

1. Set `ORACLE_ENABLED=false`.
2. Deploy/restart every process that can accept Telegram oracle traffic.
3. Confirm no new rows appear in `readings` after the replacement processes became ready.
4. Leave billing, refund, subscription, webhook and reconciliation switches unchanged unless their own incident requires action.
5. Inspect aggregate oracle quality/billing health before deciding whether to restore traffic.

The switch denies new Reading admission before private Reading content is persisted. Work that was already in flight when the old process was terminated may have reached its provider before rollback; a process restart is therefore part of the emergency procedure.

## Narrow rollback

Prefer the narrowest switch that contains the incident:

- Persona incident: add the persona code to `ORACLE_DISABLED_PERSONAS`.
- Astrology calculation incident: add `astrology-calculation-v1` to `ORACLE_DISABLED_ENGINES`.
- General oracle incident: set `ORACLE_ENABLED=false`.
- Cost pressure only: lower rollout and/or set a conservative daily spend cap.
- Abuse/burst pressure only: configure the generation rate limit and window.

A persona or engine kill switch affects new Reading admission regardless of rollout percentage.

## Rollout procedure

Use a stable `ORACLE_ROLLOUT_SEED` for the whole limited release. Recommended progression is `0 → 1 → 5 → 10 → 25 → 50 → 100` percent, advancing only after the current cohort has acceptable safety, generation quality, provider failure and billing health.

Changing the percentage with the same seed grows or shrinks one deterministic cohort. Changing the seed reshuffles the cohort and should be treated as a new rollout experiment.

## Spend cap semantics

The spend cap is deliberately conservative. Each newly admitted Reading reserves `ORACLE_MAX_RESERVED_COST_MICROUSD_PER_READING`, rather than waiting for provider telemetry after money may already have been spent.

The reservation value must upper-bound the configured model's worst expected primary generation plus the single allowed repair call. Reservations are counted from Reading creation and are not released when a Reading later fails or is deleted. The counter resets at `00:00 UTC` because the calculation counts Readings created since the UTC day boundary.

This can under-utilize the cap but must not exceed it under normal admission. If pricing, token bounds or repair policy changes, update the reservation before increasing rollout.

## Rate-limit semantics

The oracle rate limit counts Reading rows created by the same internal `user_id` inside the configured window. It is separate from the Telegram middleware burst limiter and therefore applies consistently across multiple application workers.

Failed or later-deleted Readings still count inside the window. This is intentional for abuse containment and keeps retries from bypassing the release limit.

## Verification after a control change

After restart/deploy:

1. Verify the deployed environment contains the intended oracle release values.
2. For global shutdown, confirm no new `readings.created_at` values appear after the new processes became ready.
3. For a persona or engine shutdown, confirm no new matching Reading metadata appears.
4. Confirm payment webhooks, reconciliation, refunds and subscriptions remain healthy.
5. Check aggregate `oracle_generation_observed`, LLM cost/latency, astrology errors, safety fallback and billing health.
6. Run the protected oracle safety, staging-quality and release-control gates against the exact candidate commit before restoring traffic.

Never use raw user questions, Reading plaintext, memory values, birth-profile data or Telegram identity to verify a release-control incident.

## Restore traffic

Restore the narrow switch first, not all controls at once. For example, re-enable a repaired persona while keeping the rollout percentage and spend cap unchanged. Advance rollout only after the exact deployed prompt/schema/model/engine coordinates pass the staging quality gate.

## Do not do during rollback

- Do not delete Reading, memory or BirthProfile rows to stop traffic.
- Do not rotate the content-encryption key as an availability rollback.
- Do not disable payment webhook receipt or reconciliation for an oracle-generation incident.
- Do not change `ORACLE_ROLLOUT_SEED` merely to reduce traffic; lower the percentage instead.
- Do not set the spend reservation below the worst-case cost simply to admit more traffic.
