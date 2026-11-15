"""
Evaluation harness: runs UserScenario / AttackScenario instances through
the real (vendored) Project 1 system and records verdicts.
"""

from __future__ import annotations

from dataclasses import dataclass

from vendored.guardian.graph import build_graph
from vendored.guardian.db import init_db
from src.scenarios.base import UserScenario, AttackScenario

init_db()  # ensure llm_calls / allocation_decisions tables exist


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
    vendored/guardian/llm_client.py). This wrapper lives OUTSIDE the
    vendored code deliberately - it does not alter Planner/Guardrail
    logic, only retries the same unmodified pipeline on infra flakiness.
    Logged to FINDINGS.md as a known reliability issue with the free model.
    """
    graph = build_graph()
    last_exception: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = graph.invoke(scenario.initial_state())
            return result["final_allocations"], result["agent_log"]
        except Exception as e:
            last_exception = e
            print(f"[harness] Attempt {attempt}/{max_attempts} failed with "
                  f"{type(e).__name__}: {e}. Retrying..." if attempt < max_attempts
                  else f"[harness] Attempt {attempt}/{max_attempts} failed. Giving up.")
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
