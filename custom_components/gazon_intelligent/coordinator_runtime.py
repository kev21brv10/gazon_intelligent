from __future__ import annotations

from datetime import date, datetime, timezone
from collections.abc import Container
from collections.abc import Callable
from typing import Any
from uuid import uuid4

# Posé dans la session juste avant d'enregistrer l'eau d'un cycle piloté : voir
# `is_finished_irrigation_session` pour ce qu'il protège.
WATERING_RECORDED_KEY = "watering_recorded"


def parse_datetime_value(value: Any) -> datetime | None:
    """Date/heure runtime normalisee en UTC, ou `None` si illisible."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def minutes_creditables(
    previous_value: Any,
    now: datetime,
    *,
    parser: Callable[[Any], datetime | None],
    max_minutes: float,
) -> float:
    """Minutes a crediter entre deux echantillons, bornees par le plafond runtime."""
    previous = parser(previous_value)
    if previous is None:
        return 0.0
    elapsed = (now - previous).total_seconds() / 60.0
    if 0.0 < elapsed <= max_minutes:
        return elapsed
    return 0.0


def local_datetime_text(value: Any, *, local_timezone: Any) -> str | None:
    """Texte local lisible pour une date ou date/heure runtime."""
    if value in (None, "", [], {}):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, datetime):
        dt_value = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt_value = datetime.fromisoformat(text)
        except ValueError:
            try:
                return date.fromisoformat(text[:10]).strftime("%d/%m/%Y")
            except ValueError:
                return text
    tz = local_timezone or timezone.utc
    if dt_value.tzinfo is None:
        dt_value = dt_value.replace(tzinfo=tz)
    return dt_value.astimezone(tz).strftime("%d/%m/%Y à %H:%M")


def local_date_of(
    moment: datetime,
    *,
    as_local: Callable[[datetime], datetime] | None = None,
) -> date:
    """Date civile locale d'un instant."""
    return (as_local(moment) if callable(as_local) else moment).date()


def new_runtime_id(prefix: str, now_utc: datetime, *, token_factory: Callable[[], str] | None = None) -> str:
    """Identifiant runtime horodate et court."""
    token = token_factory() if token_factory is not None else uuid4().hex
    timestamp = now_utc.strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}_{timestamp}_{token[:8]}"


def current_objective_mm(result: Any, data: Any) -> float:
    """Objectif d'arrosage courant, resolu depuis le resultat puis le snapshot publie."""
    if result is not None:
        value = getattr(result, "objectif_arrosage", None)
        try:
            if value is not None:
                return max(0.0, float(value))
        except (TypeError, ValueError):
            pass
        extra = getattr(result, "extra", None)
        if isinstance(extra, dict):
            value = extra.get("objectif_mm")
            try:
                if value is not None:
                    return max(0.0, float(value))
            except (TypeError, ValueError):
                pass

    if isinstance(data, dict):
        value = data.get("objectif_mm")
        try:
            if value is not None:
                return max(0.0, float(value))
        except (TypeError, ValueError):
            pass
    return 0.0


def serialize_runtime_value(value: Any) -> Any:
    """Valeur runtime serialisable JSON."""
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: serialize_runtime_value(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialize_runtime_value(item) for item in value]
    return value


def build_runtime_payload_for_event(
    session: dict[str, Any] | None,
    extra: dict[str, Any],
    *,
    serializer: Callable[[Any], Any] = serialize_runtime_value,
) -> dict[str, Any]:
    """Payload compact pour les evenements runtime d'irrigation."""
    payload: dict[str, Any] = {}
    if isinstance(session, dict):
        for key in (
            "session_id",
            "run_id",
            "source",
            "strategy",
            "status",
            "current_passage",
            "watering_cause",
            "watering_strategy",
            "objective_scope",
            "watering_stage",
            "surface_cycle_mm",
            "daily_cycles_target",
            "cycle_spacing_minutes",
        ):
            value = session.get(key)
            if value not in (None, "", [], {}):
                payload[key] = value
    for key, value in extra.items():
        if value not in (None, "", [], {}):
            payload[key] = serializer(value)
    return payload


def deserialize_active_irrigation_session(
    payload: Any,
    *,
    parser: Callable[[Any], datetime | None] = parse_datetime_value,
) -> dict[str, Any] | None:
    """Session d'irrigation restauree depuis le runtime persiste."""
    if not isinstance(payload, dict):
        return None
    session = dict(payload)
    for key in ("started_at", "paused_until", "last_update", "ended_at", "current_zone_started_at"):
        if key in session:
            session[key] = parser(session.get(key))
    return session


