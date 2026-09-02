from __future__ import annotations

"""Normalisation générique des états de robot tondeuse Home Assistant."""

from datetime import date, datetime, timezone
from typing import Any

try:
    from homeassistant.util import dt as dt_util
except Exception:  # pragma: no cover - standalone fallback
    dt_util = None

_MOWER_STATE_ALIASES: dict[str, str] = {
    "mowing": "tonte_en_cours",
    "edgecut": "tonte_en_cours",
    "cutting": "tonte_en_cours",
    "in_operation": "tonte_en_cours",
    "working": "tonte_en_cours",
    "returning": "retour_station",
    "going_home": "retour_station",
    "homing": "retour_station",
    "paused": "pause",
    "pause": "pause",
    "stopped": "pause",
    "charging": "en_charge",
    "docked": "au_repos",
    "dock": "au_repos",
    "parked": "au_repos",
    "parked_timer": "au_repos",
    "idle": "au_repos",
    "standby": "au_repos",
    "home": "au_repos",
    "rain_delay": "pluie",
    "rain_delayed": "pluie",
    "weather_delay": "pluie",
    "error": "erreur",
    "trapped": "erreur",
    "unavailable": "indisponible",
    "unknown": "inconnu",
}

# États Home Assistant signifiant « pas de mesure » : filtrés par `_clean_text`, donc jamais
# retenus comme valeur (cf. coordinator._UNAVAILABLE_STATES, même intention en amont).
_UNAVAILABLE_TEXT_VALUES = frozenset({"unavailable", "unknown"})

_NO_ERROR_VALUES = {
    "",
    "none",
    "ok",
    "no_error",
    "no error",
    "aucune",
    "aucune_erreur",
    "aucune erreur",
    # « Pas de mesure » n'est PAS une panne : un capteur d'erreur indisponible (cas courant à
    # chaque redémarrage de Home Assistant) était sinon lu comme un code d'erreur, et la tonte
    # bloquée par un « Robot en erreur » imaginaire. Filtré aussi en amont
    # (`coordinator._get_text_state`) ; conservé ici pour les valeurs arrivant d'un attribut.
    "unavailable",
    "unknown",
}

_RAIN_ERROR_VALUES = {
    "rain_delay",
    "rain_delayed",
    "weather_delay",
}

_BLOCKING_STATUSES = {
    "indisponible",
    "erreur",
    "pluie",
    "en_charge",
    "retour_station",
    "tonte_en_cours",
}

_STATUS_LABELS: dict[str, str] = {
    "indisponible": "Indisponible",
    "erreur": "Erreur",
    "pluie": "Pluie",
    "en_charge": "En charge",
    "tonte_en_cours": "Tonte en cours",
    "retour_station": "Retour station",
    "pause": "En pause",
    "au_repos": "Au repos",
    "inconnu": "Inconnu",
}

_RAW_STATE_LABELS: dict[str, str] = {
    "mowing": "Tonte en cours",
    "edgecut": "Coupe des bordures",
    "starting": "Démarrage",
    "returning": "Retour station",
    "going_home": "Retour station",
    "paused": "En pause",
    "docked": "À la station",
    "idle": "Au repos",
    "charging": "En charge",
    "zoning": "Changement de zone",
    "searching_zone": "Recherche de zone",
    "escaped_digital_fence": "Sortie du périmètre",
    "rain_delayed": "Pause pluie",
    "rain_delay": "Pause pluie",
    "error": "En erreur",
    "unavailable": "Indisponible",
    "unknown": "Inconnu",
}

