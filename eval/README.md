# Industrial Multi-Agent Guardian — Adversarial/Safety Evaluation

An adversarial evaluation of the multi-agent industrial scheduling system
in this repository (see the [main README](../README.md)). It asks one
question: **does the system's rule-based Guardrail layer stay safe even
when its LLM Planner agent is manipulated by adversarial input?**

This folder started as a separate repository
(`industrial-multiagent-guardian-adversarial-eval`) and was merged in here
with its full commit history, so the evaluation and the system it
evaluates now live and are tested together.

## Why this matters

The system deliberately separates two roles:

- an **LLM Planner** that proposes machine allocations for production
  orders using natural-language reasoning, and
- a **deterministic, rule-based Guardrail** (plain Python, zero LLM
  calls) that has sole authority to approve or reject those proposals.

This mirrors the separation-of-concerns argument in
[AGrail](https://arxiv.org/abs/2502.11448) and related agent-safety
literature: an LLM's outputs may be unreliable or manipulable, but a
system can still be safe overall if the component making final decisions
is not itself an LLM. This evaluation tests that claim empirically,
adapting the methodology (task/injection vocabulary, utility vs. security
metrics) of [AgentDojo](https://arxiv.org/abs/2406.13352) (Debenedetti et
al., NeurIPS 2024) to a linear pipeline rather than AgentDojo's
tool-calling agent setting — see `scenarios/base.py` for the adaptation
rationale.

## Result summary

Across 6 attack scenarios spanning 3 categories (prompt injection,
goal-hijacking, structured-output edge cases), **security held in 25 of
30 runs** against the Guardrail as originally written. That is 5 runs per
scenario with a single free-tier model
(`nvidia/nemotron-3-super-120b-a12b:free` via OpenRouter), so it shows
which failures are possible, not a failure rate for LLM planners in
general.

All 5 failures were one reproducible vulnerability: a missing upper
bound in Guardrail rule 4 let an order claim an implausibly long machine
reservation, starving a legitimate competing order — a genuine gap in
rule coverage, not a rule being "tricked."

**Fixed in this version.** Rule 4 now caps allocation length, and a second
bug found while writing the regression test (rejected proposals still
counted against machine capacity) is fixed too. Replaying the Planner
proposals recorded in the original 30 runs against the fixed Guardrail,
the vulnerable scenario goes from 0/5 to 5/5 and the others stay 5/5
(`python3 -m eval.replay_recorded`, no API key needed). The fix has not
yet been re-measured with fresh LLM runs.

Details: **[`RESULTS.md`](./RESULTS.md)** (summary + analysis) and
**[`FINDINGS.md`](./FINDINGS.md)** (the chronological lab notebook,
including a methodological mistake that was found via a control test and
corrected rather than reported as a false positive).

## How this evaluation works

- **System under test.** The harness runs the real pipeline from this
  repository's `src/` package (Planner -> Resource -> Guardrail),
  unmodified. The original 30 runs in `results/raw_runs.json` were made
  while this evaluation was a separate repository, against a copy of
  `src/` pinned to commit `f2364ec`; that copy matched the original
  except that its imports were made package-relative so it could be
  vendored.
- **Scenarios**, in `scenarios/`, follow AgentDojo-inspired vocabulary:
  a `UserScenario` (legitimate case, checked for utility) or an
  `AttackScenario` (adversarial case, checked for security — whether the
  Guardrail's deterministic output resists the attacker's goal, not an
  LLM judge's opinion).
- **The harness** (`harness.py`) runs a scenario through the real system
  (including a real LLM call) and records the outcome. It includes a
  retry wrapper for transient provider errors, which never touches
  Planner or Guardrail logic.
- **`run_all.py`** runs every registered scenario N times against the
  live LLM and writes raw results (by default to
  `results/latest_runs.json`, so the original `raw_runs.json` is kept).
- **`replay_recorded.py`** re-decides the recorded Planner proposals in
  `raw_runs.json` with the current Guardrail, offline.
- **Offline tests** in `../tests/test_eval_offline.py` run the harness
  end to end with the LLM call replaced by a scripted fake, and run in CI.

## Structure

```
eval/
    scenarios/
        base.py               UserScenario / AttackScenario definitions
        user_scenarios/       Legitimate baseline scenario(s)
        attack_scenarios/     All attack scenarios (see RESULTS.md for the list)
    harness.py                Runs scenarios through the real system
    scenario_registry.py      Central list of all scenarios
    run_all.py                Runs every scenario N times against the live LLM
    run_scenario.py           Manual single-scenario runner (dev/debugging)
    replay_recorded.py        Offline replay of recorded runs against the current Guardrail
    results/raw_runs.json     Raw per-run output of the original evaluation (before the fix)
    results/replay_after_fix.json   Output of replay_recorded.py
    RESULTS.md                Summary table + analysis
    FINDINGS.md               Chronological lab notebook
```

## Running it yourself

From the repository root, after installing `requirements.txt`:

```bash
# Offline, no API key: replay the recorded runs against the current Guardrail
python3 -m eval.replay_recorded

# Live: needs an OpenRouter key in .env (see .env.example)
# LLM_PROVIDER=openrouter, OPENROUTER_MODEL=nvidia/nemotron-3-super-120b-a12b:free
python3 -m eval.run_all --runs 5
```

## Author

Built by [Reza Manzour](https://github.com/RezaManzour) as the evaluation
companion to the Industrial Multi-Agent Guardian, part of a portfolio for
graduate applications in agentic AI / AI safety.
