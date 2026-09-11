# Numa P2 product-validation runbook

Status: execution checklist for task 11 of `numa-product-plan-2026-09-08.md`.

This document does not claim that any live observation has happened. It defines what must be inspected and what evidence may be recorded without storing private user content.

## 1. First-use observation sample

Target: 10–15 real first-use sessions before drawing product conclusions.

Use `numa-first-use-observation-template.md` for the observation rows. Keep the sample mixed across:

- personal question;
- common daily horoscope;
- group compatibility / duel;
- payment / unlock.

Do not store the user's question, generated answer, name, Telegram ID, reading ID, birth data or screenshots containing those values in the observation sheet.

For each session record only the allowed structured fields from the template and note whether the user reached a useful outcome, hesitated, abandoned, returned or paid where observable.

Do not treat 10–15 sessions as statistical proof. The sample is for finding obvious UX failures, confusing copy and broken transitions before a larger experiment.

## 2. Mobile visual QA matrix

Inspect on an actual Telegram mobile client at normal phone width. Check both short and long content where applicable.

| Surface | Required cases | Inspect |
| --- | --- | --- |
| First screen | `/start`, returning user | useful choices visible without an extra `Начать`; no internal terms; hierarchy fits one screen reasonably |
| Personal free answer | baseline and complete experiment arms | first useful statement is visible; no broken HTML; buttons are understandable; feedback appears before payment |
| Personal full answer | short and long reading | sections are scannable; no Telegram truncation; purchased result remains reopenable; follow-up entitlement wording is accurate |
| Daily horoscope | selected sign and all-sign digest | compact delivery does not feel like a large decorative card; sign switch/all-sign controls are obvious |
| Payment | single reading, pack, subscription where enabled | product, amount, period/count and auto-renewal are explicit; back navigation works; current configured price is shown |
| Payment completion | hosted payment return / supported provider route | exact saved result can be reopened; delivery failure is not described as payment failure |
| Error / recovery | stale callback, generation failure, payment status uncertainty | no technical vocabulary or invented certainty; there is a clear safe next action |
| Group result | compatibility and duel | pair/context is understandable; result does not imply factual mind-reading; one relevant private CTA is visible |
| Add-to-group | private `Играть с друзьями` entry | permissions request is minimal; first-game instructions are short |
| Share flow | share preview and Telegram picker | only purpose-built safe share content is visible; original question/full reading/birth data are absent |
| Personal stories | empty, one reading, multiple readings | create/add/move/unlink/delete consequences are understandable; `Продолжить историю` boundary between included follow-up and new session is clear |
| Astrology profile gate | profile present / absent / consent unavailable | missing data is described concretely; deleted profile is not silently reconstructed |

### Visual pass criteria

For every case answer yes/no:

1. Can the main purpose be understood without scrolling through decorative content first?
2. Is the primary action visually distinguishable from secondary actions?
3. Is the copy concise enough for Telegram while preserving the restrained mystical tone?
4. Are there duplicate images, repeated headings or repeated sales promises that can be removed?
5. Does any screen imply guaranteed events, factual mind-reading or fear-based certainty?
6. Are price, entitlement and follow-up boundaries stated accurately?
7. Does back/cancel return to a predictable place without losing an already purchased result?
8. Does long content stay readable and inside Telegram limits?

## 3. Old-vs-new free-preview review

Use the offline review packet from `build_oracle_product_review_packet.py` and score baseline vs candidate independently on the six fixed criteria:

- specificity;
- situation fit;
- clarity;
- memorable image;
- useful step;
- desire to continue.

Use the 1–5 rubric only. Do not add hidden weights after seeing results.

For the live experiment, keep `entry_source` separate from the preview arm. Compare the same arm by source before combining traffic. Exclude explicit test traffic from product conclusions.

Do not run a new independent text, price or message-frequency experiment at the same time on a small audience.

## 4. Commercial-price experiment boundary

The price experiment remains disabled until the owner supplies candidate prices in a separate launch task.

Before activation verify:

- current test prices remain the authoritative baseline;
- candidate prices are explicitly owner-approved;
- each market/currency coordinate is defined;
- no concurrent independent free-preview text or message-frequency experiment contaminates the sample;
- reporting includes exposure, checkout start, confirmed purchase, refunds, known provider fees and known variable generation costs;
- unknown costs stay unknown rather than being converted to zero;
- existing purchases, balances, entitlements, refunds and reconciliation are unaffected by assignment.

The research scaffold must never become a second billing catalog.

## 5. Evidence and decision rule

A validation note may include:

- date and app/client context;
- anonymous surface/case code;
- pass/fail for the visual criteria above;
- structured first-use observation fields;
- aggregate experiment metrics;
- an issue/PR reference for a discovered defect.

It must not include private questions, generated private answers, names, Telegram identifiers, reading identifiers, birth data, payment credentials or raw provider payloads.

Product decisions should combine four kinds of evidence rather than optimize one proxy:

1. observed user understanding and feedback;
2. voluntary return / meaningful repeat activity;
3. purchase behavior and refund behavior;
4. economics including known provider and variable generation costs.

Autoresearch remains a guard for format, repetition, cost and constraints. It is not evidence by itself that users value the product.

## 6. Completion definition for P2-11

The implementation/scaffolding portion is complete when:

- human old-vs-new review tooling exists;
- stable free-preview assignment is implemented with entry source separate;
- commercial-price test scaffolding exists without changing current prices;
- this mobile/first-use validation procedure is version-controlled;
- paid research is not auto-triggered.

The empirical portion is complete only after 10–15 real first-use sessions are observed and the mobile matrix is actually executed. Do not mark those two items complete from CI or synthetic data.
