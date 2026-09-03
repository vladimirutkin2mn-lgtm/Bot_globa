# Numa Autoresearch · LLM

This harness improves Numa's four production personas through controlled prompt/model
experiments on a fixed synthetic dataset.

It follows the same keep/discard pattern as the daily-horoscope autoresearch, but unlike
that evaluator this one makes real LLM calls and therefore can spend provider money.

## Goal

Improve `quality_score` while every hard product gate remains green.

Cost and latency are reported separately. Do not trade away safety, schema integrity,
Russian output, Tarot/astrology grounding or share-card privacy merely to reduce spend.

## The only prompt file an autonomous experiment may edit

`app/research/oracle_prompt_candidate.py`

The fixed evaluator and dataset are immutable during an experiment:

- `app/research/oracle_llm_dataset.py`
- `app/research/oracle_llm_evaluator.py`
- production prompt modules;
- validators and safety rules;
- tests, workflows and dependencies.

If the evaluator appears wrong, stop the experiment and fix the evaluator in a separate
reviewed PR. Never change the reward function and candidate in the same experiment.

## Dataset

`oracle-llm-dataset-v1` contains 12 invented cases:

- 3 Tarot reader;
- 3 Love Oracle;
- 3 Mystical Psychologist;
- 3 Astrologer.

Cases cover ordinary product questions plus prompt-injection resistance. No production user
text, memory, Telegram IDs, reading IDs or real birth data may be added.

## Hard gates

Every case must:

1. pass the production structured-output validator;
2. pass production semantic/safety validation;
3. remain predominantly Russian user-facing prose;
4. keep case-specific names/private terms out of `share_card`;
5. ignore the fixed prompt-injection marker.

Tarot symbol identity and orientation are protected by the production validator. Astrologer
fact IDs, digest and limitations are protected by the production Horoscope validator.

A candidate that fails any hard gate receives `numa_score = 0`.

## Quality score

The deterministic evaluator rewards:

- answering the concrete question rather than opening with generic filler;
- using details from the synthetic situation;
- one actionable next step;
- persona-specific voice;
- explicit uncertainty where appropriate;
- reasonable answer size;
- natural Russian.

Do not keyword-stuff these signals. A higher metric does not justify robotic copy.

## Spend discipline

The runner does real provider calls. The fixed dataset currently uses 12 primary calls and
may use one repair per case if the first answer fails validation.

Before a new model experiment:

1. know the provider's input/output token price;
2. pass both rates to the runner;
3. run the production baseline once;
4. reuse the saved baseline JSON for candidate comparisons.

Do not repeatedly regenerate the production baseline.

## Baseline

Run from `bot_globa/`:

```bash
export OPENAI_API_KEY=...
uv run python scripts/run_oracle_llm_autoresearch.py \
  --prompt-source production \
  --model <model> \
  --input-cost-usd-per-million <rate> \
  --output-cost-usd-per-million <rate> \
  --output-dir autoresearch-artifacts/oracle-llm/baseline
```

Keep `baseline/oracle-llm-autoresearch.json` locally. Do not commit generated reports.

## Experiment loop

1. Create a research branch from current `main`.
2. Establish the baseline for the exact provider/model.
3. Edit only `app/research/oracle_prompt_candidate.py`.
4. Commit one clear hypothesis.
5. Run:

```bash
uv run python scripts/run_oracle_llm_autoresearch.py \
  --prompt-source candidate \
  --model <same-model> \
  --input-cost-usd-per-million <rate> \
  --output-cost-usd-per-million <rate> \
  --baseline-report autoresearch-artifacts/oracle-llm/baseline/oracle-llm-autoresearch.json \
  --output-dir autoresearch-artifacts/oracle-llm/candidate
```

6. Inspect:

```bash
grep "^numa_score:\|^quality_score:\|^gates_passed:\|^repair_rate:\|^estimated_cost_usd:\|^quality_delta:\|^cost_delta_usd:" \
  autoresearch-run.log
```

7. Keep the change only when:
   - all hard gates pass;
   - `quality_delta > 0`;
   - any extra cost/latency is proportionate to the quality gain.

If scores are effectively equal, prefer lower repair rate, lower cost, lower latency and the
simpler prompt.

## Model comparison

Compare models using the unchanged production prompt source first. Each model gets its own
baseline report and pricing. Do not compare quality deltas across different dataset versions.

A cheaper model is a valid winner only if all hard gates pass and its quality loss is
acceptable by human review.

## LangSmith

If `LANGSMITH_ENABLED=true`, research calls use the existing privacy-safe Numa tracing
wrapper. Traces contain operational metadata/tokens/latency only, not the synthetic prompt or
model output. This keeps the same privacy contract as production.

## GitHub Actions

The paid workflow is `workflow_dispatch` only. It never runs on push or pull request, so
opening a PR cannot accidentally spend LLM budget.

## Finish state

Never promote a prompt candidate automatically.

Provide:

- provider/model;
- baseline and best quality score;
- hard-gate result;
- repair-rate delta;
- token/cost delta;
- latency delta;
- number of kept/discarded experiments;
- candidate commit and concise prompt diff.

A human decides whether to copy the winner into the production prompt modules.
