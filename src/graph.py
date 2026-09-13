"""
LangGraph orchestration for the Industrial Multi-Agent Guardian project.

Design principle:
The agents defined here (Planner, Resource) may PROPOSE allocations using
LLM reasoning, but they NEVER make the final accept/reject decision.
That authority belongs exclusively to the rule-based Guardrail layer
(src/guardrail.py, to be added in a later phase). This file only wires
together the "planning/narration" side of the system.
"""

from langgraph.graph import StateGraph, START, END

from src.state import SchedulingState, Order, Machine, Allocation
from src.llm_client import ask_llm_structured, LLMOutputError
from src.guardrail import guardrail_agent


PLANNER_SYSTEM_PROMPT = (
    "You are a Planner Agent in an industrial scheduling system. "
    "Given one order and a list of available machines, propose a single "
    "allocation: which machine to use, and the start/end hour of "
    "processing. Base the end_hour on the order's processing time for "
    "the chosen machine. Always set status to 'proposed' - you do not "
    "have authority to approve or reject allocations."
)


def planner_agent(state: SchedulingState) -> dict:
    """
    For each order not yet covered by a proposed allocation, ask the LLM
    to propose one allocation. Failures (LLMOutputError) are logged and
    skipped - they do NOT crash the graph, and they produce no allocation
    for that order (which the Guardrail layer will later need to handle
    as "no valid proposal").
    """
    proposed = list(state.get("proposed_allocations", []))
    log = list(state.get("agent_log", []))

    already_planned_order_ids = {a.order_id for a in proposed}

    for order in state["orders"]:
        if order.order_id in already_planned_order_ids:
            continue

        machines_summary = "\n".join(
            f"- {m.machine_id}: capacity={m.capacity}, "
            f"available_hours={m.available_hours}"
            for m in state["machines"]
        )
        prompt = (
            f"Order: {order.order_id}\n"
            f"Deadline hour: {order.deadline_hour}\n"
            f"Processing time by machine (hours): {order.processing_time_by_machine}\n\n"
            f"Available machines:\n{machines_summary}\n\n"
            "Propose ONE allocation for this order."
        )

        try:
            allocation = ask_llm_structured(
                prompt=prompt,
                response_model=Allocation,
                system_prompt=PLANNER_SYSTEM_PROMPT,
            )
            proposed.append(allocation)
            log.append(
                f"[Planner] Proposed allocation for {order.order_id}: "
                f"{allocation.machine_id} ({allocation.start_hour}-{allocation.end_hour})"
            )
        except LLMOutputError as e:
            log.append(
                f"[Planner] FAILED to produce a valid proposal for "
                f"{order.order_id}: {e}"
            )

    return {"proposed_allocations": proposed, "agent_log": log}


def resource_agent(state: SchedulingState) -> dict:
    """
    Consolidates the Planner's proposals for logging/inspection purposes.

    IMPORTANT: this node does NOT approve or reject allocations. It only
    prepares a readable summary. Real accept/reject logic (capacity
    limits, deadline conflicts, etc.) belongs to the rule-based Guardrail
    layer added in a later phase.
    """
    log = list(state.get("agent_log", []))
    proposed = state.get("proposed_allocations", [])

    by_machine: dict[str, int] = {}
    for a in proposed:
        by_machine[a.machine_id] = by_machine.get(a.machine_id, 0) + 1

    summary = ", ".join(f"{m}: {c} order(s)" for m, c in by_machine.items()) or "none"
    log.append(f"[Resource] Current proposed load by machine: {summary}")

    return {"agent_log": log}


def build_graph():
    """Construct and compile the multi-agent StateGraph."""
    builder = StateGraph(SchedulingState)

    builder.add_node("planner", planner_agent)
    builder.add_node("resource", resource_agent)
    builder.add_node("guardrail", guardrail_agent)

    builder.add_edge(START, "planner")
    builder.add_edge("planner", "resource")
    builder.add_edge("resource", "guardrail")
    builder.add_edge("guardrail", END)

    return builder.compile()


if __name__ == "__main__":
    # Minimal manual test scenario (Day 1-2 checklist: "test one simple scenario")
    graph = build_graph()

    orders = [
        Order(
            order_id="ORD-1",
            deadline_hour=10,
            processing_time_by_machine={"M1": 3.0, "M2": 2.0},
        ),
        Order(
            order_id="ORD-2",
            deadline_hour=8,
            processing_time_by_machine={"M1": 1.5, "M2": 4.0},
        ),
    ]
    machines = [
        Machine(machine_id="M1", capacity=1, available_hours=24),
        Machine(machine_id="M2", capacity=1, available_hours=24),
    ]

    initial_state: SchedulingState = {
        "orders": orders,
        "machines": machines,
        "proposed_allocations": [],
        "final_allocations": [],
        "agent_log": [],
    }

    result = graph.invoke(initial_state)

    print("=== Agent Log ===")
    for line in result["agent_log"]:
        print(line)

    print("\n=== Proposed Allocations ===")
    for alloc in result["proposed_allocations"]:
        print(alloc)

    print("\n=== Final Allocations (after Guardrail) ===")
    for alloc in result["final_allocations"]:
        print(alloc)
