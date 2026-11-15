"""
Unit tests for the rule-based Guardrail layer.

These tests run WITHOUT any network access or LLM calls - the Guardrail
is pure deterministic Python logic and must be fully testable in isolation.
Run with: python3 -m pytest tests/test_guardrail.py -v
"""

import pytest

from src.guardrail import (
    MAX_DURATION_FACTOR,
    evaluate_allocation,
    guardrail_agent,
    max_allowed_duration,
)
from src.state import Allocation, Machine, Order

# --- Shared fixtures ---------------------------------------------------

def make_order(order_id="ORD-1", deadline_hour=10, proc_time=None):
    return Order(
        order_id=order_id,
        deadline_hour=deadline_hour,
        processing_time_by_machine=proc_time or {"M1": 2.0, "M2": 3.0},
    )


def make_machine(machine_id="M1", capacity=1, available_hours=24):
    return Machine(machine_id=machine_id, capacity=capacity, available_hours=available_hours)


def make_allocation(order_id="ORD-1", machine_id="M1", start=0, end=2, status="proposed"):
    return Allocation(
        order_id=order_id, machine_id=machine_id,
        start_hour=start, end_hour=end, status=status,
    )


# --- Individual rule tests ----------------------------------------------

def test_valid_allocation_is_approved():
    orders = [make_order()]
    machines = [make_machine()]
    alloc = make_allocation(start=0, end=2)  # exactly matches M1's 2.0h requirement

    result = evaluate_allocation(alloc, orders, machines, already_approved=[])

    assert result.status == "approved"
    assert result.rejection_reason is None


def test_unknown_order_id_is_rejected():
    orders = [make_order(order_id="ORD-1")]
    machines = [make_machine()]
    alloc = make_allocation(order_id="ORD-DOES-NOT-EXIST")

    result = evaluate_allocation(alloc, orders, machines, already_approved=[])

    assert result.status == "rejected"
    assert "Unknown order_id" in result.rejection_reason


def test_unknown_machine_id_is_rejected():
    orders = [make_order()]
    machines = [make_machine(machine_id="M1")]
    alloc = make_allocation(machine_id="M-DOES-NOT-EXIST")

    result = evaluate_allocation(alloc, orders, machines, already_approved=[])

    assert result.status == "rejected"
    assert "Unknown machine_id" in result.rejection_reason


def test_invalid_time_range_is_rejected():
    orders = [make_order()]
    machines = [make_machine()]
    alloc = make_allocation(start=5, end=3)  # start after end

    result = evaluate_allocation(alloc, orders, machines, already_approved=[])

    assert result.status == "rejected"
    assert "Invalid time range" in result.rejection_reason


def test_insufficient_duration_is_rejected():
    orders = [make_order(proc_time={"M1": 5.0})]  # needs 5 hours
    machines = [make_machine()]
    alloc = make_allocation(start=0, end=2)  # only allocates 2 hours

    result = evaluate_allocation(alloc, orders, machines, already_approved=[])

    assert result.status == "rejected"
    assert "less than required processing time" in result.rejection_reason


def test_deadline_violation_is_rejected():
    orders = [make_order(deadline_hour=5, proc_time={"M1": 2.0})]
    machines = [make_machine()]
    alloc = make_allocation(start=4, end=6)  # ends after deadline_hour=5

    result = evaluate_allocation(alloc, orders, machines, already_approved=[])

    assert result.status == "rejected"
    assert "exceeds order deadline" in result.rejection_reason


def test_capacity_overflow_is_rejected():
    orders = [
        make_order(order_id="ORD-1", proc_time={"M1": 2.0}),
        make_order(order_id="ORD-2", proc_time={"M1": 2.0}),
    ]
    machines = [make_machine(machine_id="M1", capacity=1)]

    already_approved = [make_allocation(order_id="ORD-1", machine_id="M1", start=0, end=2, status="approved")]
    overlapping_alloc = make_allocation(order_id="ORD-2", machine_id="M1", start=1, end=3)

    result = evaluate_allocation(overlapping_alloc, orders, machines, already_approved)

    assert result.status == "rejected"
    assert "capacity" in result.rejection_reason.lower()


def test_non_overlapping_allocations_on_same_machine_both_approved():
    orders = [
        make_order(order_id="ORD-1", proc_time={"M1": 2.0}),
        make_order(order_id="ORD-2", proc_time={"M1": 2.0}),
    ]
    machines = [make_machine(machine_id="M1", capacity=1)]

    already_approved = [make_allocation(order_id="ORD-1", machine_id="M1", start=0, end=2, status="approved")]
    non_overlapping_alloc = make_allocation(order_id="ORD-2", machine_id="M1", start=2, end=4)

    result = evaluate_allocation(non_overlapping_alloc, orders, machines, already_approved)

    assert result.status == "approved"


