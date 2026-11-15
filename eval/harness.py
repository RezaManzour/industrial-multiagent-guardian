"""
Evaluation harness: runs UserScenario / AttackScenario instances through
the real system in this repository (the `src` package: Planner -> Resource
-> Guardrail) and records verdicts.

The harness never modifies Planner or Guardrail logic. The only thing it
adds is a retry wrapper for transient LLM-provider errors.

Historical note: the numbers in RESULTS.md (25/30) were produced when this
evaluation lived in its own repository and ran against a vendored copy of
`src/` pinned to commit f2364ec (the copy differed from the original only
in using package-relative imports). Since the merge, the harness runs
against the in-repo `src` package directly, so any rerun evaluates the
current Guardrail, including the rule-4 maximum-duration fix.
"""

from __future__ import annotations

from dataclasses import dataclass

from eval.scenarios.base import AttackScenario, UserScenario
from src.db import init_db
from src.graph import build_graph


@dataclass
class ScenarioResult:
    scenario_id: str
    kind: str  # "user" | "attack"
    passed: bool  # utility (user scenarios) or security (attack scenarios)
    final_allocations: list
    agent_log: list[str]


def _run(scenario, max_attempts: int = 5) -> tuple[list, list[str]]:
    """
    Runs the scenario, retrying the whole graph invocation on transient
    provider errors (observed: OpenRouter free-tier models occasionally
    return message.content=None, causing a TypeError deep in
    src/llm_client.py). This wrapper lives in the harness deliberately -
    it does not alter Planner/Guardrail logic, only retries the same
    unmodified pipeline on infra flakiness. Logged in FINDINGS.md
    (Finding 3) as a known reliability issue with the free model.
    """
    init_db()  # ensure llm_calls / allocation_decisions tables exist
    graph = build_graph()
    last_exception: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = graph.invoke(scenario.initial_state())
            return result["final_allocations"], result["agent_log"]
        except Exception as e:
            last_exception = e
            if attempt < max_attempts:
                print(
                    f"[harness] Attempt {attempt}/{max_attempts} failed with "
                    f"{type(e).__name__}: {e}. Retrying..."
                )
            else:
                print(f"[harness] Attempt {attempt}/{max_attempts} failed. Giving up.")
    raise last_exception


def run_user_scenario(scenario: UserScenario) -> ScenarioResult:
    final_allocations, agent_log = _run(scenario)
    return ScenarioResult(
        scenario_id=scenario.scenario_id,
        kind="user",
        passed=scenario.utility(final_allocations),
        final_allocations=final_allocations,
        agent_log=agent_log,
    )


def run_attack_scenario(scenario: AttackScenario) -> ScenarioResult:
    final_allocations, agent_log = _run(scenario)
    return ScenarioResult(
        scenario_id=scenario.scenario_id,
        kind="attack",
        passed=scenario.security(final_allocations),
        final_allocations=final_allocations,
        agent_log=agent_log,
    )
