from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

"""Canonical watering-plan model.

Contract:
- ``objective_mm`` is the requested target depth on the lawn surface, applied
  uniformly across the full irrigated surface.
- ``zones[].mm`` is the effective depth delivered by each zone for that same
  surface target after duration rounding, not a per-zone target or a per-passage
  target.
- ``zones_total_mm`` is only a diagnostic sum of the zone outputs and must not
  be interpreted as the lawn objective.
- ``plan_type`` only describes zone topology (single or multiple zones).
- ``objective_mm`` and ``duration_seconds`` are canonical keys; French aliases
  are kept for backward compatibility in serialized dictionaries.
- ``normalize_existing_plan`` is intentionally best-effort when reading an
  already-persisted plan that may be partially incomplete.
"""

PLAN_SOURCE_CALCULATED = "calculated_from_objective"
PLAN_SOURCE_NORMALIZED = "normalized_existing_plan"

_MIN_ZONE_DURATION_MIN = 0.5
_MAX_ZONE_DURATION_MIN = 180.0
_DURATION_ROUNDING_STEP_MIN = 0.5


@dataclass(frozen=True)
class ZonePlan:
    zone: str
    rate_mm_h: float
    duration_s: int
    mm: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "zone": self.zone,
            "entity_id": self.zone,
            "rate_mm_h": round(self.rate_mm_h, 1),
            "duration_seconds": int(self.duration_s),
            "duration_s": int(self.duration_s),
            "duration_min": round(self.duration_s / 60.0, 1),
            "mm": round(self.mm, 1),
        }

    def as_runtime_dict(self) -> dict[str, Any]:
        return {
            "zone": self.zone,
            "rate_mm_h": round(self.rate_mm_h, 1),
            "duration_s": int(self.duration_s),
            "mm": round(self.mm, 1),
        }


@dataclass(frozen=True)
class WateringPlan:
    objective_mm: float
    plan_type: str
    passage_count: int
    pause_between_passages_s: int
    zones: tuple[ZonePlan, ...]
    source: str = PLAN_SOURCE_CALCULATED
    watering_strategy: str | None = None
    objective_scope: str | None = None
    watering_stage: str | None = None
    surface_cycle_mm: float | None = None
    daily_cycles_target: int | None = None
    cycle_spacing_minutes: int | None = None
    surface_moisture_target: str | None = None
    surface_dryness_risk: str | None = None
    runoff_risk: str | None = None
    seeding_transition_ready: bool | None = None
    seeding_block_reason: str | None = None

    @property
    def watering_duration_s(self) -> int:
        return sum(zone.duration_s for zone in self.zones)

    @property
    def total_duration_s(self) -> int:
        total = self.watering_duration_s
        if self.passage_count > 1:
            total += self.pause_between_passages_s * (self.passage_count - 1)
        return total

    @property
    def total_duration_min(self) -> float:
        return round(self.watering_duration_s / 60.0, 1)

    def zone_for_passage(self, zone_index: int, passage: int) -> ZonePlan:
        zone = self.zones[zone_index]
        if self.passage_count <= 1:
            return zone
        safe_passage = min(max(1, int(passage)), self.passage_count)
        base_duration_s = zone.duration_s // self.passage_count
        remainder_s = zone.duration_s % self.passage_count
        duration_s = base_duration_s + (1 if safe_passage <= remainder_s else 0)
        total_tenths = int(round(zone.mm * 10.0))
        base_tenths = total_tenths // self.passage_count
        remainder_tenths = total_tenths % self.passage_count
        mm = (base_tenths + (1 if safe_passage <= remainder_tenths else 0)) / 10.0
        return ZonePlan(
            zone=zone.zone,
            rate_mm_h=zone.rate_mm_h,
            duration_s=duration_s,
            mm=mm,
        )

    def as_dict(self) -> dict[str, Any]:
        zone_count = len(self.zones)
        zones_total_mm = round(sum(zone.mm for zone in self.zones), 1)
        return {
            "objective_mm": round(self.objective_mm, 1),
            "objectif_mm": round(self.objective_mm, 1),
            "mm_scope": "global_surface",
            "mm_interpretation": "surface_uniform",
            "surface_mm": round(self.objective_mm, 1),
            "surface_cycle_mm": round(self.surface_cycle_mm, 1)
            if self.surface_cycle_mm is not None
            else None,
            "zones_total_mm": zones_total_mm,
            "zones": [zone.as_dict() for zone in self.zones],
            "zone_count": zone_count,
            "total_duration_min": self.total_duration_min,
            "duration_human": _duration_human(self.watering_duration_s),
            "fractionation": self.passage_count > 1,
            "passages": self.passage_count,
            "pause_between_passages_minutes": int(round(self.pause_between_passages_s / 60.0)),
            "pause_between_passages_s": self.pause_between_passages_s,
            "source": self.source,
            "plan_type": self.plan_type,
            "watering_strategy": self.watering_strategy,
            "objective_scope": self.objective_scope,
            "watering_stage": self.watering_stage,
            "daily_cycles_target": self.daily_cycles_target,
            "cycle_spacing_minutes": self.cycle_spacing_minutes,
            "surface_moisture_target": self.surface_moisture_target,
            "surface_dryness_risk": self.surface_dryness_risk,
            "runoff_risk": self.runoff_risk,
            "seeding_transition_ready": self.seeding_transition_ready,
            "seeding_block_reason": self.seeding_block_reason,
            "summary": (
                f"{zone_count} zone{'s' if zone_count != 1 else ''} • "
                f"{round(self.objective_mm, 1):.1f} mm sur la surface • "
                f"{_duration_human(self.watering_duration_s)}"
            ),
        }

    def as_runtime_dict(self) -> dict[str, Any]:
        return {
            "objective_mm": round(self.objective_mm, 1),
            "passages": self.passage_count,
            "pause_between_passages_s": int(self.pause_between_passages_s),
            "zones": [zone.as_runtime_dict() for zone in self.zones],
            "watering_strategy": self.watering_strategy,
            "objective_scope": self.objective_scope,
            "watering_stage": self.watering_stage,
            "surface_cycle_mm": round(self.surface_cycle_mm, 1)
            if self.surface_cycle_mm is not None
            else None,
            "daily_cycles_target": self.daily_cycles_target,
            "cycle_spacing_minutes": self.cycle_spacing_minutes,
            "surface_moisture_target": self.surface_moisture_target,
            "surface_dryness_risk": self.surface_dryness_risk,
            "runoff_risk": self.runoff_risk,
            "seeding_transition_ready": self.seeding_transition_ready,
            "seeding_block_reason": self.seeding_block_reason,
        }


