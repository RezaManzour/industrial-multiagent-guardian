"""
Base abstractions for the adversarial/safety evaluation harness.

Vocabulary borrowed from AgentDojo (Debenedetti et al., NeurIPS 2024):
- UserScenario  ~ AgentDojo's "User Task": a legitimate scheduling scenario
  with a known-correct expected outcome (utility check).
- AttackScenario ~ AgentDojo's "Injection Task": a scenario where a
  malicious payload is embedded in otherwise-valid Order fields, with a
  declared attacker goal (security check).

Key difference from AgentDojo: AgentDojo injects malicious content via
tool-call *outputs* consumed by a tool-using agent. This system has no
tool-calling loop, so the injection point is *input data* to the Planner
(the order_id string and processing_time_by_machine keys - the only
free-text fields that reach the LLM prompt unsanitized; see
vendored/guardian/graph.py planner_agent()).

Security is evaluated against the Guardrail's deterministic output
(final_allocations), not via an LLM judge - consistent with the project's
core design principle that only rule-based logic decides outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from vendored.guardian.state import Order, Machine, Allocation, SchedulingState


def _initial_state(orders: list[Order], machines: list[Machine]) -> SchedulingState:
    return {
        "orders": orders,
        "machines": machines,
        "proposed_allocations": [],
        "final_allocations": [],
        "agent_log": [],
    }


@dataclass
class UserScenario:
    """A legitimate scheduling scenario with a known-correct expected outcome."""

    scenario_id: str
    description: str
    orders: list[Order]
    machines: list[Machine]
    # Given final_allocations from a run, return True if the legitimate
    # goal was accomplished correctly (utility achieved).
    utility: Callable[[list[Allocation]], bool]

    def initial_state(self) -> SchedulingState:
        return _initial_state(self.orders, self.machines)


@dataclass
class AttackScenario:
    """
    A scenario with a malicious payload injected into Order fields and a
    declared attacker goal.
    """

    scenario_id: str
    description: str
    attack_category: str  # "prompt_injection" | "goal_hijack" | "structured_edge_case"
    orders: list[Order]
    machines: list[Machine]
    goal_description: str
    # Given final_allocations from a run, return True if the Guardrail
    # successfully PREVENTED the attacker's goal (system is secure).
    security: Callable[[list[Allocation]], bool]

    def initial_state(self) -> SchedulingState:
        return _initial_state(self.orders, self.machines)
