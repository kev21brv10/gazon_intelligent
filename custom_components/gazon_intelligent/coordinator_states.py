from __future__ import annotations

from datetime import datetime, timezone
from logging import Logger
from math import isfinite
from typing import Any

from .coordinator_constants import _UNAVAILABLE_STATES


def validate_sensor_value(
    value: float | None,
    sensor_type: str,
    logger: Logger,
) -> float | None:
    """Valide une valeur capteur et rejette les aberrations."""
    if value is None:
        return None
    if sensor_type == "temperature":
        if value < -20 or value > 55:
            logger.warning("Valeur température aberrante rejetée: %s°C", value)
            return None
    elif sensor_type == "pluie":
        if value < 0 or value > 150:
            logger.warning("Valeur pluie aberrante rejetée: %s mm", value)
            return None
    elif sensor_type == "etp":
        if value < 0 or value > 15:
            logger.warning("Valeur ETP aberrante rejetée: %s mm", value)
            return None
    elif sensor_type == "humidite":
        if value < 0 or value > 100:
            logger.warning("Valeur humidité aberrante rejetée: %s%%", value)
            return None
    return value


def get_state_unit(hass: Any, entity_id: str | None) -> str | None:
    """Unité déclarée par l'entité, ou `None`."""
    try:
        if not entity_id:
            return None
        state = hass.states.get(entity_id)
        if state is None:
            return None
        unite = (state.attributes or {}).get("unit_of_measurement")
        return str(unite) if unite not in (None, "") else None
    except Exception:  # noqa: BLE001
        return None


def get_float_state(hass: Any, entity_id: str | None, logger: Logger) -> float | None:
    """Retourne l'état float d'une entité Home Assistant."""
    if not entity_id:
        return None

    state = hass.states.get(entity_id)
    if state is None:
        return None

    try:
        raw = str(state.state).strip().replace(",", ".")
        value = float(raw)
    except (TypeError, ValueError):
        logger.debug("Impossible de convertir l'état de %s en float: %s", entity_id, state.state)
        return None
    # `float("nan")` et `float("inf")` NE lèvent PAS : un capteur publiant `nan` propagerait
    # une valeur non finie dans tous les calculs (ET0, bilan sol, scores), où elle contamine
    # silencieusement chaque opération. Une valeur non finie est une ABSENCE de mesure.
    if not isfinite(value):
        logger.debug("État non fini ignoré pour %s: %s", entity_id, state.state)
        return None
    return value


def get_text_state(hass: Any, entity_id: str | None) -> str | None:
    """Retourne l'état textuel d'une entité Home Assistant, ou None si indisponible."""
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    if state is None:
        return None
    text = str(state.state or "").strip()
    if text.lower() in _UNAVAILABLE_STATES:
        return None
    return text or None


def minutes_since_state_change(hass: Any, entity_id: str | None, now: datetime) -> float | None:
    """Depuis combien de minutes l'état de cette entité est passé à sa valeur actuelle, ou `None`.

    Lu sur `last_changed` (pas `last_updated` : un simple changement d'attribut ne doit pas
    rajeunir un état). `None` quand on ne peut rien affirmer : entité absente, date absente ou
    illisible, ou date POSTÉRIEURE à `now` (décalage d'horloge). Appelant : traiter `None`
    comme « inconnu », jamais comme « ancien ».
    """
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    changed = getattr(state, "last_changed", None)
    if not isinstance(changed, datetime) or not isinstance(now, datetime):
        return None
    if changed.tzinfo is None:
        changed = changed.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    minutes = (now - changed).total_seconds() / 60.0
    return minutes if minutes >= 0.0 else None


def get_bool_state(hass: Any, entity_id: str | None) -> bool | None:
    """Retourne l'état booléen standardisé d'une entité Home Assistant."""
    raw = get_text_state(hass, entity_id)
    if raw is None:
        return None
    lowered = raw.lower()
    if lowered in {"on", "true", "home", "detected"}:
        return True
    if lowered in {"off", "false", "not_home", "clear"}:
        return False
    return None
