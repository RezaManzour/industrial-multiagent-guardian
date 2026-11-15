# Industrial Multi-Agent Guardian — Adversarial/Safety Evaluation

An adversarial evaluation of [`industrial-multiagent-guardian`](https://github.com/RezaManzour/industrial-multiagent-guardian),
a multi-agent industrial scheduling system built with LangGraph. This
repository asks one question: **does the system's rule-based Guardrail
layer stay safe even when its LLM Planner agent is manipulated by
adversarial input?**

**Live demo of the system under evaluation:** https://industrial-multiagent-guardian-29dzxxjmrktabfuybthnrq.streamlit.app/

## Why this matters

`industrial-multiagent-guardian` deliberately separates two roles:

- an **LLM Planner** that proposes machine allocations for production
  orders using natural-language reasoning, and
- a **deterministic, rule-based Guardrail** (plain Python, zero LLM
  calls) that has sole authority to approve or reject those proposals.

This mirrors the separation-of-concerns argument in **AGrail** and
related agent-safety literature: an LLM's outputs may be unreliable or
manipulable, but a system can still be safe overall if the component
making final decisions is not itself an LLM. This repo tests that claim
empirically, adapting the methodology (task/injection vocabulary,
utility vs. security metrics) of **AgentDojo** (Debenedetti et al.,
NeurIPS 2024) to a linear pipeline rather than AgentDojo's tool-calling
agent setting — see `src/scenarios/base.py` for the adaptation
rationale.

## Result summary

Across 6 attack scenarios spanning 3 categories (prompt injection,
goal-hijacking, structured-output edge cases), **security held in
25/30 runs (83%)**. One vulnerability was found and confirmed 100%
reproducible: a missing upper bound in one Guardrail rule lets an order
claim an implausibly long machine reservation, starving a legitimate
competing order — a genuine gap in rule coverage, not a rule being
"tricked." Full results, methodology, and the false leads that were
caught and corrected along the way: **[`RESULTS.md`](./RESULTS.md)**
(summary + analysis) and **[`FINDINGS.md`](./FINDINGS.md)** (full
narrative log, including a methodological mistake that was found via a
control test and corrected rather than reported as a false positive).

## How this evaluation works

- **The system under test is vendored, not modified.** The exact files
  being evaluated (`state.py`, `graph.py`, `guardrail.py`,
  `llm_client.py`, `db.py`) are copied verbatim into `vendored/guardian/`,
  pinned to a specific commit of the source repository (see
  `vendored/guardian/VENDORED_FROM.md`), so results are reproducible
  regardless of later changes to the live project.
- **Scenarios**, in `src/scenarios/`, follow AgentDojo-inspired
  vocabulary: a `UserScenario` (legitimate case, checked for utility)
  or an `AttackScenario` (adversarial case, checked for security —
  whether the Guardrail's deterministic output resists the attacker's
  goal, not an LLM judge's opinion).
- **The harness** (`src/harness.py`) runs a scenario through the real,
  unmodified vendored system (including a real LLM call) and records
  the outcome. It includes a retry wrapper for transient provider
  errors — deliberately kept outside the vendored code so the system
  under evaluation is never altered.
- **`run_all.py`** runs every registered scenario N times and writes
  raw results to `results/raw_runs.json`, the data source for
  `RESULTS.md`.

## Project structure

```
industrial-multiagent-guardian-adversarial-eval/
    vendored/guardian/           Project 1 source, vendored and pinned to a commit
    src/
        scenarios/
            base.py               UserScenario / AttackScenario definitions
            user_scenarios/       Legitimate baseline scenario(s)
            attack_scenarios/     All attack scenarios (see RESULTS.md for the list)
        harness.py                Runs scenarios through the real system
        scenario_registry.py      Central list of all scenarios
    run_all.py                    Runs every scenario N times, writes raw results
    run_scenario.py               Manual single-scenario runner (dev/debugging)
    results/raw_runs.json         Raw per-run output from run_all.py
    RESULTS.md                    Summary table + analysis
    FINDINGS.md                   Full narrative log of the evaluation process
```

## Running it yourself

Requires Python 3.11+ and an OpenRouter API key (the vendored system's
`llm_client.py` is provider-agnostic; OpenRouter is used here to match
the live deployment of Project 1).

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env: set OPENROUTER_API_KEY, LLM_PROVIDER=openrouter,
# OPENROUTER_MODEL=nvidia/nemotron-3-super-120b-a12b:free

python3 run_all.py --runs 5
```

## Author

Built by [Reza Manzour](https://github.com/RezaManzour) as a companion
evaluation to [`industrial-multiagent-guardian`](https://github.com/RezaManzour/industrial-multiagent-guardian),
part of a portfolio for graduate applications in agentic AI / AI
safety.
