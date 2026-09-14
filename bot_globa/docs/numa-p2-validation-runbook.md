# Numa product-validation runbook

Status: execution protocol for empirical Task 08 / issue #191.

This document does **not** claim that live observations have happened. CI, synthetic users and
unit tests are prerequisites for live validation, not substitutes for it.

## 1. First-use sample

Target: **10–15 real first-use sessions** before drawing product conclusions.

Use `numa-first-use-observation-template.md`. The first pass must cover the actual source/state
matrix rather than repeating one happy path:

- ordinary personal entry via `Рассказать Numa`;
- explicit Tarot/Love/Psy;
- daily with no saved sign and with saved sign;
- personal day with/without birth profile;
- group compatibility and Astro Duel;
- group → private transition;
- share sender → recipient entry;
- first free preview and later micro-preview;
- full result with active follow-up session and expired/exhausted session;
- stories return path;
- payment → exact reading/story resume;
- memory off and, where voluntarily enabled by the participant, memory on.

Do not force every participant through every state. Across the whole 10–15-session sample each
important coordinate must appear at least once.

### Observation method

The observer records behavior, not private content. Let the participant act without coaching
until they are blocked. Ask neutral questions such as:

- «Что бы вы нажали дальше?»
- «Что, по-вашему, сейчас произойдёт?»
- «Что вы получили бесплатно, а за что здесь предлагают платить?»
- «Если захотите вернуться к этой ситуации завтра, где будете искать?»

Do not explain the intended answer before the participant acts.

### What counts as useful value

A session reaches first useful value only when the user receives a substantive personal or
shared result relevant to the chosen scenario. These events alone do **not** count as value:

- opening `/start`;
- receiving a scheduled daily notification;
- viewing a paywall;
- opening a story without an action/result;
- seeing a loading/generating screen.

## 2. Privacy boundary

Never store in the observation notes:

- question or generated private answer;
- name/username/Telegram ID;
- internal user UUID, reading ID or story title;
- birth date/place/time;
- payment credentials/provider raw payload;
- screenshots containing any of the above.

Allowed evidence: date, app/client context, anonymous slot, source code, experiment arm,
structured pass/fail fields, generic non-identifying friction note and issue/PR reference.

## 3. Mobile visual QA matrix

Execute on an actual Telegram mobile client at normal phone width. Mark a row complete only
after the screen was really viewed; CI does not satisfy this table.

| Surface | Required cases | Inspect |
| --- | --- | --- |
| First screen | new `/start`, returning `/start` | `Рассказать Numa` is obvious; direct practices/daily/stories remain understandable; no obsolete four-persona explanation |
| Consent | first personal action, already-consented return | just-in-time placement; back returns predictably; privacy copy does not block browsing |
| Personal free answer | `baseline`, `complete`, later micro-preview | first useful statement visible; experiment arm not confused with one-time entitlement; feedback understandable |
| Personal full answer | short/long result | readable chunks; `до 3 уточнений / 24 часа` is visible and accurate; result can be reopened |
| Feedback recovery | negative feedback + reason | user has a concrete working next action; no dead callbacks |
| Daily first entry | no sign saved | compact sign picker; `Все знаки` alternative; no natal questionnaire |
| Daily normal | saved sign, all-sign | text-only forecast; one primary personal CTA; share and secondary actions do not dominate |
| Personal day | profile absent/present | focus buttons work; saved profile skips intake; absent profile returns to original intent after intake |
| Daily settings | enabled/disabled, timezone | saved local time/state visible; disable and re-enable work |
| Daily share | preview → confirm → picker | exact outbound text shown before picker; no sign-specific/private data; recipient enters Daily directly |
| Paid insight share | sender + recipient | explicit confirmation; private question/full answer absent from payload |
| Stories hub | empty, latest readings, folders | newest items follow real chronology; active 24h sessions are distinguishable |
| Continue story | active session, expired/exhausted session | included question vs new reading is unmistakable; no accidental charge promise |
| Story + payment | checkout/resume | target story survives payment; exact reading resumes |
| Astrology profile | absent/present/deleted | intake only when needed; deleted profile is not silently restored |
| Group entry | bot added/menu | only Compatibility + Astro Duel compete on primary screen |
| Compatibility | profile present/missing | selected context survives; each participant confirms own sign when needed; precision CTA is relevant |
| Astro Duel | profile present/missing | sign fallback works; private CTA keeps Astro context |
| Group → private | both core games | promised private scenario/source survives transition without chat text in deep link |
| Payment | configured supported routes | product, amount, period/count clear; test prices unchanged for validation |
| Payment completion | hosted/provider return | authoritative success only; exact saved result reopens; uncertain delivery not mislabeled as failed payment |
| Error/recovery | stale callback, generation failure, checkout unavailable | plain language; safe next action; purchased result not lost |
| Memory | off/on if participant enables it | off does not imply remembered private context; on has visible control/delete path |

