"""
SQLite logging layer for the Industrial Multi-Agent Guardian project.

Design principle: this module is purely for observability/logging. It
does NOT make any decisions - it only records what already happened
(LLM calls and Guardrail decisions) for the Streamlit dashboard to read.

Two tables:
  - llm_calls: every LLM API call made by the Planner (provider, model,
    token usage, estimated cost). Cost is computed from a configurable
    price table so this works correctly even for free models (cost=0)
    and remains ready for paid models without code changes.
  - allocation_decisions: every final Guardrail decision (approved/
    rejected + reason), for the dashboard's accept/reject stats.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "guardian_log.db"

# Price per 1M tokens (USD). Update as needed; unknown models default to 0
# (safe default - never silently overcharge/undercharge in a misleading way,
# just report $0 and let the dashboard flag "unknown pricing" if needed).
_PRICE_PER_1M_TOKENS = {
    # provider/model -> (prompt_price, completion_price)
    "openrouter/google/gemma-4-26b-a4b-it:free": (0.0, 0.0),
    "openrouter/nvidia/nemotron-3-super-120b-a12b:free": (0.0, 0.0),
    "deepseek/deepseek-chat": (0.27, 1.10),  # illustrative fallback pricing
}


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create tables if they don't exist yet. Safe to call multiple times."""
    conn = _get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS llm_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                estimated_cost_usd REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS allocation_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                order_id TEXT NOT NULL,
                machine_id TEXT NOT NULL,
                start_hour INTEGER,
                end_hour INTEGER,
                status TEXT NOT NULL,
                rejection_reason TEXT
            )
        """)
        conn.commit()
    finally:
        conn.close()


def estimate_cost_usd(provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Look up price per token for provider/model; unknown -> 0.0 (safe default)."""
    key = f"{provider}/{model}"
    prompt_price, completion_price = _PRICE_PER_1M_TOKENS.get(key, (0.0, 0.0))
    return (prompt_tokens / 1_000_000) * prompt_price + (completion_tokens / 1_000_000) * completion_price


def log_llm_call(provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> None:
    """Record one LLM API call. Never raises - logging failures must not crash the pipeline."""
    try:
        cost = estimate_cost_usd(provider, model, prompt_tokens, completion_tokens)
        conn = _get_connection()
        try:
            conn.execute(
                "INSERT INTO llm_calls (timestamp, provider, model, prompt_tokens, completion_tokens, estimated_cost_usd) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (datetime.now(timezone.utc).isoformat(), provider, model, prompt_tokens, completion_tokens, cost),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print(f"[db] WARNING: failed to log LLM call: {e}")


def log_allocation_decision(
    order_id: str, machine_id: str, start_hour: int, end_hour: int,
    status: str, rejection_reason: str | None,
) -> None:
    """Record one final Guardrail decision. Never raises."""
    try:
        conn = _get_connection()
        try:
            conn.execute(
                "INSERT INTO allocation_decisions "
                "(timestamp, order_id, machine_id, start_hour, end_hour, status, rejection_reason) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (datetime.now(timezone.utc).isoformat(), order_id, machine_id, start_hour, end_hour, status, rejection_reason),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print(f"[db] WARNING: failed to log allocation decision: {e}")


def get_all_llm_calls() -> list[dict]:
    conn = _get_connection()
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM llm_calls ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_all_allocation_decisions() -> list[dict]:
    conn = _get_connection()
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM allocation_decisions ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
