# Numa product plan — 8 September 2026

Status: owner-approved execution plan.

Repository baseline used by the review: `main` at `9a9d677ed4baefd3eef852c9eba7cf0b1ebaad17`.

This document is the execution index for the detailed owner brief dated 8 September 2026. When implementing a task, preserve the acceptance criteria and product constraints from that brief; do not reinterpret a working feature merely to make the code uniform.

## Product goal

Improve four things independently:

1. the first useful answer;
2. voluntary returns;
3. acquisition through groups and sharing;
4. the transition to payment.

Numa combines personal Tarot / Love Oracle / reflection / astrology readings, a free daily horoscope and group games. A user may arrive for support in uncertainty, a daily ritual or entertainment with friends. Measure these paths separately.

## Execution rules

- Work in small sequential changes and verifiable draft PRs.
- Do not merge PRs, change production configuration or deploy as part of this plan.
- Preserve current intentionally low test prices, currencies, balances, existing purchases and entitlements.
- Do not add a paid LLM classifier for routine routing.
- Routine tests must not make paid LLM calls or send messages to real users.
- Reuse current mechanisms: unified `Расскажите Numa` entry, zero-per-recipient-LLM daily horoscope, history, consented memory, feedback, analytics, cost controls and the 3-follow-up / 24-hour session.
- Distinguish documentation, branch code, `main`, and confirmed live-bot behavior.
- Reuse PR #162 as the foundation of paid insight sharing; do not duplicate it.

## Priority order

| Priority | Tasks | Outcome |
| --- | --- | --- |
| P0 | 01–03 | Correct routing, correct unsubscribe behavior, consistent promises |
| P1 / 1 | 04–05 | Measurable funnel and a complete free answer |
| P1 / 2 | 06–07 | Compact daily experience and understandable paid session |
| P1 / 3 | 08–09 | Two core group games and result distribution |
| P2 | 10–11 | Personal stories and product-hypothesis validation |

## 01 — Scenario choice and transitions — P0

- Route by context, not broad word matches. `чувствую` and `отношения` alone are not romantic intent.
- `Я чувствую, что выгораю на работе` and `У меня сложные отношения с начальником` must not route to romance.
- `Что он ко мне чувствует?` and `Стоит ли написать ему первой?` must still route to Love Oracle.
- For genuinely ambiguous input, ask one short clarification or let the user change the proposed practice.
- Explicit user practice choice wins over auto-routing.
- Separate group `Проверить совместимость` from private `Разобрать отношения лично`.
- Compatibility must continue the selected pair with both participants' required confirmation.
- Preserve the original intent across consent and birth-profile intake. Daily personal CTA must return to today's personal forecast after profile completion, including after handler restart.
- Preserve current commands, deep links and unfinished FSM recovery.

## 02 — Morning and evening message controls — P0

- Keep the morning-horoscope toggle.
- Add a separate evening-feedback toggle, default off, including for existing users after migration.
- Disabling daily messages suppresses/cancels unsent evening requests.
- Re-enabling must not drain stale evening requests.
- Re-check current preferences, contactability, local date and timezone immediately before send.
- Preserve dedupe, ambiguous Telegram result handling and unavailable-recipient handling.
- A request already accepted by Telegram must not later be presented as cancelled.

## 03 — Names and promises — P0

- A 12-sign digest is called `Гороскоп на сегодня`, not a personal natal forecast.
- Remove the intermediate `Начать` action between welcome and useful capabilities; keep just-in-time personal-data consent.
- Describe the actual paid entitlement: one complete situation reading plus up to three follow-up questions within 24 hours after full unlock, with no extra charge for those included follow-ups.
- Remove stale promises of only one follow-up.
- Explain follow-up-window expiry separately from storage/access to the purchased result.
- Replace `точнее предсказывает` with a concrete description of additional data used.
- Compatibility percentages are playful indicators, not probabilities of future events.
- Do not change prices or already-paid rights to make copy easier.

## 04 — Analytics — P1

Extend the typed analytics schema; do not bypass it with arbitrary fields.

Required attribution dimensions:

- entry source: normal start, daily horoscope, specific group mechanic, shared insight, test campaign;
- scenario version and experiment assignment;
- existing `conversion_hook_v1` as an explicit factor/control;
- daily prepared vs confirmed delivery vs explicit action;
- share-card shown vs share intent vs recipient entry;
- unlock from existing credits/package separately from a new purchase.

Required metrics:

- activation = new user receiving first complete free answer;
- answer speed = accepted question → ready answer, with confirmed send separated where observable;
- free-answer rating = `Попало` / `Мимо` plus feedback participation;
- repeat within days 1–7, with reopening old result separate;
- D1 and D7 meaningful activity with explicit calculation timezone;
- first confirmed successful purchase;
- next separate confirmed purchase, with auto-renewals separate;
- group acquisition by source/game;
- economics = revenue less refunds, known actual fees and variable generation costs.

Synthetic-data acceptance: trace source → answer → payment → repeat, no double counting on repeated update delivery, test identities/payments excludable, unknown costs remain unknown rather than zero.

## 05 — Complete value in the free answer — P1