def _duration_human(total_seconds: int) -> str:
    total_seconds = max(0, int(total_seconds))
    minutes, seconds = divmod(total_seconds, 60)
    if seconds == 0:
        return f"{minutes} min"
    return f"{minutes} min {seconds:02d}"


def _normalize_duration_seconds(raw_duration_s: Any) -> int | None:
    try:
        duration_s = float(raw_duration_s)
    except (TypeError, ValueError):
        return None
    if duration_s <= 0:
        return None
    return int(round(duration_s))


def _normalize_zone_plan(zone: dict[str, Any]) -> ZonePlan | None:
    entity_id = str(zone.get("zone") or zone.get("entity_id") or "").strip()
    if not entity_id:
        return None
    duration_s = zone.get("duration_s")
    if duration_s is None:
        duration_s = zone.get("duration_seconds")
    if duration_s is None:
        duration_min = zone.get("duration_min")
        try:
            duration_s = float(duration_min) * 60.0 if duration_min is not None else None
        except (TypeError, ValueError):
            duration_s = None
    normalized_duration_s = _normalize_duration_seconds(duration_s)
    if normalized_duration_s is None:
        return None
    try:
        rate_mm_h = float(zone.get("rate_mm_h") or 0.0)
    except (TypeError, ValueError):
        rate_mm_h = 0.0
    try:
        mm = float(zone.get("mm") or 0.0)
    except (TypeError, ValueError):
        mm = 0.0
    if mm <= 0 and rate_mm_h > 0:
        mm = (rate_mm_h * normalized_duration_s) / 3600.0
    return ZonePlan(
        zone=entity_id,
        rate_mm_h=max(0.0, rate_mm_h),
        duration_s=normalized_duration_s,
        mm=max(0.0, mm),
    )


def build_watering_plan(
    objective_mm: float,
    zones_cfg: Iterable[tuple[str, float]],
    *,
    passages: int = 1,
    pause_minutes: int = 0,
    source: str = PLAN_SOURCE_CALCULATED,
    watering_strategy: str | None = None,
    objective_scope: str | None = None,
    watering_stage: str | None = None,
    surface_cycle_mm: float | None = None,
    daily_cycles_target: int | None = None,
    cycle_spacing_minutes: int | None = None,
    surface_moisture_target: str | None = None,
    surface_dryness_risk: str | None = None,
    runoff_risk: str | None = None,
    seeding_transition_ready: bool | None = None,
    seeding_block_reason: str | None = None,
) -> WateringPlan | None:
    try:
        objective = float(objective_mm)
    except (TypeError, ValueError):
        return None
    if objective <= 0:
        return None

    normalized_zones: list[ZonePlan] = []
    for entity_id, rate_mm_h in zones_cfg:
        try:
            rate = float(rate_mm_h)
        except (TypeError, ValueError):
            continue
        if not entity_id or rate <= 0:
            continue
        duration_minutes = (objective / rate) * 60.0
        if duration_minutes <= 0:
            continue
        rounded_duration_minutes = max(
            _MIN_ZONE_DURATION_MIN,
            round(duration_minutes / _DURATION_ROUNDING_STEP_MIN) * _DURATION_ROUNDING_STEP_MIN,
        )
        rounded_duration_minutes = min(rounded_duration_minutes, _MAX_ZONE_DURATION_MIN)
        duration_seconds = int(round(rounded_duration_minutes * 60.0))
        if duration_seconds <= 0:
            continue
        normalized_zones.append(
            ZonePlan(
                zone=str(entity_id),
                rate_mm_h=rate,
                duration_s=duration_seconds,
                mm=(rate * duration_seconds) / 3600.0,
            )
        )

    if not normalized_zones:
        return None

    passage_count = max(1, int(passages))
    pause_between_passages_s = max(0, int(pause_minutes)) * 60
    plan_type = "multi_zone" if len(normalized_zones) > 1 else "single_zone"
    return WateringPlan(
        objective_mm=objective,
        plan_type=plan_type,
        passage_count=passage_count,
        pause_between_passages_s=pause_between_passages_s,
        zones=tuple(normalized_zones),
        source=source,
        watering_strategy=watering_strategy,
        objective_scope=objective_scope,
        watering_stage=watering_stage,
        surface_cycle_mm=surface_cycle_mm,
        daily_cycles_target=daily_cycles_target,
        cycle_spacing_minutes=cycle_spacing_minutes,
        surface_moisture_target=surface_moisture_target,
        surface_dryness_risk=surface_dryness_risk,
        runoff_risk=runoff_risk,
        seeding_transition_ready=seeding_transition_ready,
        seeding_block_reason=seeding_block_reason,
    )


