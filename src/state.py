"""
Core data schema for the Industrial Multi-Agent Guardian project.

Defines the shared state that flows through the LangGraph StateGraph:
orders to be scheduled, machines available for allocation, and the
running record of allocation decisions (including any rejections from
the rule-based Guardrail layer).

Design principle: this module only defines DATA structures. No decision
logic (safety or otherwise) lives here - that belongs in src/guardrail.py
(rule-based) and src/graph.py (agent orchestration).
"""

from typing import TypedDict, Literal
from pydantic import BaseModel, Field


class Order(BaseModel):
    """A single production order that needs to be scheduled on a machine."""

    order_id: str
    deadline_hour: int = Field(
        ..., description="Deadline expressed as hours from the start of the scheduling horizon."
    )
    # Processing time (in hours) required for this order on each machine,
    # keyed by machine_id. Different machines may take different times
    # for the same order (e.g. due to tooling or speed differences).
    processing_time_by_machine: dict[str, float] = Field(
        ..., description="machine_id -> hours required to process this order on that machine."
    )
    priority: int = Field(default=1, description="Higher number = higher priority. Reserved for future use.")


class Machine(BaseModel):
    """A production machine with a fixed capacity."""

    machine_id: str
    capacity: int = Field(
        ..., description="Max number of orders this machine can process concurrently."
    )
    available_hours: int = Field(
        ..., description="Total hours this machine is available within the scheduling horizon."
    )


class Allocation(BaseModel):
    """A single order->machine assignment decision, with its outcome."""

    order_id: str
    machine_id: str
    start_hour: int
    end_hour: int
    status: Literal["proposed", "approved", "rejected"]
    rejection_reason: str | None = Field(
        default=None, description="Set by the Guardrail layer when status == 'rejected'."
    )


class SchedulingState(TypedDict):
    """
    The shared state object passed between LangGraph nodes (agents).

    LangGraph nodes receive this state, return partial updates to it,
    and the framework merges updates according to each field's reducer
    (default: overwrite, unless a custom reducer is defined later).
    """

    orders: list[Order]
    machines: list[Machine]

    # Filled in by the Planner Agent: proposed assignments not yet checked.
    proposed_allocations: list[Allocation]

    # Filled in by the Guardrail layer: final decisions after rule checks.
    final_allocations: list[Allocation]

    # Free-text reasoning/narration from the LLM agents, for logging/dashboard display.
    # This is NEVER used for decision-making - narration only.
    agent_log: list[str]
