"""@module core/time/config
@purpose Single source for default game-day length and offline cap.
@depends none
@usedBy core/state/envelope, core/time/model
@see ./INDEX.md
"""
DEFAULT_GAME_DAY_MS = 120_000
TIME_SETTINGS = {"offline_cap_hours": 24, "catchup_budget_ms": 4000}
OFFLINE_CAP_MS = TIME_SETTINGS["offline_cap_hours"] * 60 * 60 * 1000
# Historical windows/receipts remain valid; this is not the new-window cap.
PERSISTED_OFFLINE_CAP_MS = 72 * 60 * 60 * 1000
CATCHUP_BUDGET_MS = TIME_SETTINGS["catchup_budget_ms"]
SETTLEMENT_BUDGET_MS = 1500
SETTLEMENT_MAX_EVENTS = 4096

# Recent online presentation retains the original per-event combat path.
OFFLINE_COMBAT_RECENT_MS = 60_000