def test_rejected_allocation_does_not_consume_capacity():
    # guardrail_agent passes every earlier decision (approved and rejected)
    # as already_approved. A rejected proposal must not block the machine.
    orders = [
        make_order(order_id="ORD-1", proc_time={"M1": 2.0}),
        make_order(order_id="ORD-2", proc_time={"M1": 2.0}),
    ]
    machines = [make_machine(machine_id="M1", capacity=1)]

    earlier = [make_allocation(order_id="ORD-1", machine_id="M1", start=0, end=2, status="rejected")]
    alloc = make_allocation(order_id="ORD-2", machine_id="M1", start=0, end=2)

    result = evaluate_allocation(alloc, orders, machines, earlier)

    assert result.status == "approved"


# --- Rule 4 upper bound (max allocation duration) -----------------------
#
# Added after the adversarial evaluation (eval/, scenario
# goal_hijack_resource_hogging_v2) found that rule 4 had no maximum: an
# order needing 1h could reserve a shared machine for 24h.

def test_over_allocation_far_beyond_requirement_is_rejected():
    orders = [make_order(proc_time={"M1": 1.0}, deadline_hour=24)]
    machines = [make_machine()]
    alloc = make_allocation(start=0, end=24)  # 24h for a 1h job

    result = evaluate_allocation(alloc, orders, machines, already_approved=[])

    assert result.status == "rejected"
    assert "exceeds the maximum allowed" in result.rejection_reason


def test_small_slack_above_requirement_is_still_approved():
    orders = [make_order(proc_time={"M1": 2.0})]
    machines = [make_machine()]
    alloc = make_allocation(start=0, end=3)  # 2h job, 1h of slack (factor 1.5)

    result = evaluate_allocation(alloc, orders, machines, already_approved=[])

    assert result.status == "approved"


@pytest.mark.parametrize(
    ("required", "end", "expected"),
    [
        (1.5, 2, "approved"),  # minimum whole-hour slot for a 1.5h job
        (1.5, 3, "approved"),  # ceil(1.5 * 1.5) = 3 is the upper bound
        (1.5, 4, "rejected"),  # one hour past the bound
        (1.0, 2, "approved"),  # ceil(1.0 * 1.5) = 2
        (1.0, 3, "rejected"),
    ],
)
def test_max_duration_boundaries(required, end, expected):
    orders = [make_order(proc_time={"M1": required}, deadline_hour=24)]
    machines = [make_machine()]
    alloc = make_allocation(start=0, end=end)

    result = evaluate_allocation(alloc, orders, machines, already_approved=[])

    assert result.status == expected


def test_max_duration_factor_is_configurable():
    orders = [make_order(proc_time={"M1": 2.0})]
    machines = [make_machine()]
    alloc = make_allocation(start=0, end=3)

    strict = evaluate_allocation(
        alloc, orders, machines, already_approved=[], max_duration_factor=1.0
    )
    lenient = evaluate_allocation(
        alloc, orders, machines, already_approved=[], max_duration_factor=2.0
    )

    assert strict.status == "rejected"
    assert lenient.status == "approved"


def test_max_allowed_duration_helper():
    assert MAX_DURATION_FACTOR == 1.5
    assert max_allowed_duration(2.0) == 3
    assert max_allowed_duration(1.5) == 3
    with pytest.raises(ValueError):
        max_allowed_duration(2.0, factor=0.5)


# --- Full guardrail_agent (graph node) integration test -----------------

def test_guardrail_agent_rejects_duplicate_order_proposals():
    orders = [make_order(order_id="ORD-1", proc_time={"M1": 2.0})]
    machines = [make_machine(machine_id="M1", capacity=1)]

    state = {
        "orders": orders,
        "machines": machines,
        "proposed_allocations": [
            make_allocation(order_id="ORD-1", machine_id="M1", start=0, end=2),
            make_allocation(order_id="ORD-1", machine_id="M1", start=3, end=5),  # duplicate order
        ],
        "final_allocations": [],
        "agent_log": [],
    }

    result = guardrail_agent(state)
    statuses = [a.status for a in result["final_allocations"]]

    assert statuses == ["approved", "rejected"]
    assert "duplicate" in result["final_allocations"][1].rejection_reason.lower()
