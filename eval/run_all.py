"""
Runs every scenario in the registry N times each, prints a summary
table, and writes raw per-run results to results/raw_runs.json for
RESULTS.md to be built from.

Usage: python3 run_all.py [--runs N]
"""

import argparse
import json
import sys
from pathlib import Path

from src.harness import run_user_scenario, run_attack_scenario
from src.scenario_registry import USER_SCENARIOS, ATTACK_SCENARIOS, CONFOUNDED_ATTACK_SCENARIOS

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def _run_many(scenario, run_fn, n):
    outcomes = []
    for i in range(1, n + 1):
        print(f"  [{scenario.scenario_id}] run {i}/{n}...", flush=True)
        try:
            result = run_fn(scenario)
            outcomes.append({
                "run": i,
                "passed": result.passed,
                "agent_log": result.agent_log,
                "final_allocations": [a.model_dump() for a in result.final_allocations],
            })
        except Exception as e:
            outcomes.append({
                "run": i,
                "passed": None,
                "error": f"{type(e).__name__}: {e}",
            })
    return outcomes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args()

    all_results = {"user_scenarios": {}, "attack_scenarios": {}, "confounded_attack_scenarios": {}}

    print(f"=== Running {len(USER_SCENARIOS)} user scenario(s), {args.runs} runs each ===")
    for s in USER_SCENARIOS:
        all_results["user_scenarios"][s.scenario_id] = _run_many(s, run_user_scenario, args.runs)

    print(f"\n=== Running {len(ATTACK_SCENARIOS)} attack scenario(s), {args.runs} runs each ===")
    for s in ATTACK_SCENARIOS:
        all_results["attack_scenarios"][s.scenario_id] = _run_many(s, run_attack_scenario, args.runs)

    print(f"\n=== Running {len(CONFOUNDED_ATTACK_SCENARIOS)} confounded attack scenario(s) (excluded from official results), {args.runs} runs each ===")
    for s in CONFOUNDED_ATTACK_SCENARIOS:
        all_results["confounded_attack_scenarios"][s.scenario_id] = _run_many(s, run_attack_scenario, args.runs)

    RESULTS_DIR.mkdir(exist_ok=True)
    out_path = RESULTS_DIR / "raw_runs.json"
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2)

    print(f"\n=== Summary (pass rate = utility for user scenarios, security-held rate for attack scenarios) ===")
    for category, scenarios in all_results.items():
        print(f"\n-- {category} --")
        for scenario_id, outcomes in scenarios.items():
            valid = [o for o in outcomes if o["passed"] is not None]
            errored = [o for o in outcomes if o["passed"] is None]
            passed = sum(1 for o in valid if o["passed"])
            print(f"  {scenario_id}: {passed}/{len(valid)} passed"
                  + (f" ({len(errored)} errored/skipped)" if errored else ""))

    print(f"\nRaw results written to {out_path}")


if __name__ == "__main__":
    sys.exit(main())
