from __future__ import annotations

import math
from typing import Any


def plan_morning_departure(
    *,
    window_start_minute: int,
    sunrise_minute: int | None,
    duration_s: float,
    margin_minutes: int,
) -> dict[str, int] | None:
    """Départ du matin calé pour FINIR juste avant le lever du soleil (minutes locales).

    Arbitrage de Kévin, 15/09/2026 (étape 2) : arroser sur la rosée et finir avant que le soleil
    ne sèche le feuillage (NC State : « just before sunrise »). La fin visée est `lever − marge`.
    Le départ ne précède jamais l'ouverture de la fenêtre. Un cycle trop long pour tenir avant la
    fin visée part donc à l'ouverture et finit plus tard.

    ⚠️ AUCUN PLAFOND LIÉ À LA TONTE. Un premier jet finissait au plus tard à 07:00, pour que le délai
    de reprise de 180 min tombe à 10:00. La prémisse était fausse : après ce délai, le ressuyage
    estimé (`recent_watering`) retient encore la tonte, 4 à 6 h après la fin de l'arrosage en sol
    limoneux. Le plafond ne rendait donc pas la tonte de 10:00. Kévin a choisi de tondre plus tard
    et d'élargir les fenêtres de tonte (`decision_mowing`).

    `None` quand le lever du soleil est inconnu : l'appelant garde l'ouverture de la fenêtre,
    comme avant.
    """
    if sunrise_minute is None:
        return None
    duree_min = int(math.ceil(max(0.0, float(duration_s)) / 60.0))
    fin_visee = int(sunrise_minute) - max(0, int(margin_minutes))
    depart = max(int(window_start_minute), fin_visee - duree_min)
    return {"departure_minute": depart, "end_minute": depart + duree_min}


def _int_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def is_matching_zone_segment(segment: Any, *, passage: int, zone_index: int) -> bool:
    """Vrai si un segment runtime désigne exactement ce passage et cette zone."""
    if not isinstance(segment, dict):
        return False
    return (
        _int_or_none(segment.get("passage")) == passage
        and _int_or_none(segment.get("zone_index")) == zone_index
    )


def zone_rate_mm_min(entity_id: str | None, rate_h: Any | None) -> float:
    """Debit d'une zone en mm/min."""
    if not entity_id or rate_h is None:
        return 0.0
    try:
        return float(rate_h) / 60.0
    except (TypeError, ValueError):
        return 0.0


def zone_rate_mm_h(entity_id: str | None, rate_h: Any | None) -> float:
    """Debit d'une zone en mm/h."""
    if not entity_id:
        return 0.0
    try:
        return float(rate_h or 0.0)
    except (TypeError, ValueError):
        return 0.0


def build_pending_zone_segments(plan: Any) -> list[dict[str, Any]]:
    """Segments restant a executer, avec dose/duree par passage."""
    pending: list[dict[str, Any]] = []
    for passage in range(1, plan.passage_count + 1):
        for zone_index, zone in enumerate(plan.zones):
            segment = plan.zone_for_passage(zone_index, passage)
            pending.append(
                {
                    "passage": passage,
                    "zone_index": zone_index,
                    "zone": zone.zone,
                    "duration_s": segment.duration_s,
                    "mm": round(segment.mm, 1),
                }
            )
    return pending


def build_zone_execution_record(
    *,
    zone: Any,
    passage: int,
    order: int,
    effective_duration_s: float | None = None,
) -> dict[str, Any]:
    """Trace d'execution d'une zone, proratee sur le temps reellement ouvert."""
    planned_s = float(zone.duration_s)
    effective_s = planned_s if effective_duration_s is None else max(0.0, float(effective_duration_s))
    ratio = 1.0 if planned_s <= 0 else min(1.0, effective_s / planned_s)
    record: dict[str, Any] = {
        "order": order,
        "passage": passage,
        "zone": zone.zone,
        "entity_id": zone.zone,
        "rate_mm_h": round(zone.rate_mm_h, 1),
        "duration_s": int(effective_s),
        "duration_seconds": int(effective_s),
        "duration_min": round(effective_s / 60.0, 1),
        "mm": round(zone.mm * ratio, 1),
    }
    if ratio < 0.995:
        record["interrupted"] = True
        record["planned_duration_s"] = int(planned_s)
    return record
