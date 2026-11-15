"""
Rule-based Guardrail layer for the Industrial Multi-Agent Guardian project.

Design principle (core to this whole project):
This module contains NO LLM calls whatsoever. Every decision here is
deterministic Python logic, testable in isolation, and fully explainable.
This is the ONLY place in the system authorized to approve or reject
an allocation. Planner/Resource agents (src/graph.py) only propose;
this module decides.

Rules enforced (in order; first violated rule determines rejection):
  1. order_id must reference a real order in the current state
  2. machine_id must reference a real machine in the current state
  3. start_hour must be >= 0 and strictly less than end_hour
  4. the allocated duration must cover the order's required processing
     time on that machine (no under-allocating time), and must not exceed
     it by more than MAX_DURATION_FACTOR (no over-allocating time)
  5. end_hour must not exceed the order's deadline_hour
  6. the allocation must not exceed the machine's capacity at any
     overlapping time slot (checked against already-approved allocations)
"""

import math

from src.state import SchedulingState, Order, Machine, Allocation
from src.db import log_allocation_decision

# Upper bound for rule 4. An allocation may reserve at most
# MAX_DURATION_FACTOR times the order's required processing time on that
# machine (rounded up to whole hours, since allocations use integer hours).
#
# Why this exists: the adversarial evaluation in eval/ (scenario
# goal_hijack_resource_hogging_v2, eval/RESULTS.md) showed that rule 4
# originally had only a lower bound. An order whose data talked the LLM
# Planner into reserving a shared machine for 24h despite needing 1h was
# approved, and a legitimate competing order was then rejected for
# capacity. With this bound, that reservation is rejected by rule 4.
MAX_DURATION_FACTOR = 1.5


def max_allowed_duration(
    required_hours: float, factor: float = MAX_DURATION_FACTOR
) -> int:
    """Longest allocation (in whole hours) rule 4 accepts for an order."""
    if factor < 1:
        raise ValueError(f"max duration factor must be >= 1, got {factor}")
    return math.ceil(required_hours * factor)


def _find_order(orders: list[Order], order_id: str) -> Order | None:
    return next((o for o in orders if o.order_id == order_id), None)


def _find_machine(machines: list[Machine], machine_id: str) -> Machine | None:
    return next((m for m in machines if m.machine_id == machine_id), None)


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    """Two half-open intervals [start, end) overlap if they share any hour."""
    return a_start < b_end and b_start < a_end


def _concurrent_count_at_overlap(
    approved_on_machine: list[Allocation], candidate: Allocation
) -> int:
    """
    Count how many already-approved allocations on the same machine
    overlap in time with the candidate (used to enforce capacity).
    """
    return sum(
        1
        for a in approved_on_machine
        if _overlaps(a.start_hour, a.end_hour, candidate.start_hour, candidate.end_hour)
    )


