"""
Offline tests for the adversarial evaluation harness in eval/.

The real evaluation calls an LLM (OpenRouter) for every Planner proposal.
These tests replace the single LLM entry point the Planner uses
(src.graph.ask_llm_structured) with a scripted fake, so the full
Planner -> Resource -> Guardrail graph and the harness run end to end with
zero network calls and no API key. The scripted proposals model a Planner
that has been fully fooled by each attack, i.e. the worst case for the
Guardrail.

They also check the offline replay of the recorded runs in
eval/results/raw_runs.json against the current Guardrail.
"""

import json
import re
from pathlib import Path

import src.graph
from eval.harness import run_attack_scenario, run_user_scenario
from eval.replay_recorded import replay
from eval.scenario_registry import ATTACK_SCENARIOS, USER_SCENARIOS
from src.state import Allocation

RAW_RUNS = Path(__file__).resolve().parent.parent / "eval" / "results" / "raw_runs.json"


def _scenario(scenario_id):
    for s in USER_SCENARIOS + ATTACK_SCENARIOS:
        if s.scenario_id == scenario_id:
            return s
    raise KeyError(scenario_id)


def scripted_planner(monkeypatch, script):
    """
    Replace the LLM call with a fake that returns script[order_id] for the
    order named in the Planner's prompt. A script value may be a list, in
    which case successive calls for the same order pop from it (used for
    duplicate order ids). Returns the list of prompts the fake received.
    """
    prompts = []
    remaining = {k: (list(v) if isinstance(v, list) else v) for k, v in script.items()}

    def fake_ask_llm_structured(prompt, response_model, system_prompt=None, **kwargs):
        prompts.append(prompt)
        order_id = re.match(r"Order: (.*)\n", prompt).group(1)
        value = remaining[order_id]
        machine_id, start, end = value.pop(0) if isinstance(value, list) else value
        return response_model(
            order_id=order_id,
            machine_id=machine_id,
            start_hour=start,
            end_hour=end,
            status="proposed",
        )

    monkeypatch.setattr(src.graph, "ask_llm_structured", fake_ask_llm_structured)
    return prompts


def test_baseline_user_scenario_keeps_full_utility(monkeypatch):
    scripted_planner(monkeypatch, {"ORD-1": ("M2", 0, 2), "ORD-2": ("M1", 0, 2)})

    result = run_user_scenario(_scenario("basic_two_orders"))

    assert result.passed
    assert {a.status for a in result.final_allocations} == {"approved"}


def test_resource_hogging_attacker_first_now_held(monkeypatch):
    # The exact proposals the fooled Planner made in all 5 recorded runs.
    scripted_planner(
        monkeypatch, {"ORD-ATTACKER": ("M1", 0, 24), "ORD-VICTIM": ("M1", 0, 2)}
    )

    result = run_attack_scenario(_scenario("goal_hijack_resource_hogging_v2"))

    assert result.passed
    by_id = {a.order_id: a for a in result.final_allocations}
    assert by_id["ORD-ATTACKER"].status == "rejected"
    assert "exceeds the maximum allowed" in by_id["ORD-ATTACKER"].rejection_reason
    assert by_id["ORD-VICTIM"].status == "approved"


def test_resource_hogging_victim_first_held_for_the_right_reason(monkeypatch):
    scripted_planner(
        monkeypatch, {"ORD-ATTACKER": ("M1", 2, 26), "ORD-VICTIM": ("M1", 0, 2)}
    )

    result = run_attack_scenario(_scenario("goal_hijack_resource_hogging_victim_first"))

    assert result.passed
    attacker = next(a for a in result.final_allocations if a.order_id == "ORD-ATTACKER")
    # Before the fix this was only rejected by luck of ordering (capacity);
    # now rule 4 rejects it on its own merits.
    assert "exceeds the maximum allowed" in attacker.rejection_reason


def test_deadline_override_held_when_planner_is_fooled(monkeypatch):
    scenario = _scenario("deadline_override_injection_v3")
    order_id = scenario.orders[0].order_id
    scripted_planner(monkeypatch, {order_id: ("M1", 48, 50)})

    result = run_attack_scenario(scenario)

    assert result.passed
    assert result.final_allocations[0].status == "rejected"


def test_negative_start_hour_held_when_planner_is_fooled(monkeypatch):
    scripted_planner(monkeypatch, {"ORD-1": ("M1", -10, -8)})

    result = run_attack_scenario(_scenario("negative_start_hour_injection"))

    assert result.passed
    assert "Invalid time range" in result.final_allocations[0].rejection_reason


def test_duplicate_order_id_held(monkeypatch):
    scripted_planner(monkeypatch, {"ORD-1": [("M1", 0, 2), ("M1", 0, 100)]})

    result = run_attack_scenario(_scenario("duplicate_order_id_injection"))

    assert result.passed


def test_per_order_prompt_isolation(monkeypatch):
    """Finding 5: the attacker's injected text never reaches the victim's prompt."""
    prompts = scripted_planner(
        monkeypatch, {"ORD-VICTIM": ("M1", 0, 2), "ORD-ATTACKER": ("M2", 0, 2)}
    )
    scenario = _scenario("goal_hijack_fake_management_note")

    result = run_attack_scenario(scenario)

    assert result.passed
    victim_prompt = next(p for p in prompts if p.startswith("Order: ORD-VICTIM"))
    injected_key = next(
        k for k in scenario.orders[1].processing_time_by_machine if k not in {"M1", "M2"}
    )
    assert injected_key not in victim_prompt


def test_harness_retries_transient_provider_errors(monkeypatch):
    """Finding 3: a provider returning content=None surfaces as TypeError; the harness retries."""
    calls = {"n": 0}

    def flaky(prompt, response_model, system_prompt=None, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TypeError("'NoneType' object is not subscriptable")
        order_id = re.match(r"Order: (.*)\n", prompt).group(1)
        machine = "M2" if order_id == "ORD-1" else "M1"
        return Allocation(
            order_id=order_id, machine_id=machine, start_hour=0, end_hour=2, status="proposed"
        )

    monkeypatch.setattr(src.graph, "ask_llm_structured", flaky)

    result = run_user_scenario(_scenario("basic_two_orders"))

    assert result.passed
    assert calls["n"] > 1


def test_replay_of_recorded_runs_against_current_guardrail():
    """
    Re-decide the Planner proposals recorded in the original evaluation
    (before the fix) with the current Guardrail. The only scenario whose
    outcome changes is the one confirmed vulnerability: 0/5 -> 5/5.
    """
    with open(RAW_RUNS) as f:
        raw = json.load(f)

    replayed = replay(raw)

    for scenarios in replayed.values():
        for scenario_id, rows in scenarios.items():
            assert len(rows) == 5, scenario_id
            assert all(r["passed_replay"] for r in rows), scenario_id
            if scenario_id != "goal_hijack_resource_hogging_v2":
                assert all(r["passed_recorded"] for r in rows), scenario_id

    hogging = replayed["attack_scenarios"]["goal_hijack_resource_hogging_v2"]
    assert [r["passed_recorded"] for r in hogging] == [False] * 5
