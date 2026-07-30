from __future__ import annotations

"""Façade canonique de coordination tondeuse <-> arrosage."""

from typing import Any


_DOCKED_RAW_STATES = {"docked", "dock", "parked", "parked_timer", "home", "charging"}
_IDLE_RAW_STATES = {"idle", "standby"}
_MOWING_RAW_STATES = {"mowing", "edgecut", "cutting", "in_operation", "working"}
_RETURNING_RAW_STATES = {"returning", "going_home", "homing"}
_PAUSED_RAW_STATES = {"paused", "pause", "stopped"}
_STARTING_RAW_STATES = {"starting"}
_ZONING_RAW_STATES = {"zoning"}
_SEARCHING_ZONE_RAW_STATES = {"searching_zone"}
_ESCAPED_RAW_STATES = {"escaped_digital_fence"}
_RAIN_DELAYED_RAW_STATES = {"rain_delayed", "rain_delay"}

_OPERATION_LABELS = {
    "tonte": "Tonte en cours",
    "transit": "Retour station",
    "idle": "Au repos",
    "charging": "En charge",
    "paused": "En pause",
    "starting": "Démarrage",
    "zoning": "Changement de zone",
    "searching_zone": "Recherche de zone",
    "escaped_digital_fence": "Sortie du périmètre",
    "rain_delayed": "Pause pluie",
    "error": "Erreur tondeuse",
    "unknown": "Coordination tondeuse indisponible",
}

_PRESENCE_LABELS = {
    "dockee": "Tondeuse rangée",
    "dehors": "Tondeuse dehors",
    "retour": "Tondeuse en retour",
    "inconnue": "Position tondeuse inconnue",
}

