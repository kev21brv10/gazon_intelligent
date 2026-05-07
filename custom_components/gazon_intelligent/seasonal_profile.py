from __future__ import annotations

from datetime import date
from typing import Any


_MONTH_PROFILES: dict[int, dict[str, Any]] = {
    1: {
        "season": "winter",
        "season_phase": "ralentissement_hivernal",
        "month_profile": "repos_hivernal",
        "watering_bias": "minimal",
        "mowing_bias": "low_growth",
        "intervention_bias": "very_prudent",
        "risk_bias": "cold_wet",
        "weekly_budget_min_mm": 17.0,
        "weekly_budget_max_mm": 22.0,
    },
    2: {
        "season": "winter",
        "season_phase": "ralentissement_hivernal",
        "month_profile": "repos_hivernal",
        "watering_bias": "minimal",
        "mowing_bias": "low_growth",
        "intervention_bias": "very_prudent",
        "risk_bias": "cold_wet",
        "weekly_budget_min_mm": 17.0,
        "weekly_budget_max_mm": 22.0,
    },
    3: {
        "season": "shoulder",
        "season_phase": "reveil_printanier",
        "month_profile": "reveil_progressif",
        "watering_bias": "progressive_restart",
        "mowing_bias": "gentle_restart",
        "intervention_bias": "prudent",
        "risk_bias": "soft_growth",
        "weekly_budget_min_mm": 18.5,
        "weekly_budget_max_mm": 23.5,
    },
    4: {
        "season": "shoulder",
        "season_phase": "reveil_printanier",
        "month_profile": "relance_vegetative",
        "watering_bias": "balanced_growth",
        "mowing_bias": "growth_restart",
        "intervention_bias": "open",
        "risk_bias": "moderate_growth",
        "weekly_budget_min_mm": 19.0,
        "weekly_budget_max_mm": 24.0,
    },
    5: {
        "season": "summer",
        "season_phase": "croissance_active",
        "month_profile": "croissance_active",
        "watering_bias": "growth_support",
        "mowing_bias": "active_growth",
        "intervention_bias": "open",
        "risk_bias": "growth",
        "weekly_budget_min_mm": 20.0,
        "weekly_budget_max_mm": 25.0,
    },
    6: {
        "season": "summer",
        "season_phase": "croissance_active",
        "month_profile": "densification",
        "watering_bias": "controlled_support",
        "mowing_bias": "active_growth",
        "intervention_bias": "measured",
        "risk_bias": "warm_growth",
        "weekly_budget_min_mm": 20.5,
        "weekly_budget_max_mm": 25.5,
    },
    7: {
        "season": "summer",
        "season_phase": "defense_estivale",
        "month_profile": "defense_thermique",
        "watering_bias": "defensive",
        "mowing_bias": "heat_protection",
        "intervention_bias": "cautious",
        "risk_bias": "heat",
        "weekly_budget_min_mm": 21.0,
        "weekly_budget_max_mm": 26.0,
    },
    8: {
        "season": "summer",
        "season_phase": "defense_estivale",
        "month_profile": "defense_thermique",
        "watering_bias": "defensive",
        "mowing_bias": "heat_protection",
        "intervention_bias": "cautious",
        "risk_bias": "heat",
        "weekly_budget_min_mm": 20.5,
        "weekly_budget_max_mm": 25.5,
    },
    9: {
        "season": "summer",
        "season_phase": "reprise_automnale",
        "month_profile": "reprise_racinaire",
        "watering_bias": "recovery_support",
        "mowing_bias": "recovery_growth",
        "intervention_bias": "open",
        "risk_bias": "recovery",
        "weekly_budget_min_mm": 20.0,
        "weekly_budget_max_mm": 25.0,
    },
    10: {
        "season": "shoulder",
        "season_phase": "reprise_automnale",
        "month_profile": "consolidation",
        "watering_bias": "measured_recharge",
        "mowing_bias": "steady_growth",
        "intervention_bias": "prudent",
        "risk_bias": "cool_recovery",
        "weekly_budget_min_mm": 18.5,
        "weekly_budget_max_mm": 23.5,
    },
    11: {
        "season": "shoulder",
        "season_phase": "ralentissement_hivernal",
        "month_profile": "ralentissement",
        "watering_bias": "reduced",
        "mowing_bias": "slow_growth",
        "intervention_bias": "very_prudent",
        "risk_bias": "cool_wet",
        "weekly_budget_min_mm": 18.0,
        "weekly_budget_max_mm": 23.0,
    },
    12: {
        "season": "winter",
        "season_phase": "ralentissement_hivernal",
        "month_profile": "repos_hivernal",
        "watering_bias": "minimal",
        "mowing_bias": "low_growth",
        "intervention_bias": "very_prudent",
        "risk_bias": "cold_wet",
        "weekly_budget_min_mm": 17.0,
        "weekly_budget_max_mm": 22.0,
    },
}


def get_seasonal_profile(today: date) -> dict[str, Any]:
    month = int(getattr(today, "month", 1) or 1)
    profile = dict(_MONTH_PROFILES.get(month) or _MONTH_PROFILES[1])
    profile["month"] = month
    return profile


__all__ = ["get_seasonal_profile"]