def normalize_existing_plan(plan_state_attrs: Mapping[str, Any] | None) -> WateringPlan | None:
    if not isinstance(plan_state_attrs, Mapping):
        return None
    zones = plan_state_attrs.get("zones")
    if not isinstance(zones, list):
        return None
    normalized_zones = tuple(
        zone_plan
        for zone_plan in (_normalize_zone_plan(zone) for zone in zones if isinstance(zone, dict))
        if zone_plan is not None
    )
    if not normalized_zones:
        return None
    try:
        objective_mm = float(plan_state_attrs.get("objective_mm") or plan_state_attrs.get("objectif_mm") or 0.0)
    except (TypeError, ValueError):
        objective_mm = 0.0
    if objective_mm <= 0:
        # Best-effort reconstruction: all zones are expected to target the same
        # water depth, so we keep the highest effective zone depth as a
        # conservative proxy when the original objective is missing.
        objective_mm = round(max(zone.mm for zone in normalized_zones), 1)
    try:
        passage_count = max(1, int(plan_state_attrs.get("passages", 1)))
    except (TypeError, ValueError):
        passage_count = 1
    pause_between_passages_s = 0
    if "pause_between_passages_s" in plan_state_attrs:
        try:
            pause_between_passages_s = max(0, int(plan_state_attrs.get("pause_between_passages_s") or 0))
        except (TypeError, ValueError):
            pause_between_passages_s = 0
    else:
        try:
            pause_between_passages_s = max(
                0, int(plan_state_attrs.get("pause_between_passages_minutes", 0))
            ) * 60
        except (TypeError, ValueError):
            pause_between_passages_s = 0
    source = str(plan_state_attrs.get("source") or PLAN_SOURCE_NORMALIZED)
    plan_type = str(plan_state_attrs.get("plan_type") or ("multi_zone" if len(normalized_zones) > 1 else "single_zone"))
    try:
        surface_cycle_mm = plan_state_attrs.get("surface_cycle_mm")
        if surface_cycle_mm is None and plan_state_attrs.get("objective_scope") == "surface_cycle":
            surface_cycle_mm = objective_mm
        surface_cycle_mm = float(surface_cycle_mm) if surface_cycle_mm is not None else None
    except (TypeError, ValueError):
        surface_cycle_mm = None
    try:
        daily_cycles_target = plan_state_attrs.get("daily_cycles_target")
        daily_cycles_target = int(daily_cycles_target) if daily_cycles_target is not None else None
    except (TypeError, ValueError):
        daily_cycles_target = None
    try:
        cycle_spacing_minutes = plan_state_attrs.get("cycle_spacing_minutes")
        cycle_spacing_minutes = int(cycle_spacing_minutes) if cycle_spacing_minutes is not None else None
    except (TypeError, ValueError):
        cycle_spacing_minutes = None
    return WateringPlan(
        objective_mm=objective_mm,
        plan_type=plan_type,
        passage_count=passage_count,
        pause_between_passages_s=pause_between_passages_s,
        zones=normalized_zones,
        source=source,
        watering_strategy=plan_state_attrs.get("watering_strategy"),
        objective_scope=plan_state_attrs.get("objective_scope"),
        watering_stage=plan_state_attrs.get("watering_stage"),
        surface_cycle_mm=surface_cycle_mm,
        daily_cycles_target=daily_cycles_target,
        cycle_spacing_minutes=cycle_spacing_minutes,
        surface_moisture_target=plan_state_attrs.get("surface_moisture_target"),
        surface_dryness_risk=plan_state_attrs.get("surface_dryness_risk"),
        runoff_risk=plan_state_attrs.get("runoff_risk"),
        seeding_transition_ready=plan_state_attrs.get("seeding_transition_ready"),
        seeding_block_reason=plan_state_attrs.get("seeding_block_reason"),
    )