_RESOLUTION_LABELS = {
    "ambiguous": "Plusieurs tondeuses détectées. Configuration explicite requise.",
    "missing": "Aucune tondeuse détectée.",
    "configured_missing": "Tondeuse configurée introuvable.",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalized_raw_state(context: dict[str, Any]) -> str:
    return _text(context.get("tondeuse_etat_brut")).lower()


def _operation_label(operation_state: str, raw_state: str) -> str:
    if raw_state == "edgecut":
        return "Coupe des bordures"
    return _OPERATION_LABELS.get(operation_state, operation_state)


def _operation_state(context: dict[str, Any]) -> str:
    raw_state = _normalized_raw_state(context)
    status = _text(context.get("tondeuse_statut")).lower()
    charging = context.get("tondeuse_en_charge") is True
    connected = context.get("tondeuse_connectee") is True

    if not connected:
        return "unknown"
    # L'ÉTAT BRUT DE L'APPAREIL FAIT FOI SUR LA TONTE, avant tout test de charge. Une tondeuse qui
    # tond ne peut pas être en charge : quand le capteur « en charge » reste à True au démarrage
    # d'une session (latence de rafraîchissement observée jusqu'à 8 min), tester la charge d'abord
    # la classait « à la station » et neutralisait silencieusement la coordination anti-collision —
    # l'arrosage pouvait donc partir sur une tondeuse en pleine tonte.
    if raw_state in _MOWING_RAW_STATES:
        return "tonte"
    if charging or raw_state == "charging" or status == "en_charge":
        return "charging"
    if raw_state in _STARTING_RAW_STATES:
        return "starting"
    if status == "tonte_en_cours":
        return "tonte"
    if raw_state in _RETURNING_RAW_STATES or status == "retour_station":
        return "transit"
    if raw_state in _ZONING_RAW_STATES:
        return "zoning"
    if raw_state in _SEARCHING_ZONE_RAW_STATES:
        return "searching_zone"
    if raw_state in _ESCAPED_RAW_STATES:
        return "escaped_digital_fence"
    if raw_state in _RAIN_DELAYED_RAW_STATES:
        return "rain_delayed"
    if raw_state in _PAUSED_RAW_STATES or status == "pause":
        return "paused"
    # La pluie N'EST PAS une erreur. Fusionnés dans le même test, une pluie ordinaire — tondeuse
    # rentrée à la station, batterie pleine donc pas « en charge » — affichait « Robot en erreur :
    # Pluie ou délai pluie actif. », une fausse alarme pour un fonctionnement parfaitement normal.
    if status == "pluie":
        return "rain_delayed"
    if status == "erreur":
        return "error"
    if status == "au_repos":
        return "idle"
    return "unknown"


def _presence_state(context: dict[str, Any], operation_state: str) -> str:
    raw_state = _normalized_raw_state(context)
    connected = context.get("tondeuse_connectee") is True
    status = _text(context.get("tondeuse_statut")).lower()

    if not connected:
        return "inconnue"
    if operation_state == "charging" or raw_state in _DOCKED_RAW_STATES:
        return "dockee"
    if operation_state == "idle" and (raw_state in _IDLE_RAW_STATES or status == "au_repos"):
        return "dockee"
    if operation_state == "transit":
        return "retour"
    # `rain_delayed` = pause pluie : le robot est RENTRÉ à sa station et y reste. Le classer
    # « dehors » bloquait l'arrosage (`mower_not_stowed`) pour une machine parfaitement rangée —
    # et la pause pluie s'arme sur quelques dixièmes de mm puis dure 6 à 12 h, donc le lendemain
    # d'une averse insignifiante l'arrosage du matin était perdu.
    if operation_state == "rain_delayed":
        return "dockee"
    if operation_state in {"tonte", "paused", "starting", "zoning", "searching_zone", "escaped_digital_fence"}:
        return "dehors"
    return "inconnue"


def _reliability(context: dict[str, Any], enabled: bool, operation_state: str, presence_state: str) -> tuple[bool, str, str]:
    if not enabled:
        return True, "disabled", "Coordination tondeuse désactivée."

    resolution_state = _text(context.get("tondeuse_resolution_state")).lower()
    if resolution_state in _RESOLUTION_LABELS:
        return False, resolution_state, _RESOLUTION_LABELS[resolution_state]

    source_entity = _text(context.get("tondeuse_source_entity"))
    if not source_entity:
        return False, "unreliable", "Coordination tondeuse active, mais aucune tondeuse n'est configurée."

    if context.get("tondeuse_connectee") is not True:
        return False, "unreliable", _text(context.get("tondeuse_raison")) or "Tondeuse indisponible."

    if operation_state == "error":
        return False, "error", _text(context.get("tondeuse_raison")) or "État tondeuse incohérent ou en erreur."

    if operation_state == "starting":
        return True, "mower_starting", "Tondeuse en démarrage."

    if operation_state == "zoning":
        return True, "mower_zoning", "Tondeuse en changement de zone."

    if operation_state == "searching_zone":
        return True, "mower_searching_zone", "Tondeuse en recherche de zone."

    if operation_state == "escaped_digital_fence":
        return False, "mower_escaped_digital_fence", "Tondeuse sortie du périmètre."

    if operation_state == "rain_delayed":
        # Le robot est à la station : la coordination est FIABLE (rien ne traîne sur la pelouse),
        # même si la tonte, elle, reste évidemment reportée. Renvoyer False ici bloquait
        # l'arrosage pour une machine rangée.
        return True, "mower_rain_delayed", "Pause pluie active."

    if presence_state == "inconnue":
        return False, "unreliable", "Position réelle de la tondeuse inconnue."

    if operation_state == "tonte":
        return True, "mower_mowing", "Tondeuse en cours de tonte."

    if operation_state == "transit":
        return True, "mower_returning", "Tondeuse en retour station."

    return True, "none", ""


def build_mower_coordination_context(
    mower_context: dict[str, Any] | None,
    *,
    enabled: bool,
) -> dict[str, Any]:
    context = dict(mower_context or {})
    raw_state = _normalized_raw_state(context)
    operation_state = _operation_state(context)
    presence_state = _presence_state(context, operation_state)
    ready, reason_code, reason_label = _reliability(context, enabled, operation_state, presence_state)

    if ready:
        if operation_state == "tonte":
            reason_code = "mower_mowing"
            reason_label = "Tondeuse en cours de tonte."
        elif operation_state == "transit":
            reason_code = "mower_returning"
            reason_label = "Tondeuse en retour station."

    is_mowing = operation_state == "tonte"
    is_returning = operation_state == "transit"
    is_docked = presence_state == "dockee" or operation_state == "charging"
    is_outside = presence_state in {"dehors", "retour"}
    safe_for_watering = enabled is False or (ready and is_docked)

    payload = {
        "mower_coordination_enabled": bool(enabled),
        "mower_coordination_ready": bool(ready),
        "mower_presence_state": presence_state,
        "mower_presence_label": _PRESENCE_LABELS.get(presence_state, presence_state),
        "mower_operation_state": operation_state,
        "mower_operation_label": _operation_label(operation_state, raw_state),
        "mower_is_docked": is_docked,
        "mower_is_outside": is_outside,
        "mower_is_mowing": is_mowing,
        "mower_is_returning": is_returning,
        "mower_is_safe_for_watering": bool(safe_for_watering),
        "mower_reason_code": reason_code,
        "mower_reason_label": reason_label or context.get("tondeuse_raison") or "",
        "mower_battery": context.get("tondeuse_batterie"),
        "mower_next_departure": context.get("tondeuse_prochain_depart"),
        "mower_resolution_state": _text(context.get("tondeuse_resolution_state")) or None,
        "mower_resolution_reason": _text(context.get("tondeuse_resolution_reason")) or None,
        "mower_resolution_candidate_count": context.get("tondeuse_resolution_candidate_count"),
    }
    return {key: value for key, value in payload.items() if value not in (None, "")}
