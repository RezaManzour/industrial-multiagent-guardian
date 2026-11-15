"""
Manual runner for a single scenario, for interactive testing during development.

Run from the repository root: python3 -m eval.run_scenario
"""

import sys

from eval.harness import run_user_scenario
from eval.scenarios.user_scenarios.basic_two_orders import SCENARIO


def main() -> int:
    result = run_user_scenario(SCENARIO)

    print(f"=== Scenario: {result.scenario_id} ({result.kind}) ===")
    print(f"PASSED: {result.passed}\n")

    print("--- Agent Log ---")
    for line in result.agent_log:
        print(line)

    print("\n--- Final Allocations ---")
    for alloc in result.final_allocations:
        print(alloc)

    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
