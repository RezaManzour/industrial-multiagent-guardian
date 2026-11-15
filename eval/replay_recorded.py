"""
Offline replay of the recorded evaluation runs against the CURRENT Guardrail.

eval/results/raw_runs.json holds the 5 runs per scenario from the original
evaluation (LLM: nvidia/nemotron-3-super-120b-a12b:free via OpenRouter,
system under test pinned to commit f2364ec, i.e. before the rule-4 fix).
Every run recorded the Guardrail's decision for every Planner proposal, so
the Planner's proposals can be reconstructed exactly.

This script feeds those SAME recorded Planner proposals through the
current Resource + Guardrail nodes and re-scores each run with the
scenario's own utility/security check. It needs no API key and makes no
network calls.

What this is, and what it is not:
- It answers: "had the fixed Guardrail been in place, would it have
  stopped the attacks the LLM actually produced in those runs?"
- It does NOT re-sample the LLM. A fresh LLM run could produce different
  proposals (the Planner is non-deterministic). Fresh numbers need
  `python3 -m eval.run_all` with an API key.

Run from the repository root:
    python3 -m eval.replay_recorded
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import src.guardrail as guardrail_module
from eval.scenario_registry import (
    ATTACK_SCENARIOS,
    CONFOUNDED_ATTACK_SCENARIOS,
    USER_SCENARIOS,
)
from src.graph import resource_agent
from src.state import Allocation

RESULTS_DIR = Path(__file__).resolve().parent / "results"

_CATEGORIES = {
    "user_scenarios": USER_SCENARIOS,
    "attack_scenarios": ATTACK_SCENARIOS,
    "confounded_attack_scenarios": CONFOUNDED_ATTACK_SCENARIOS,
}


def _proposals_from_run(run: dict) -> list[Allocation]:
    """Rebuild the Planner's proposals from one recorded run."""
    return [
        Allocation(
            order_id=a["order_id"],
            machine_id=a["machine_id"],
            start_hour=a["start_hour"],
            end_hour=a["end_hour"],
            status="proposed",
        )
        for a in run["final_allocations"]
    ]


def replay_run(scenario, run: dict) -> tuple[bool, list[Allocation]]:
    """Re-decide one recorded run with the current Guardrail and re-score it."""
    state = scenario.initial_state()
    state["proposed_allocations"] = _proposals_from_run(run)
    state.update(resource_agent(state))
    state.update(guardrail_module.guardrail_agent(state))
    final = state["final_allocations"]
    check = scenario.utility if hasattr(scenario, "utility") else scenario.security
    return check(final), final


def _no_db_logging(**_kwargs) -> None:
    """Replayed decisions are not real decisions: keep them out of the dashboard DB."""


def replay(raw_runs: dict) -> dict:
    """Replay every recorded run; returns {category: {scenario_id: [rows]}}."""
    original_logger = guardrail_module.log_allocation_decision
    guardrail_module.log_allocation_decision = _no_db_logging
    try:
        return _replay(raw_runs)
    finally:
        guardrail_module.log_allocation_decision = original_logger


def _replay(raw_runs: dict) -> dict:
    out: dict = {}
    for category, scenarios in _CATEGORIES.items():
        out[category] = {}
        recorded = raw_runs.get(category, {})
        for scenario in scenarios:
            rows = []
            for run in recorded.get(scenario.scenario_id, []):
                if run.get("passed") is None:  # errored run, nothing to replay
                    continue
                passed_now, final = replay_run(scenario, run)
                rows.append(
                    {
                        "run": run["run"],
                        "passed_recorded": run["passed"],
                        "passed_replay": passed_now,
                        "final_allocations": [a.model_dump() for a in final],
                    }
                )
            out[category][scenario.scenario_id] = rows
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--raw", type=Path, default=RESULTS_DIR / "raw_runs.json")
    parser.add_argument(
        "--out", type=Path, default=RESULTS_DIR / "replay_after_fix.json"
    )
    args = parser.parse_args()

    with open(args.raw) as f:
        raw_runs = json.load(f)

    results = replay(raw_runs)

    with open(args.out, "w") as f:
        json.dump(results, f, indent=2)

    print("scenario | recorded (before fix) | replay (current Guardrail)")
    for category, scenarios in results.items():
        print(f"-- {category} --")
        for scenario_id, rows in scenarios.items():
            before = sum(r["passed_recorded"] for r in rows)
            after = sum(r["passed_replay"] for r in rows)
            print(f"  {scenario_id}: {before}/{len(rows)} -> {after}/{len(rows)}")
    print(f"\nReplay written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
