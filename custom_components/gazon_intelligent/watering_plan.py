from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


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
    source: str = "calculated_from_objective"

    @property
    def per_passage_duration_s(self) -> int:
        return sum(zone.duration_s for zone in self.zones)

    @property
    def total_duration_s(self) -> int:
        if self.passage_count <= 1:
            return self.per_passage_duration_s
        return (
            self.per_passage_duration_s * self.passage_count
            + self.pause_between_passages_s * (self.passage_count - 1)
        )

    @property
    def total_duration_min(self) -> float:
        return round(self.per_passage_duration_s / 60.0, 1)

    def as_dict(self) -> dict[str, Any]:
        zone_count = len(self.zones)
        return {
            "objective_mm": round(self.objective_mm, 1),
            "objectif_mm": round(self.objective_mm, 1),
            "zones": [zone.as_dict() for zone in self.zones],
            "zone_count": zone_count,
            "total_duration_min": self.total_duration_min,
            "duration_human": _duration_human(self.per_passage_duration_s),
            "fractionation": self.passage_count > 1,
            "passages": self.passage_count,
            "pause_between_passages_minutes": int(round(self.pause_between_passages_s / 60.0)),
            "pause_between_passages_s": self.pause_between_passages_s,
            "source": self.source,
            "plan_type": self.plan_type,
            "summary": (
                f"{zone_count} zone{'s' if zone_count != 1 else ''} • "
                f"{round(self.objective_mm, 1):.1f} mm • {_duration_human(self.per_passage_duration_s)}"
            ),
        }

    def as_runtime_dict(self) -> dict[str, Any]:
        return {
            "objective_mm": round(self.objective_mm, 1),
            "passages": self.passage_count,
            "pause_between_passages_s": int(self.pause_between_passages_s),
            "zones": [zone.as_runtime_dict() for zone in self.zones],
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
    source: str = "calculated_from_objective",
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
        rounded_duration_minutes = max(0.5, round(duration_minutes * 2.0) / 2.0)
        rounded_duration_minutes = min(rounded_duration_minutes, 180.0)
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
    )


def normalize_existing_plan(plan_state_attrs: dict[str, Any] | None) -> WateringPlan | None:
    if not isinstance(plan_state_attrs, dict):
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
    source = str(plan_state_attrs.get("source") or "normalized_existing_plan")
    plan_type = str(plan_state_attrs.get("plan_type") or ("multi_zone" if len(normalized_zones) > 1 else "single_zone"))
    return WateringPlan(
        objective_mm=objective_mm,
        plan_type=plan_type,
        passage_count=passage_count,
        pause_between_passages_s=pause_between_passages_s,
        zones=normalized_zones,
        source=source,
    )