def evaluate_allocation(
    allocation: Allocation,
    orders: list[Order],
    machines: list[Machine],
    already_approved: list[Allocation],
    max_duration_factor: float = MAX_DURATION_FACTOR,
) -> Allocation:
    """
    Apply all 6 rules to a single proposed allocation and return a new
    Allocation with status set to 'approved' or 'rejected' (with reason).
    Does not mutate the input allocation.
    """
    order = _find_order(orders, allocation.order_id)
    if order is None:
        return allocation.model_copy(
            update={"status": "rejected", "rejection_reason": "Unknown order_id"}
        )

    machine = _find_machine(machines, allocation.machine_id)
    if machine is None:
        return allocation.model_copy(
            update={"status": "rejected", "rejection_reason": "Unknown machine_id"}
        )

    if allocation.start_hour < 0 or allocation.start_hour >= allocation.end_hour:
        return allocation.model_copy(
            update={
                "status": "rejected",
                "rejection_reason": (
                    f"Invalid time range: start_hour={allocation.start_hour}, "
                    f"end_hour={allocation.end_hour}"
                ),
            }
        )

    required_hours = order.processing_time_by_machine.get(allocation.machine_id)
    if required_hours is None:
        return allocation.model_copy(
            update={
                "status": "rejected",
                "rejection_reason": (
                    f"Order {order.order_id} has no defined processing time "
                    f"for machine {allocation.machine_id}"
                ),
            }
        )

    allocated_duration = allocation.end_hour - allocation.start_hour
    if allocated_duration < required_hours:
        return allocation.model_copy(
            update={
                "status": "rejected",
                "rejection_reason": (
                    f"Allocated duration ({allocated_duration}h) is less than "
                    f"required processing time ({required_hours}h)"
                ),
            }
        )

    max_duration = max_allowed_duration(required_hours, max_duration_factor)
    if allocated_duration > max_duration:
        return allocation.model_copy(
            update={
                "status": "rejected",
                "rejection_reason": (
                    f"Allocated duration ({allocated_duration}h) exceeds the "
                    f"maximum allowed for this order ({max_duration}h = "
                    f"{required_hours}h required x {max_duration_factor}, "
                    f"rounded up)"
                ),
            }
        )

    if allocation.end_hour > order.deadline_hour:
        return allocation.model_copy(
            update={
                "status": "rejected",
                "rejection_reason": (
                    f"end_hour ({allocation.end_hour}) exceeds order deadline "
                    f"({order.deadline_hour})"
                ),
            }
        )

    # Only allocations that were actually approved hold capacity. The graph
    # node passes every decision made so far (approved and rejected), and a
    # rejected proposal must not block a later legitimate one.
    approved_on_this_machine = [
        a
        for a in already_approved
        if a.machine_id == allocation.machine_id and a.status == "approved"
    ]
    concurrent = _concurrent_count_at_overlap(approved_on_this_machine, allocation)
    if concurrent + 1 > machine.capacity:
        return allocation.model_copy(
            update={
                "status": "rejected",
                "rejection_reason": (
                    f"Machine {machine.machine_id} capacity ({machine.capacity}) "
                    f"would be exceeded during hours "
                    f"{allocation.start_hour}-{allocation.end_hour}"
                ),
            }
        )

    return allocation.model_copy(update={"status": "approved"})


def guardrail_agent(state: SchedulingState) -> dict:
    """
    LangGraph node: evaluates every proposed allocation against the
    rule-based Guardrail and produces final_allocations (approved/rejected).

    One final allocation per order_id at most: if an order already has an
    approved allocation, any further proposals for that same order are
    rejected as duplicates.
    """
    log = list(state.get("agent_log", []))
    final: list[Allocation] = []
    approved_order_ids: set[str] = set()

    for proposal in state.get("proposed_allocations", []):
        if proposal.order_id in approved_order_ids:
            rejected = proposal.model_copy(
                update={
                    "status": "rejected",
                    "rejection_reason": (
                        f"Order {proposal.order_id} already has an approved "
                        f"allocation; duplicate proposal rejected"
                    ),
                }
            )
            final.append(rejected)
            log.append(
                f"[Guardrail] REJECTED (duplicate) {proposal.order_id}: "
                f"{rejected.rejection_reason}"
            )
            continue

        decided = evaluate_allocation(
            proposal, state["orders"], state["machines"], final
        )
        final.append(decided)

        log_allocation_decision(
            order_id=decided.order_id,
            machine_id=decided.machine_id,
            start_hour=decided.start_hour,
            end_hour=decided.end_hour,
            status=decided.status,
            rejection_reason=decided.rejection_reason,
        )

        if decided.status == "approved":
            approved_order_ids.add(decided.order_id)
            log.append(
                f"[Guardrail] APPROVED {decided.order_id} -> "
                f"{decided.machine_id} ({decided.start_hour}-{decided.end_hour})"
            )
        else:
            log.append(
                f"[Guardrail] REJECTED {decided.order_id}: {decided.rejection_reason}"
            )

    return {"final_allocations": final, "agent_log": log}
