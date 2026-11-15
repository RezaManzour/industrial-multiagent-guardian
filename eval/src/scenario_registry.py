"""
Central registry of all scenarios in this evaluation, used by
run_all.py to execute everything systematically and by any future
reporting script.

Deliberate exclusions from the "official" security-rate calculation
(kept in the repo/registry for transparency, per FINDINGS.md Finding 2):
- deadline_override_injection (v1) and deadline_override_injection_v2:
  confounded by the order_id identity-matching issue: rejections were
  an artifact of the Planner not echoing multi-line order_id strings
  verbatim, not evidence about the deadline rule itself. Superseded by
  v3.
"""

from src.scenarios.user_scenarios.basic_two_orders import SCENARIO as basic_two_orders

from src.scenarios.attack_scenarios.deadline_override_injection import SCENARIO as deadline_v1_confounded
from src.scenarios.attack_scenarios.deadline_override_injection_v2 import SCENARIO as deadline_v2_confounded
from src.scenarios.attack_scenarios.deadline_override_injection_v3 import SCENARIO as deadline_v3
from src.scenarios.attack_scenarios.goal_hijack_fake_management_note import SCENARIO as goal_hijack_direct
from src.scenarios.attack_scenarios.goal_hijack_resource_hogging_v2 import SCENARIO as resource_hogging_attacker_first
from src.scenarios.attack_scenarios.goal_hijack_resource_hogging_victim_first import SCENARIO as resource_hogging_victim_first
from src.scenarios.attack_scenarios.negative_start_hour_injection import SCENARIO as negative_start_hour
from src.scenarios.attack_scenarios.duplicate_order_id_injection import SCENARIO as duplicate_order_id

USER_SCENARIOS = [
    basic_two_orders,
]

# Included in the official RESULTS.md security-rate table.
ATTACK_SCENARIOS = [
    deadline_v3,
    goal_hijack_direct,
    resource_hogging_attacker_first,
    resource_hogging_victim_first,
    negative_start_hour,
    duplicate_order_id,
]

# Kept for transparency (documents the methodological correction in
# Finding 2) but excluded from the official results table.
CONFOUNDED_ATTACK_SCENARIOS = [
    deadline_v1_confounded,
    deadline_v2_confounded,
]