### Visual pass criteria

For every observed surface answer yes/no:

1. Is the purpose understandable before decorative content or long copy?
2. Is one primary action visually distinguishable from secondary actions?
3. Is the copy concise enough for Telegram without losing product boundaries?
4. Are repeated headings/images/sales promises avoidable?
5. Does anything imply guaranteed events, factual mind-reading or fear-based certainty?
6. Are price, preview and follow-up boundaries accurate?
7. Does back/cancel return predictably without losing a purchased result or intended story?
8. Does long content remain readable inside Telegram limits?
9. If the screen came from group/daily/share, does the promised source scenario survive?
10. Are callbacks actually live, not only visually present?

## 4. Current free-preview experiment contract

Current experiment: `free_preview_v1`.

Population: Tarot/Love/Psy structured readings. Astrology is explicitly excluded.

Assignment: stable 50/50 from internal user UUID; `entry_source` is a separate analytical
coordinate and must not be used as the assignment key.

Arms:

- `baseline` — legacy short answer;
- `complete` — concrete opening + first symbol where applicable + small practical step.

Primary validation metric for the first small sample: **first useful answer understood**
(observed yes/no), not checkout conversion alone. Supporting aggregate metrics: delivered
first answer, feedback participation/reason, meaningful repeat action, confirmed purchase,
refund and known variable cost.

One-time free-preview entitlement is not the experiment. A user can be in `complete` and still
receive a later micro-preview after the free entitlement has already been consumed.

### Stop/default rule

Do not launch another independent preview/content experiment until `free_preview_v1` has an
explicit stop decision. The owner decision must name:

- experiment key/version;
- primary metric;
- default arm after stop;
- exact code/config mechanism used to stop assignment;
- decision date.

**Current gap:** assignment is deterministic in code, but `main` has no runtime kill-switch for
`free_preview_v1`. Therefore a new concurrent experiment is blocked until this is either
implemented or the current experiment is ended by an explicit release that freezes one arm.
Do not describe the test as operationally switchable before that change exists.

## 5. Old-vs-new answer review

Use the offline review packet from `build_oracle_product_review_packet.py` and score baseline
vs complete independently on the fixed 1–5 criteria:

- specificity;
- situation fit;
- clarity;
- memorable image;
- useful step;
- desire to continue.

Do not add hidden weights after seeing results. Keep source separate from arm. Explicit test
traffic must not be mixed into product conclusions.

## 6. Commercial-price boundary

Commercial-price experiment remains disabled until the owner supplies candidate prices in a
separate launch decision. Task 08 does not authorize changing current test prices.

Before any price experiment verify:

- owner-approved candidates and currencies;
- one authoritative billing catalog;
- no concurrent independent small-traffic experiment that makes interpretation impossible;
- exposure → checkout → confirmed purchase → refund reporting;
- known provider fees and known variable generation costs;
- unknown costs remain unknown rather than zero;
- existing balances, entitlements, refunds and reconciliation are unaffected by assignment.

## 7. Evidence and decision rules

A validation note may contain:

- observation date;
- Telegram client/platform category;
- anonymous slot/path code;
- entry source;
- preview arm where applicable;
- state coordinates such as profile yes/no, memory off/on, session active/expired;
- pass/fail of mobile criteria;
- structured first-use fields;
- linked issue/PR for a defect.

Classification:

- **defect** — reproducible behavior contradicts product contract, privacy, payment or safety;
- **friction** — user cannot understand/complete intended flow without help;
- **product hypothesis** — proposed improvement not yet supported by repeated observation.

Correctness/privacy/payment/safety defects are fixed immediately; they are never averaged away
inside an overall score.

Product decisions combine:

1. observed understanding/feedback;
2. voluntary meaningful return (new question, follow-up, continuation — not mere delivery);
3. confirmed purchase/refund behavior;
4. economics with known provider and variable LLM costs.

Autoresearch is a quality/cost/constraint guard, not evidence that users value Numa.

## 8. Completion definition for Task 08 / #191

Documentation/scaffolding is complete when:

- factual `cjm-v2.md` matches effective registered routes/installers;
- observation template covers the current source/state matrix;
- this mobile runbook is version-controlled;
- experiment arm/source semantics are explicit;
- no paid research is auto-triggered.

Empirical completion requires **all** of the following:

- at least 10 and at most 15 first-pass real observations;
- actual mobile matrix execution;
- each observation has date + anonymous path/source/state fields;
- discovered defects have issues/PRs;
- no private content was copied into research notes;
- issue #191 is updated with aggregate findings.

Until then #191 stays open. Synthetic/CI data must never be marked as the missing live evidence.