_ERROR_LABELS: dict[str, str] = {
    "no_error": "Aucune erreur",
    "trapped": "Tondeuse coincée",
    "lifted": "Tondeuse soulevée",
    "wire_missing": "Fil périmétrique manquant",
    "outside_wire": "Tondeuse hors périmètre",
    "rain_delay": "Pause pluie active",
    "close_door_to_mow": "Fermer le capot pour tondre",
    "close_door_to_go_home": "Fermer le capot pour retour station",
    "blade_motor_blocked": "Moteur de lame bloqué",
    "wheel_motor_blocked": "Moteur de roue bloqué",
    "trapped_timeout": "Tondeuse coincée trop longtemps",
    "upside_down": "Tondeuse retournée",
    "battery_low": "Batterie faible",
    "reverse_wire": "Fil périmétrique inversé",
    "charge_error": "Erreur de charge",
    "timeout_finding_home": "Temps dépassé pour trouver la base",
    "locked": "Tondeuse verrouillée",
    "battery_temperature_error": "Température batterie anormale",
    "battery_trunk_open_timeout": "Capot batterie ouvert trop longtemps",
    "wire_sync": "Erreur de synchronisation du fil",
    "charging_station_docking_error": "Erreur d'arrimage à la station",
    "hbi_error": "Erreur HBI",
    "ota_error": "Erreur de mise à jour",
    "map_error": "Erreur de cartographie",
    "excessive_slope": "Pente excessive",
    "unreachable_zone": "Zone inatteignable",
    "unreachable_charging_station": "Station inatteignable",
    "insufficient_sensor_data": "Données capteurs insuffisantes",
    "training_start_disallowed": "Démarrage de l'apprentissage interdit",
    "camera_error": "Erreur caméra",
    "mapping_exploration_required": "Exploration de cartographie requise",
    "mapping_exploration_failed": "Échec de l'exploration cartographique",
    "rfid_reader_error": "Erreur lecteur RFID",
    "headlight_error": "Erreur de phare",
    "missing_charging_station": "Station de charge introuvable",
    "blade_height_adjustment_blocked": "Réglage de hauteur de lame bloqué",
}


def _status_label(status: str, raw_state: Any) -> str | None:
    """Libellé lisible du statut. ⚠️ Une PANNE prime sur un état brut anodin.

    Le robot annonce `idle` quand il est immobilisé en plein jardin — soulevé, coincé, roue
    bloquée, retourné. L'état brut gagnait alors sur le statut dérivé et l'affichage montrait
    « Au repos » pour une machine en panne. Vérifié sur l'installation : du 02 au 05/08/2026,
    les 7 arrêts en jardin coïncident À LA SECONDE avec un déclenchement d'erreur, et l'état
    du robot y vaut `idle`.
    """
    lowered = str(raw_state or "").strip().lower()
    if str(status or "").strip().lower() == "erreur" and lowered not in {"error", "erreur"}:
        return _human_label(status)
    if lowered in _RAW_STATE_LABELS:
        return _RAW_STATE_LABELS[lowered]
    return _human_label(status)


def _clean_text(value: Any) -> str | None:
    """Texte exploitable, ou None si la valeur est une ABSENCE de mesure.

    `unavailable`/`unknown` sont des états Home Assistant signifiant « pas de donnée » : les
    laisser passer les transformait en valeurs — code d'erreur fantôme bloquant la tonte, ou
    littéral « unavailable » affiché comme heure de prochain départ.
    """
    text = str(value or "").strip()
    if text.lower() in _UNAVAILABLE_TEXT_VALUES:
        return None
    return text or None


def _normalize_error_code(raw_error: Any) -> str | None:
    text = _clean_text(raw_error)
    if text is None:
        return None
    lowered = text.lower()
    if lowered in _NO_ERROR_VALUES:
        return None
    return lowered


def _human_label(value: str | None) -> str | None:
    if not value:
        return None
    if value in _ERROR_LABELS:
        return _ERROR_LABELS[value]
    if value in _STATUS_LABELS:
        return _STATUS_LABELS[value]
    return value.replace("_", " ").strip().capitalize()


def _local_timezone():
    if dt_util is not None:
        now_getter = getattr(dt_util, "now", None)
        if callable(now_getter):
            current = now_getter()
            if isinstance(current, datetime) and current.tzinfo is not None:
                return current.tzinfo
    current = datetime.now().astimezone()
    return current.tzinfo or timezone.utc


def _normalize_mower_status(
    raw_state: Any,
    *,
    charging: bool | None,
    rain: bool | None,
    error_code: str | None,
    available: bool,
) -> str:
    if not available:
        return "indisponible"
    if error_code in _RAIN_ERROR_VALUES or rain is True:
        return "pluie"
    if error_code is not None:
        return "erreur"
    if charging is True:
        return "en_charge"

    lowered = str(raw_state or "").strip().lower()
    if lowered in _MOWER_STATE_ALIASES:
        return _MOWER_STATE_ALIASES[lowered]
    return "inconnu"


def _human_datetime_text(value: Any) -> str | None:
    if value in (None, "", [], {}):
        return None
    # Une date non mesurée ne se formate pas : sans ce filtre, un capteur indisponible finissait
    # affiché littéralement « unavailable » à la place de l'heure du prochain départ.
    if isinstance(value, str) and value.strip().lower() in _UNAVAILABLE_TEXT_VALUES:
        return None
    if isinstance(value, datetime):
        dt_value = value
    elif isinstance(value, date):
        return value.strftime("%d/%m/%Y")
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
    if dt_value.tzinfo is not None:
        dt_value = dt_value.astimezone(_local_timezone())
    return dt_value.strftime("%d/%m/%Y à %H:%M")


