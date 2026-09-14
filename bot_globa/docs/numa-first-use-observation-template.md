# Numa first-use observation template

Purpose: record 10–15 real first-use sessions without turning private user content into a
research dataset.

## Privacy boundary

Record behavior and product friction, not private content. Do **not** store questions, generated
answers, names, usernames, Telegram IDs, internal user UUIDs, reading IDs, story titles, birth
data, payment credentials or raw provider payloads. Do not commit screenshots containing such
data.

Repository examples may be synthetic, but synthetic rows do not count toward issue #191.

## Coverage target

The first pass needs at least 10 and at most 15 real observations. The 15 slots below cover the
current effective CJM; one real session may cover more than one slot if the participant reaches
those states naturally.

| Slot | Path | Required state/source |
| --- | --- | --- |
| P1 | `Рассказать Numa` | new user, ordinary source |
| P2 | explicit personal practice | Tarot or Love |
| P3 | explicit Psy | ordinary source, recovery/navigation clarity |
| P4 | later personal reading | free entitlement already used → micro-preview |
| H1 | Daily first entry | no saved sign → sign picker / all-sign alternative |
| H2 | Daily → personal | birth profile absent → intake → resume intent |
| H3 | Daily → personal | birth profile already present → no repeated intake |
| G1 | Group Compatibility | quick mode, at least one missing natal profile/sign fallback |
| G2 | Astro Duel | self-confirmed signs where needed |
| G3 | Group → private | promised personal scenario/source preserved |
| S1 | Daily share sender | exact preview → explicit confirm → native picker |
| S2 | Share recipient | recipient enters the promised Daily scenario |
| R1 | Stories | active 24h session → included continuation |
| R2 | Stories | expired/exhausted session → clearly new reading |
| $1 | Payment | preview → purchase → exact reading/story resume |

Across the sample also cover:

- `free_preview_v1:baseline` and `free_preview_v1:complete` where assignment permits;
- memory off; memory on only if a participant voluntarily enables it;
- new and returning users;
- short and long full result;
- enabled/disabled Daily delivery/settings;
- at least one error/recovery state.

Do not manipulate a participant's production account just to force an experiment arm.

## Observation fields

Copy this block once per real observed session. Use only category/code values; never paste the
private content that caused the observation.

```text
observation_date: YYYY-MM-DD
slot:
telegram_client: ios / android / desktop / other
real_session: yes/no
user_state: new / returning
entry_source: ordinary / group / daily / share
scenario_version:
practice: auto / tarot / love / psy / astro / daily / group / none
experiment_assignment: free_preview_v1:baseline / free_preview_v1:complete / not_applicable / unknown
preview_entitlement: first / already_used / full / not_applicable / unknown
birth_profile: absent / present / deleted / not_applicable / unknown
memory_state: off / on / not_checked
session_state: active / expired_or_exhausted / not_applicable / unknown
story_state: none / existing / target_story / not_applicable
first_use_completed: yes/no
first_useful_value_delivered: yes/no
next_action_understood_without_help: yes/no
steps_before_useful_value:
answer_wait_bucket: <5s / 5–15s / 15–30s / >30s / unknown
user_hesitation_or_dead_end:
copy_or_navigation_issue:
source_promise_preserved: yes/no/not_applicable
share_exact_text_confirmed: yes/no/not_applicable
payment_terms_understood: yes/no/not_shown
exact_result_resume_worked: yes/no/not_applicable
included_followup_understood: yes/no/not_applicable
mobile_visual_issue:
live_callback_failure: yes/no
severity: none / minor / blocks_value / blocks_completion / correctness_privacy_payment_safety
linked_issue_or_pr:
non_identifying_note:
```

## Observer prompts

Use neutral prompts only after the participant has had a chance to act:

- «Что бы вы нажали дальше?»
- «Что, по-вашему, сейчас произойдёт?»
- «Что здесь уже получилось бесплатно?»
- «Что изменится после оплаты?»
- «Где вы будете искать эту ситуацию завтра?»

Do not teach the intended navigation before recording whether it was understood.

## Review rule

Do not turn one session into a product conclusion. After at least 10 real observations,
summarize repeated friction by path while keeping `entry_source`, preview arm and entitlement
state separate.

If a session exposes a correctness, privacy, payment or safety defect, create/fix it independently
rather than averaging it into a UX score. A proposed change without repeated evidence remains a
`product hypothesis`.