- One situation-specific observation.
- One appropriate symbol/image.
- One small practical next step.
- Use the already validated result; no extra LLM call just for preview.
- Preserve selected Tarot cards and calculated astrology facts from preview through unlock/reopen.
- Explain paid session value once and concisely: details, alternative scenarios, conditions, included follow-ups.
- Remove repetitive `hidden trajectory/deep layer` sales copy.
- Make feedback available before payment.
- After `Мимо`, optional reasons: `Слишком общее`, `Не про мой вопрос`, `Непонятно`.
- Feedback must not unlock full content or expose another user's result.

## 06 — Compact daily horoscope — P1

- Optional zodiac-sign choice without birth date/place/time.
- Sign selection must not silently create a natal profile.
- Show selected sign first with a short day theme; keep `Все знаки`, change-sign and existing 12-sign digest.
- Reuse shared calculated content for the date; no per-recipient LLM generation.
- Personal natal forecast keeps its separate explanation/route and may have a saved default topic plus optional free-form question.
- Remove the repeated large decorative image from compact daily delivery.
- Review 14 consecutive days × 12 signs for semantic repetition, not just exact-string duplicates.

## 07 — Understandable paid offer — P1

- First paid CTA prioritizes one session; pack remains the next option.
- Push subscription more actively after repeat meaningful usage, while keeping purchases/subscription-management access.
- Accurately show duration, reading count and auto-renewal from real configuration.
- After confirmed payment, return automatically to the exact saved result.
- Delivery failure is not payment failure; reopening must not charge again.
- Economics include pre-payment generation, repair attempts, retries and included follow-ups.
- Keep existing budget controls.
- Do not introduce two-stage generation architecture in this task.
- Prepare launch documentation for current Telegram Stars requirements, but preserve low test prices and manual-test payment routes until a separate launch task.

## 08 — Two core group games — P1

Initial priorities: compatibility and duel. Keep other working games in an extra menu.

- `/compatibility` gets a quick zodiac-sign mode without forcing two natal profiles.
- Each participant confirms participation and chooses their own data.
- Do not read ordinary group chat or enumerate all members.
- After quick result, offer a richer profile-based variant and say what extra data is used.
- Add a clear private `Играть с друзьями` entry with add-to-group action and short first-game instructions.
- Require only necessary bot permissions.
- Each major group result has one contextually related private action and carries safe game/source attribution through onboarding/consent.

## 09 — Sharing — P1

Reuse PR #162 first.

- Personal result sharing uses only a purpose-built safe `share_card`.
- Never copy the original question, full reading or birth data into the shared payload.
- Check owner and entitlement before loading shareable content.
- Add free-audience sharing of a common day card or anonymized game result.
- No other participant names/details without their own action.
- Public/deep-link attribution uses a limited source/campaign code only; no Telegram ID, reading ID, personal text or birth data in public URL.
- Preview → explicit user action → Telegram chat picker; user performs the send.
- `share intent` is not proven send or acquisition.

## 10 — Personal stories — P2

- Manually link readings into a story first; no new LLM classifier.
- `Продолжить историю` asks what changed.
- New question may use confirmed story facts and memory only with memory consent.
- Saved-reading access still works without memory consent, but no new long-term memory records are created.
- Allow correcting links and deleting a story with clear consequences.
- Do not nag after memory-consent decline/revocation.
- Distinguish included follow-up within 24 hours from a new paid session.
- Story titles/summaries use the same protection as other personal data.
- Model guesses must not become biographical facts.

## 11 — Hypotheses and quality validation — P2

- Prepare 10–15 observed first-use sessions across personal question, horoscope, group game and payment.
- Maintain synthetic question/answer comparisons for specificity, situation fit, clarity, memorable image, useful step and desire to continue.
- Stable old-vs-new free-preview experiment assignment with entry source kept separate.
- Avoid simultaneous independent price/text/frequency tests on a small audience.
- Future commercial-price test gets configuration/report scaffolding only; owner supplies prices and current test values remain.
- Visually inspect real mobile messages: first screen, short/long result, daily, payment, error, group card, share flow.
- Preserve mystical palette/card imagery while reducing repetitive decorative screens.
- Autoresearch controls format/repetition/cost/constraints; product success is observed feedback, returns, purchases and economics.
- Paid research runs do not auto-trigger.

## Global constraints

- User-facing name: Numa.
- Russian copy: simple, warm, concise, with a restrained magical atmosphere.
- Do not expose internal prompt/ledger/technical vocabulary to users.
- No new 18+ gate and no new practices in this plan.
- Preserve safety: no claims of factual mind-reading, guaranteed events, fear-based threats or paid protection from invented danger; preserve crisis exits.
- Tarot cards are fixed before interpretation.
- Astrology coordinates come from the calculation engine.
- Retry must not silently replace the spread/calculation or paid result.
- Analytics must not contain questions, answers, story summaries, names, Telegram IDs or birth data.
- Preserve ledger, financial idempotency, reconciliation, refunds, ownership checks, encryption and consent management.
- Add migrations; never rewrite applied migrations.
- CJM documentation must follow implemented behavior, not lead it.

## Stage report template

For each stage report:

1. task numbers and user-visible changes;
2. draft PR links and changed files;
3. before / after;
4. checks actually run and remaining limitations;
5. events / metrics used to evaluate the change;
6. next available stage.
