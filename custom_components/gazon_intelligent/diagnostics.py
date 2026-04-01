from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_CONFIG_HISTORY_KEYS: tuple[str, ...] = (
    "zone_1",
    "zone_2",
    "zone_3",
    "zone_4",
    "zone_5",
    "debit_zone_1",
    "debit_zone_2",
    "debit_zone_3",
    "debit_zone_4",
    "debit_zone_5",
    "type_sol",
    "entite_meteo",
    "capteur_pluie_24h",
    "capteur_pluie_demain",
    "capteur_temperature",
    "capteur_etp",
    "capteur_humidite",
    "capteur_humidite_sol",
    "capteur_vent",
    "capteur_rosee",
    "capteur_hauteur_gazon",
    "capteur_retour_arrosage",
    "hauteur_min_tondeuse_cm",
    "hauteur_max_tondeuse_cm",
)

_SNAPSHOT_KEYS: tuple[str, ...] = (
    "mode",
    "phase_active",
    "phase_dominante",
    "phase_dominante_source",
    "sous_phase",
    "sous_phase_detail",
    "sous_phase_age_days",
    "sous_phase_progression",
    "objectif_mm",
    "objectif_arrosage",
    "arrosage_recommande",
    "type_arrosage",
    "arrosage_conseille",
    "niveau_action",
    "fenetre_optimale",
    "risque_gazon",
    "tonte_autorisee",
    "tonte_statut",
    "hauteur_tonte_recommandee_cm",
    "hauteur_tonte_min_cm",
    "hauteur_tonte_max_cm",
    "conseil_principal",
    "action_recommandee",
    "action_a_eviter",
    "raison_decision",
    "decision_resume",
    "water_balance",
    "phase_context",
    "advanced_context",
    "assistant",
)

_MEMORY_KEYS: tuple[str, ...] = (
    "historique_total",
    "derniere_tonte",
    "dernier_arrosage",
    "dernier_arrosage_significatif",
    "derniere_phase_active",
    "dernier_conseil",
    "derniere_action_utilisateur",
    "derniere_application",
    "feedback_observation",
    "prochaine_reapplication",
    "catalogue_produits",
    "date_derniere_mise_a_jour",
    "auto_irrigation_enabled",
)

_HISTORY_KEYS: tuple[str, ...] = (
    "date",
    "date_action",
    "type",
    "intervention",
    "action",
    "source",
    "zone",
    "zone_count",
    "passages",
    "objectif_mm",
    "total_mm",
    "mm",
    "duration_min",
    "duration_seconds",
    "plan_type",
    "state",
    "reason",
    "summary",
)


def _compact_dict(data: dict[str, Any] | None, keys: tuple[str, ...] | None = None) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    if keys is None:
        return {key: value for key, value in data.items() if value is not None}
    return {key: data[key] for key in keys if key in data and data[key] is not None}


def _compact_history_item(item: dict[str, Any]) -> dict[str, Any]:
    return _compact_dict(item, _HISTORY_KEYS)


def _build_history_tail(history: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    if not isinstance(history, list) or not history:
        return []
    tail = history[-limit:]
    compacted: list[dict[str, Any]] = []
    for item in tail:
        if isinstance(item, dict):
            compacted.append(_compact_history_item(item))
    return compacted


def _select_snapshot(coordinator: Any) -> dict[str, Any]:
    snapshot = getattr(coordinator, "data", None)
    if isinstance(snapshot, dict) and snapshot:
        return snapshot
    last_result = getattr(coordinator, "last_result", None)
    if last_result is not None and hasattr(last_result, "to_snapshot"):
        try:
            result_snapshot = last_result.to_snapshot()
        except Exception:
            return {}
        if isinstance(result_snapshot, dict):
            return result_snapshot
    return {}


def _build_runtime_summary(coordinator: Any, snapshot: dict[str, Any]) -> dict[str, Any]:
    memory = getattr(coordinator, "memory", None)
    if not isinstance(memory, dict):
        memory = {}
    return {
        "loaded": bool(getattr(coordinator, "_loaded", False)),
        "mode": snapshot.get("mode"),
        "date_action": snapshot.get("date_action"),
        "auto_irrigation_enabled": bool(getattr(coordinator, "auto_irrigation_enabled", False)),
        "history_count": len(getattr(coordinator, "history", []) or []),
        "products_count": len(getattr(coordinator, "products", {}) or {}),
        "soil_balance": _compact_dict(getattr(coordinator, "soil_balance", {})),
        "memory": _compact_dict(memory, _MEMORY_KEYS),
    }


def _build_snapshot_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    return _compact_dict(snapshot, _SNAPSHOT_KEYS)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Retourne un diagnostic local de l'intégration Gazon Intelligent."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id) if hasattr(hass, "data") else None
    snapshot = _select_snapshot(coordinator) if coordinator is not None else {}

    return {
        "config_entry": {
            "entry_id": entry.entry_id,
            "title": getattr(entry, "title", ""),
            "version": getattr(entry, "version", None),
            "data": _compact_dict(getattr(entry, "data", {})),
            "options": _compact_dict(getattr(entry, "options", {})),
        },
        "runtime": _build_runtime_summary(coordinator, snapshot) if coordinator is not None else {},
        "decision": _build_snapshot_summary(snapshot),
        "history_tail": _build_history_tail(getattr(coordinator, "history", []) or []) if coordinator is not None else [],
    }
