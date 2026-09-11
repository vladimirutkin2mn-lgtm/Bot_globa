# Numa first-use observation template

Purpose: review 10–15 concrete first-use sessions without turning private user content into a research dataset.

## Privacy boundary

Record behavior and product friction, not private content. Do **not** put questions, answers, names, Telegram IDs, reading IDs, birth dates/places/times, payment credentials or story titles into this file. Repository examples should use test/synthetic sessions only. Production observations should be reduced to non-identifying product notes before they are copied here.

## Coverage target

Use at least 10 completed observations before drawing a product conclusion. The 12 slots below deliberately cover different entry paths so one successful scenario does not hide another broken one.

| Slot | Path | Suggested first-use scenario |
| --- | --- | --- |
| P1 | Personal question | `Рассказать Numa` → auto-routed personal reading |
| P2 | Personal question | Explicit Tarot selection |
| P3 | Personal question | Explicit Love Oracle selection |
| P4 | Personal question | Reflection / mystical psychologist selection |
| H1 | Horoscope | General horoscope → selected zodiac sign |
| H2 | Horoscope | Daily personal CTA → astrology intake |
| H3 | Horoscope | Existing birth profile → personal astrology question |
| G1 | Group | Compatibility quick mode |
| G2 | Group | Duel |
| G3 | Group | Group result → related private action |
| $1 | Payment | Free preview → single-session purchase → exact result resume |
| $2 | Payment | Purchased full result → included follow-up within 24 hours |

## Observation fields

Copy this block once per observed session:

```text
slot:
test_or_synthetic_session: yes/no
entry_source:
scenario_version:
experiment_assignment:
first_use_completed: yes/no
first_complete_free_answer_delivered: yes/no
steps_before_useful_value:
answer_wait_bucket: <5s / 5–15s / 15–30s / >30s / unknown
user_hesitation_or_dead_end:
copy_or_navigation_issue:
payment_terms_understood: yes/no/not_shown
exact_result_resume_worked: yes/no/not_applicable
included_followup_understood: yes/no/not_applicable
mobile_visual_issue:
severity: none / minor / blocks_value / blocks_completion
non_identifying_note:
```

## Review rule

Do not turn one observation into a product conclusion. Summarize repeated friction by path after at least 10 observations, keeping entry source and experiment assignment separate. If a session exposes a correctness, privacy, payment or safety defect, fix that defect independently rather than averaging it away in a score.
