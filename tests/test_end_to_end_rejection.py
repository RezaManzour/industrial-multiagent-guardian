"""
End-to-end (graph-level) adversarial tests for the Guardrail pipeline.

These tests deliberately construct "broken" proposed_allocations - as if
a Planner Agent (LLM) had proposed something unsafe or nonsensical - and
run them through the REAL resource_agent + guardrail_agent graph nodes
(not just the isolated evaluate_allocation function tested in
test_guardrail.py). This proves the actual graph nodes used in production
correctly reject bad input end-to-end.

Design note: we intentionally do NOT invoke the Planner node or the full
compiled graph here, because Planner depends on a live LLM API call
(network + free-tier rate limits). Making automated tests depend on an
external, rate-limited service would make them slow and flaky. Instead,
we hand-craft the proposed_allocations that the Planner would produce in
a failure/adversarial scenario, and verify the deterministic downstream
nodes handle them correctly. Run with:
    python3 -m pytest tests/test_end_to_end_rejection.py -v
"""

from src.state import Order, Machine, Allocation
from src.graph import resource_agent, guardrail_agent


def run_downstream_pipeline(orders, machines, proposed_allocations):
    """Simulates the resource -> guardrail portion of the graph."""
    state = {
        "orders": orders,
        "machines": machines,
        "proposed_allocations": proposed_allocations,
        "final_allocations": [],
        "agent_log": [],
    }
    state.update(resource_agent(state))
    state.update(guardrail_agent(state))
    return state


def test_overlapping_allocations_on_single_capacity_machine():
    """
    Adversarial scenario: two orders both proposed on the SAME machine
    with OVERLAPPING hours, but the machine can only handle 1 at a time.
    One must be approved, the other must be rejected for capacity.
    """
    orders = [
        Order(order_id="ORD-1", deadline_hour=10, processing_time_by_machine={"M1": 2.0}),
        Order(order_id="ORD-2", deadline_hour=10, processing_time_by_machine={"M1": 2.0}),
    ]
    machines = [Machine(machine_id="M1", capacity=1, available_hours=24)]

    proposed = [
        Allocation(order_id="ORD-1", machine_id="M1", start_hour=0, end_hour=2, status="proposed"),
        Allocation(order_id="ORD-2", machine_id="M1", start_hour=1, end_hour=3, status="proposed"),
    ]

    result = run_downstream_pipeline(orders, machines, proposed)
    statuses = {a.order_id: a.status for a in result["final_allocations"]}

    assert statuses["ORD-1"] == "approved"
    assert statuses["ORD-2"] == "rejected"
    assert any("capacity" in line.lower() for line in result["agent_log"])


def test_deadline_violation_scenario():
    """
    Adversarial scenario: Planner "hallucinates" an allocation that
    finishes after the order's deadline. Must be rejected, not silently
    accepted just because the machine/timing otherwise looks fine.
    """
    orders = [
        Order(order_id="ORD-1", deadline_hour=4, processing_time_by_machine={"M1": 2.0}),
    ]
    machines = [Machine(machine_id="M1", capacity=1, available_hours=24)]

    proposed = [
        Allocation(order_id="ORD-1", machine_id="M1", start_hour=3, end_hour=5, status="proposed"),
    ]

    result = run_downstream_pipeline(orders, machines, proposed)

    assert result["final_allocations"][0].status == "rejected"
    assert "deadline" in result["final_allocations"][0].rejection_reason.lower()


def test_hallucinated_machine_id_scenario():
    """
    Adversarial scenario: Planner "hallucinates" a machine_id that does
    not exist in the current state (a realistic LLM failure mode). Must
    be rejected outright, never approved by accident.
    """
    orders = [
        Order(order_id="ORD-1", deadline_hour=10, processing_time_by_machine={"M1": 2.0}),
    ]
    machines = [Machine(machine_id="M1", capacity=1, available_hours=24)]

    proposed = [
        Allocation(order_id="ORD-1", machine_id="M99-GHOST", start_hour=0, end_hour=2, status="proposed"),
    ]

    result = run_downstream_pipeline(orders, machines, proposed)

    assert result["final_allocations"][0].status == "rejected"
    assert "unknown machine_id" in result["final_allocations"][0].rejection_reason.lower()


def test_mixed_scenario_some_approved_some_rejected():
    """
    Realistic mixed scenario: 3 orders, one clean approval, one deadline
    violation, one capacity conflict with the first. Verifies the pipeline
    handles a heterogeneous batch correctly in one pass.
    """
    orders = [
        Order(order_id="ORD-1", deadline_hour=10, processing_time_by_machine={"M1": 2.0}),
        Order(order_id="ORD-2", deadline_hour=1, processing_time_by_machine={"M2": 2.0}),
        Order(order_id="ORD-3", deadline_hour=10, processing_time_by_machine={"M1": 2.0}),
    ]
    machines = [
        Machine(machine_id="M1", capacity=1, available_hours=24),
        Machine(machine_id="M2", capacity=1, available_hours=24),
    ]

    proposed = [
        Allocation(order_id="ORD-1", machine_id="M1", start_hour=0, end_hour=2, status="proposed"),
        Allocation(order_id="ORD-2", machine_id="M2", start_hour=0, end_hour=2, status="proposed"),  # violates deadline_hour=1
        Allocation(order_id="ORD-3", machine_id="M1", start_hour=1, end_hour=3, status="proposed"),  # overlaps ORD-1
    ]

    result = run_downstream_pipeline(orders, machines, proposed)
    statuses = {a.order_id: a.status for a in result["final_allocations"]}

    assert statuses["ORD-1"] == "approved"
    assert statuses["ORD-2"] == "rejected"
    assert statuses["ORD-3"] == "rejected"