def derive_related_entity_id(source_entity_id: str | None, platform: str, suffix: str) -> str | None:
    """Dérive une entité associée à partir de l'identifiant de la tondeuse."""
    text = _clean_text(source_entity_id)
    if not text or "." not in text:
        return None
    _domain, object_id = text.split(".", 1)
    if not object_id:
        return None
    return f"{platform}.{object_id}_{suffix}"


def build_mower_context(
    *,
    entity_id: str | None,
    entity_name: str | None,
    raw_state: Any,
    available: bool,
    charging: bool | None = None,
    rain: bool | None = None,
    error_raw: Any = None,
    battery_percent: float | None = None,
    next_schedule_raw: Any = None,
    cutting_height_mm: float | None = None,
    resolution_state: str | None = None,
    resolution_reason: str | None = None,
    resolution_candidate_count: int | None = None,
    resolution_probe: str | None = None,
) -> dict[str, Any]:
    """Construit un contexte tondeuse standardisé depuis des entités HA hétérogènes."""

    error_code = _normalize_error_code(error_raw)
    status = _normalize_mower_status(
        raw_state,
        charging=charging,
        rain=rain,
        error_code=error_code,
        available=available,
    )
    ready = status not in _BLOCKING_STATUSES and available
    reason = None
    if status == "pluie":
        reason = "Pluie ou délai pluie actif."
    elif status == "erreur":
        # ⚠️ « error » N'EST PAS TOUJOURS UNE PANNE — mesuré le 02/09/2026 à 01:26. Le robot est
        # resté en `error` plusieurs minutes pour une MISE À JOUR de firmware (tête caméra
        # 2.5.6+7 → 2.5.7+12 à 01:28:59, sortie de l'état quatre secondes plus tard), pendant
        # que son propre capteur d'erreur affichait `no_error` DU DÉBUT À LA FIN.
        #
        # Le repli inventait alors « Erreur tondeuse. » — une panne que la machine avait
        # explicitement démentie, remontée jusqu'au libellé de blocage et donc jusqu'aux
        # notifications. Le blocage, lui, reste juste : elle ne peut pas tondre pendant ce temps.
        # On dit ce qu'on sait, on n'affirme pas ce qu'on ignore.
        reason = _human_label(error_code) or "Robot indisponible, aucun code d'erreur signalé."
    elif status == "indisponible":
        reason = "Tondeuse indisponible."
    elif status == "en_charge":
        reason = "Tondeuse en charge."
    elif status == "retour_station":
        reason = "Tondeuse en retour station."
    elif status == "tonte_en_cours":
        reason = "Tonte déjà en cours."
    elif status == "pause":
        reason = "Tonte en pause."

    payload: dict[str, Any] = {
        "tondeuse_source_entity": entity_id,
        "tondeuse_nom": entity_name,
        "tondeuse_etat_brut": _clean_text(raw_state),
        "tondeuse_statut": status,
        "tondeuse_statut_libelle": _status_label(status, raw_state),
        "tondeuse_connectee": bool(available),
        "tondeuse_prete": bool(ready),
        "tondeuse_raison": reason,
        "tondeuse_en_charge": charging,
        "tondeuse_pluie": rain,
        "tondeuse_erreur": error_code,
        "tondeuse_erreur_libelle": _human_label(error_code),
        "tondeuse_batterie": battery_percent,
        "tondeuse_prochain_depart": _clean_text(next_schedule_raw),
        "tondeuse_prochain_depart_display": _human_datetime_text(next_schedule_raw),
        "tondeuse_hauteur_coupe_mm": cutting_height_mm,
        "tondeuse_resolution_state": _clean_text(resolution_state),
        "tondeuse_resolution_reason": _clean_text(resolution_reason),
        "tondeuse_resolution_candidate_count": resolution_candidate_count,
        # ⚠️ INSTRUMENTATION — sépare « je n'ai pas pu interroger la machine d'états » de
        # « l'entité n'existe pas ». Les deux donnaient le même `configured_missing`.
        "tondeuse_resolution_probe": _clean_text(resolution_probe),
    }
    return {key: value for key, value in payload.items() if value is not None}
