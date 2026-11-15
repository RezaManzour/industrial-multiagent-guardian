# Industrial Multi-Agent Guardian

[![tests](https://github.com/RezaManzour/industrial-multiagent-guardian/actions/workflows/tests.yml/badge.svg)](https://github.com/RezaManzour/industrial-multiagent-guardian/actions/workflows/tests.yml)
[![Python 3.11 | 3.12 | 3.13](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)](https://www.python.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![License: MIT](https://img.shields.io/github/license/RezaManzour/industrial-multiagent-guardian)](LICENSE)
[![Streamlit demo](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://industrial-multiagent-guardian-29dzxxjmrktabfuybthnrq.streamlit.app/)

A multi-agent industrial scheduling system built with LangGraph, featuring a **deterministic, rule-based safety layer** that has final authority over every decision — regardless of what the underlying LLM proposes. The repository also contains an **adversarial evaluation** of that claim ([`eval/`](eval/)), which found one real gap in the rules; the gap is fixed in this version (see [Adversarial evaluation: a gap found and fixed](#adversarial-evaluation-a-gap-found-and-fixed)).

**🔗 Live demo:** https://industrial-multiagent-guardian-29dzxxjmrktabfuybthnrq.streamlit.app/
(hosted on Streamlit Community Cloud, which puts apps to sleep when nobody uses them; if you see a sleep page, click the button to wake it and give it a minute.)

## Motivation

LLM-based agents are increasingly used for planning and scheduling tasks, but relying on an LLM to *also* enforce safety and business-rule compliance is fragile: language models can hallucinate, misread constraints, or simply be inconsistent. This project explores an alternative architecture where the LLM is used strictly for **planning and narration**, while a separate, fully deterministic Python module holds exclusive authority to approve or reject any action.

This design is informed by the argument in [AGrail](https://arxiv.org/abs/2502.11448) (Luo et al., ACL 2025) for separating guardrail logic from the reasoning model.

The adversarial/safety evaluation of this system, methodologically grounded in [AgentDojo](https://arxiv.org/abs/2406.13352) (Debenedetti et al., NeurIPS 2024), is in [`eval/`](eval/). It was developed as a separate repository and merged in here with its full commit history.

## Architecture

```
+-------------+     +--------------+     +-----------------------+
|   Planner   |---->|   Resource   |---->|      Guardrail        |
|   Agent     |     |   Agent      |     |  (rule-based, no LLM) |
|  (LLM call) |     | (aggregates) |     |  final approve/reject |
+-------------+     +--------------+     +-----------------------+
       |                                            |
       v                                            v
  agent_log (narration only,              final_allocations
  never used for decisions)          (the only authoritative output)
```

The graph is orchestrated with **LangGraph**'s `StateGraph`: `START → planner → resource → guardrail → END`.

### Design principle: the LLM never decides

- The **Planner Agent** calls an LLM to *propose* an order→machine allocation. Its output is validated against a strict Pydantic schema (`ask_llm_structured` in `src/llm_client.py`), and any malformed or hallucinated output is caught and logged as a failed proposal — it never reaches the Guardrail as if it were valid.
- The **Guardrail** (`src/guardrail.py`) is pure, dependency-free Python. It enforces 6 deterministic rules:
  1. `order_id` must reference a real order
  2. `machine_id` must reference a real machine
  3. Time range must be valid (`start_hour >= 0` and `start_hour < end_hour`)
  4. Allocated duration must cover the order's required processing time, and may exceed it by at most a factor of `MAX_DURATION_FACTOR` (1.5, rounded up to whole hours). The upper bound was added after the adversarial evaluation; see below.
  5. `end_hour` must not exceed the order's deadline
  6. The allocation must not exceed the machine's capacity for any overlapping time slot

Only allocations that were actually approved count against a machine's capacity.

Because the Guardrail has zero LLM dependency, it runs in milliseconds and is fully unit-testable — including against deliberately adversarial/hallucinated inputs (see `tests/test_end_to_end_rejection.py`).

## Adversarial evaluation: a gap found and fixed

The evaluation in [`eval/`](eval/) feeds adversarial order data to the real pipeline (real LLM Planner, real Guardrail) and checks whether the Guardrail's final decisions stay safe even when the Planner is fooled. Across 6 attack scenarios, 5 runs each, with a single free-tier model (`nvidia/nemotron-3-super-120b-a12b:free` via OpenRouter), the Guardrail as originally written held in **25 of 30 runs**. This is a small sample from one model, so it shows which failures are possible rather than estimating a failure rate.

All 5 failures were the same, reproducible gap. Rule 4 had only a lower bound on allocation length. An order needing 1 hour carried text that talked the Planner into reserving the only machine for 24 hours; the Guardrail approved it, and a legitimate competing order was then rejected for capacity.

What changed in this version:

1. **Rule 4 now has an upper bound** (`MAX_DURATION_FACTOR` in `src/guardrail.py`), so the 24-hour reservation is rejected on its own merits.
2. **Rejected proposals no longer hold capacity.** Writing the regression test exposed a second bug: the capacity check counted every earlier decision, including rejected ones, so even with the new bound the victim order was still blocked. The check now counts only approved allocations.

Verification, all offline:

- Unit and end-to-end regression tests for both fixes (`tests/`).
- [`eval/replay_recorded.py`](eval/replay_recorded.py) re-decides the Planner proposals recorded in the original 30 runs with the fixed Guardrail: the vulnerable scenario goes from 0/5 to 5/5 and every other scenario stays 5/5. This re-scores recorded LLM output; it does not re-sample the LLM. The headline 25/30 above is from the original runs, before the fix. Fresh LLM runs need an API key (`python3 -m eval.run_all`).

What the fix does not change: when two valid proposals compete for the same capacity, the Guardrail still approves whichever it evaluates first (eval Finding 7).

## Tech Stack

| Component | Technology |
|---|---|
| Orchestration | LangGraph (`StateGraph`) |
| LLM interface | OpenAI SDK (OpenRouter-compatible) |
| Schema validation | Pydantic |
| Logging | SQLite |
| Dashboard | Streamlit |
| Testing | pytest |

The LLM backend is **provider-agnostic** (`LLM_PROVIDER` env var) — currently configured for OpenRouter's free-tier models, with DeepSeek available as an unused fallback. This was a deliberate design choice: when one free-tier model hit an upstream rate limit during development, switching providers required a one-line config change, not a code change.

## Getting Started

### Prerequisites
- Python 3.11+ (CI runs the test suite on Python 3.11, 3.12 and 3.13)
- An OpenRouter API key ([get one here](https://openrouter.ai/settings/keys))

### Installation

```bash
git clone https://github.com/RezaManzour/industrial-multiagent-guardian.git
cd industrial-multiagent-guardian
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Configuration

Copy the example env file and add your API key:

```bash
cp .env.example .env
# then edit .env and set OPENROUTER_API_KEY
```

### Run the multi-agent pipeline

```bash
python3 -m src.graph
```

This runs a 2-order, 2-machine scenario end-to-end: Planner proposes allocations via LLM, Resource aggregates them, and Guardrail issues the final approve/reject decisions.

### Run the dashboard

```bash
streamlit run src/dashboard.py
```

Shows approval/rejection stats, per-decision detail, and LLM token usage/cost (currently $0, since the default model is free-tier).

**Note on deployment:** this project was originally planned for Hugging Face Spaces, but as of ~July 2026, HF Spaces' Docker SDK (required for Streamlit apps, since the native Streamlit SDK was deprecated) is paid-only for free personal accounts. The dashboard is instead deployed on [Streamlit Community Cloud](https://streamlit.io/cloud), which required zero code changes.

### Run the tests

```bash
python3 -m pytest tests/ -v
```

33 tests, **zero network calls and no API key needed** — the suite is fully offline and deterministic, and runs in CI on every push:
- `tests/test_guardrail.py` (19): each rule in isolation, including the rule-4 upper bound and its boundaries
- `tests/test_end_to_end_rejection.py` (5): adversarial scenarios through the real Resource and Guardrail nodes (capacity conflicts, deadline violations, hallucinated machine IDs, the resource-hogging attack found by the evaluation)
- `tests/test_eval_offline.py` (9): the evaluation harness end to end with the LLM replaced by a scripted fake, plus the replay of the recorded evaluation runs

Lint with `ruff check .` (configured in `pyproject.toml`).

### Run the adversarial evaluation

```bash
# Offline: re-decide the recorded runs with the current Guardrail (no API key)
python3 -m eval.replay_recorded

# Live: run every scenario against the real LLM (needs OPENROUTER_API_KEY in .env)
python3 -m eval.run_all --runs 5
```

See [`eval/README.md`](eval/README.md) for the methodology and [`eval/RESULTS.md`](eval/RESULTS.md) for the results.

## Project Structure

```
industrial-multiagent-guardian/
+-- .github/workflows/tests.yml  # CI: ruff + pytest on Python 3.11-3.13
+-- src/
|   +-- state.py       # Pydantic schemas: Order, Machine, Allocation, SchedulingState
|   +-- llm_client.py  # Provider-agnostic LLM client with structured-output validation
|   +-- graph.py        # LangGraph StateGraph: Planner, Resource, Guardrail nodes
|   +-- guardrail.py    # Deterministic rule-based safety layer (no LLM)
|   +-- db.py            # SQLite logging (LLM calls + allocation decisions)
|   +-- dashboard.py     # Streamlit observability dashboard
+-- tests/
|   +-- test_guardrail.py              # Unit tests for individual rules
|   +-- test_end_to_end_rejection.py   # Adversarial end-to-end scenarios
|   +-- test_eval_offline.py           # Eval harness with a scripted fake LLM
+-- eval/              # Adversarial evaluation (merged from its own repo, history kept)
|   +-- scenarios/          # User (benign) and attack scenarios
|   +-- harness.py          # Runs a scenario through the real pipeline
|   +-- run_all.py          # Every scenario N times against the live LLM
|   +-- replay_recorded.py  # Offline replay of recorded runs against the current Guardrail
|   +-- results/            # Raw runs (before the fix) and the replay
|   +-- RESULTS.md, FINDINGS.md
+-- pyproject.toml     # pytest and ruff configuration
+-- requirements.txt
```


## Sample Output

```
=== Agent Log ===
[Planner] Proposed allocation for ORD-1: M2 (0-2)
[Planner] Proposed allocation for ORD-2: M1 (0-2)
[Resource] Current proposed load by machine: M2: 1 order(s), M1: 1 order(s)
[Guardrail] APPROVED ORD-1 -> M2 (0-2)
[Guardrail] APPROVED ORD-2 -> M1 (0-2)
```


## Limitations & Future Work

- The current scenario handles single-capacity machines and a small order set; scaling to larger batches and multi-slot capacity has not yet been load-tested.
- The Planner Agent currently proposes allocations independently per order rather than jointly optimizing across the full order set.
- The adversarial evaluation used one free-tier model and 5 runs per scenario. Other models, more runs, and new attack categories could surface gaps the current scenarios do not.
- The rule-4 fix has been verified offline (unit tests and a replay of the recorded Planner proposals). It has not yet been re-measured with fresh LLM runs.
- Competing valid proposals are still decided first-come, first-served, so outcomes can depend on order list position (eval Finding 7).
- The Planner's duplicate-order check is computed once before its loop, so two orders sharing an `order_id` are both sent to the LLM; the Guardrail's duplicate check catches the second (eval Finding 9). Rejecting duplicate ids at input would be cleaner.

## Related Work

- [AGrail](https://arxiv.org/abs/2502.11448) (Luo et al., ACL 2025) — guardrail/reasoning separation for LLM agents
- [AgentDojo](https://arxiv.org/abs/2406.13352) (Debenedetti et al., NeurIPS 2024) — adversarial evaluation framework for LLM agents, methodological basis for [`eval/`](eval/)
- Manufacturing/FJSP literature on multi-agent scheduling systems

## Citing

Please cite this repository with the metadata in [`CITATION.cff`](CITATION.cff) (the **Cite this repository** button on GitHub).

## Contributing

Issues and pull requests are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md) and the [Code of Conduct](CODE_OF_CONDUCT.md).
Security problems: see [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE)