def is_finished_irrigation_session(session: dict[str, Any], *, now_utc: datetime) -> bool:
    """Une session d'irrigation runtime est-elle terminee ?"""
    status = str(session.get("status") or "").strip().lower()
    if status in {"completed", "failed", "cancelled"}:
        return True
    active_zones = session.get("active_zones")
    has_active_zones = bool(active_zones) if isinstance(active_zones, (dict, list, tuple, set)) else False
    if has_active_zones or session.get("current_zone"):
        return False
    if session.get(WATERING_RECORDED_KEY):
        return True
    try:
        planned_total_seconds = max(0.0, float(session.get("planned_total_seconds") or 0.0))
    except (TypeError, ValueError):
        planned_total_seconds = 0.0
    zones_pending = session.get("zones_pending")
    has_pending_segments = isinstance(zones_pending, list) and len(zones_pending) > 0
    # ⚠️ Plus aucun segment en attente ne veut pas dire « eau enregistrée ». La dernière zone
    # est purgée PUIS sauvegardée, et l'eau n'est enregistrée qu'après : un arrêt ou un
    # redémarrage pendant cette sauvegarde clôturait la session sans rien enregistrer (0 mm au
    # lieu de 6 sur un cycle 3 zones × 2 passages). Tant que des zones ont tourné sans que
    # l'eau soit inscrite, la session reste active : l'arrêt ou la reprise l'enregistrent.
    eau_non_enregistree = bool(session.get("zones_done")) and not session.get(WATERING_RECORDED_KEY)
    if eau_non_enregistree:
        return False
    started_at = session.get("started_at")
    if planned_total_seconds > 0 and isinstance(started_at, datetime) and not has_pending_segments:
        elapsed_seconds = max((now_utc - started_at).total_seconds(), 0.0)
        if elapsed_seconds >= planned_total_seconds:
            return True
    try:
        current_passage = max(1, int(session.get("current_passage") or 1))
    except (TypeError, ValueError):
        current_passage = 1
    try:
        passage_count = max(1, int(session.get("passage_count") or 1))
    except (TypeError, ValueError):
        passage_count = 1
    return current_passage >= passage_count and not has_pending_segments and isinstance(zones_pending, list)


def normalize_watering_cause(
    value: Any,
    *,
    source: str | None = None,
    known_causes: Container[str],
) -> str:
    """Cause d'arrosage canonique exposee a l'historique."""
    raw_cause = str(value or "").strip().lower()
    if raw_cause in known_causes:
        return raw_cause
    raw_source = str(source or "").strip().lower()
    if raw_source in {"application_technique", "application_technique_auto", "manual_application"}:
        return "post_application"
    return "hydrique"


def round_runtime_mm(value: Any) -> float:
    """Millimetres runtime arrondis, bornes a zero."""
    try:
        return round(max(0.0, float(value or 0.0)), 1)
    except (TypeError, ValueError):
        return 0.0


def build_execution_plan_metrics(
    session: dict[str, Any],
    *,
    rounder: Callable[[Any], float] = round_runtime_mm,
) -> dict[str, Any]:
    """Metriques prevues du plan d'execution d'irrigation."""
    plan = session.get("plan")
    if not isinstance(plan, dict):
        return {
            "planned_mm": 0.0,
            "planned_zone_count": 0,
            "planned_zone_segments": 0,
            "planned_total_seconds": rounder(session.get("planned_total_seconds")),
        }
    zones = plan.get("zones")
    if not isinstance(zones, list):
        zones = []
    passage_count = max(1, int(plan.get("passages") or session.get("passage_count") or 1))
    planned_zone_count = len(zones)
    planned_zone_segments = planned_zone_count * passage_count
    planned_mm = rounder(sum(rounder(zone.get("mm")) for zone in zones))
    try:
        planned_total_seconds = max(0.0, float(session.get("planned_total_seconds") or 0.0))
    except (TypeError, ValueError):
        planned_total_seconds = 0.0
    return {
        "planned_mm": planned_mm,
        "planned_zone_count": planned_zone_count,
        "planned_zone_segments": planned_zone_segments,
        "planned_total_seconds": int(round(planned_total_seconds)),
    }


def build_active_irrigation_session(
    *,
    plan: Any,
    source: str,
    strategy: str,
    watering_cause: str,
    run_id: str,
    session_id: str,
    now: datetime,
    zones_pending: list[dict[str, Any]],
) -> dict[str, Any]:
    """Session runtime active prete pour l'execution d'un plan d'irrigation."""
    return {
        "session_id": session_id,
        "run_id": run_id,
        "source": source,
        "strategy": strategy,
        "watering_cause": watering_cause,
        "watering_strategy": plan.watering_strategy or strategy,
        "objective_scope": plan.objective_scope,
        "watering_stage": plan.watering_stage,
        "surface_cycle_mm": plan.surface_cycle_mm,
        "daily_cycles_target": plan.daily_cycles_target,
        "cycle_spacing_minutes": plan.cycle_spacing_minutes,
        "surface_moisture_target": plan.surface_moisture_target,
        "surface_dryness_risk": plan.surface_dryness_risk,
        "runoff_risk": plan.runoff_risk,
        "seeding_transition_ready": plan.seeding_transition_ready,
        "seeding_block_reason": plan.seeding_block_reason,
        "status": "running",
        "target_mm": round(plan.objective_mm, 1),
        "plan": plan.as_runtime_dict(),
        "passage_count": plan.passage_count,
        "current_passage": 1,
        "current_zone_index": 0,
        "current_zone": None,
        "active_zones": [],
        "zones_done": [],
        "zones_failed": [],
        "zones_pending": zones_pending,
        "planned_total_seconds": float(plan.total_duration_s),
        "started_at": now,
        "last_activity_at": now,
        "paused_until": None,
        "last_update": now,
        "last_error": None,
    }
