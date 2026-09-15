# Industrial Multi-Agent Guardian

A multi-agent industrial scheduling system built with LangGraph, featuring a **deterministic, rule-based safety layer** that has final authority over every decision — regardless of what the underlying LLM proposes.

**🔗 Live demo:** https://industrial-multiagent-guardian-29dzxxjmrktabfuybthnrq.streamlit.app/

## Motivation

LLM-based agents are increasingly used for planning and scheduling tasks, but relying on an LLM to *also* enforce safety and business-rule compliance is fragile: language models can hallucinate, misread constraints, or simply be inconsistent. This project explores an alternative architecture where the LLM is used strictly for **planning and narration**, while a separate, fully deterministic Python module holds exclusive authority to approve or reject any action.

This design is informed by the AGrail framework's argument for separating guardrail logic from the reasoning model, and mirrors patterns used in production safety-critical agent systems (e.g. the "Aizen" architecture on Hugging Face Spaces).

A companion project (in progress) performs an adversarial/safety evaluation of this system, methodologically grounded in the [AgentDojo](https://github.com/ethz-spylab/agentdojo) framework.

## Architecture

The graph is orchestrated with **LangGraph**'s `StateGraph`: `START → planner → resource → guardrail → END`.

### Design principle: the LLM never decides

- The **Planner Agent** calls an LLM to *propose* an order→machine allocation. Its output is validated against a strict Pydantic schema (`ask_llm_structured` in `src/llm_client.py`), and any malformed or hallucinated output is caught and logged as a failed proposal — it never reaches the Guardrail as if it were valid.
- The **Guardrail** (`src/guardrail.py`) is pure, dependency-free Python. It enforces 6 deterministic rules:
  1. `order_id` must reference a real order
  2. `machine_id` must reference a real machine
  3. Time range must be valid (`start_hour >= 0` and `start_hour < end_hour`)
  4. Allocated duration must cover the order's required processing time
  5. `end_hour` must not exceed the order's deadline
  6. The allocation must not exceed the machine's capacity for any overlapping time slot

Because the Guardrail has zero LLM dependency, it runs in milliseconds and is fully unit-testable — including against deliberately adversarial/hallucinated inputs (see `tests/test_end_to_end_rejection.py`).

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
- Python 3.11+ (developed and tested on 3.14)
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

13 tests, all passing, **zero network calls** — the Guardrail test suite is fully offline and deterministic:
- 9 unit tests covering each of the 6 rules in isolation
- 4 end-to-end adversarial tests simulating realistic LLM failure modes (capacity conflicts, deadline violations, hallucinated machine IDs)

## Project Structure

## Sample Output

## Limitations & Future Work

- The current scenario handles single-capacity machines and a small order set; scaling to larger batches and multi-slot capacity has not yet been load-tested.
- The Planner Agent currently proposes allocations independently per order rather than jointly optimizing across the full order set.
- Deployment to Hugging Face Spaces and a full adversarial safety evaluation (Project 2) are in progress.

## Related Work

- AGrail — guardrail/reasoning separation for LLM agents
- AgentDojo — adversarial evaluation framework for LLM agents (methodological basis for the companion Project 2)
- Manufacturing/FJSP literature on multi-agent scheduling systems

## License

MIT
