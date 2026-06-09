from __future__ import annotations

from datetime import date, datetime, timezone
from math import ceil
from typing import Any

try:
    from homeassistant.util import dt as dt_util
except Exception:  # pragma: no cover - standalone fallback
    dt_util = None

from .seasonal_profile import get_seasonal_profile
from .const import (
    OBJECTIVE_SCOPE_GLOBAL_SURFACE,
    OBJECTIVE_SCOPE_SURFACE_CYCLE,
    WATERING_STAGE_ENRACINEMENT,
    WATERING_STAGE_GERMINATION,
    WATERING_STAGE_LEVEE,
    WATERING_STAGE_NORMAL,
    WATERING_STRATEGY_ADULT_DEEP,
    WATERING_STRATEGY_SEMIS_FREQUENT,
)
from .decision_models import normalize_watering_contract
from .watering_policy import resolve_semis_stage_program, resolve_watering_policy
from .water import compute_recent_watering_count
