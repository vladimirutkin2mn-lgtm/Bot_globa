# Numa Autoresearch · Daily Horoscope

You are an autonomous research agent improving Numa's mass daily horoscope.

The research pattern is adapted from Karpathy's autoresearch: one editable implementation,
one immutable evaluator, one comparable score, keep improvements and discard regressions.

## Goal

Increase `numa_score` while preserving every hard product gate.

The score is deterministic and evaluated on the same 60 civil dates every experiment.
Production Numa v6 is evaluated on the exact same dates and is the baseline.

## The only file you may edit

`app/research/daily_horoscope_candidate.py`

Everything inside that file is fair game: story inventory, rotation logic, composition logic,
topic wording and compact editorial structure.

## Files you must not edit during an experiment run

- `app/research/daily_horoscope_evaluator.py`
- `app/services/daily_horoscope_benchmark.py`
- `app/services/daily_sky.py`
- `app/services/daily_horoscope_editorial.py`
- `app/bot/daily_horoscope.py`
- `scripts/run_daily_horoscope_autoresearch.py`
- tests, workflows, dependencies or migration files

Do not reduce the date window, weaken gates, alter score weights or change the production
baseline. Do not fetch competitor copy and do not insert Orakul text into the candidate.

## Product invariants

- The astronomy / solar-sign engine remains the source of the daily topic signal.
- Telegram caption limit is mandatory.
- Every day must contain all 12 signs exactly once.
- No adjacent-day exact repeats for a sign.
- Copy must remain compact enough for a morning Telegram digest.
- Advice should be useful and concrete, not keyword stuffing.
- Better metrics never justify awkward, robotic or misleading prose.
- Simpler improvements are preferable when scores are effectively equal.

## Setup

1. Create a fresh branch from current main, e.g. `autoresearch/daily-2026-09-01`.
2. Read:
   - this file;
   - `app/research/daily_horoscope_candidate.py`;
   - `app/research/daily_horoscope_evaluator.py`;
   - `app/services/daily_sky.py`.
3. Create an untracked `autoresearch/daily_horoscope/results.tsv` with:

```
commit\tnuma_score\tdelta\tgates\tstatus\tdescription
```

4. Establish the baseline candidate run before changing anything:

```bash
uv run python scripts/run_daily_horoscope_autoresearch.py > run.log 2>&1
grep "^numa_score:\|^baseline_score:\|^delta:\|^gates_passed:" run.log
```

## Experiment loop

Repeat until manually stopped:

1. Inspect the current best candidate and results history.
2. Form one clear editorial hypothesis.
3. Edit only `app/research/daily_horoscope_candidate.py`.
4. Run formatter/lint for that file.
5. Commit the candidate experiment.
6. Run:

```bash
uv run python scripts/run_daily_horoscope_autoresearch.py > run.log 2>&1
```

7. Read:

```bash
grep "^numa_score:\|^baseline_score:\|^delta:\|^gates_passed:" run.log
```

8. Append one line to `results.tsv` (do not commit the TSV).
9. Keep the commit only when:
   - `gates_passed: true`; and
   - its `numa_score` is strictly higher than the best kept score.

Otherwise reset to the previous best commit and try a different hypothesis.

If a run crashes, inspect the tail of `run.log`. Fix trivial implementation mistakes; discard
ideas that fundamentally violate the candidate contract.

## What to try

Prefer hypotheses such as:

- better topic coverage without adding length;
- more concrete situation → action phrasing;
- larger phrase inventory where repetition pressure is highest;
- better rotation across adjacent days;
- more natural lexical variation between signs;
- stronger temporal diversity without fake date-specific noise;
- cleaner phrasing that achieves equal metrics with less complexity.

Avoid gaming the evaluator by repeating topic/action keywords, adding filler, or making every
forecast structurally identical.

## Finish state

Never merge autonomously.

Leave the research branch at the highest-scoring valid candidate and provide:

- best score and production baseline;
- delta;
- number of experiments;
- kept/discarded/crashed counts;
- best candidate commit;
- concise explanation of the winning changes.

A human reviews the diff and decides whether to promote the winner into production.
