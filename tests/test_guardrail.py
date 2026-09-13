"""
Unit tests for the rule-based Guardrail layer.

These tests run WITHOUT any network access or LLM calls - the Guardrail
is pure deterministic Python logic and must be fully testable in isolation.
Run with: python3 -m pytest tests/test_guardrail.py -v
"""

import pytest

from src.state import Order, Machine, Allocation
from src.guardrail import evaluate_allocation, guardrail_agent


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
