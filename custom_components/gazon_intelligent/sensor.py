from __future__ import annotations

from datetime import date, datetime
import re
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.helpers.entity import EntityCategory
from homeassistant.util import dt as dt_util

from .assistant import build_assistant_decision
from .const import (
    APPLICATION_INTERVENTIONS,
    BLOCK_REASON_DISPLAY_LABELS,
    DOMAIN,
    PLUIE_SOURCE_INDISPONIBLE,
    PLUIE_SOURCE_NON_DISPONIBLE,
)
from .decision_models import TYPE_ARROSAGE_DISPLAY_LABELS
from .entity_base import GazonEntityBase
from .entity_ids import public_entity_id, resolve_entry_instance_slug
from .intervention_recommendation import build_intervention_recommendation, public_intervention_ui
from .memory import build_application_summary, compute_application_state, normalize_post_application_status
from .watering_plan import build_watering_plan
from .water import (
    _is_technical_watering,
    _zone_session_surface_mm,
    _zone_session_total_mm,
    compute_live_session_water,
)


def _session_surface_mm(session: dict[str, Any]) -> float | None:
    """Surface réelle (mm) d'une session d'arrosage.

    Privilégie la valeur canonique de l'intégration (`session_total_mm`/`total_mm` = surface
    uniforme déjà calculée). Recalculer depuis la liste `zones` est FAUX pour un cycle piloté
    multi-passages (N zones × M passages : la moyenne divise par N×M au lieu de N → « dernier
    arrosage » sous-évalué, ex. 1,7 mm au lieu de 5). On ne recalcule depuis les zones qu'en
    dernier recours (sessions sans total canonique).
    """
    if not isinstance(session, dict):
        return None
    for key in ("session_total_mm", "total_mm", "objectif_mm", "objective_mm"):
        value = session.get(key)
        try:
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            continue
    zones = session.get("zones")
    return _zone_session_surface_mm(zones if isinstance(zones, list) else None)

RECOMMENDATION_RUNTIME_PROBE = "constraints_probe_20260404_01"
_APPLICATION_SUMMARY_PUBLIC_KEYS = (
    "produit_id",
    "libelle",
    "type",
    "date",
    "date_action",
    "declared_at",
    "produit",
    "dose",
    "note",
    "reapplication_after_days",
    "source",
)
_APPLICATION_PUBLIC_ATTR_KEYS = (
    "application_type",
    "application_requires_watering_after",
    "application_post_watering_mm",
    "application_irrigation_mode",
    "application_post_watering_status",
)
# ⚠️ HOMONYME VOLONTAIREMENT DIFFÉRENT de `binary_sensor._APPLICATION_STATUS_ATTR_KEYS`, qui
# porte en plus `auto_irrigation_enabled`. Ici cette clé est exposée par un AUTRE chemin
# (cf. la liste d'attributs plus bas), l'ajouter ici la publierait deux fois. Ne pas
# « harmoniser par symétrie » : deux constantes de même nom au contenu différent sont un
# piège, et c'est justement pour ça que l'écart est noté des deux côtés.
_APPLICATION_STATUS_ATTR_KEYS = (
    "application_block_active",
    "application_block_remaining_minutes",
    "application_post_watering_pending",
    "application_post_watering_delay_remaining_minutes",
    "application_post_watering_ready",
    "application_post_watering_remaining_mm",
)
_GENERIC_NOOP_ACTION_LABELS = {
    "réévalue au prochain cycle météo.",
    "réévalue au prochain cycle meteo.",
    "reevalue au prochain cycle meteo.",
    "n'arrose pas pour le moment.",
    "narrose pas pour le moment.",
}


def _coordinator_snapshot(coordinator) -> dict[str, Any]:
    snapshot = getattr(coordinator, "data", None)
    return snapshot if isinstance(snapshot, dict) else {}


def _coordinator_used_entities_attributes(coordinator) -> dict[str, Any]:
    getter = getattr(coordinator, "get_used_entities_attributes", None)
    if not callable(getter):
        return {}
    attrs = getter()
    return attrs if isinstance(attrs, dict) else {}


def _entry_coordinator(hass, entry):
    data = getattr(hass, "data", None)
    if not isinstance(data, dict):
        return None
    domain_data = data.get(DOMAIN)
    if not isinstance(domain_data, dict):
        return None
    return domain_data.get(entry.entry_id)


def _clean_public_attrs(attrs: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(attrs, dict):
        return None
    clean = {
        key: value
        for key, value in attrs.items()
        if value not in (None, "", [], {})
    }
    return clean or None


# États Home Assistant qui signifient « pas de donnée » : ils ne doivent jamais ressortir tels
# quels d'un formateur d'affichage (l'utilisateur lirait « unavailable » à la place d'une date).
# Filtrés en amont côté coordinateur ; conservé ici pour les valeurs venant d'un état restauré
# ou d'un attribut, qui ne passent pas par ce chemin.
_UNAVAILABLE_TEXTS: frozenset[str] = frozenset({"unavailable", "unknown"})


def _is_unavailable_text(value: object) -> bool:
    return isinstance(value, str) and value.strip().lower() in _UNAVAILABLE_TEXTS


def _human_datetime_text(value: object) -> str | None:
    if value in (None, "", [], {}) or _is_unavailable_text(value):
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            try:
                return date.fromisoformat(text[:10]).strftime("%d/%m/%Y")
            except ValueError:
                return text
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            local_tz = dt_util.now().tzinfo
            if local_tz is not None:
                dt = dt.replace(tzinfo=local_tz)
        local_tz = dt_util.now().tzinfo
        if local_tz is not None:
            return dt.astimezone(local_tz).strftime("%d/%m/%Y à %H:%M")
        return dt.strftime("%d/%m/%Y à %H:%M")
    return None


def _human_date_text(value: object) -> str | None:
    if value in (None, "", [], {}) or _is_unavailable_text(value):
        return None
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return date.fromisoformat(text[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return text


def _assistant_action_fallback(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict) or not payload:
        return None
    action = str(payload.get("action") or "none").strip().lower()
    status = str(payload.get("status") or "no_need").strip().lower()
    reason = str(payload.get("reason") or "").strip().casefold()
    if action in {"none", "", "aucune_action"}:
        if status == "blocked_due_to_conditions":
            if reason:
                return f"Arrosage bloqué par conditions: {str(payload.get('reason') or '').strip()}."
            return "Arrosage bloqué par conditions."
        return None
    if action == "tonte":
        if status == "blocked":
            if "battery low" in reason or "batterie faible" in reason:
                return "Tonte différée: batterie faible."
            if "nocturne" in reason or "nuit" in reason or "lever du soleil" in reason:
                return "Tonte différée: nuit en cours."
            if "en cours" in reason or "cours de tonte" in reason:
                return "Tonte en cours."
            if "en retour" in reason:
                return "Tondeuse en retour station."
        return "Attends avant de tondre." if status == "blocked" else "Tonte possible maintenant."
    if action == "traitement":
        return "Attends avant le traitement." if status == "blocked" else "Traite maintenant."
    if action == "arrosage":
        return "Attends avant d'arroser." if status == "blocked" else "Arrosage à faire."
    return None


def _public_mowing_facade(entity: GazonEntityBase) -> dict[str, Any]:
    facade = entity._public_mowing_facade()
    if facade:
        return facade
    snapshot = _coordinator_snapshot(entity.coordinator)
    return {
        key: snapshot.get(key)
        for key in (
            "tonte_autorisee",
            "tonte_statut",
            "niveau_action",
            "action_possible",
            "mowing_blocked",
            "next_mowing_date",
            "next_mowing_display",
            "raison_blocage_tonte",
            "raison_blocage_code",
            "mowing_block_reason_code",
            "mowing_block_reason_label",
            "mowing_window_reason",
            "mowing_machine_unavailable_detail",
            "mowing_machine_unavailable_label",
            "assistant",
        )
        if snapshot.get(key) is not None
    }


def _is_generic_noop_action_label(value: object | None) -> bool:
    text = str(value or "").strip().casefold()
    return text in _GENERIC_NOOP_ACTION_LABELS


def _public_action_recommandee(entity: GazonEntityBase) -> str | None:
    action = entity._decision_value("action_recommandee")
    action_text = str(action).strip() if action not in (None, [], {}) else ""
    action_text = _aligned_public_watering_action_text(entity, action_text)
    snapshot = _coordinator_snapshot(entity.coordinator)
    blocked_due_to_conditions = _irrigation_blocked_due_to_conditions_summary(entity)
    if blocked_due_to_conditions:
        return blocked_due_to_conditions
    assistant_payload = entity._decision_value("assistant")
    if not isinstance(assistant_payload, dict) and snapshot:
        assistant_payload = build_assistant_decision(snapshot)
    assistant_fallback = _assistant_action_fallback(assistant_payload)
    if (not action_text or _is_generic_noop_action_label(action_text)) and assistant_fallback:
        return assistant_fallback
    return action_text or None


def _int_public_value(entity: GazonEntityBase, key: str, default: int, minimum: int = 0) -> int:
    raw_value = entity._decision_value(key)
    try:
        if raw_value is not None:
            return max(minimum, int(raw_value))
    except (TypeError, ValueError):
        pass
    snapshot = _coordinator_snapshot(entity.coordinator)
    try:
        raw_value = snapshot.get(key)
        if raw_value is not None:
            return max(minimum, int(raw_value))
    except (TypeError, ValueError):
        pass
    return default


def _build_public_watering_action_text(entity: GazonEntityBase, passages: int, pause_minutes: int) -> str | None:
    objective_mm = _objective_mm_value(entity)
    if objective_mm <= 0.0:
        return None
    type_arrosage = _normalized_public_type_arrosage(entity)
    if passages > 1:
        pause_text = f" avec {pause_minutes} min de pause" if pause_minutes > 0 else ""
        return f"Applique {objective_mm:.1f} mm en {passages} passages{pause_text}."
    if type_arrosage == "auto":
        return f"Applique {objective_mm:.1f} mm en arrosage automatique."
    if type_arrosage == "manuel":
        return f"Applique {objective_mm:.1f} mm manuellement."
    return f"Applique {objective_mm:.1f} mm."


def _aligned_public_watering_action_text(entity: GazonEntityBase, action_text: str) -> str:
    if not action_text or not bool(entity._decision_value("arrosage_recommande", False)):
        return action_text
    passages = _int_public_value(entity, "watering_passages", default=1, minimum=1)
    pause_minutes = _int_public_value(entity, "watering_pause_minutes", default=0, minimum=0)
    normalized = action_text.casefold()
    explicit_passages_match = re.search(r"(\d+)\s+passages?", normalized)
    explicit_passages = int(explicit_passages_match.group(1)) if explicit_passages_match else None

    if explicit_passages is not None and explicit_passages != passages:
        return _build_public_watering_action_text(entity, passages, pause_minutes) or action_text
    if passages <= 1 and "passage" in normalized:
        return _build_public_watering_action_text(entity, passages, pause_minutes) or action_text
    return action_text


def _assistant_public_summary(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict) or not payload:
        return None
    action = str(payload.get("action") or "none").strip().lower()
    status = str(payload.get("status") or "no_need").strip().lower()
    reason = str(payload.get("reason") or "").strip().casefold()
    if action in {"none", "", "aucune_action"}:
        if status == "blocked_due_to_conditions":
            reason_text = str(payload.get("reason") or "").strip()
            if reason_text:
                return f"Arrosage bloqué par conditions: {reason_text}."
            return "Arrosage bloqué par conditions."
        return None
    if action == "tonte":
        if status == "blocked":
            if "nocturne" in reason or "nuit" in reason or "lever du soleil" in reason:
                return "Tonte différée: nuit en cours."
            if "en cours" in reason or "cours de tonte" in reason:
                return "Tonte en cours."
            if "en retour" in reason:
                return "Tondeuse en retour station."
            if "battery low" in reason or "batterie faible" in reason:
                return "Tonte différée: batterie faible."
            return "Tonte à différer."
        return "Tonte possible maintenant." if status != "blocked" else "Tonte à différer."
    if action == "traitement":
        return "Traitement à faire maintenant." if status != "blocked" else "Traitement bloqué pour le moment."
    if action == "arrosage":
        return None
    return None


def _irrigation_blocked_due_to_conditions_summary(entity: GazonEntityBase) -> str | None:
    assistant_payload = _assistant_payload_for_public(entity)
    if isinstance(assistant_payload, dict) and assistant_payload:
        status = str(assistant_payload.get("status") or "").strip().lower()
        if status == "blocked_due_to_conditions":
            reason_text = str(assistant_payload.get("reason") or "").strip()
            if reason_text:
                return f"Arrosage bloqué par conditions: {reason_text}."
            return "Arrosage bloqué par conditions."

    objective = _objective_mm_value(entity)
    if objective > 0.0 or bool(entity._decision_value("arrosage_recommande", False)):
        return None

    type_arrosage = _normalized_public_type_arrosage(entity)
    block_reason = str(entity._decision_value("block_reason") or "").strip()
    post_status = normalize_post_application_status(entity._decision_value("application_post_watering_status"))
    if type_arrosage == "bloque" or block_reason or post_status == "bloque":
        block_label = _block_reason_display_label(block_reason) or block_reason
        if block_label:
            return f"Arrosage bloqué par conditions: {block_label}."
        return "Arrosage bloqué par conditions."
    return None


def _assistant_payload_for_public(entity: GazonEntityBase) -> dict[str, Any] | None:
    facade = _public_mowing_facade(entity)
    assistant_payload = facade.get("assistant")
    if not isinstance(assistant_payload, dict) or not assistant_payload:
        assistant_payload = entity._decision_value("assistant")
    snapshot = _coordinator_snapshot(entity.coordinator)
    if not isinstance(assistant_payload, dict) and snapshot:
        assistant_payload = build_assistant_decision(snapshot)
    if not isinstance(assistant_payload, dict) or not assistant_payload:
        return None
    action = str(assistant_payload.get("action") or "none").strip().lower()
    if action in {"none", "", "aucune_action"}:
        return None
    return assistant_payload


def _intervention_public_summary(entity: GazonEntityBase) -> str | None:
    payload = entity._decision_value("intervention_recommendation")
    if not isinstance(payload, dict) or not payload:
        return None
    ui = public_intervention_ui(payload)
    status = str(payload.get("status") or "").strip().lower()
    ready_to_declare = bool(payload.get("ready_to_declare"))
    summary = str(ui.get("summary") or "").strip()
    if ready_to_declare:
        return f"{summary}." if summary else "Intervention prête à déclarer."
    if status == "recommended":
        return f"{summary}." if summary else "Intervention recommandée."
    if status == "preparation":
        return f"{summary}." if summary else "Intervention à préparer."
    if status == "blocked":
        return f"{summary}." if summary else "Intervention bloquée."
    return None


def _watering_public_summary(entity: GazonEntityBase) -> str | None:
    blocked_due_to_conditions = _irrigation_blocked_due_to_conditions_summary(entity)
    if blocked_due_to_conditions:
        return blocked_due_to_conditions
    watering_cause = _watering_cause_value(entity)
    if bool(entity._decision_value("arrosage_recommande", False)):
        conseil = entity._decision_value("conseil_principal")
        if conseil not in (None, "", [], {}):
            return str(conseil).strip() or None
        return "Arrosage post-produit à prévoir." if watering_cause == "post_application" else "Arrosage à prévoir."
    post_status = normalize_post_application_status(entity._decision_value("application_post_watering_status"))
    if post_status == "autorise":
        return "Arrosage post-produit autorisé."
    if post_status in {"bloque", "en_attente", "non_autorise"}:
        return "Arrosage post-produit en attente." if post_status == "en_attente" else "Arrosage post-produit bloqué."
    return "Pas d'arrosage nécessaire."


def _public_conseil_principal(entity: GazonEntityBase) -> str | None:
    # Le conseil principal reste une vue globale priorisée; il peut donc refléter l'événement dominant du moment.
    assistant_payload = _assistant_payload_for_public(entity)

    raw_conseil = entity._decision_value("conseil_principal")
    raw_text = str(raw_conseil).strip() if raw_conseil not in (None, [], {}) else ""
    blocked_due_to_conditions = _irrigation_blocked_due_to_conditions_summary(entity)
    intervention_text = _intervention_public_summary(entity)
    watering_text = _watering_public_summary(entity)
    intervention_payload = entity._decision_value("intervention_recommendation")
    intervention_status = ""
    intervention_ready = False
    if isinstance(intervention_payload, dict) and intervention_payload:
        intervention_status = str(intervention_payload.get("status") or "").strip().lower()
        intervention_ready = bool(intervention_payload.get("ready_to_declare"))
    mowing_block_reason_code = str(
        entity._decision_value("raison_blocage_code")
        or entity._decision_value("mowing_block_reason_code")
        or ""
    ).strip().lower()
    mowing_block_reason_label = str(
        entity._decision_value("mowing_block_reason_label")
        or entity._decision_value("raison_blocage_tonte")
        or ""
    ).strip()
    next_mowing_display = str(
        entity._decision_value("next_mowing_display")
        or entity._decision_value("next_mowing_date")
        or ""
    ).strip()

    if mowing_block_reason_code in {"phase_sursemis", "phase_traitement", "phase_hivernage"}:
        if mowing_block_reason_label:
            return mowing_block_reason_label
        if next_mowing_display:
            return f"Tonte à reconsidérer le {next_mowing_display}."
        return "Tonte à différer."

    if blocked_due_to_conditions:
        return blocked_due_to_conditions
    if intervention_ready or intervention_status == "recommended":
        return intervention_text or raw_text or watering_text or None
    assistant_text = _assistant_public_summary(assistant_payload)
    if assistant_text:
        return assistant_text
    if raw_text and not _is_generic_noop_action_label(entity._decision_value("action_recommandee")):
        return raw_text
    if intervention_status == "preparation":
        return intervention_text or raw_text or watering_text or None
    return raw_text or watering_text or intervention_text or None


def _normalize_recommendation_constraints_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or not payload:
        return payload

    normalized = dict(payload)
    changed = False

    status = str(normalized.get("status") or "").strip().lower()
    if status == "possible":
        normalized["status"] = "preparation"
        changed = True

    ui = normalized.get("ui")
    if isinstance(ui, dict):
        ui_normalized = dict(ui)
        if status == "possible":
            if str(ui_normalized.get("title") or "").strip().lower() in {"possible", ""}:
                ui_normalized["title"] = "À préparer"
            if str(ui_normalized.get("badge") or "").strip().lower() in {"possible", ""}:
                ui_normalized["badge"] = "À préparer"
            changed = True
        normalized["ui"] = ui_normalized

    context = normalized.get("context")
    if not isinstance(context, dict):
        return normalized if changed else payload

    current_phase = context.get("current_phase")
    current_month = context.get("current_month")
    if current_phase is None and current_month is None:
        return normalized if changed else payload

    constraints = normalized.get("constraints")
    if not isinstance(constraints, list):
        return normalized if changed else payload

    normalized_constraints: list[dict[str, Any] | object] = []
    for constraint in constraints:
        if not isinstance(constraint, dict):
            normalized_constraints.append(constraint)
            continue

        item = dict(constraint)
        value = item.get("value")
        if isinstance(value, dict):
            value = dict(value)
            if item.get("code") == "phase_compatibility" and current_phase is not None and value.get("current") is None:
                value["current"] = current_phase
                changed = True
            if item.get("code") == "application_months" and current_month is not None and value.get("current_month") is None:
                value["current_month"] = current_month
                changed = True
            item["value"] = value
        normalized_constraints.append(item)

    if not changed:
        return payload

    normalized["constraints"] = normalized_constraints
    return normalized


def _mowing_visibility_flags(entity: GazonEntityBase) -> dict[str, bool]:
    gazon_permet_tonte = bool(entity._public_mowing_value("tonte_autorisee", entity._decision_value("tonte_autorisee", False)))
    mower_coordination_enabled = entity._decision_value("mower_coordination_enabled", True)
    mower_coordination_ready = entity._decision_value("mower_coordination_ready", True)
    machine_permet_tonte = (
        bool(entity._decision_value("tondeuse_prete", False))
        and mower_coordination_enabled is not False
        and mower_coordination_ready is not False
    )
    mowing_blocked = bool(entity._public_mowing_value("mowing_blocked", entity._decision_value("mowing_blocked", False)))
    return {
        "gazon_permet_tonte": gazon_permet_tonte,
        "machine_permet_tonte": machine_permet_tonte,
        "mowing_blocked": mowing_blocked,
        "action_possible": gazon_permet_tonte and machine_permet_tonte and not mowing_blocked,
    }


def _public_source_entity(entity: GazonEntityBase, platform: str, suffix: str) -> str:
    return public_entity_id(platform, suffix, instance_slug=entity.instance_slug)


def _normalized_public_type_arrosage(entity: GazonEntityBase, raw_value: object | None = None) -> str:
    raw_type = str(raw_value if raw_value is not None else entity._decision_value("type_arrosage") or "").strip().lower()
    if raw_type != "personnalise":
        return raw_type
    objectif_mm = entity._decision_value("objectif_mm", 0.0)
    try:
        objectif_mm = float(objectif_mm or 0.0)
    except (TypeError, ValueError):
        objectif_mm = 0.0
    decision_resume = entity._decision_value("decision_resume")
    if (
        objectif_mm <= 0.0
        and isinstance(decision_resume, dict)
        and str(decision_resume.get("action") or "").strip() in {"aucune_action", "none"}
    ):
        return "aucune_action"
    return raw_type


def _watering_cause_value(entity: GazonEntityBase, raw_value: object | None = None) -> str:
    raw_cause = str(raw_value if raw_value is not None else entity._decision_value("watering_cause") or "").strip().lower()
    if raw_cause in {"hydrique", "post_application"}:
        return raw_cause
    post_status = normalize_post_application_status(entity._decision_value("application_post_watering_status"))
    raw_type = _normalized_public_type_arrosage(entity)
    if post_status in {"bloque", "en_attente", "autorise"}:
        return "post_application"
    if raw_type in {"application_technique", "application_technique_auto"}:
        return "post_application"
    return "hydrique"


def _hydric_balance_level(balance_mm: float | None, deficit_3j: float | None, deficit_7j: float | None) -> str | None:
    """Niveau hydrique affiché, dérivé du SEUL bilan signé.

    `balance_mm` est un bilan SIGNÉ (0 = au seuil MAD, négatif = déficit), normalisé par
    `_objective_display_balance` (réserve recentrée sur le seuil d'épuisement). Il porte à lui
    seul l'information : ne PAS lui passer la réserve brute (≥ 0), les branches négatives
    redeviendraient inertes.

    ⚠️ VETO PAR CUMUL RETIRÉ le 29/07/2026 (arbitrage de Kévin), NE PAS LE REMETTRE.
    Les quatre seuils sont à l'échelle d'un déficit JOURNALIER, mais `deficit_3j` / `deficit_7j`
    sont des CUMULS (12 à 42 mm en pleine saison) : le veto était donc toujours armé.
    Mesuré sur une grille ET0 2-7 mm/j : **2 niveaux sur 5 seulement** étaient atteignables —
    « excédentaire », « équilibré » ET « léger déficit » étaient hors d'atteinte, et un gazon
    au bilan +5 mm s'affichait « déficit ». L'attribut ne portait plus aucune information.

    Deux correctifs partiels ont été mesurés puis écartés :
    - normaliser les cumuls en taux journalier SEUL → régresse le correctif 0.16.0
      (cf. test_objectif_sensor_fort_deficit_atteignable_via_recentrage_mad, qui retombe
      sur « déficit ») ;
    - normaliser ET aligner la dernière branche sur `and` → 4 niveaux sur 5, mais le cas qui
      motivait le correctif (gazon en forme) affichait encore « déficit ».

    Les paramètres `deficit_3j` / `deficit_7j` sont conservés dans la signature : les appelants
    les passent encore, et les garder documente explicitement qu'ils sont ignorés ici.
    """
    if balance_mm is None and deficit_3j is None and deficit_7j is None:
        return None
    balance_mm = float(balance_mm or 0.0)
    if balance_mm >= 2.0:
        return "excédentaire"
    if balance_mm >= 0.5:
        return "équilibré"
    if balance_mm >= -0.5:
        return "léger déficit"
    if balance_mm >= -2.0:
        return "déficit"
    return "fort déficit"


def _hydric_strategy(balance_mm: float | None, deficit_3j: float | None, deficit_7j: float | None) -> str | None:
    level = _hydric_balance_level(balance_mm, deficit_3j, deficit_7j)
    if level is None:
        return None
    if level == "excédentaire":
        return "reporter"
    if level == "équilibré":
        return "surveiller"
    if level == "léger déficit":
        return "attendre ou regrouper"
    if level == "déficit":
        return "arroser profondément"
    return "arroser rapidement en profondeur"


def _objective_mm_value(entity: GazonEntityBase) -> float:
    try:
        return float(entity._decision_value("objectif_mm", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _phase_support_phase(entity: GazonEntityBase) -> str | None:
    phase = str(
        entity._decision_value("phase_dominante")
        or entity._decision_value("phase_active")
        or ""
    ).strip()
    if phase in APPLICATION_INTERVENTIONS:
        return phase
    return None


def _is_phase_support_irrigation_context(entity: GazonEntityBase, attrs: dict[str, Any] | None = None) -> bool:
    if _objective_mm_value(entity) <= 0.0 or not bool(entity._decision_value("arrosage_recommande", False)):
        return False
    if _phase_support_phase(entity) is None:
        return False

    attrs = attrs or {}
    hydric_state = str(attrs.get("hydric_state") or entity._decision_value("hydric_state") or "").strip().lower()
    if hydric_state in {"plein", "confort"}:
        return True

    for key, threshold in (("depletion_ratio", 0.10), ("reserve_available_ratio", 0.95)):
        raw_value = attrs.get(key, entity._decision_value(key))
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        if key == "depletion_ratio" and value <= threshold:
            return True
        if key == "reserve_available_ratio" and value >= threshold:
            return True
    return False


def _niveau_action_hydrique(entity: GazonEntityBase) -> str:
    post_status = normalize_post_application_status(entity._decision_value("application_post_watering_status"))
    hydric_actionable = bool(entity._decision_value("arrosage_recommande", False)) or post_status == "autorise"
    global_level = str(entity._decision_value("niveau_action") or "").strip().lower()
    objective_mm = _objective_mm_value(entity)

    if hydric_actionable:
        return "critique" if global_level == "critique" else "a_faire"
    if objective_mm > 0.0 or post_status in {"bloque", "en_attente"}:
        return "surveiller"
    return "aucune_action"


def _normalized_public_niveau_action(entity: GazonEntityBase) -> str:
    facade = _public_mowing_facade(entity)
    niveau_action = str(
        facade.get("niveau_action")
        or entity._decision_value("niveau_action")
        or ""
    ).strip().lower()
    if niveau_action not in {"aucune_action", "surveiller", "a_faire", "critique"}:
        niveau_action = "aucune_action"

    decision_resume = entity._decision_value("decision_resume")
    objectif_mm = _objective_mm_value(entity)
    assistant_payload = _assistant_payload_for_public(entity)

    if (
        niveau_action == "surveiller"
        and objectif_mm <= 0.0
        and isinstance(decision_resume, dict)
        and str(decision_resume.get("action") or "").strip() in {"aucune_action", "none"}
        and not assistant_payload
    ):
        niveau_action = "aucune_action"

    if not assistant_payload:
        return niveau_action

    action = str(assistant_payload.get("action") or "none").strip().lower()
    status = str(assistant_payload.get("status") or "no_need").strip().lower()

    if action in {"none", "", "aucune_action", "arrosage"}:
        return niveau_action

    if status == "action_required":
        return "critique" if niveau_action == "critique" else "a_faire"
    if status == "blocked" and niveau_action == "aucune_action":
        return "surveiller"
    return niveau_action


def _is_passive_irrigation_context(entity: GazonEntityBase) -> bool:
    post_status = normalize_post_application_status(entity._decision_value("application_post_watering_status"))
    return (
        _objective_mm_value(entity) <= 0.0
        and not bool(entity._decision_value("arrosage_recommande", False))
        and post_status in {"indisponible", "non_requis", "termine"}
    )


def _hydric_state_from_depletion_ratio(value: Any) -> str | None:
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        return None
    if ratio <= 0.10:
        return "plein"
    if ratio <= 0.45:
        return "confort"
    if ratio <= 0.75:
        return "depletion"
    return "critique"


def _hydric_state_from_reserve_ratio(current: Any, useful: Any) -> str | None:
    try:
        current_value = float(current)
        useful_value = float(useful)
    except (TypeError, ValueError):
        return None
    if useful_value <= 0.0:
        return None
    fill_ratio = max(0.0, min(1.0, current_value / useful_value))
    if fill_ratio >= 0.90:
        return "plein"
    if fill_ratio >= 0.55:
        return "confort"
    if fill_ratio >= 0.25:
        return "depletion"
    return "critique"


def _hydric_state_for_objective_sensor(entity: GazonEntityBase, attrs: dict[str, Any]) -> str | None:
    hydric_state = _hydric_state_from_depletion_ratio(attrs.get("depletion_ratio"))
    if hydric_state is not None:
        return hydric_state

    hydric_state = _hydric_state_from_reserve_ratio(
        attrs.get("reserve_actuelle_mm"),
        attrs.get("reserve_utile_mm"),
    )
    if hydric_state is not None:
        return hydric_state

    if _objective_mm_value(entity) > 0.0 or bool(entity._decision_value("arrosage_recommande", False)):
        return None

    try:
        # Valeur d'un instantané hétérogène : le `except` couvre l'absence comme le non-numérique.
        legacy_reserve = float(attrs.get("reserve_hydrique_sol_mm"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return "plein" if legacy_reserve > 0.0 else None


def _harmonized_hydric_labels(
    entity: GazonEntityBase,
    objective_mm: float,
    hydric_state: str | None,
    hydric_balance_level: str | None,
    hydric_strategy: str | None,
    attrs: dict[str, Any] | None = None,
) -> tuple[str | None, str | None]:
    if _is_phase_support_irrigation_context(entity, attrs):
        return "équilibré", "maintenir le niveau hydrique"
    if objective_mm > 0.0:
        return hydric_balance_level, hydric_strategy
    if hydric_state == "plein":
        return "excédentaire", "reporter"
    if hydric_state == "confort":
        return "équilibré", "surveiller"
    return hydric_balance_level, hydric_strategy


def _objective_display_balance(attrs: dict[str, Any]) -> float | None:
    # Bilan SIGNÉ pour classer le niveau hydrique (`_hydric_balance_level`, seuils signés : 0 = à la
    # cible, négatif = déficit). La réserve sol brute est TOUJOURS ≥ 0 ; on la recentre sur le seuil
    # d'épuisement MAD (`reserve_minimale_mm`, sous lequel l'arrosage se déclenche) → réserve au seuil
    # = 0 (limite), au-dessus = positif, en-dessous = négatif. Ainsi tous les niveaux (dont « fort
    # déficit ») redeviennent atteignables ET cohérents avec le déclencheur d'arrosage — sinon une
    # réserve pile au seuil pouvait s'afficher « excédentaire ». Replis : bilan journalier signé quand
    # la réserve est absente (ledger vide) ; réserve brute si le seuil MAD manque (tout premier cycle).
    reserve = attrs.get("reserve_hydrique_sol_mm")
    if reserve not in (None, "", [], {}):
        try:
            reserve_val = float(reserve)
        except (TypeError, ValueError):
            reserve_val = None
        if reserve_val is not None:
            seuil = attrs.get("reserve_minimale_mm")
            try:
                seuil_val = float(seuil) if seuil not in (None, "", [], {}) else None
            except (TypeError, ValueError):
                seuil_val = None
            return reserve_val - seuil_val if seuil_val is not None else reserve_val
    reference = attrs.get("bilan_hydrique_mm")
    try:
        return float(reference) if reference is not None else None
    except (TypeError, ValueError):
        return None


def _score_level_and_tone(score: Any) -> tuple[str | None, str]:
    try:
        value = float(score)
    except (TypeError, ValueError):
        return None, "neutral"
    if value <= 30.0:
        return "faible", "neutral"
    if value <= 70.0:
        return "moyen", "warning"
    return "élevé", "success"


def _score_level_summary_label(level: str | None) -> str | None:
    if level == "moyen":
        return "moyenne"
    if level == "élevé":
        return "élevée"
    return level


def _window_display_label(value: object) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    labels = {
        "maintenant": "Maintenant",
        "ce_matin": "Ce matin",
        "demain_matin": "Demain matin",
        "apres_pluie": "Après la pluie",
        "soir": "Soir",
        "attendre": "Attendre",
    }
    return labels.get(normalized, normalized.replace("_", " "))


def _block_reason_display_label(value: object) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    return BLOCK_REASON_DISPLAY_LABELS.get(normalized, normalized.replace("_", " "))


# Libellé d'affichage HONNÊTE du niveau de stress. La clé interne `heat_stress_level` est un score
# COMPOSITE de stress hydrique (temp + ET0 + humidité + vent + pluie + déficit), pas une mesure de
# canicule — d'où des libellés « stress hydrique » plutôt que « canicule » pour l'affichage. Clé
# interne inchangée (utilisée dans la logique). Seul mapping d'affichage, pas de doublon d'état.
_HEAT_STRESS_DISPLAY_LABELS: dict[str, str] = {
    "normal": "Normal",
    "vigilance": "Vigilance",
    "eleve": "Stress hydrique élevé",
    "severe": "Stress hydrique sévère",
}


def _heat_stress_display_label(value: object) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    return _HEAT_STRESS_DISPLAY_LABELS.get(normalized)


def _fallback_machine_unavailable_label_from_attrs(attrs: dict[str, Any]) -> str | None:
    operation_state = str(attrs.get("mower_operation_state") or attrs.get("tondeuse_statut") or "").strip().lower()
    operation_label = str(attrs.get("mower_operation_label") or attrs.get("tondeuse_statut_libelle") or "").strip()
    reason_code = str(attrs.get("mower_reason_code") or "").strip().lower()
    error_code = str(
        attrs.get("tondeuse_erreur") or attrs.get("mower_error") or attrs.get("tondeuse_erreur_code") or ""
    ).strip().lower()
    has_error_code = error_code not in {"", "no_error", "no error", "none", "ok", "aucune", "aucune_erreur", "aucune erreur"}
    if operation_state in {"error", "erreur"} or reason_code == "error" or has_error_code:
        message = (
            str(attrs.get("mower_reason_label") or "").strip()
            or str(attrs.get("tondeuse_erreur_libelle") or "").strip()
            or "défaut signalé, vérifier le robot"
        )
        return f"Robot en erreur: {message}"
    if operation_state in {"mowing", "tonte", "tonte_en_cours", "edgecut"} or reason_code == "mower_mowing":
        return "Robot déjà en tonte: attendre la fin du cycle en cours."
    if operation_state in {"returning", "going_home", "homing", "retour_station"} or reason_code == "mower_returning":
        return "Robot en retour station: attendre qu'elle soit prête."
    if operation_state in {"charging", "en_charge"}:
        return "Robot en charge: attendre qu'elle soit prête."
    if reason_code == "mower_starting":
        return "Robot en démarrage: attendre qu'elle soit prête."
    if reason_code == "mower_zoning":
        return "Robot en changement de zone: attendre qu'elle soit prête."
    if reason_code == "mower_searching_zone":
        return "Robot en recherche de zone: attendre qu'elle soit prête."
    if operation_label:
        return f"Robot {operation_label[0].lower()}{operation_label[1:]}."
    return None


def _apply_public_mower_aliases(attrs: dict[str, Any]) -> dict[str, Any]:
    tondeuse_erreur = attrs.get("tondeuse_erreur")
    if tondeuse_erreur not in (None, "", [], {}):
        attrs.setdefault("tondeuse_erreur_code", tondeuse_erreur)
        attrs.setdefault("mower_error", tondeuse_erreur)
    mower_operation_state = attrs.get("mower_operation_state")
    if mower_operation_state not in (None, "", [], {}):
        attrs.setdefault("mower_activity_code", mower_operation_state)
    return attrs


def _minute_range_display(start_minute: Any, end_minute: Any) -> str | None:
    # `Any` et non `object` : ces minutes sortent de snapshots hétérogènes et sont
    # converties en interne. `object` obligeait chaque appelant à re-typer.
    try:
        start = int(start_minute)
        end = int(end_minute)
    except (TypeError, ValueError):
        return None
    if start < 0 or end < 0:
        return None

    def _fmt(value: int) -> str:
        hours = value // 60
        minutes = value % 60
        return f"{hours:02d}:{minutes:02d}"

    return f"{_fmt(start)}–{_fmt(end)}"


def _datetime_from_date_and_minute(date_value: Any, minute_value: Any) -> str | None:
    date_text = str(date_value or "").strip()
    try:
        minute = int(minute_value)
    except (TypeError, ValueError):
        return None
    if not date_text or minute < 0:
        return None
    try:
        day = date.fromisoformat(date_text[:10])
    except ValueError:
        return None
    hour = minute // 60
    minute_part = minute % 60
    local_tz = dt_util.now().tzinfo
    if local_tz is None:
        return datetime.combine(day, datetime.min.time()).replace(hour=hour, minute=minute_part).isoformat()
    return datetime(day.year, day.month, day.day, hour, minute_part, tzinfo=local_tz).isoformat()


def _window_reason_summary(
    entity: GazonEntityBase,
    attrs: dict[str, Any],
    contextual_state: dict[str, Any] | None,
) -> str | None:
    summary = str((contextual_state or {}).get("summary") or "").strip()
    if summary == "Aucun arrosage nécessaire":
        return summary

    status = str((contextual_state or {}).get("status") or "").strip().lower()
    objective_mm = _objective_mm_value(entity)
    block_reason = str(attrs.get("block_reason") or "").strip()
    window_value = str(entity._decision_value("fenetre_optimale") or "").strip()
    window_label = (_window_display_label(window_value) or "").strip()

    if status == "bloque" and block_reason:
        label = _block_reason_display_label(block_reason) or block_reason.replace("_", " ")
        return f"Arrosage bloqué : {label}"
    if status == "auto":
        return "Arrosage automatique planifié"
    if status == "autorise":
        post_status = normalize_post_application_status(entity._decision_value("application_post_watering_status"))
        if post_status == "autorise":
            return "Arrosage post-application disponible"
        return "Arrosage autorisé"
    if status == "en_attente":
        post_status = normalize_post_application_status(entity._decision_value("application_post_watering_status"))
        if post_status == "en_attente":
            return "Arrosage post-application en attente"
        if objective_mm <= 0.0:
            return "Aucun arrosage nécessaire"
        if block_reason:
            label = _block_reason_display_label(block_reason) or block_reason.replace("_", " ")
            return f"Arrosage reporté : {label}"
        if window_label:
            return f"Créneau conseillé : {window_label.lower()}"
        return "Arrosage en attente"
    if objective_mm <= 0.0:
        return "Aucun arrosage nécessaire"
    if window_label:
        return f"Créneau conseillé : {window_label.lower()}"
    return summary or None


def _compact_application_summary(summary: object) -> dict[str, Any] | None:
    if not isinstance(summary, dict) or not summary:
        return None
    compact = {
        key: summary.get(key)
        for key in _APPLICATION_SUMMARY_PUBLIC_KEYS
        if summary.get(key) not in (None, "", [], {})
    }
    return compact or None


def _skip_history_entries(history: object, n: int = 5) -> list[dict[str, Any]]:
    if not isinstance(history, list):
        return []
    result: list[dict[str, Any]] = []
    for item in reversed(history):
        if not isinstance(item, dict):
            continue
        if item.get("type") != "decision_skip":
            continue
        entry: dict[str, Any] = {"reason": item.get("reason"), "date": item.get("date")}
        for key in ("fenetre", "objectif_mm", "raison_decision", "recorded_at"):
            if item.get(key) not in (None, ""):
                entry[key] = item[key]
        result.append(entry)
        if len(result) >= n:
            break
    return result


def _watering_history_entries(history: object, n: int = 7) -> list[dict[str, Any]]:
    """Return the last n arrosage entries for the history card display."""
    if not isinstance(history, list):
        return []
    result: list[dict[str, Any]] = []
    for item in reversed(history):
        if not isinstance(item, dict):
            continue
        if item.get("type") != "arrosage":
            continue
        entry: dict[str, Any] = {
            "date": item.get("date"),
            "recorded_at": item.get("recorded_at"),
            # Début du cycle : c'est lui que la liste « dernières sessions » de la carte doit
            # afficher. `recorded_at` reste publié — l'historique garde les deux bouts.
            "started_at": item.get("started_at"),
            "source": item.get("source"),
        }
        for key in ("watering_cause", "surface_mm", "total_mm", "zone_count"):
            if item.get(key) not in (None, ""):
                entry[key] = item[key]
        zones = item.get("zones")
        if isinstance(zones, list) and zones:
            zone_keys = ("order", "entity_id", "zone", "duration_min", "mm")
            entry["zones"] = [
                {k: z.get(k) for k in zone_keys if z.get(k) is not None}
                for z in zones
                if isinstance(z, dict)
            ]
        result.append(entry)
        if len(result) >= n:
            break
    return result


def _application_history_entries(history: object) -> list[dict[str, Any]]:
    if not isinstance(history, list):
        return []
    entries: list[dict[str, Any]] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        if item.get("type") not in APPLICATION_INTERVENTIONS:
            continue
        summary = build_application_summary(item)
        compact_summary = _compact_application_summary(summary)
        if compact_summary:
            entries.append(compact_summary)
    return entries


def _public_intervention_attributes(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or not payload:
        return {}
    product = payload.get("product")
    if not isinstance(product, dict):
        product = {}
    context = payload.get("context")
    if not isinstance(context, dict):
        context = {}
    ui = public_intervention_ui(payload)
    attrs = {
        "recommended_action": payload.get("recommended_action"),
        "priority": payload.get("priority"),
        "score": payload.get("score"),
        "reason": payload.get("reason"),
        "why_now": payload.get("why_now"),
        "product_id": product.get("id"),
        "product_name": product.get("name"),
        "ready_to_declare": payload.get("ready_to_declare"),
        "selected_product_ready": payload.get("selected_product_ready"),
        "month_match": payload.get("month_match"),
        "current_phase": context.get("current_phase"),
        "current_month": context.get("current_month"),
        "opportunity_level": context.get("opportunity_level"),
        "summary": ui.get("summary"),
        "hint": ui.get("hint"),
        "action_label": ui.get("action_label"),
        # `reason` est la concaténation « · » de TOUS les critères, satisfaits et bloquants
        # mêlés : la carte affichait quatre puces identiques et l'utilisateur devait deviner
        # laquelle retenait l'intervention. La polarité existe pourtant depuis toujours dans
        # `constraints` (`met` / `blocking`) — elle n'était simplement jamais publiée.
        # On expose une forme compacte, prête à l'affichage : pas de `value`, pas de `hint`.
        "application_constraints": _public_intervention_constraints(payload),
    }
    return _clean_public_attrs(attrs) or {}


def _public_intervention_constraints(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Critères d'application, réduits à ce dont un affichage a besoin."""
    constraints = payload.get("constraints")
    if not isinstance(constraints, list):
        return []
    public: list[dict[str, Any]] = []
    for constraint in constraints:
        if not isinstance(constraint, dict):
            continue
        label = str(constraint.get("label") or "").strip()
        if not label:
            continue
        public.append(
            {
                "code": str(constraint.get("code") or ""),
                "label": label,
                "met": bool(constraint.get("met")),
                "blocking": bool(constraint.get("blocking")),
            }
        )
    return public


# Table de présentation des raisons de blocage de l'arrosage automatique.
# Clé = code renvoyé par coordinator._should_launch_auto_irrigation.
# Valeur = (état lisible, blocage « dur » nécessitant une action, pourquoi, comment débloquer).
_AUTO_IRRIGATION_BLOCK_INFO: dict[str, tuple[str, bool, str, str]] = {
    "safety_lock": (
        "Bloqué (sécurité)",
        True,
        "Une vanne ne s'est pas confirmée fermée lors d'un arrosage : par sécurité, "
        "l'arrosage automatique est suspendu (risque de vanne restée ouverte).",
        "Vérifie que tes vannes d'arrosage sont bien fermées, puis appuie sur le bouton "
        "« Retour au mode normal » (ou appelle le service gazon_intelligent.reset_mode).",
    ),
    "startup_guard": (
        "Démarrage en cours",
        False,
        "Home Assistant vient de démarrer : les capteurs ne sont pas encore tous prêts.",
        "Aucune action : se débloque automatiquement au premier cycle de données valide.",
    ),
    "auto_irrigation_disabled": (
        "Désactivé",
        True,
        "L'arrosage automatique est désactivé.",
        "Active l'interrupteur « Arrosage auto autorisé ».",
    ),
    "user_confirmation_required": (
        "Confirmation requise",
        True,
        "L'arrosage automatique attend une confirmation explicite de l'utilisateur.",
        "Confirme l'arrosage automatique.",
    ),
    "no_plan_available": (
        "Plan indisponible",
        True,
        "Aucun plan d'arrosage exploitable n'a pu être construit (zones ou débits manquants ?).",
        "Vérifie la configuration des zones et de leurs débits dans l'intégration.",
    ),
    "auto_not_allowed": (
        "Mode non automatique",
        False,
        "Le profil d'arrosage courant n'autorise pas le déclenchement automatique.",
        "Aucune action : la phase/le mode courant gère l'arrosage autrement.",
    ),
    "execution_not_allowed": (
        "Exécution non autorisée",
        False,
        "L'exécution de l'arrosage n'est pas permise dans le contexte courant.",
        "Aucune action immédiate.",
    ),
    "no_objective": (
        "Aucun besoin",
        False,
        "Aucun besoin d'arrosage : l'objectif est à 0 (réserve hydrique suffisante).",
        "Aucune action : l'arrosage partira quand la réserve baissera.",
    ),
    "not_recommended": (
        "Non recommandé",
        False,
        "L'arrosage n'est pas recommandé actuellement.",
        "Aucune action.",
    ),
    "irrigation_blocked": (
        "Bloqué par conditions",
        False,
        "Arrosage bloqué par les conditions (pluie annoncée, sol déjà humide, ou tondeuse en cours).",
        "Aucune action : se lèvera quand les conditions le permettront.",
    ),
    "window_unavailable": (
        "Hors fenêtre",
        False,
        "On est hors de la fenêtre d'arrosage du jour.",
        "Aucune action : l'arrosage partira dans la fenêtre du matin (ou du soir si activé).",
    ),
    "outside_window": (
        "Hors fenêtre",
        False,
        "On est hors de la fenêtre d'arrosage du matin.",
        "Aucune action : attends la fenêtre du matin.",
    ),
    "outside_evening_window": (
        "Hors fenêtre du soir",
        False,
        "On est hors de la fenêtre d'arrosage du soir.",
        "Aucune action.",
    ),
    "evening_cooling_done": (
        "Rafraîchissement déjà fait",
        False,
        "Le rafraîchissement du soir a déjà eu lieu aujourd'hui.",
        "Aucune action : la fenêtre du soir est close jusqu'à demain.",
    ),
    "watering_in_progress": (
        "Arrosage en cours",
        False,
        "Un arrosage est déjà en cours.",
        "Aucune action : attends la fin du cycle.",
    ),
    "recent_watering": (
        "Arrosé récemment",
        False,
        "La pelouse a été arrosée récemment.",
        "Aucune action.",
    ),
    "target_date_future": (
        "Programmé plus tard",
        False,
        "La date cible d'arrosage est dans le futur.",
        "Aucune action.",
    ),
    "semis_target_reached": (
        "Objectif semis atteint",
        False,
        "Le nombre de cycles d'arrosage du jour pour le semis est atteint.",
        "Aucune action.",
    ),
    "semis_cycle_pending": (
        "Cycle semis en attente",
        False,
        "Le prochain micro-cycle de semis n'est pas encore dû.",
        "Aucune action.",
    ),
    # Motifs côté DÉCISION qui mettent l'objectif à 0 (l'exécution rapporte alors
    # "no_objective", mais la vraie cause est l'un de ceux-ci → on l'affiche).
    "cooldown_24h": (
        "Repos après arrosage",
        False,
        "La pelouse a été arrosée il y a moins de 24 h : un délai est respecté avant un nouvel arrosage.",
        "Aucune action : si la réserve reste basse, l'arrosage repartira à la fin du délai.",
    ),
    "pluie_prevue_suffisante": (
        "Pluie prévue suffisante",
        False,
        "De la pluie est annoncée et devrait couvrir le besoin : arroser serait inutile.",
        "Aucune action : l'arrosage repartira si la pluie ne tombe pas comme prévu.",
    ),
    "pluie_active": (
        "Pluie en cours",
        False,
        "Il pleut actuellement : pas d'arrosage.",
        "Aucune action : se lèvera après la pluie.",
    ),
    "sol_deja_humide": (
        "Sol déjà humide",
        False,
        "Le sol est déjà suffisamment humide : pas besoin d'arroser.",
        "Aucune action.",
    ),
    "humidite_excessive": (
        "Conditions trop humides",
        False,
        "L'humidité est élevée (ou la réserve est déjà au-dessus du plein) : l'arrosage est superflu.",
        "Aucune action.",
    ),
    "garde_fou_hebdomadaire": (
        "Budget hebdo atteint",
        False,
        "Le budget d'arrosage de la semaine est atteint : on plafonne pour éviter le sur-arrosage.",
        "Aucune action : le budget se reconstitue au fil des jours.",
    ),
    "relaunch_cooldown": (
        "Repos post-cycle",
        False,
        "Un cycle d'arrosage vient de se terminer : un délai de 6 h est respecté avant de pouvoir en relancer un autre.",
        "Aucune action : se débloque automatiquement après le délai.",
    ),
}

_AUTO_IRRIGATION_READY_REASONS = {"ready", "post_application_ready"}


class GazonArrosageAutoBlocageSensor(GazonEntityBase, SensorEntity):
    """Diagnostic : dit explicitement pourquoi l'arrosage automatique ne se déclenche pas."""

    _attr_name = "Blocage arrosage auto"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:water-alert"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "arrosage_auto_blocage")

    def _coordinator_data(self) -> dict:
        data = getattr(self.coordinator, "data", None)
        return data if isinstance(data, dict) else {}

    def _resolve_block_reason(self):
        """Raison la plus informative pour l'utilisateur.

        L'exécution rapporte « no_objective » dès que l'objectif est à 0 — y compris
        quand c'est un blocage de décision (cooldown, pluie, sol humide, budget hebdo…)
        qui a mis l'objectif à 0. Dans ce cas on remonte le **vrai** motif plutôt que de
        laisser croire à une « réserve suffisante » (qui serait faux si la réserve est
        basse mais qu'on est en cooldown, par exemple).
        """
        reason = self._coordinator_data().get("auto_irrigation_block_reason")
        if reason == "no_objective":
            decision_block = str(self._decision_value("block_reason") or "").strip()
            if decision_block and decision_block in _AUTO_IRRIGATION_BLOCK_INFO:
                return decision_block
        return reason

    @property
    def native_value(self):
        reason = self._resolve_block_reason()
        if reason in _AUTO_IRRIGATION_READY_REASONS:
            return "Prêt"
        if reason is None:
            return "En attente"
        info = _AUTO_IRRIGATION_BLOCK_INFO.get(str(reason))
        return info[0] if info is not None else str(reason)

    @property
    def extra_state_attributes(self):
        data = self._coordinator_data()
        reason = self._resolve_block_reason()
        safety_lock = bool(data.get("auto_irrigation_safety_lock"))
        if reason in _AUTO_IRRIGATION_READY_REASONS:
            return {
                "bloque": False,
                "code": reason,
                "pourquoi": "L'arrosage automatique est prêt à se déclencher (ou en cours de lancement).",
                "comment_debloquer": "Aucune action requise.",
                "safety_lock_actif": safety_lock,
            }
        info = _AUTO_IRRIGATION_BLOCK_INFO.get(str(reason)) if reason is not None else None
        if info is None:
            return {
                # Défaut prudent : un motif présent mais non répertorié signifie que
                # quelque chose bloque réellement → bloque=True (ne pas faire croire à
                # une automatisation que l'arrosage est opérationnel). reason=None = pas
                # encore évalué → non bloqué.
                "bloque": reason is not None,
                "code": reason,
                "pourquoi": (
                    "Aucun cycle d'arrosage automatique n'a encore été évalué."
                    if reason is None
                    else "Raison de blocage inconnue."
                ),
                "comment_debloquer": "Aucune action connue.",
                "safety_lock_actif": safety_lock,
            }
        _label, blocked, pourquoi, comment = info
        if reason == "garde_fou_hebdomadaire":
            heat_stress = str(self._decision_value("heat_stress_level") or "")
            if heat_stress in {"eleve", "severe"}:
                comment = (
                    "Le budget hebdomadaire est atteint. En cas de stress hydrique sévère ET de "
                    "forte chaleur réelle (≥ 32 °C), un arrosage de secours se déclenchera quand "
                    "même si la réserve tombe sous le seuil critique (déplétion réelle ≥ 90 %)."
                )
        return {
            "bloque": blocked,
            "code": reason,
            "pourquoi": pourquoi,
            "comment_debloquer": comment,
            "safety_lock_actif": safety_lock,
        }


async def async_setup_entry(hass, entry, async_add_entities):
    await _async_ensure_assistant_entity_id(hass, entry)
    coordinator = _entry_coordinator(hass, entry)
    if coordinator is None:
        return
    async_add_entities(
        [
            GazonAssistantSensor(coordinator),
            GazonTonteEtatSensor(coordinator),
            GazonHauteurTonteSensor(coordinator),
            GazonHauteurEstimeeSensor(coordinator),
            GazonConseilPrincipalSensor(coordinator),
            GazonActionRecommandeeSensor(coordinator),
            GazonActionAEviterSensor(coordinator),
            GazonNiveauActionSensor(coordinator),
            GazonFenetreOptimaleSensor(coordinator),
            GazonRisqueGazonSensor(coordinator),
            GazonPhaseActiveSensor(coordinator),
            GazonSousPhaseSensor(coordinator),
            GazonObjectifMmSensor(coordinator),
            GazonObjectifLegacySensor(coordinator),
            GazonObjectifDepletionSensor(coordinator),
            GazonEt0Sensor(coordinator),
            GazonEtoHoraireSensor(coordinator),
            GazonEtcSensor(coordinator),
            GazonReserveActuelleSensor(coordinator),
            GazonDepletionRatioSensor(coordinator),
            GazonEtatHydriqueSensor(coordinator),
            GazonTypeArrosageSensor(coordinator),
            GazonPlanArrosageSensor(coordinator),
            GazonArrosageEnCoursSensor(coordinator),
            GazonDernierArrosageDetecteSensor(coordinator),
            GazonDernierArrosageTotalZonesSensor(coordinator),
            GazonProchainArrosageSensor(coordinator),
            GazonProchaineTonteSensor(coordinator),
            GazonDerniereApplicationSensor(coordinator),
            GazonDerniereActionUtilisateurSensor(coordinator),
            GazonCatalogueProduitsSensor(coordinator),
            GazonInterventionRecommendationSensor(coordinator),
            GazonDebugInterventionSensor(coordinator),
            GazonScoreNiveauSensor(coordinator),
            GazonProchaineFenetreOptimaleSensor(coordinator),
            GazonProchainBlocageAttenduSensor(coordinator),
            GazonArrosageAutoBlocageSensor(coordinator),
        ]
    )


async def _async_ensure_assistant_entity_id(hass, entry) -> None:
    from homeassistant.helpers import entity_registry as er

    desired_entity_id = public_entity_id("sensor", "assistant", instance_slug=resolve_entry_instance_slug(entry))
    desired_unique_id = f"{entry.entry_id}_assistant"
    registry = er.async_get(hass)
    current_entity = None
    for entity in registry.entities.values():
        if getattr(entity, "config_entry_id", None) != entry.entry_id:
            continue
        if getattr(entity, "unique_id", None) != desired_unique_id:
            continue
        current_entity = entity
        break

    if current_entity is None or current_entity.entity_id == desired_entity_id:
        return

    existing = registry.entities.get(desired_entity_id)
    if existing is not None and getattr(existing, "unique_id", None) != desired_unique_id:
        return

    registry.async_update_entity(current_entity.entity_id, new_entity_id=desired_entity_id)


class GazonPhaseActiveSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Phase dominante"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:grass"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "phase_active")

    @property
    def native_value(self):
        return self._decision_value("phase_active")

    @property
    def extra_state_attributes(self):
        attrs = {}
        result_attrs = self._attrs_from_result("phase_dominante_source")
        if result_attrs:
            attrs.update(result_attrs)
        possible_values = self._possible_values_attr("phase_dominante")
        if possible_values:
            attrs.update(possible_values)
        result = self.decision_result
        if result is not None:
            extra = getattr(result, "extra", None)
            if isinstance(extra, dict):
                type_sol = extra.get("type_sol")
                if type_sol in (None, "", [], {}):
                    configuration = extra.get("configuration")
                    if isinstance(configuration, dict):
                        type_sol = configuration.get("type_sol")
                if type_sol not in (None, "", [], {}):
                    attrs["type_sol"] = type_sol
                pluie_demain_source = extra.get("pluie_demain_source")
                if pluie_demain_source is not None:
                    if pluie_demain_source == PLUIE_SOURCE_INDISPONIBLE:
                        pluie_demain_source = PLUIE_SOURCE_NON_DISPONIBLE
                    attrs["pluie_demain_source"] = pluie_demain_source
        if attrs:
            return attrs
        fallback_attrs = _coordinator_used_entities_attributes(self.coordinator)
        configuration = fallback_attrs.pop("configuration", None)
        if isinstance(configuration, dict):
            type_sol = configuration.get("type_sol")
            if type_sol not in (None, "", [], {}):
                fallback_attrs["type_sol"] = type_sol
        return _clean_public_attrs(fallback_attrs)


class GazonHauteurTonteSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Hauteur de tonte conseillée"
    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "cm"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:content-cut"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "hauteur_tonte")

    @property
    def native_value(self):
        return self._decision_value("hauteur_tonte_recommandee_cm")

    @property
    def extra_state_attributes(self):
        attrs = self._attrs_from_result(
            "hauteur_tonte_min_cm",
            "hauteur_tonte_max_cm",
            "hauteur_tonte_garde_fou_label",
            "tonte_statut",
            "phase_active",
            "mowing_frequency_target_per_week",
            "mowing_frequency_label",
            "mowing_window_state",
            "mowing_window_label",
            "mowing_window_reason",
            "tondeuse_statut",
            "tondeuse_statut_libelle",
            "tondeuse_batterie",
            "tondeuse_hauteur_coupe_mm",
            "mowing_blocked_by_watering",
            "mowing_blocked",
            "mowing_block_reason_code",
            "mowing_block_reason_label",
            "mowing_block_reason",
            "mowing_cooldown_remaining_minutes",
            "mowing_watering_coordination",
            "mowing_watering_coordination_msg",
        )
        return attrs or None


class GazonHauteurEstimeeSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Hauteur de gazon estimée"
    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "cm"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:grass"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "hauteur_gazon_estimee")

    @property
    def native_value(self):
        return self._decision_value("gazon_hauteur_estimee_cm")

    @property
    def extra_state_attributes(self):
        attrs = self._attrs_from_result(
            "tondeuse_hauteur_coupe_mm",
            "mowing_overdue_days",
            "mowing_overdue_factor",
            "mowing_is_overdue",
            # Rend visible ce que l'arrondi au 0,1 cm masque : par forte chaleur la journée
            # entière ne vaut qu'un cran, et on ne voyait donc rien bouger.
            "gazon_pousse_jour_cm",
        )
        return attrs or None


class GazonSousPhaseSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Sous-phase"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:sprout"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "sous_phase")

    @property
    def native_value(self):
        return self._decision_value("sous_phase")

    @property
    def extra_state_attributes(self):
        attrs = self._attrs_from_result(
            "phase_dominante",
            "phase_dominante_source",
            "sous_phase_detail",
            "sous_phase_age_days",
            "sous_phase_progression",
        ) or {}
        possible_values = self._possible_values_attr("sous_phase")
        if possible_values:
            attrs.update(possible_values)
        attrs = _apply_public_mower_aliases(attrs)
        return attrs or None


class GazonObjectifMmSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Objectif d'arrosage"
    _attr_native_unit_of_measurement = "mm"
    _attr_has_entity_name = True
    _attr_icon = "mdi:water"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "objectif_mm")
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        return self._decision_value("objectif_mm")

    @staticmethod
    def _objective_attrs_keys() -> tuple[str, ...]:
        return (
            "phase_active",
            "phase_dominante",
            "sous_phase",
            "bilan_hydrique_mm",
            "reserve_hydrique_sol_mm",
            "bilan_hydrique_precedent_mm",
            "deficit_3j",
            "deficit_7j",
            "pluie_demain",
            "forecast_pluie_j2",
            "forecast_pluie_3j",
            "forecast_probabilite_max_3j",
            "temperature",
            "forecast_temperature_today",
            "temperature_source",
            "etp",
            "depletion_ratio",
            # Réserve AFFICHÉE (descente progressive selon le soleil) — affichage carte seul.
            "et_elapsed_fraction",
            "reserve_actuelle_affichee_mm",
            "reserve_stock_affichee_mm",
            "depletion_affichee_mm",
            "depletion_ratio_affiche",
            "evening_cooling_likely",
            "evening_cooling_debug",
            "fenetre_optimale_profil",
            "reserve_utile_mm",
            "reserve_actuelle_mm",
            "reserve_stock_mm",
            "reserve_stock_max_mm",
            "reserve_surplus_mm",
            "reserve_fill_ratio",
            "reserve_available_ratio",
            "reserve_minimale_mm",
            "depletion_mm",
            "depletion_allowed_mm",
            # Ce que le sol RÉCLAME, que l'arrosage soit permis ou non. L'état de l'entité,
            # lui, reste « ce qui sera versé » — donc 0 pendant un blocage.
            "besoin_mm",
            # Les deux COMMUTATEURS qui changent tout le calcul, jusqu'ici invisibles :
            #  · `reserve_from_soil_ledger` : quel modèle pilote (déplétion vs déficit legacy)
            #  · `etp_connue` : les déficits sont-ils mesurés, ou nuls par défaut
            "reserve_from_soil_ledger",
            "etp_connue",
            "mad_ratio",
            "soil_moisture_override_state",
            "soil_moisture_confidence_adjustment",
            "et0_mm",
            "et0_source",
            "kc_gazon",
            "etc_mm",
        )

    @property
    def extra_state_attributes(self):
        attrs = self._attrs_from_result(*self._objective_attrs_keys()) or {}
        display_balance = _objective_display_balance(attrs)
        hydric_balance_level = _hydric_balance_level(
            display_balance,
            attrs.get("deficit_3j"),
            attrs.get("deficit_7j"),
        )
        hydric_strategy = _hydric_strategy(
            display_balance,
            attrs.get("deficit_3j"),
            attrs.get("deficit_7j"),
        )
        if hydric_balance_level is not None:
            attrs["hydric_balance_level"] = hydric_balance_level
        if hydric_strategy is not None:
            attrs["hydric_strategy"] = hydric_strategy
        hydric_state = _hydric_state_for_objective_sensor(self, attrs)
        if hydric_state is not None:
            attrs["hydric_state"] = hydric_state
        harmonized_level, harmonized_strategy = _harmonized_hydric_labels(
            self,
            _objective_mm_value(self),
            hydric_state,
            attrs.get("hydric_balance_level"),
            attrs.get("hydric_strategy"),
            attrs,
        )
        if harmonized_level is not None:
            attrs["hydric_balance_level"] = harmonized_level
        if harmonized_strategy is not None:
            attrs["hydric_strategy"] = harmonized_strategy
        return attrs or None


class GazonObjectifLegacySensor(GazonEntityBase, SensorEntity):
    _attr_name = "Objectif legacy"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_native_unit_of_measurement = "mm"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:water-minus"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "objectif_legacy_mm")

    @property
    def native_value(self):
        for key in (
            "objectif_mm",
            "mm_final_recommande",
            "mm_final",
            "mm_cible",
            "objectif_legacy_mm",
            "objectif_legacy",
        ):
            try:
                value = self._decision_value(key, None)
                if value not in (None, "", [], {}):
                    return float(value)
            except (TypeError, ValueError):
                continue
        return 0.0

    @property
    def extra_state_attributes(self):
        attrs = self._attrs_from_result(
            "objectif_mm",
            "mm_final_recommande",
            "use_depletion_logic",
            "type_arrosage",
        ) or {}
        attrs["comparison_mode"] = "legacy"
        return attrs or None


class GazonObjectifDepletionSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Objectif déplétion"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_native_unit_of_measurement = "mm"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:water-sync"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "objectif_depletion_mm")

    @property
    def native_value(self):
        for key in ("mm_cible_depletion", "objectif_depletion_mm", "objectif_depletion"):
            try:
                value = self._decision_value(key, None)
                if value not in (None, "", [], {}):
                    return float(value)
            except (TypeError, ValueError):
                continue
        return 0.0

    @property
    def extra_state_attributes(self):
        attrs = self._attrs_from_result(
            "reserve_actuelle_mm",
            "reserve_stock_mm",
            "reserve_stock_max_mm",
            "reserve_surplus_mm",
            "reserve_fill_ratio",
            "reserve_available_ratio",
            "reserve_minimale_mm",
            "depletion_mm",
            "depletion_ratio",
            "use_depletion_logic",
        ) or {}
        attrs["comparison_mode"] = "depletion"
        return attrs or None


class GazonEt0Sensor(GazonEntityBase, SensorEntity):
    _attr_name = "ET0"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_native_unit_of_measurement = "mm"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:weather-sunny"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "et0")

    def _restored_state_float(self) -> float | None:
        hass = getattr(self, "hass", None)
        states = getattr(hass, "states", None)
        getter = getattr(states, "get", None)
        if not callable(getter):
            return None
        state = getter(getattr(self, "entity_id", None))
        raw = getattr(state, "state", None)
        try:
            value = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None
        if value is None or value <= 0:
            return None
        return value

    @property
    def native_value(self):
        try:
            value = float(self._decision_value("et0_mm", 0.0) or 0.0)
        except (TypeError, ValueError):
            value = 0.0
        if value > 0:
            return value
        temperature = self._decision_value("temperature", None)
        forecast = self._decision_value("forecast_temperature_today", None)
        reference = self._decision_value("temperature_reference_hydrique", None)
        if temperature is None and forecast is None and reference is None:
            restored = self._restored_state_float()
            if restored is not None:
                return restored
        return value

    @property
    def extra_state_attributes(self):
        return self._attrs_from_result(
            "et0_source",
            "temperature",
            "forecast_temperature_today",
            "temperature_reference_hydrique",
        )


class GazonEtoHoraireSensor(GazonEntityBase, SensorEntity):
    """ET0 de référence horaire (FAO-56 Eq. 53), en mm/h.

    Calculée à partir du rayonnement et de la pression mesurés quand ils sont configurés
    (sinon replis : modèle nuages / pression standard, visibles dans les attributs).

    ⚠️ Cette entité est de catégorie DIAGNOSTIC, mais la VALEUR qu'elle affiche, elle, pilote
    le bilan sol depuis la 0.19.0 : le ledger l'intègre au fil du temps (× Kc) pour débiter la
    réserve. L'entité sert à vérifier d'un coup d'œil que le calcul tourne bien sur des valeurs
    MESURÉES (`radiation_source`/`pressure_source` = « capteur ») et non sur les replis.
    """

    _attr_name = "ETo horaire"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_native_unit_of_measurement = "mm/h"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:water-thermometer-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "eto_horaire")

    @property
    def native_value(self):
        value = self._decision_value("eto_horaire_mm_h", None)
        try:
            return round(float(value), 4) if value is not None else None
        except (TypeError, ValueError):
            return None

    @property
    def extra_state_attributes(self):
        diagnostic = self._decision_value("eto_horaire_diagnostic", None)
        if not isinstance(diagnostic, dict):
            return {"methode": "FAO-56 Penman-Monteith horaire (Eq. 53)"}
        attrs = {k: v for k, v in diagnostic.items() if k != "value"}
        attrs["methode"] = "FAO-56 Penman-Monteith horaire (Eq. 53)"
        return attrs


class GazonEtcSensor(GazonEntityBase, SensorEntity):
    _attr_name = "ETc"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_native_unit_of_measurement = "mm"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:grass"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "etc")

    def _restored_state_float(self) -> float | None:
        hass = getattr(self, "hass", None)
        states = getattr(hass, "states", None)
        getter = getattr(states, "get", None)
        if not callable(getter):
            return None
        state = getter(getattr(self, "entity_id", None))
        raw = getattr(state, "state", None)
        try:
            value = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None
        if value is None or value <= 0:
            return None
        return value

    @property
    def native_value(self):
        try:
            value = float(self._decision_value("etc_mm", 0.0) or 0.0)
        except (TypeError, ValueError):
            value = 0.0
        if value > 0:
            return value
        et0_mm = self._decision_value("et0_mm", None)
        try:
            et0_value = float(et0_mm) if et0_mm is not None else None
        except (TypeError, ValueError):
            et0_value = None
        if et0_value is None or et0_value <= 0:
            restored = self._restored_state_float()
            if restored is not None:
                return restored
        return value

    @property
    def extra_state_attributes(self):
        return self._attrs_from_result("et0_mm", "kc_gazon", "phase_dominante", "sous_phase")


class GazonReserveActuelleSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Réserve utile actuelle"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_native_unit_of_measurement = "mm"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:cup-water"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "reserve_actuelle")

    @property
    def native_value(self):
        try:
            return float(self._decision_value("reserve_actuelle_mm", 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @property
    def extra_state_attributes(self):
        attrs = self._attrs_from_result(
            "reserve_utile_mm",
            "reserve_stock_mm",
            "reserve_stock_max_mm",
            "reserve_surplus_mm",
            "reserve_available_ratio",
            "reserve_minimale_mm",
            "depletion_mm",
            "depletion_ratio",
            "bilan_hydrique_mm",
            "reserve_hydrique_sol_mm",
            "arrosage_recent_jour",
            "arrosage_recent_3j",
            "arrosage_recent_7j",
            "arrosage_applique_7j",
            "pluie_efficace",
            "retour_arrosage",
            "et0_mm",
        ) or {}
        soil_balance = self._decision_value("soil_balance")
        if isinstance(soil_balance, dict):
            attrs["sol_reserve_precedente_mm"] = soil_balance.get("previous_reserve_mm")
            attrs["sol_delta_mm"] = soil_balance.get("delta_mm")
        hydric_state = _hydric_state_for_objective_sensor(self, attrs)
        if hydric_state is not None:
            attrs["hydric_state"] = hydric_state
        # LOT A — santé capteurs (lecture directe coordinator.data)
        _data = getattr(self.coordinator, "data", None) or {}
        _sh = _data.get("sensor_health")
        if isinstance(_sh, dict) and _sh:
            attrs["sensor_health"] = _sh
        # LOT B — urgence hydrique malgré blocage
        _crit = _data.get("irrigation_blocked_but_critical")
        if _crit is not None:
            attrs["irrigation_blocked_but_critical"] = bool(_crit)
        _cmm = _data.get("critical_deficit_mm")
        if _cmm is not None:
            attrs["critical_deficit_mm"] = _cmm
        _cr = _data.get("critical_irrigation_reason")
        if _cr is not None:
            attrs["critical_irrigation_reason"] = _cr
        return attrs or None


class GazonDepletionRatioSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Déplétion"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:gauge"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "depletion_ratio")

    @property
    def native_value(self):
        try:
            ratio = float(self._decision_value("depletion_ratio", 0.0) or 0.0)
        except (TypeError, ValueError):
            ratio = 0.0
        return round(max(0.0, min(ratio, 1.0)) * 100.0, 1)

    @property
    def extra_state_attributes(self):
        raw_ratio = self._decision_value("depletion_ratio")
        attrs = {"depletion_ratio_raw": raw_ratio}
        hydric_state = _hydric_state_from_depletion_ratio(raw_ratio)
        if hydric_state is not None:
            attrs["hydric_state"] = hydric_state
        return attrs or None


class GazonEtatHydriqueSensor(GazonEntityBase, SensorEntity):
    _attr_name = "État hydrique"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_icon = "mdi:water-percent-alert"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "etat_hydrique")

    @property
    def native_value(self):
        hydric_state = self._decision_value("hydric_state")
        if hydric_state not in (None, "", [], {}):
            return hydric_state
        attrs = self.extra_state_attributes or {}
        return _hydric_state_for_objective_sensor(self, attrs)

    @property
    def extra_state_attributes(self):
        attrs = self._attrs_from_result(
            "reserve_actuelle_mm",
            "reserve_stock_mm",
            "reserve_stock_max_mm",
            "reserve_surplus_mm",
            "reserve_fill_ratio",
            "reserve_available_ratio",
            "reserve_minimale_mm",
            "depletion_mm",
            "depletion_ratio",
        ) or {}
        hydric_state = _hydric_state_for_objective_sensor(self, attrs)
        if hydric_state is not None:
            attrs["hydric_state"] = hydric_state
        return attrs or None


class GazonTypeArrosageSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Profil d'arrosage"
    _attr_has_entity_name = True
    _attr_icon = "mdi:sprinkler"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "type_arrosage")

    @property
    def native_value(self):
        result = self.decision_result
        if result is not None:
            objective = self._decision_value("objectif_mm", 0.0)
            try:
                objective = float(objective or 0.0)
            except (TypeError, ValueError):
                objective = 0.0
            decision_resume = self._decision_value("decision_resume")
            if (
                objective <= 0.0
                and isinstance(decision_resume, dict)
                and str(decision_resume.get("action") or "").strip() in {"aucune_action", "none"}
            ):
                return "Aucune action"
            return result.display_label_for("type_arrosage")
        raw_value = _normalized_public_type_arrosage(self)
        return TYPE_ARROSAGE_DISPLAY_LABELS.get(raw_value, raw_value)

    @property
    def extra_state_attributes(self):
        result = self.decision_result
        if result is None:
            raw_values = (self._possible_values_attr("type_arrosage") or {}).get("possible_values") or []
            if not raw_values:
                return None
            possible_values = [
                TYPE_ARROSAGE_DISPLAY_LABELS.get(str(value), str(value))
                for value in raw_values
            ]
            return {"possible_values": possible_values}
        possible_values = list(result.possible_display_values_for("type_arrosage") or [])
        objective = self._decision_value("objectif_mm", 0.0)
        try:
            objective = float(objective or 0.0)
        except (TypeError, ValueError):
            objective = 0.0
        decision_resume = self._decision_value("decision_resume")
        if (
            objective <= 0.0
            and isinstance(decision_resume, dict)
            and str(decision_resume.get("action") or "").strip() in {"aucune_action", "none"}
        ):
            if "Aucune action" not in possible_values:
                possible_values.insert(0, "Aucune action")
            possible_values = [value for value in possible_values if value != "Réglage personnalisé"]
        if not possible_values:
            return None
        # Hétérogène : au-delà de `possible_values`, on y ajoute un booléen et un flottant.
        attrs: dict[str, Any] = {"possible_values": possible_values}
        # LOT B — urgence hydrique malgré blocage (lecture directe coordinator.data)
        data = getattr(self.coordinator, "data", None) or {}
        critical = data.get("irrigation_blocked_but_critical")
        if critical is not None:
            attrs["irrigation_blocked_but_critical"] = bool(critical)
        critical_mm = data.get("critical_deficit_mm")
        if critical_mm is not None:
            attrs["critical_deficit_mm"] = critical_mm
        critical_reason = data.get("critical_irrigation_reason")
        if critical_reason is not None:
            attrs["critical_irrigation_reason"] = critical_reason
        return attrs


class GazonDernierArrosageDetecteSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Dernière session détectée"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = "mm"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:water-check"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "dernier_arrosage_detecte")

    def _configured_zone_ids(self) -> set[str]:
        iterator = getattr(self.coordinator, "_iter_zones_with_rate", None)
        if not callable(iterator):
            return set()
        return {
            str(entity_id).strip()
            for entity_id, _rate in iterator()
            if str(entity_id).strip()
        }

    def _latest_zone_session(self) -> dict[str, Any] | None:
        history = getattr(self.coordinator, "history", None)
        if not isinstance(history, list):
            return None
        allowed_zone_ids = self._configured_zone_ids()
        for item in reversed(history):
            if not isinstance(item, dict):
                continue
            if item.get("type") != "arrosage":
                continue
            # DERNIER arrosage RÉEL (piloté par l'intégration OU externe), pas seulement les
            # détections passives `zone_session` : sinon un cycle auto/manuel n'apparaît jamais et
            # la carte reste figée sur la dernière session externe (cas vécu : 22,5 mm du 22/06 au
            # lieu des 5 mm pilotés du 24/06). On exclut juste les arrosages TECHNIQUES
            # (rafraîchissement du soir, post-application) qui ne sont pas une vraie recharge.
            if _is_technical_watering(item):
                continue
            zones = item.get("zones")
            if not allowed_zone_ids:
                return item
            # Les cycles pilotés n'ont pas toujours le détail `zones` dans l'historique (juste
            # total_mm) : on les accepte. On ne filtre par zones que si ce détail est présent.
            if isinstance(zones, list) and zones:
                item_zone_ids = {
                    str(zone.get("entity_id") or zone.get("zone") or "").strip()
                    for zone in zones
                    if isinstance(zone, dict)
                }
                item_zone_ids.discard("")
                if item_zone_ids and not (item_zone_ids & allowed_zone_ids):
                    continue
            return item
        return None

    @staticmethod
    def _zone_detail_keys() -> tuple[str, ...]:
        return ("order", "zone", "entity_id", "rate_mm_h", "duration_min", "duration_seconds", "mm")

    @staticmethod
    def _session_when_text(session: dict[str, Any]) -> str | None:
        # ⚠️ LE DÉBUT, PAS LA FIN. Cet horodatage est ce que l'utilisateur lit — « arrosé à
        # 05:18 » pour un cycle parti à 03:45:13 lui a fait croire à 1 h 30 de retard qui
        # n'existait pas (04/08/2026). Les entrées antérieures à la 0.41.0 n'ont pas de
        # `started_at` : elles retombent sur la fin, comme avant.
        # ⚠️ NE PAS reporter cette priorité dans `water.resolve_history_moment` : lui sert au
        # calcul d'espacement (cooldown 24 h), qui doit garder la même référence.
        for key in ("started_at", "detected_at", "recorded_at", "date"):
            value = session.get(key)
            human = _human_datetime_text(value)
            if human:
                return human
        return None

    def _zone_session_attributes(self, session: dict[str, Any]) -> dict[str, Any] | None:
        zones = session.get("zones")
        zone_details: list[dict[str, Any]] = []
        zones_used: list[str] = []
        if isinstance(zones, list):
            for zone in zones:
                if not isinstance(zone, dict):
                    continue
                zone_id = zone.get("entity_id") or zone.get("zone")
                if zone_id is not None:
                    zones_used.append(str(zone_id))
                zone_detail = {
                    key: zone.get(key)
                    for key in self._zone_detail_keys()
                    if zone.get(key) is not None
                }
                if zone_detail:
                    zone_details.append(zone_detail)

        surface_mm = _session_surface_mm(session)
        zones_total_mm = _zone_session_total_mm(zones if isinstance(zones, list) else None)
        if surface_mm is None:
            surface_mm = 0.0

        attrs: dict[str, Any] = {
            "mm_scope": "global_surface",
            "mm_interpretation": "surface_uniform",
            "mm_measurement_kind": "surface_equivalent",
            "date_action": session.get("date"),
            "source": session.get("source"),
            "last_watering_when": self._session_when_text(session),
            "zone_count": session.get("zone_count") if session.get("zone_count") is not None else len(zone_details),
            "zones_used": zones_used,
            "zones": zone_details,
        }
        attrs["surface_mm"] = surface_mm
        attrs["total_mm"] = surface_mm
        if zones_total_mm is not None:
            attrs["zones_total_mm"] = zones_total_mm
        try:
            zone_count = int(attrs.get("zone_count") or 0)
        except (TypeError, ValueError):
            zone_count = 0
        when_text = self._session_when_text(session)
        source = str(session.get("source") or "").strip()
        raw_detected_at = session.get("detected_at") or session.get("date")
        if raw_detected_at not in (None, "", [], {}):
            attrs["detected_at_utc"] = raw_detected_at
            attrs["detected_at"] = when_text or raw_detected_at
        elif when_text:
            attrs["detected_at"] = when_text
        if when_text:
            if zones_total_mm is not None and zone_count > 1:
                attrs["summary"] = (
                    f"Dernier arrosage: {surface_mm:.1f} mm sur la surface "
                    f"({zones_total_mm:.1f} mm cumulés sur {zone_count} zones) le {when_text}"
                    + (f" ({source})" if source else "")
                )
            else:
                attrs["summary"] = (
                    f"Dernier arrosage: {surface_mm:.1f} mm sur la surface le {when_text}"
                    + (f" ({source})" if source else "")
                )
        else:
            if zones_total_mm is not None and zone_count > 1:
                attrs["summary"] = (
                    f"Dernier arrosage: {surface_mm:.1f} mm sur la surface "
                    f"({zones_total_mm:.1f} mm cumulés sur {zone_count} zones)"
                )
            else:
                attrs["summary"] = f"Dernier arrosage: {surface_mm:.1f} mm sur la surface"
        clean = {key: value for key, value in attrs.items() if value not in (None, "", [], {})}
        return clean or None

    @property
    def native_value(self):
        session = self._latest_zone_session()
        if not session:
            return 0.0
        surface_mm = _session_surface_mm(session)
        return surface_mm if surface_mm is not None else 0.0

    @property
    def extra_state_attributes(self):
        session = self._latest_zone_session()
        skips = _skip_history_entries(getattr(self.coordinator, "history", None))
        if not session:
            attrs: dict[str, Any] = {
                "source": "none",
                "zone_count": 0,
                "surface_mm": 0.0,
                "total_mm": 0.0,
                "summary": "Aucun arrosage détecté",
            }
            if skips:
                attrs["derniers_refus"] = skips
            watering_entries = _watering_history_entries(getattr(self.coordinator, "history", None))
            if watering_entries:
                attrs["derniers_arrosages"] = watering_entries
            return attrs
        result = self._zone_session_attributes(session) or {}
        if skips:
            result["derniers_refus"] = skips
        watering_entries = _watering_history_entries(getattr(self.coordinator, "history", None))
        if watering_entries:
            result["derniers_arrosages"] = watering_entries
        return result


class GazonDernierArrosageTotalZonesSensor(GazonDernierArrosageDetecteSensor):
    _attr_name = "Dernière session cumulée"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "dernier_arrosage_total_zones")

    def _zone_session_attributes(self, session: dict[str, Any]) -> dict[str, Any] | None:
        attrs = super()._zone_session_attributes(session)
        if not attrs:
            return attrs

        surface_mm = attrs.get("surface_mm")
        zones_total_mm = attrs.get("zones_total_mm")
        try:
            zone_count = int(attrs.get("zone_count") or 0)
        except (TypeError, ValueError):
            zone_count = 0
        try:
            zones_total_value = float(zones_total_mm) if zones_total_mm is not None else None
        except (TypeError, ValueError):
            zones_total_value = None
        try:
            surface_value = float(surface_mm) if surface_mm is not None else None
        except (TypeError, ValueError):
            surface_value = None

        if zones_total_value is None:
            zones_total_value = surface_value or 0.0
        attrs["total_mm"] = zones_total_value
        attrs["zones_total_mm"] = zones_total_value
        if surface_value is not None:
            attrs["surface_mm"] = surface_value

        when_text = attrs.get("last_watering_when")
        source = str(attrs.get("source") or "").strip()
        if when_text:
            if zone_count > 1:
                attrs["summary"] = (
                    f"Dernier arrosage: {zones_total_value:.1f} mm cumulés sur {zone_count} zones "
                    f"({surface_value:.1f} mm sur la surface) le {when_text}"
                    + (f" ({source})" if source else "")
                )
            else:
                attrs["summary"] = (
                    f"Dernier arrosage: {zones_total_value:.1f} mm cumulés sur la surface le {when_text}"
                    + (f" ({source})" if source else "")
                )
        else:
            if zone_count > 1:
                attrs["summary"] = (
                    f"Dernier arrosage: {zones_total_value:.1f} mm cumulés sur {zone_count} zones "
                    f"({surface_value:.1f} mm sur la surface)"
                )
            else:
                attrs["summary"] = f"Dernier arrosage: {zones_total_value:.1f} mm cumulés sur la surface"
        attrs["mm_measurement_kind"] = "zones_total"
        return attrs

    @property
    def native_value(self):
        session = self._latest_zone_session()
        if not session:
            return 0.0
        zones_total_mm = _zone_session_total_mm(session.get("zones") if isinstance(session.get("zones"), list) else None)
        if zones_total_mm is not None:
            return zones_total_mm
        surface_mm = _zone_session_surface_mm(session.get("zones") if isinstance(session.get("zones"), list) else None)
        if surface_mm is not None:
            return surface_mm
        for key in ("total_mm", "session_total_mm", "objectif_mm", "objective_mm"):
            value = session.get(key)
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return 0.0


class GazonDerniereApplicationSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Dernière application"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:spray-bottle"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "derniere_application")

    @staticmethod
    def _empty_application_state() -> dict[str, Any]:
        return {
            "derniere_application": None,
            "summary": "Aucune application détectée",
            "application_type": None,
            "application_requires_watering_after": False,
            "application_post_watering_mm": 0.0,
            "application_irrigation_block_hours": 0.0,
            "application_irrigation_delay_minutes": 0.0,
            "application_irrigation_mode": None,
            "application_label_notes": None,
            "application_post_watering_status": "indisponible",
            "declared_at": None,
            "application_block_until": None,
            "application_block_active": False,
            "application_block_remaining_minutes": 0.0,
            "application_post_watering_pending": False,
            "application_post_watering_ready_at": None,
            "application_post_watering_delay_remaining_minutes": 0.0,
            "application_post_watering_ready": False,
            "application_post_watering_remaining_mm": 0.0,
        }

    @staticmethod
    def _application_when_text(summary: dict[str, Any]) -> str | None:
        for key in ("date_action", "date", "declared_at", "recorded_at"):
            value = summary.get(key)
            human = _human_date_text(value) if key in {"date_action", "date"} else _human_datetime_text(value)
            if human:
                return human
        return None

    def _application_state(self) -> dict[str, Any]:
        memory = getattr(self.coordinator, "memory", None)
        if isinstance(memory, dict):
            state = {
                "derniere_application": memory.get("derniere_application"),
                "application_type": memory.get("application_type"),
                "application_requires_watering_after": memory.get("application_requires_watering_after"),
                "application_post_watering_mm": memory.get("application_post_watering_mm"),
                "application_irrigation_block_hours": memory.get("application_irrigation_block_hours"),
                "application_irrigation_delay_minutes": memory.get("application_irrigation_delay_minutes"),
                "application_irrigation_mode": memory.get("application_irrigation_mode"),
                "application_label_notes": memory.get("application_label_notes"),
                "application_post_watering_status": memory.get("application_post_watering_status"),
                "declared_at": memory.get("declared_at"),
                "application_block_until": memory.get("application_block_until"),
                "application_block_active": memory.get("application_block_active"),
                "application_block_remaining_minutes": memory.get("application_block_remaining_minutes"),
                "application_post_watering_pending": memory.get("application_post_watering_pending"),
                "application_post_watering_ready_at": memory.get("application_post_watering_ready_at"),
                "application_post_watering_delay_remaining_minutes": memory.get(
                    "application_post_watering_delay_remaining_minutes"
                ),
                "application_post_watering_ready": memory.get("application_post_watering_ready"),
                "application_post_watering_remaining_mm": memory.get("application_post_watering_remaining_mm"),
            }
            state["application_post_watering_status"] = normalize_post_application_status(
                memory.get("application_post_watering_status")
            )
            summary = state.get("derniere_application")
            if isinstance(summary, dict) and summary:
                return state
        history = getattr(self.coordinator, "history", None)
        if isinstance(history, list):
            return compute_application_state(history)
        return self._empty_application_state()

    @staticmethod
    def _application_attr_keys() -> tuple[str, ...]:
        return _APPLICATION_PUBLIC_ATTR_KEYS + _APPLICATION_STATUS_ATTR_KEYS

    def _application_extra_attributes(self, state: dict[str, Any]) -> dict[str, Any] | None:
        summary = state.get("derniere_application")
        attrs: dict[str, Any] = {}
        compact_summary = _compact_application_summary(summary)
        if compact_summary:
            attrs.update(compact_summary)
        history_entries = _application_history_entries(getattr(self.coordinator, "history", None))
        if history_entries:
            attrs["application_history"] = history_entries
            attrs["application_history_count"] = len(history_entries)
        for key in self._application_attr_keys():
            value = state.get(key)
            if value not in (None, "", [], {}):
                attrs[key] = value
        if compact_summary:
            when_text = self._application_when_text(compact_summary)
            if when_text:
                attrs["last_application_when"] = when_text
            label = str(
                compact_summary.get("libelle")
                or compact_summary.get("produit")
                or compact_summary.get("type")
                or "application"
            ).strip()
            details: list[str] = [f"Dernière application: {label}"]
            if when_text:
                details.append(f"le {when_text}")
            application_type = str(attrs.get("application_type") or "").strip()
            if application_type:
                details.append(f"type {application_type}")
            application_mode = str(attrs.get("application_irrigation_mode") or "").strip()
            if application_mode:
                details.append(f"mode {application_mode}")
            attrs["summary"] = " - ".join(details)
        else:
            attrs["summary"] = state.get("summary") or "Aucune application détectée"
        attrs.setdefault("source", "none" if not compact_summary else compact_summary.get("source"))
        return attrs or None

    @property
    def native_value(self):
        state = self._application_state()
        summary = state.get("derniere_application")
        if isinstance(summary, dict) and summary:
            return summary.get("libelle") or summary.get("produit") or summary.get("type") or "Application"
        return "Aucune application"

    @property
    def extra_state_attributes(self):
        return self._application_extra_attributes(self._application_state())


class GazonDerniereActionUtilisateurSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Dernière exécution"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:gesture-tap-button"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "derniere_action_utilisateur")

    def _latest_action(self) -> dict[str, Any] | None:
        memory = getattr(self.coordinator, "memory", None)
        if not isinstance(memory, dict):
            return None
        summary = memory.get("derniere_action_utilisateur")
        if isinstance(summary, dict) and summary:
            return summary
        return None

    @staticmethod
    def _clean_action_summary(summary: dict[str, Any]) -> dict[str, Any] | None:
        rename_map = {
            "action": "execution_action",
            "state": "execution_state",
            "reason": "execution_reason",
            "source": "execution_source",
            "plan_type": "execution_plan_type",
            "zone_count": "executed_zone_count",
            "passages": "executed_passages",
            "triggered_at": "execution_triggered_at",
        }
        attrs = {
            rename_map.get(key, key): value
            for key, value in summary.items()
            if value not in (None, "", [], {})
        }
        return attrs or None

    @staticmethod
    def _action_when_text(summary: dict[str, Any]) -> str | None:
        for key in ("triggered_at", "date", "recorded_at"):
            value = summary.get(key)
            human = _human_datetime_text(value)
            if human:
                return human
        return None

    @staticmethod
    def _action_summary_text(summary: dict[str, Any]) -> str:
        action = str(summary.get("action") or "Action").strip()
        state = str(summary.get("state") or "").strip()
        when_text = GazonDerniereActionUtilisateurSensor._action_when_text(summary)
        details: list[str] = [f"Dernière exécution: {action}"]
        if when_text:
            details.append(f"le {when_text}")
        if state:
            details.append(f"état {state}")
        return " - ".join(details)

    @property
    def native_value(self):
        summary = self._latest_action()
        if not summary:
            return "aucune_action"
        state = str(summary.get("state") or "").strip()
        if not state or state == "none":
            return "aucune_action"
        return state

    @property
    def extra_state_attributes(self):
        summary = self._latest_action()
        if not summary:
            return {"summary": "Aucune action récente"}
        attrs = self._clean_action_summary(summary) or {}
        when_text = self._action_when_text(summary)
        if when_text:
            attrs["last_action_when"] = when_text
        attrs["summary"] = self._action_summary_text(summary)
        return attrs


class GazonCatalogueProduitsSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Catalogue produits"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:package-variant-closed"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "catalogue_produits")

    def _products(self) -> list[dict[str, Any]]:
        products = getattr(self.coordinator, "products", None)
        if not isinstance(products, dict):
            return []
        ordered: list[dict[str, Any]] = []
        for product_id in sorted(products.keys()):
            product = products.get(product_id)
            if isinstance(product, dict):
                ordered.append(product)
        return ordered

    @staticmethod
    def _compact_product(product: dict[str, Any]) -> dict[str, Any]:
        keys = (
            "id",
            "nom",
            "type",
            "dose_conseillee",
            "usage_mode",
            "max_applications_per_year",
            "application_months_label",
            "application_requires_watering_after",
            "application_post_watering_mm",
            "application_irrigation_mode",
        )
        return {key: product.get(key) for key in keys if product.get(key) not in (None, "", [], {})}

    @property
    def native_value(self):
        return len(self._products())

    @property
    def extra_state_attributes(self):
        products = self._products()
        if not products:
            return {
                "products_count": 0,
                "product_ids": [],
                "product_names": [],
                "summary": "Aucun produit enregistré",
            }
        product_ids = [str(product.get("id") or "").strip() for product in products if str(product.get("id") or "").strip()]
        product_names = [str(product.get("nom") or product.get("id") or "").strip() for product in products if str(product.get("nom") or product.get("id") or "").strip()]
        return {
            "products_count": len(products),
            "product_ids": product_ids,
            "product_names": product_names,
            "products_summary": [self._compact_product(product) for product in products],
            "summary": (
                "1 produit enregistré"
                if len(products) == 1
                else f"{len(products)} produits enregistrés"
            ),
        }


class GazonInterventionRecommendationSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Prochaine intervention"
    _attr_has_entity_name = True
    _attr_icon = "mdi:spray-bottle"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "prochaine_intervention")

    def _recommendation_payload(self) -> dict[str, Any]:
        snapshot = _coordinator_snapshot(self.coordinator)
        recommendation = snapshot.get("intervention_recommendation")
        if isinstance(recommendation, dict) and recommendation:
            return _normalize_recommendation_constraints_payload(recommendation)
        recommendation = self._decision_value("intervention_recommendation")
        if isinstance(recommendation, dict) and recommendation:
            return _normalize_recommendation_constraints_payload(recommendation)
        if snapshot:
            recommendation = build_intervention_recommendation(
                today=dt_util.now().date(),
                phase_active=snapshot.get("phase_active") or snapshot.get("mode"),
                phase_source=snapshot.get("phase_dominante_source"),
                sous_phase=snapshot.get("sous_phase"),
                selected_product_id=getattr(self.coordinator, "selected_product_id", None),
                selected_product_name=getattr(self.coordinator, "selected_product_name", None),
                products=getattr(self.coordinator, "products", None),
                history=getattr(self.coordinator, "history", None),
                application_state=snapshot,
                temperature=snapshot.get("temperature"),
                forecast_temperature_today=snapshot.get("forecast_temperature_today"),
                temperature_source=snapshot.get("temperature_source"),
            )
            if isinstance(recommendation, dict) and recommendation:
                return _normalize_recommendation_constraints_payload(recommendation)
        return {
            "schema_version": 3,
            "status": "unavailable",
            "recommended_action": "add_product",
            "priority": "none",
            "score": 0,
            "reason": "Aucun produit enregistré",
            "why_now": "Ajoute au moins un produit au catalogue pour obtenir une recommandation.",
            "reasons": [],
            "constraints": [
                {
                    "code": "catalogue_empty",
                    "label": "Aucun produit enregistré",
                    "value": {"catalogue_count": 0},
                    "hint": "Ajoute au moins un produit au catalogue pour obtenir une recommandation.",
                    "blocking": True,
                    "met": False,
                }
            ],
            "missing_requirements": [
                {
                    "code": "catalogue_empty",
                    "label": "Ajouter un produit au catalogue",
                    "value": {"catalogue_count": 0},
                    "hint": "Ajoute au moins un produit au catalogue pour obtenir une recommandation.",
                    "blocking": True,
                }
            ],
            "month_match": False,
            "ready_to_declare": False,
            "selected_product_ready": False,
            "product": {
                "id": None,
                "name": None,
                "type": None,
                "months": [],
                "months_label": None,
                "phase_compatible": [],
                "latest_application_date": None,
                "next_reapplication_date": None,
                "next_reapplication_display": None,
                "due": False,
                "phase_match": False,
                "month_match": False,
            },
            "selection": {
                "id": getattr(self.coordinator, "selected_product_id", None),
                "name": getattr(self.coordinator, "selected_product_name", None),
                "months": [],
                "months_label": None,
                "ready": False,
            },
            "context": {
                "catalogue_count": 0,
                "eligible_count": 0,
                "current_month": dt_util.now().date().month,
                "current_phase": None,
                "current_sub_phase": None,
            },
            "ui": {
                "title": "Non disponible",
                "badge": "Non disponible",
                "tone": "neutral",
                "icon": "mdi:package-variant-closed",
                "summary": "Non disponible",
                "hint": "Ajoute au moins un produit au catalogue pour obtenir une recommandation.",
                "action_label": "Ajouter un produit",
                "selection_summary": "Aucun produit disponible dans le catalogue.",
                "selection_hint": "Ajoute au moins un produit avant de préparer une intervention.",
                "declaration_summary": "Sélectionne un produit pour activer la déclaration.",
                "declaration_hint": "Le bouton se débloque dès qu’un produit est prêt.",
                "history_summary": "Dernière application",
                "history_hint": "Historique local des applications enregistrées.",
            },
            "runtime_probe": RECOMMENDATION_RUNTIME_PROBE,
        }

    @property
    def native_value(self):
        return str(self._recommendation_payload().get("status") or "unavailable")

    @property
    def extra_state_attributes(self):
        payload = self._recommendation_payload()
        return _public_intervention_attributes(payload) or None


class GazonDebugInterventionSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Debug intervention"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:bug-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "debug_intervention")

    def _debug_payload(self) -> dict[str, Any]:
        snapshot = _coordinator_snapshot(self.coordinator)
        payload = snapshot.get("intervention_recommendation")
        if isinstance(payload, dict) and payload:
            return _normalize_recommendation_constraints_payload(payload)
        payload = self._decision_value("intervention_recommendation")
        if isinstance(payload, dict) and payload:
            return _normalize_recommendation_constraints_payload(payload)
        return {}

    @staticmethod
    def _constraint_impact(constraint: dict[str, Any]) -> str:
        if bool(constraint.get("blocking")):
            return "bloquant"
        if constraint.get("met") is False:
            return "dégradant"
        return "neutre"

    def _constraint_view(self, constraint: dict[str, Any]) -> dict[str, Any]:
        item = dict(constraint)
        item["impact"] = self._constraint_impact(item)
        return item

    @property
    def native_value(self):
        return str(self._debug_payload().get("status") or "unavailable")

    @property
    def extra_state_attributes(self):
        payload = self._debug_payload()
        if not payload:
            return {
                "status": "unavailable",
                "summary": "Aucune recommandation de debug disponible",
            }

        product = payload.get("product")
        if not isinstance(product, dict):
            product = {}
        ui = payload.get("ui")
        if not isinstance(ui, dict):
            ui = {}
        context = payload.get("context")
        if not isinstance(context, dict):
            context = {}
        product_temperature = {
            "current": product.get("temperature_value"),
            "min": product.get("temperature_min"),
            "max": product.get("temperature_max"),
            "source": product.get("temperature_source"),
            "matched": product.get("temperature_evaluation", {}).get("matched")
            if isinstance(product.get("temperature_evaluation"), dict)
            else None,
        }
        cleaned_context = {
            "phase": context.get("current_phase"),
            "month": context.get("current_month"),
            "temperature": product_temperature.get("current"),
            "temperature_source": product_temperature.get("source"),
        }
        cleaned_context = {key: value for key, value in cleaned_context.items() if value not in (None, "", [], {})}
        constraints = payload.get("constraints")
        if not isinstance(constraints, list):
            constraints = []
        normalized_constraints = [
            self._constraint_view(constraint)
            for constraint in constraints
            if isinstance(constraint, dict)
        ]
        summary = (
            ui.get("summary")
            or payload.get("reason")
            or payload.get("why_now")
            or "Recommandation disponible"
        )
        return {
            "score": payload.get("score"),
            "status": payload.get("status"),
            "recommended_action": payload.get("recommended_action"),
            "product_id": product.get("id"),
            "product_name": product.get("name"),
            "product": {
                "id": product.get("id"),
                "name": product.get("name"),
                "type": product.get("type"),
                "months": product.get("months") or [],
                "months_label": product.get("months_label"),
            },
            "constraints": normalized_constraints,
            "reasons": payload.get("reasons") or [],
            "missing_requirements": payload.get("missing_requirements") or [],
            "context": cleaned_context,
            "summary": summary,
            "reason": payload.get("reason"),
            "why_now": payload.get("why_now"),
            "ready_to_declare": payload.get("ready_to_declare"),
            "selected_product_ready": payload.get("selected_product_ready"),
            "selection": payload.get("selection") or {},
            "runtime_probe": RECOMMENDATION_RUNTIME_PROBE,
        }


class GazonScoreNiveauSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Niveau de pertinence"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:signal"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "score_niveau")

    def _score_payload(self) -> dict[str, Any]:
        payload = self._decision_value("intervention_recommendation")
        if isinstance(payload, dict) and payload:
            return payload
        payload = _coordinator_snapshot(self.coordinator).get("intervention_recommendation")
        if isinstance(payload, dict) and payload:
            return payload
        return {}

    @property
    def native_value(self):
        payload = self._score_payload()
        score = payload.get("score")
        if score is None:
            return None
        level, _tone = _score_level_and_tone(score)
        return level

    @property
    def extra_state_attributes(self):
        payload = self._score_payload()
        if not payload:
            return None
        score = payload.get("score")
        if score is None:
            return None
        level, tone = _score_level_and_tone(score)
        if level is None:
            return None
        try:
            score_value = int(round(float(score)))
        except (TypeError, ValueError):
            return None
        return {
            "score": score_value,
            "score_level": level,
            "summary": f"Pertinence {_score_level_summary_label(level)} ({score_value}/100)",
            "tone": tone,
            "source_entity": _public_source_entity(self, "sensor", "prochaine_intervention"),
        }


class GazonProchaineFenetreOptimaleSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Prochaine fenêtre optimale"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:clock-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "prochaine_fenetre_optimale")

    def _window_context(self) -> dict[str, Any]:
        payload = self._decision_value("intervention_recommendation")
        context = payload.get("context") if isinstance(payload, dict) else {}
        if not isinstance(context, dict):
            context = {}
        data = getattr(self.coordinator, "data", None)
        if not isinstance(data, dict):
            data = {}
        block_reason = str(self._decision_value("block_reason") or "").strip() or None
        if _is_passive_irrigation_context(self):
            block_reason = None
        return {
            "source_state": str(self._decision_value("fenetre_optimale") or "attendre").strip().lower() or "attendre",
            "block_reason": block_reason,
            "confidence_score": self._decision_value("confidence_score"),
            "phase": context.get("current_phase") or self._decision_value("phase_active"),
            "month": context.get("current_month") or dt_util.now().date().month,
            "temperature": self._decision_value("temperature"),
        }

    @property
    def native_value(self):
        source_state = str(self._decision_value("fenetre_optimale") or "").strip().lower()
        if source_state not in {"maintenant", "ce_matin", "demain_matin", "apres_pluie", "soir", "attendre"}:
            source_state = "attendre"
        return source_state

    @property
    def extra_state_attributes(self):
        context = self._window_context()
        source_state = str(context.get("source_state") or "attendre").strip().lower()
        summary_label = _window_display_label(source_state) or "Attendre"
        attrs = {
            "source_entity": _public_source_entity(self, "sensor", "fenetre_optimale"),
            "source_state": source_state,
            "block_reason": context.get("block_reason"),
            "confidence_score": context.get("confidence_score"),
            "phase": context.get("phase"),
            "month": context.get("month"),
            "temperature": context.get("temperature"),
            "summary": f"Prochaine fenêtre: {summary_label}",
        }
        return _clean_public_attrs(attrs)


class GazonProchainBlocageAttenduSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Prochain blocage attendu"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "prochain_blocage_attendu")

    def _source_context(self) -> dict[str, Any]:
        payload = self._decision_value("intervention_recommendation")
        context = payload.get("context") if isinstance(payload, dict) else {}
        if not isinstance(context, dict):
            context = {}
        block_reason = str(self._decision_value("block_reason") or "").strip() or None
        if _is_passive_irrigation_context(self):
            block_reason = None
        source_status = str(self._decision_value("fenetre_optimale") or "").strip().lower() or "attendre"
        return {
            "source_status": source_status,
            "block_reason": block_reason,
            "confidence_score": self._decision_value("confidence_score"),
            "phase": context.get("current_phase") or self._decision_value("phase_active"),
            "month": context.get("current_month") or dt_util.now().date().month,
            "temperature": self._decision_value("temperature"),
        }

    @property
    def native_value(self):
        context = self._source_context()
        block_reason = str(context.get("block_reason") or "").strip()
        source_status = str(context.get("source_status") or "").strip().lower()
        if block_reason:
            return block_reason
        if source_status == "bloque":
            return "bloque"
        return "aucun"

    @property
    def extra_state_attributes(self):
        context = self._source_context()
        block_reason = str(context.get("block_reason") or "").strip()
        source_status = str(context.get("source_status") or "").strip().lower()
        block_label = None
        if block_reason:
            block_label = _block_reason_display_label(block_reason)
        elif source_status == "bloque":
            block_label = _block_reason_display_label(source_status)
        summary = "Aucun blocage attendu"
        if block_label:
            summary = f"Blocage attendu: {block_label}"
        attrs = {
            "source_entity": _public_source_entity(self, "sensor", "fenetre_optimale"),
            "source_status": source_status or None,
            "block_reason": block_reason or None,
            "block_label": block_label,
            "confidence_score": context.get("confidence_score"),
            "phase": context.get("phase"),
            "month": context.get("month"),
            "temperature": context.get("temperature"),
            "summary": summary,
        }
        return _clean_public_attrs(attrs)


class GazonProchaineTonteSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Prochaine tonte"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "prochaine_tonte")

    def _mowing_attrs(self) -> dict[str, Any]:
        keys = (
            "next_mowing_date",
            "next_mowing_display",
            "mowing_window_reason",
            "raison_blocage_tonte",
            "raison_blocage_code",
            "tonte_statut",
            "mowing_blocked",
            "action_possible",
            "mowing_daily_session_limit",
            "mowing_daily_session_policy",
            "tondeuse_prochain_depart",
            "tondeuse_prochain_depart_display",
            "tondeuse_statut",
            "tondeuse_statut_libelle",
            "mowing_machine_unavailable_detail",
            "mowing_machine_unavailable_label",
            "mowing_block_reason_code",
            "mowing_block_reason_label",
            "mower_operation_state",
            "mower_operation_label",
            "mower_reason_code",
            "mower_reason_label",
        )
        attrs = self._attrs_from_data(*keys) or {}
        facade = _public_mowing_facade(self)
        for key in keys:
            if facade.get(key) is not None:
                attrs[key] = facade.get(key)
        missing = tuple(key for key in keys if key not in attrs)
        if missing:
            attrs.update(self._attrs_from_result(*missing) or {})
        return attrs or {}

    @property
    def native_value(self):
        attrs = self._mowing_attrs()
        action_possible = bool(attrs.get("action_possible"))
        next_display = str(attrs.get("next_mowing_display") or "").strip()
        next_date = str(attrs.get("next_mowing_date") or "").strip()
        tonte_statut = str(attrs.get("tonte_statut") or "").strip().lower()
        if action_possible:
            return "Maintenant"
        if next_display:
            return next_display
        if next_date:
            return _human_date_text(next_date) or next_date
        if tonte_statut == "interdite":
            return "Interdite"
        return "À estimer"

    @property
    def extra_state_attributes(self):
        attrs = self._mowing_attrs()
        next_display = str(attrs.get("next_mowing_display") or "").strip()
        mower_departure = str(attrs.get("tondeuse_prochain_depart") or "").strip()
        mower_departure_display = str(attrs.get("tondeuse_prochain_depart_display") or "").strip()
        action_possible = bool(attrs.get("action_possible"))
        block_reason = str(
            attrs.get("raison_blocage_code") or attrs.get("mowing_block_reason_code") or ""
        ).strip()
        machine_label = str(attrs.get("mowing_machine_unavailable_label") or "").strip()
        if block_reason == "machine_unavailable" and not machine_label:
            machine_label = _fallback_machine_unavailable_label_from_attrs(
                {
                    **(_coordinator_snapshot(self.coordinator) or {}),
                    **attrs,
                }
            ) or ""
        block_reason_label = str(
            attrs.get("mowing_block_reason_label") or attrs.get("raison_blocage_tonte") or ""
        ).strip()
        if block_reason == "machine_unavailable" and machine_label:
            block_reason_label = machine_label
        reason = str(
            block_reason_label or attrs.get("raison_blocage_tonte") or attrs.get("mowing_window_reason") or ""
        ).strip()
        summary = (
            "Tonte possible maintenant"
            if action_possible
            else (f"Prochaine tonte estimée le {next_display}" if next_display else reason or "Prochaine tonte à estimer")
        )
        if not action_possible and next_display:
            if block_reason == "mowing_night":
                summary = "Tonte possible au lever du jour"
            elif block_reason in {"wet_grass", "rosee_persistante", "soil_wet"}:
                summary = "Tonte possible après ressuyage"
            elif block_reason in {"recent_watering", "watering_cooldown", "watering_in_progress"}:
                summary = "Tonte possible après le délai post-arrosage"
            elif block_reason in {"pluie_en_cours", "pluie_annoncee", "pluie_proche", "rain", "rain_detected"}:
                summary = "Tonte possible après l'épisode pluvieux"
            elif block_reason == "machine_unavailable":
                summary = machine_label or "Tonte possible dès que le robot est prêt"
            elif block_reason == "mowing_spacing":
                summary = f"Tonte à reconsidérer le {next_display}"
            elif block_reason in {"phase_sursemis", "phase_traitement", "phase_hivernage"}:
                summary = f"Tonte à reconsidérer le {next_display}"
        public_attrs = {
            "source_entity": _public_source_entity(self, "binary_sensor", "tonte_autorisee"),
            "target_date": str(attrs.get("next_mowing_date") or "").strip() or None,
            "target_display": next_display or self.native_value,
            "target_datetime": mower_departure or None,
            "target_datetime_display": mower_departure_display or _human_datetime_text(mower_departure),
            "action_possible": action_possible,
            "tonte_statut": attrs.get("tonte_statut"),
            "block_reason": block_reason or None,
            "machine_unavailable_detail": attrs.get("mowing_machine_unavailable_detail"),
            "machine_unavailable_label": machine_label or None,
            "daily_session_limit": attrs.get("mowing_daily_session_limit"),
            "daily_session_policy": attrs.get("mowing_daily_session_policy"),
            "reason": reason or None,
            "summary": summary,
        }
        return _clean_public_attrs(public_attrs) or {}


class GazonPlanArrosageSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Cycle calculé"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:timer-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "plan_arrosage")

    def _latest_objective(self) -> float | None:
        result = self.decision_result
        if result is not None:
            value = getattr(result, "objectif_arrosage", None)
            try:
                if value is not None:
                    return float(value)
            except (TypeError, ValueError):
                pass
        data = getattr(self.coordinator, "data", None)
        if isinstance(data, dict):
            value = data.get("objectif_mm")
            try:
                if value is not None:
                    return float(value)
            except (TypeError, ValueError):
                return None
        return None

    def _int_setting(self, key: str, default: int, minimum: int) -> int:
        result = self.decision_result
        if result is not None:
            value = getattr(result, key, None)
            try:
                if value is not None:
                    return max(minimum, int(value))
            except (TypeError, ValueError):
                pass
            extra = getattr(result, "extra", None)
            if isinstance(extra, dict):
                value = extra.get(key)
                try:
                    if value is not None:
                        return max(minimum, int(value))
                except (TypeError, ValueError):
                    pass
        data = getattr(self.coordinator, "data", None)
        if isinstance(data, dict):
            value = data.get(key)
            try:
                if value is not None:
                    return max(minimum, int(value))
            except (TypeError, ValueError):
                pass
        return default

    def _watering_passages(self) -> int:
        return self._int_setting("watering_passages", default=1, minimum=1)

    def _watering_pause_minutes(self) -> int:
        passages = self._watering_passages()
        if passages <= 1:
            return 0
        return self._int_setting("watering_pause_minutes", default=0, minimum=0)

    def _build_plan(self) -> dict[str, Any] | None:
        objective = self._latest_objective()

        def _empty_plan(reason: str) -> dict[str, Any]:
            return {
                "objective_mm": round(max(0.0, objective or 0.0), 1),
                "objectif_mm": round(max(0.0, objective or 0.0), 1),
                "zones": [],
                "zone_count": 0,
                "total_duration_min": 0.0,
                "duration_human": "0 min",
                "fractionation": False,
                "passages": self._watering_passages(),
                "pause_between_passages_minutes": self._watering_pause_minutes(),
                "pause_between_passages_s": self._watering_pause_minutes() * 60,
                "source": "no_plan",
                "reason": reason,
                "plan_type": "no_plan",
                "summary": "Aucun cycle calculé",
            }

        if objective is None or objective <= 0:
            return _empty_plan("objective_non_positive")

        def _conf(key: str):
            getter = getattr(self.coordinator, "_get_conf", None)
            if callable(getter):
                return getter(key)
            entry = getattr(self.coordinator, "entry", None)
            if entry is not None:
                options = getattr(entry, "options", None)
                if isinstance(options, dict) and key in options:
                    return options.get(key)
                data = getattr(entry, "data", None)
                if isinstance(data, dict) and key in data:
                    return data.get(key)
            data = getattr(self.coordinator, "data", None)
            if isinstance(data, dict):
                return data.get(key)
            return None

        zones_cfg: list[tuple[str, float]] = []
        for idx in range(1, 6):
            entity_id = _conf(f"zone_{idx}")
            raw_rate = _conf(f"debit_zone_{idx}")
            if not entity_id:
                continue
            try:
                rate_mm_h = float(raw_rate)
            except (TypeError, ValueError):
                continue
            if rate_mm_h <= 0:
                continue
            zones_cfg.append((str(entity_id), rate_mm_h))

        plan = build_watering_plan(
            objective,
            zones_cfg,
            passages=self._watering_passages(),
            pause_minutes=self._watering_pause_minutes(),
            watering_strategy=getattr(self.decision_result, "watering_strategy", None),
            objective_scope=getattr(self.decision_result, "objective_scope", None),
            watering_stage=getattr(self.decision_result, "watering_stage", None),
            surface_cycle_mm=getattr(self.decision_result, "surface_cycle_mm", None),
            daily_cycles_target=getattr(self.decision_result, "daily_cycles_target", None),
            cycle_spacing_minutes=getattr(self.decision_result, "cycle_spacing_minutes", None),
            surface_moisture_target=getattr(self.decision_result, "surface_moisture_target", None),
            surface_dryness_risk=getattr(self.decision_result, "surface_dryness_risk", None),
            runoff_risk=getattr(self.decision_result, "runoff_risk", None),
            seeding_transition_ready=getattr(self.decision_result, "seeding_transition_ready", None),
            seeding_block_reason=getattr(self.decision_result, "seeding_block_reason", None),
        )
        if plan is None:
            return _empty_plan("no_valid_zones")
        return plan.as_dict()

    @property
    def native_value(self):
        plan = self._build_plan()
        if plan is None:
            return None
        return plan["total_duration_min"]

    @property
    def extra_state_attributes(self):
        plan = self._build_plan()
        if plan is None:
            return None
        return plan


class GazonArrosageEnCoursSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Arrosage en cours"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:progress-clock"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "arrosage_en_cours")

    @staticmethod
    def _current_session(coordinator) -> dict[str, Any] | None:
        runtime_session_getter = getattr(coordinator, "_get_active_irrigation_session", None)
        if callable(runtime_session_getter):
            runtime_session = runtime_session_getter()
            if isinstance(runtime_session, dict) and runtime_session:
                return runtime_session
        session = getattr(coordinator, "_watering_session", None)
        if not isinstance(session, dict):
            return None
        active_zones = session.get("active_zones")
        if not isinstance(active_zones, dict) or not active_zones:
            return None
        return session

    @property
    def native_value(self):
        progress = self._progress_state()
        return progress["progress_percent"] if progress["active"] else 0.0

    def _live_water_state(self, session: dict[str, Any], now: datetime) -> dict[str, Any]:
        """mm appliqués par zone + réserve/surplus projetés EN TEMPS RÉEL."""
        rate_getter = getattr(self.coordinator, "_get_zone_rate_mm_h", None)

        def _rate(zone_id: str) -> float:
            if callable(rate_getter):
                try:
                    return float(rate_getter(zone_id))
                except (TypeError, ValueError):
                    return 0.0
            return 0.0

        def _f(value: object) -> float | None:
            try:
                return float(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return None

        live = compute_live_session_water(session, now=now, rate_fn=_rate)
        # Réserve de base lue depuis le résultat métier (DecisionResult, via _decision_value), et
        # NON depuis coordinator.data (qui ne porte pas ces clés → live_reserve/live_surplus
        # restaient à None pendant l'arrosage). Base au démarrage + mm appliqués = réserve live.
        reserve_stock = _f(self._decision_value("reserve_stock_mm"))
        reserve_utile = _f(self._decision_value("reserve_utile_mm"))
        reserve_max = _f(self._decision_value("reserve_stock_max_mm"))

        live_reserve_mm: float | None = None
        live_surplus_mm: float | None = None
        if reserve_stock is not None:
            projected = reserve_stock + float(live["surface_mm"])
            if reserve_max is not None and reserve_max > 0:
                projected = min(projected, reserve_max)
            live_reserve_mm = round(projected, 1)
            if reserve_utile is not None:
                live_surplus_mm = round(max(0.0, projected - reserve_utile), 1)

        return {
            "zone_mm_applied": live["zone_mm"],
            "surface_mm_applied": live["surface_mm"],
            "total_mm_applied": live["total_mm"],
            "live_reserve_mm": live_reserve_mm,
            "live_surplus_mm": live_surplus_mm,
        }

    def _progress_state(self) -> dict[str, Any]:
        session = self._current_session(self.coordinator)
        if session is None:
            return {
                "active": False,
                "progress_percent": 0.0,
                "summary": "Aucun arrosage en cours",
                "detail": "Aucune session active",
            }

        started_at = session.get("started_at")
        if not isinstance(started_at, datetime):
            started_at = session.get("last_activity_at")
        now = dt_util.now()
        elapsed_seconds = 0.0
        if isinstance(started_at, datetime):
            elapsed_seconds = max((now - started_at).total_seconds(), 0.0)

        active_zones = session.get("active_zones")
        if isinstance(active_zones, dict):
            active_zone_names = [str(zone_id) for zone_id in active_zones]
        elif isinstance(active_zones, list):
            active_zone_names = [str(zone_id) for zone_id in active_zones]
        else:
            active_zone_names = []
        active_zone_count = len(active_zone_names)
        zones = session.get("zones")
        if isinstance(zones, dict):
            zone_count = len(zones)
        else:
            plan = session.get("plan")
            zone_count = len(plan.get("zones", [])) if isinstance(plan, dict) else active_zone_count
        started_text = _human_datetime_text(started_at) if isinstance(started_at, datetime) else None
        last_activity = _human_datetime_text(session.get("last_activity_at")) if isinstance(session, dict) else None
        planned_total_seconds = 0.0
        try:
            planned_total_seconds = float(session.get("planned_total_seconds") or 0.0)
        except (TypeError, ValueError):
            planned_total_seconds = 0.0

        detail_parts = []
        if started_text:
            detail_parts.append(f"Démarré {started_text}")
        if active_zone_count:
            detail_parts.append(f"{active_zone_count} zone{'s' if active_zone_count > 1 else ''} active{'s' if active_zone_count > 1 else ''}")
        if last_activity:
            detail_parts.append(f"Dernière activité {last_activity}")

        summary = "Arrosage en cours"
        if detail_parts:
            summary = f"{summary} · {detail_parts[0]}"

        progress_percent = 0.0
        if planned_total_seconds > 0:
            progress_percent = min(100.0, (elapsed_seconds / planned_total_seconds) * 100.0)
        live_state = self._live_water_state(session, now)
        _last_activity = session.get("last_activity_at")
        return {
            "active": True,
            "summary": summary,
            "detail": " · ".join(detail_parts) if detail_parts else "Session en cours",
            "progress_percent": progress_percent,
            "elapsed_seconds": elapsed_seconds,
            "planned_total_seconds": planned_total_seconds,
            "active_zone_count": active_zone_count,
            "zone_count": zone_count,
            "session_id": session.get("session_id"),
            "run_id": session.get("run_id"),
            "source": session.get("source"),
            "strategy": session.get("strategy"),
            "current_passage": session.get("current_passage"),
            "passage_count": session.get("passage_count"),
            "remaining_session_seconds": max(
                0.0,
                planned_total_seconds - elapsed_seconds,
            ) if planned_total_seconds > 0 else 0.0,
            "last_error": session.get("last_error"),
            "started_at": started_text,
            "started_at_utc": started_at.isoformat() if isinstance(started_at, datetime) else None,
            "last_activity_at": last_activity,
            # Lu UNE fois : l'ancienne écriture appelait `session.get` deux fois, et le test
            # `isinstance` portait donc sur une lecture différente de celle qu'on déréférence.
            "last_activity_at_utc": _last_activity.isoformat() if isinstance(_last_activity, datetime) else None,
            "active_zones": active_zone_names,
            "target_mm": session.get("target_mm"),
            **live_state,
        }

    @property
    def extra_state_attributes(self):
        progress = self._progress_state()
        if not progress["active"]:
            return {
                "active": False,
                "summary": "Aucun arrosage en cours",
                "detail": "Aucune session active",
                "progress_percent": 0.0,
                "elapsed_seconds": 0.0,
                "active_zone_count": 0,
                "zone_count": 0,
                "active_zones": [],
                "remaining_session_seconds": 0.0,
                "zone_mm_applied": {},
                "surface_mm_applied": 0.0,
                "total_mm_applied": 0.0,
                "live_reserve_mm": None,
                "live_surplus_mm": None,
            }
        return progress


class GazonTonteEtatSensor(GazonEntityBase, SensorEntity):
    _attr_name = "État de tonte"
    _attr_has_entity_name = True
    _attr_icon = "mdi:content-cut"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "tonte_etat")

    @property
    def native_value(self):
        facade = _public_mowing_facade(self)
        if facade.get("tonte_statut") not in (None, "", [], {}):
            return facade.get("tonte_statut")
        return self._decision_value("tonte_statut")

    @staticmethod
    def _mowing_height_keys() -> tuple[str, ...]:
        return (
            "hauteur_tonte_recommandee_cm",
            "hauteur_tonte_min_cm",
            "hauteur_tonte_max_cm",
            "hauteur_tonte_garde_fou_label",
        )

    def _mowing_height_attributes(self) -> dict[str, Any] | None:
        attrs = self._attrs_from_result(*self._mowing_height_keys())
        if attrs:
            return attrs
        return self._attrs_from_data(*self._mowing_height_keys())

    @property
    def extra_state_attributes(self):
        attrs = self._mowing_height_attributes() or {}
        mower_attrs = self._attrs_from_result(
            "tondeuse_source_entity",
            "tondeuse_nom",
            "tondeuse_statut",
            "tondeuse_statut_libelle",
            "tondeuse_connectee",
            "tondeuse_prete",
            "tondeuse_raison",
            "tondeuse_en_charge",
            "tondeuse_pluie",
            "tondeuse_erreur",
            "tondeuse_erreur_libelle",
            "tondeuse_batterie",
            "tondeuse_prochain_depart",
            "tondeuse_prochain_depart_display",
            "tondeuse_hauteur_coupe_mm",
            "tondeuse_resolution_state",
            "tondeuse_resolution_reason",
            "tondeuse_resolution_candidate_count",
            "mower_coordination_enabled",
            "mower_coordination_ready",
            "mower_presence_state",
            "mower_presence_label",
            "mower_operation_state",
            "mower_operation_label",
            "mower_is_docked",
            "mower_is_outside",
            "mower_is_safe_for_watering",
            "mower_reason_code",
            "mower_reason_label",
            "mower_resolution_state",
            "mower_resolution_reason",
            "mower_resolution_candidate_count",
            "mower_resolution_probe",
            # Fiabilité de la machine sur la journée : visible sans requête d'historique.
            "mower_blocked_minutes_today",
            "mower_mowing_minutes_today",
            "mower_block_count_today",
            "mower_reliability_today",
            # Auto-déclaration : son état dit pourquoi elle n'a pas agi, pas seulement qu'elle
            # n'a pas agi.
            "mower_auto_declaration_state",
            "mower_auto_declaration_threshold_minutes",
            "mower_auto_declared_today",
            # Carnet de passes : ce que la machine fait vraiment, passe par passe.
            "mower_pass_in_progress",
            "mower_pass_count_today",
            "mower_last_pass_minutes",
            "mower_last_pass_battery_start",
            "mower_last_pass_battery_end",
            "mower_last_pass_end_reason",
            "mower_passes_observed",
            "mower_full_pass_minutes_median",
            "mower_autonomous_return_battery_median",
            "mower_passes_per_day_median",
            "mower_recommendation_ignored_minutes",
            "mower_recommendation_ignored",
            "mowing_blocked_by_watering",
            "mowing_blocked",
            "mowing_block_reason_code",
            "mowing_block_reason_label",
            "mowing_block_reason",
            "mowing_cooldown_remaining_minutes",
            "mowing_post_application_active",
        )
        if mower_attrs:
            attrs.update(mower_attrs)
        attrs.update(_mowing_visibility_flags(self))
        possible_values = self._possible_values_attr("tonte_statut")
        if possible_values:
            attrs.update(possible_values)
        attrs = _apply_public_mower_aliases(attrs)
        return attrs or None


class GazonAssistantSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Assistant"
    _attr_has_entity_name = True
    _attr_icon = "mdi:account-tie-hat-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "assistant")

    def _assistant_payload(self) -> dict[str, Any]:
        facade = _public_mowing_facade(self)
        assistant = facade.get("assistant")
        if not isinstance(assistant, dict) or not assistant:
            assistant = self._decision_value("assistant")
        if isinstance(assistant, dict) and assistant:
            return assistant

        snapshot = _coordinator_snapshot(self.coordinator)
        if snapshot:
            assistant = build_assistant_decision(snapshot)
            if isinstance(assistant, dict) and assistant:
                return assistant

        return {
            "action": "none",
            "moment": "none",
            "quantity_mm": 0.0,
            "status": "no_need",
            "reason": "conditions optimales",
        }

    @property
    def native_value(self):
        payload = self._assistant_payload()
        action = str(payload.get("action") or "none").strip() or "none"
        status = str(payload.get("status") or "no_need").strip() or "no_need"
        if action == "none" and status == "blocked_due_to_conditions":
            return "attente_conditions"
        if action == "none":
            return "aucune_action"
        return action

    @property
    def extra_state_attributes(self):
        payload = self._assistant_payload()
        action = str(payload.get("action") or "none").strip() or "none"
        public_action = "aucune_action" if action == "none" else action
        moment = str(payload.get("moment") or "none").strip() or "none"
        if action == "none" and moment == "none":
            moment = "attendre"
        status = str(payload.get("status") or "no_need").strip() or "no_need"
        reason = str(payload.get("reason") or "").strip()
        try:
            quantity_mm = round(float(payload.get("quantity_mm") or 0.0), 1)
        except (TypeError, ValueError):
            quantity_mm = 0.0
        if not reason:
            if status == "blocked_due_to_conditions":
                reason = "Arrosage bloqué par conditions."
            elif action == "none":
                reason = "conditions optimales"
            elif status == "blocked":
                reason = "action bloquée"
            else:
                reason = "action requise"
        attrs = {
            "action": public_action,
            "moment": moment,
            "quantity_mm": quantity_mm,
            "status": status,
            "reason": reason,
        }
        # VRAIE canicule (≥ 32 °C réels + réserve quasi vide) : signale un arrosage de SURVIE,
        # à distinguer d'une recharge de routine. Les codes d'action ne portent PAS cette
        # information (leurs valeurs sont `aucune_action`/`surveiller`/`a_faire`/`critique`),
        # d'où cet attribut dédié — le seul moyen pour un affichage de le savoir.
        _survie = self._decision_value("survie_canicule_active", None)
        if _survie is not None:
            attrs["survie_canicule_active"] = bool(_survie)
        target_date = (
            payload.get("next_action_date")
            or payload.get("watering_target_date")
            or self._decision_value("next_action_date")
            or self._decision_value("watering_target_date")
        )
        if target_date not in (None, "", [], {}):
            attrs["next_action_date"] = target_date
            # `watering_target_display` a été retirée de cette chaîne : elle n'est produite NULLE
            # PART dans l'intégration (vérifié sur les 39 modules le 29/07/2026), donc ces deux
            # replis ne se déclenchaient jamais. Du code fantôme de ce genre a déjà égaré un audit.
            display_date = payload.get("next_action_display")
            if display_date in (None, "", [], {}):
                display_date = self._decision_value("next_action_display")
            if display_date in (None, "", [], {}):
                display_date = _human_date_text(target_date)
            if display_date not in (None, "", [], {}):
                attrs["next_action_display"] = display_date
        attrs.update(_mowing_visibility_flags(self))
        return attrs


class GazonConseilPrincipalSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Conseil principal"
    _attr_has_entity_name = True
    _attr_icon = "mdi:message-text-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "conseil_principal")

    @property
    def native_value(self):
        return _public_conseil_principal(self)

    @property
    def extra_state_attributes(self):
        attrs = self._attrs_from_result(
            "action_recommandee",
            "action_a_eviter",
            "niveau_action",
            "fenetre_optimale",
            "risque_gazon",
            "watering_cause",
            "watering_blocked_by_mower",
            "watering_block_reason_code",
            "watering_block_reason_label",
            "mowing_blocked_by_watering",
            "mowing_block_reason_code",
            "mowing_block_reason_label",
            "mowing_block_reason",
            "mowing_frequency_target_per_week",
            "mowing_frequency_label",
            "mowing_window_state",
            "mowing_window_label",
            "mowing_window_reason",
            "mowing_cooldown_remaining_minutes",
            "next_action_date",
            "next_action_display",
        )
        if attrs is None:
            attrs = self._attrs_from_data(
                "action_recommandee",
                "action_a_eviter",
                "niveau_action",
                "fenetre_optimale",
                "risque_gazon",
                "watering_cause",
                "next_action_date",
                "next_action_display",
                "watering_blocked_by_mower",
                "watering_block_reason_code",
                "watering_block_reason_label",
                "mowing_blocked_by_watering",
                "mowing_block_reason_code",
                "mowing_block_reason_label",
                "mowing_block_reason",
                "mowing_frequency_target_per_week",
                "mowing_frequency_label",
                "mowing_window_state",
                "mowing_window_reason",
                "mowing_cooldown_remaining_minutes",
            ) or {}
        attrs["niveau_action"] = _normalized_public_niveau_action(self)
        attrs["watering_cause"] = _watering_cause_value(self)
        public_action = _public_action_recommandee(self)
        if public_action is not None:
            attrs["action_recommandee"] = public_action
        else:
            attrs.pop("action_recommandee", None)
        target_date = self._decision_value("next_action_date") or self._decision_value("watering_target_date")
        if target_date not in (None, "", [], {}):
            attrs["next_action_date"] = target_date
            display_date = (
                self._decision_value("next_action_display")
            )
            if display_date in (None, "", [], {}):
                display_date = _human_date_text(target_date)
            if display_date not in (None, "", [], {}):
                attrs["next_action_display"] = display_date

        decision_resume = self._decision_value("decision_resume")
        attrs["niveau_action_hydrique"] = _niveau_action_hydrique(self)
        if isinstance(decision_resume, dict):
            if decision_resume.get("action") is not None:
                attrs["action_type"] = decision_resume.get("action")
            if decision_resume.get("moment") is not None:
                attrs["action_moment"] = decision_resume.get("moment")
            if decision_resume.get("objectif_mm") is not None:
                attrs["objectif_mm"] = decision_resume.get("objectif_mm")
            if decision_resume.get("type_arrosage") is not None:
                attrs["type_arrosage"] = _normalized_public_type_arrosage(
                    self,
                    decision_resume.get("type_arrosage"),
                )
        attrs.update(_mowing_visibility_flags(self))

        public_summary = _public_conseil_principal(self)
        if public_summary not in (None, "", [], {}):
            attrs["summary"] = public_summary
        return attrs or None


class GazonActionRecommandeeSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Action recommandée"
    _attr_has_entity_name = True
    _attr_icon = "mdi:check-circle-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "action_recommandee")

    @property
    def native_value(self):
        return _public_action_recommandee(self)


class GazonActionAEviterSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Action à éviter"
    _attr_has_entity_name = True
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "action_a_eviter")

    @property
    def native_value(self):
        return self._decision_value("action_a_eviter")


class GazonNiveauActionSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Niveau d'action"
    _attr_has_entity_name = True
    _attr_icon = "mdi:signal"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "niveau_action")

    @property
    def native_value(self):
        return _normalized_public_niveau_action(self)

    @property
    def extra_state_attributes(self):
        attrs = self._possible_values_attr("niveau_action") or {}
        attrs["niveau_action_hydrique"] = _niveau_action_hydrique(self)
        return attrs or None


class GazonFenetreOptimaleSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Fenêtre optimale"
    _attr_has_entity_name = True
    _attr_icon = "mdi:clock-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "fenetre_optimale")

    @property
    def native_value(self):
        return self._decision_value("fenetre_optimale")

    def _contextual_watering_state(self) -> dict[str, Any] | None:
        snapshot = _coordinator_snapshot(self.coordinator)
        result = self.decision_result
        extra = getattr(result, "extra", None) if result is not None else None
        if not isinstance(extra, dict):
            extra = {}
        if snapshot:
            merged_extra = dict(snapshot)
            merged_extra.update(extra)
            extra = merged_extra

        objective = self._decision_value("objectif_mm", 0.0)
        try:
            objective = float(objective or 0.0)
        except (TypeError, ValueError):
            objective = 0.0

        target_date = str(extra.get("watering_target_date") or "").strip()
        watering_window = str(self._decision_value("fenetre_optimale", "") or "").strip()
        application_mode = str(extra.get("application_irrigation_mode") or "").strip().lower()
        type_arrosage = str(self._decision_value("type_arrosage", "") or "").strip().lower()
        watering_cause = str(extra.get("watering_cause") or self._decision_value("watering_cause") or "").strip().lower()
        auto_autorise = bool(self._decision_value("arrosage_auto_autorise", False))
        arrosage_recommande = bool(self._decision_value("arrosage_recommande", False))
        application_block_active = bool(extra.get("application_block_active", False))
        application_requires = bool(extra.get("application_requires_watering_after", False))
        application_pending = bool(extra.get("application_post_watering_pending", False))
        auto_irrigation_enabled = bool(extra.get("auto_irrigation_enabled", True))
        application_type = str(extra.get("application_type") or "").strip().lower()
        application_type_known = application_type in {"sol", "foliaire"}
        post_status = normalize_post_application_status(extra.get("application_post_watering_status"))
        application_label = "Arrosage"
        display_window = watering_window.replace("_", " ").strip()
        block_reason = str(extra.get("block_reason") or "").strip()
        block_reason_label = (
            str(extra.get("watering_block_reason_label") or "").strip()
            or _block_reason_display_label(block_reason)
            or block_reason
        )
        application_summary = extra.get("derniere_application")
        if isinstance(application_summary, dict) and application_summary:
            application_label = str(
                application_summary.get("libelle")
                or application_summary.get("produit")
                or application_summary.get("type")
                or application_label
            )
        application_label_active = bool(application_summary) and post_status in {"bloque", "en_attente", "autorise"} and (
            application_block_active or application_requires or application_pending or post_status == "autorise"
        )
        if watering_cause not in {"hydrique", "post_application"}:
            watering_cause = (
                "post_application"
                if post_status in {"bloque", "en_attente", "autorise"} or type_arrosage in {"application_technique", "application_technique_auto"}
                else "hydrique"
            )

        today = dt_util.now().date().isoformat()
        if application_summary and not application_type_known:
            return {
                "status": "bloque",
                "next_action": "Vérifier le type d'application",
                "summary": f"Arrosage post-produit bloqué ({application_label}): type d'application inconnu",
                "watering_cause": "post_application",
            }

        if post_status == "bloque" or application_block_active or type_arrosage == "bloque":
            summary = "Arrosage post-produit bloqué" if watering_cause == "post_application" else "Arrosage bloqué"
            show_application_label = watering_cause == "post_application" and bool(application_summary) and (
                application_block_active or post_status == "bloque"
            )
            if show_application_label:
                summary = f"{summary} ({application_label})"
            if block_reason_label:
                summary = f"{summary}: {block_reason_label}"
            if watering_cause == "post_application":
                next_action = "Attendre la fin du blocage post-produit"
            elif block_reason in {"pluie_prevue_suffisante", "pluie_active", "pluie_probabilite_elevee"}:
                next_action = "Attendre après la pluie"
            else:
                next_action = "Attendre des conditions favorables"
            return {
                "status": "bloque",
                "next_action": next_action,
                "summary": summary,
                "watering_cause": watering_cause,
            }

        if post_status == "en_attente" or (application_requires and application_pending and not bool(extra.get("application_post_watering_ready"))):
            summary = "Arrosage post-application en attente"
            if application_label_active:
                summary = f"{summary} ({application_label})"
            if block_reason:
                summary = f"{summary}: {block_reason}"
            return {
                "status": "en_attente",
                "next_action": "Attendre la fin du délai applicatif",
                "summary": summary,
                "watering_cause": "post_application",
            }

        if post_status == "autorise":
            if auto_irrigation_enabled and application_mode == "auto" and auto_autorise:
                summary = "Arrosage post-produit automatique prêt"
                if application_label_active:
                    summary = f"{summary} ({application_label})"
                return {
                    "status": "auto",
                    "next_action": "Aucune action requise",
                    "summary": summary,
                    "watering_cause": "post_application",
                }
            summary = "Arrosage post-produit autorisé"
            if application_label_active:
                summary = f"{summary} ({application_label})"
            return {
                "status": "autorise",
                "next_action": (
                    "Arrosage manuel immédiat"
                    if application_mode == "manuel"
                    else "Décider manuellement"
                ),
                "summary": summary,
                "watering_cause": "post_application",
            }

        if not auto_irrigation_enabled:
            return {
                "status": "bloque",
                "next_action": "Réactiver l'arrosage automatique",
                "summary": "Arrosage automatique désactivé",
                "auto_irrigation_enabled": False,
                "watering_cause": watering_cause,
            }

        if objective <= 0 or not arrosage_recommande:
            depletion_ratio = float(extra.get("depletion_ratio") or 0.0)
            mad_ratio = float(extra.get("mad_ratio") or 0.5)
            soil_needs_water = depletion_ratio >= mad_ratio
            if block_reason == "garde_fou_hebdomadaire" and soil_needs_water:
                # Objectif ramené à 0 par le plafond hebdomadaire alors que le sol a
                # réellement besoin (réserve sous le seuil MAD) : l'afficher honnêtement
                # comme un plafonnement plutôt que « aucun arrosage nécessaire » (qui
                # masquait le vrai motif). Si le sol n'a pas de besoin, on garde « aucun
                # arrosage nécessaire » et on n'alarme pas inutilement.
                return {
                    "status": "bloque",
                    "next_action": "Attendre la reconstitution du budget hebdomadaire",
                    "summary": "Arrosage plafonné cette semaine (garde-fou hebdomadaire)",
                    "block_reason": block_reason,
                    "watering_cause": watering_cause,
                }
            return {
                "status": "termine",
                "next_action": "Aucun arrosage nécessaire",
                "summary": "Aucun arrosage nécessaire",
                "watering_cause": watering_cause,
            }

        if application_mode == "manuel":
            return {
                "status": "en_attente",
                "next_action": "Arrosage manuel immédiat",
                "summary": f"Arrosage prévu {display_window or 'plus tard'} (manuel)",
                "watering_cause": watering_cause,
            }

        if application_mode == "suggestion":
            return {
                "status": "en_attente",
                "next_action": "Décider manuellement",
                "summary": f"Arrosage suggéré {display_window or 'plus tard'} (suggestion)",
                "watering_cause": watering_cause,
            }

        if target_date and target_date > today:
            return {
                "status": "en_attente",
                "next_action": "Attendre le créneau prévu",
                "summary": f"Arrosage prévu {display_window or 'plus tard'} (auto)",
                "watering_cause": watering_cause,
            }

        if auto_autorise:
            return {
                "status": "auto",
                "next_action": "Aucune action requise",
                "summary": f"Arrosage prévu {display_window or 'maintenant'} (auto)",
                "watering_cause": watering_cause,
            }

        return {
            "status": "en_attente",
            "next_action": "Attendre le prochain créneau",
            "summary": f"Arrosage en attente {display_window or 'plus tard'}",
            "watering_cause": watering_cause,
        }

    def _next_action_date_attributes(self) -> dict[str, Any] | None:
        snapshot = _coordinator_snapshot(self.coordinator)
        result = self.decision_result
        extra = getattr(result, "extra", None) if result is not None else None
        if not isinstance(extra, dict):
            extra = {}
        if snapshot:
            merged_extra = dict(snapshot)
            merged_extra.update(extra)
            extra = merged_extra

        target_date = str(
            extra.get("next_action_date")
            or extra.get("watering_target_date")
            or self._decision_value("watering_target_date", "")
            or ""
        ).strip()
        display_date = (
            extra.get("next_action_display")
        )
        if display_date is None:
            display_date = _human_date_text(target_date)

        attrs: dict[str, Any] = {}
        if target_date:
            attrs["next_action_date"] = target_date
        if display_date:
            attrs["next_action_display"] = display_date
        return _clean_public_attrs(attrs)

    def _base_watering_attributes(self) -> dict[str, Any] | None:
        # Ajoute UN libellé d'affichage honnête (`stress_hydrique`) dérivé du niveau brut, là où
        # celui-ci est déjà exposé — source unique, pas de doublon. La carte Lovelace peut pointer
        # dessus au lieu de la clé technique `heat_stress_level`/`heat_stress_phase` (inchangées).
        attrs = self._base_watering_attributes_raw()
        if isinstance(attrs, dict):
            stress_label = _heat_stress_display_label(attrs.get("heat_stress_level"))
            if stress_label is not None:
                attrs["stress_hydrique"] = stress_label
        return attrs

    def _base_watering_attributes_raw(self) -> dict[str, Any] | None:
        attrs = self._attrs_from_result(
            "watering_cause",
            "next_action_date",
            "next_action_display",
            "watering_window_start_minute",
            "watering_window_end_minute",
            "watering_window_optimal_start_minute",
            "watering_window_optimal_end_minute",
            "watering_window_acceptable_end_minute",
            "watering_evening_start_minute",
            "watering_evening_end_minute",
            "watering_window_profile",
            "watering_evening_allowed",
            "heat_stress_level",
            "heat_stress_phase",
            "confidence_score",
            "confidence_reasons",
            "block_reason",
            "watering_blocked_by_mower",
            "watering_block_reason_code",
            "watering_block_reason_label",
            "watering_strategy",
            "objective_scope",
            "watering_stage",
            "surface_cycle_mm",
            "daily_cycles_target",
            "cycle_spacing_minutes",
            "surface_moisture_target",
            "surface_dryness_risk",
            "runoff_risk",
            "seeding_transition_ready",
            "seeding_block_reason",
            "semis_followup_state",
            "semis_followup_due_at",
            "semis_followup_due_display",
            "semis_cycles_completed_today",
            "semis_cycles_remaining_today",
            "semis_daily_cycles_target",
            "semis_cycle_spacing_minutes",
            "semis_last_cycle_at",
            "semis_last_cycle_display",
            "mm_requested",
            "mm_applied",
            "mm_detected",
            "weekly_guardrail_mm_min",
            "weekly_guardrail_mm_max",
            "weekly_guardrail_reason",
            "soil_profile",
            "soil_retention_factor",
            "soil_drainage_factor",
            "soil_infiltration_factor",
            "soil_need_factor",
            "target_cycle_mm",
            "objective_mm_source",
            "feedback_observation",
            "application_post_watering_status",
            "auto_irrigation_enabled",
            "forecast_pluie_j2",
            "forecast_pluie_3j",
            "forecast_probabilite_max_3j",
        )
        if attrs:
            return attrs
        return self._attrs_from_data(
            "watering_cause",
            "next_action_date",
            "next_action_display",
            "watering_window_start_minute",
            "watering_window_end_minute",
            "watering_window_optimal_start_minute",
            "watering_window_optimal_end_minute",
            "watering_window_acceptable_end_minute",
            "watering_evening_start_minute",
            "watering_evening_end_minute",
            "watering_window_profile",
            "watering_evening_allowed",
            "heat_stress_level",
            "heat_stress_phase",
            "confidence_score",
            "confidence_reasons",
            "block_reason",
            "watering_blocked_by_mower",
            "watering_block_reason_code",
            "watering_block_reason_label",
            "watering_strategy",
            "objective_scope",
            "watering_stage",
            "surface_cycle_mm",
            "daily_cycles_target",
            "cycle_spacing_minutes",
            "surface_moisture_target",
            "surface_dryness_risk",
            "runoff_risk",
            "seeding_transition_ready",
            "seeding_block_reason",
            "semis_followup_state",
            "semis_followup_due_at",
            "semis_followup_due_display",
            "semis_cycles_completed_today",
            "semis_cycles_remaining_today",
            "semis_daily_cycles_target",
            "semis_cycle_spacing_minutes",
            "semis_last_cycle_at",
            "semis_last_cycle_display",
            "mm_requested",
            "mm_applied",
            "mm_detected",
            "weekly_guardrail_mm_min",
            "weekly_guardrail_mm_max",
            "weekly_guardrail_reason",
            "soil_profile",
            "soil_retention_factor",
            "soil_drainage_factor",
            "soil_infiltration_factor",
            "soil_need_factor",
            "target_cycle_mm",
            "objective_mm_source",
            "feedback_observation",
            "application_post_watering_status",
            "forecast_pluie_j2",
            "forecast_pluie_3j",
            "forecast_probabilite_max_3j",
        )

    @property
    def extra_state_attributes(self):
        attrs = self._base_watering_attributes()
        contextual_state = self._contextual_watering_state()
        if contextual_state:
            attrs = attrs or {}
            attrs.update(contextual_state)
            if (
                contextual_state.get("status") in {"en_attente", "termine"}
                and contextual_state.get("summary") == "Aucun arrosage nécessaire"
            ):
                attrs.pop("block_reason", None)
                confidence_reasons = attrs.get("confidence_reasons")
                if isinstance(confidence_reasons, list):
                    filtered_reasons = [
                        reason
                        for reason in confidence_reasons
                        if not str(reason or "").strip().lower().startswith("blocage=")
                    ]
                    if filtered_reasons:
                        attrs["confidence_reasons"] = filtered_reasons
                    else:
                        attrs.pop("confidence_reasons", None)
        attrs = attrs or {}
        attrs["watering_cause"] = attrs.get("watering_cause") or _watering_cause_value(self)
        watering_window_display = _minute_range_display(
            attrs.get("watering_window_start_minute"),
            attrs.get("watering_window_end_minute"),
        )
        optimal_window_display = _minute_range_display(
            attrs.get("watering_window_optimal_start_minute"),
            attrs.get("watering_window_optimal_end_minute"),
        )
        evening_window_display = None
        if bool(attrs.get("watering_evening_allowed")):
            evening_window_display = _minute_range_display(
                attrs.get("watering_evening_start_minute"),
                attrs.get("watering_evening_end_minute"),
            )
        if watering_window_display:
            attrs["watering_window_display"] = watering_window_display
        if optimal_window_display:
            attrs["optimal_window_display"] = optimal_window_display
        if evening_window_display:
            attrs["evening_window_display"] = evening_window_display
        window_reason_summary = _window_reason_summary(self, attrs, contextual_state)
        if window_reason_summary:
            attrs["window_reason_summary"] = window_reason_summary
        next_action_date_attrs = self._next_action_date_attributes()
        if next_action_date_attrs:
            attrs = attrs or {}
            attrs.update(next_action_date_attrs)
        if attrs and attrs.get("block_reason"):
            attrs["block_reason_label"] = _block_reason_display_label(attrs["block_reason"])
        if attrs:
            possible_values = self._possible_values_attr("fenetre_optimale")
            if possible_values:
                attrs.update(possible_values)
            return attrs
        return attrs


class GazonProchainArrosageSensor(GazonFenetreOptimaleSensor):
    _attr_name = "Prochain arrosage"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "prochain_arrosage")

    def _target_date(self) -> str | None:
        attrs = self._next_action_date_attributes() or {}
        target_date = str(attrs.get("next_action_date") or "").strip()
        return target_date or None

    def _target_display(self) -> str | None:
        attrs = self._next_action_date_attributes() or {}
        display = str(attrs.get("next_action_display") or "").strip()
        if display:
            return display
        target_date = self._target_date()
        return _human_date_text(target_date) if target_date else None

    def _motif_de_blocage(self) -> str | None:
        """Motif de blocage courant, ou None. Lu au même endroit que ce qui est publié."""
        return str(self._decision_value("block_reason") or "").strip() or None

    @property
    def native_value(self):
        contextual = self._contextual_watering_state() or {}
        status = str(contextual.get("status") or "").strip().lower()
        objective_mm = _objective_mm_value(self)
        target_display = self._target_display()
        window_value = str(self._decision_value("fenetre_optimale") or "").strip().lower()
        window_label = _window_display_label(window_value)

        # ⚠️ « NON REQUIS » NE DOIT PAS COUVRIR UN BLOCAGE.
        # L'objectif tombe à 0 quand un garde-fou retient l'eau : dire « non requis » dans ce
        # cas, c'est annoncer que le gazon n'a besoin de rien alors qu'on lui refuse justement
        # ce dont il a besoin. Mesuré le 31/07/2026 à 10:46:50 : état « Non requis », résumé
        # « Aucun arrosage nécessaire pour le moment » — et dans ses propres attributs
        # `block_reason: garde_fou_hebdomadaire`. Le mensonge était l'état, pas le motif : on
        # garde donc le motif et on corrige l'état.
        if status == "termine" and objective_mm <= 0.0 and not self._motif_de_blocage():
            return "Non requis"
        if status == "termine" and objective_mm <= 0.0:
            return "Retenu"
        if status == "bloque":
            return "Bloqué"
        if target_display:
            return target_display
        if status == "auto":
            return "Aujourd'hui"
        if status == "autorise":
            return "Maintenant"
        if window_label:
            return window_label
        return "À définir"

    @property
    def extra_state_attributes(self):
        contextual = self._contextual_watering_state() or {}
        base_attrs = self._base_watering_attributes() or {}
        status = str(contextual.get("status") or "").strip().lower()
        objective_mm = _objective_mm_value(self)
        window_value = str(self._decision_value("fenetre_optimale") or "").strip().lower()
        window_label = _window_display_label(window_value)
        block_reason = str(base_attrs.get("block_reason") or "").strip()
        expose_target = status not in {"bloque", "termine"} and objective_mm > 0.0
        target_date = self._target_date() if expose_target else None
        optimal_target_datetime = (
            _datetime_from_date_and_minute(
                target_date,
                base_attrs.get("watering_window_optimal_start_minute"),
            )
            if target_date
            else None
        )
        target_datetime = (
            optimal_target_datetime
            or _datetime_from_date_and_minute(
                target_date,
                base_attrs.get("watering_window_start_minute"),
            )
            if target_date
            else None
        )
        summary = str(contextual.get("summary") or "").strip() or None
        next_action = str(contextual.get("next_action") or "").strip() or None
        block_reason_label = _block_reason_display_label(block_reason)
        target_display = self._target_display() if expose_target else None
        if status == "bloque":
            if block_reason in {"sol_non_adapte", "soil_wet", "wet_grass"}:
                summary = "Arrosage à reprendre après ressuyage du sol"
            elif block_reason in {"mower_mowing", "mower_returning"}:
                summary = "Arrosage en attente de la tondeuse"
            elif block_reason == "pluie_prevue_suffisante":
                summary = "Aucun arrosage nécessaire, la pluie prévue suffit"
            elif block_reason in {"pluie_en_cours", "pluie_annoncee", "pluie_proche", "rain", "rain_detected"}:
                summary = "Arrosage bloqué par la pluie"
            elif block_reason_label:
                summary = f"Arrosage bloqué: {block_reason_label}"
        elif status == "termine" and objective_mm <= 0.0:
            # Même règle que pour l'état : ne pas annoncer « rien à faire » quand un garde-fou
            # retient l'eau. Le motif existe déjà dans les attributs, il doit se lire ici aussi.
            if block_reason_label:
                summary = f"Arrosage retenu: {block_reason_label}"
            elif block_reason:
                summary = "Arrosage retenu par un garde-fou"
            else:
                summary = "Aucun arrosage nécessaire pour le moment"
        elif expose_target and target_display:
            if window_value == "apres_pluie":
                summary = f"Arrosage à reconsidérer après pluie, cible {target_display}"
            elif window_value == "demain_matin":
                summary = f"Arrosage prévu demain matin ({target_display})"
            elif window_value == "ce_matin":
                summary = f"Arrosage prévu ce matin ({target_display})"
            elif window_value == "maintenant":
                summary = "Arrosage possible maintenant"
        attrs = {
            "source_entity": _public_source_entity(self, "sensor", "fenetre_optimale"),
            "source_status": status or None,
            "target_date": target_date,
            "target_display": target_display,
            "target_datetime": target_datetime,
            "optimal_target_datetime": optimal_target_datetime,
            "target_window": window_value or None,
            "target_window_label": window_label,
            "next_action": next_action,
            "summary": summary,
            "objective_mm": objective_mm,
            "type_arrosage": _normalized_public_type_arrosage(self),
            "watering_cause": _watering_cause_value(self),
            "block_reason": block_reason or None,
            "block_reason_label": block_reason_label,
            "confidence_score": base_attrs.get("confidence_score"),
            "confidence_reasons": base_attrs.get("confidence_reasons"),
            "forecast_pluie_j2": base_attrs.get("forecast_pluie_j2"),
            "forecast_pluie_3j": base_attrs.get("forecast_pluie_3j"),
            "forecast_probabilite_max_3j": base_attrs.get("forecast_probabilite_max_3j"),
            "watering_window_display": _minute_range_display(
                base_attrs.get("watering_window_start_minute"),
                base_attrs.get("watering_window_end_minute"),
            ),
            "optimal_window_display": _minute_range_display(
                base_attrs.get("watering_window_optimal_start_minute"),
                base_attrs.get("watering_window_optimal_end_minute"),
            ),
            # Estimation indicative du prochain jour d'arrosage (déplétion réserve → MAD au
            # rythme ~ETc/jour). Diagnostic/affichage seul — n'entre dans aucune décision.
            "jours_avant_arrosage_estime": self._decision_value("jours_avant_arrosage_estime"),
            "date_prochain_arrosage_estime": self._decision_value("date_prochain_arrosage_estime"),
        }
        return _clean_public_attrs(attrs) or {}


class GazonRisqueGazonSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Risque gazon"
    _attr_has_entity_name = True
    _attr_icon = "mdi:shield-alert-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("sensor", "risque_gazon")

    @property
    def native_value(self):
        return self._decision_value("risque_gazon")

    @property
    def extra_state_attributes(self):
        # Lecture directe depuis coordinator.data pour les champs post-snapshot
        # (fungal_risk et sensor_health sont injectés après result.to_snapshot()
        #  et ne sont pas dans result.extra — _decision_value ne les trouve pas fiablement)
        data = getattr(self.coordinator, "data", None) or {}
        attrs: dict = {}
        # ⚠️ Le capteur n'expliquait PAS son niveau : il n'exposait que le risque FONGIQUE,
        # si bien qu'un état « élevé » était incompréhensible sans lire le code (question de
        # Kévin le 31/07/2026 : « pourquoi risque gazon élevé ? » — il a fallu vingt minutes
        # de lecture pour répondre). Les raisons viennent en tête, avant le détail fongique.
        # ⚠️ `_decision_value` et NON `data.get` : `coordinator.data` ne porte que les champs
        # injectés APRÈS le snapshot (risque fongique, santé des capteurs). Les raisons, elles,
        # viennent du snapshot — comme `native_value` juste au-dessus. Posé au mauvais endroit,
        # l'attribut restait introuvable et le capteur continuait de ne rien expliquer.
        # ⚠️ Exposé INCONDITIONNELLEMENT. Une liste vide est falsy : la masquer laissait le
        # capteur muet exactement comme avant le correctif, et rendait impossible de distinguer
        # « aucune raison fournie par ce chemin » de « attribut jamais posé ». Le capteur doit
        # toujours s'expliquer — même pour dire qu'il n'a rien à signaler.
        raisons = self._decision_value("risque_gazon_raisons")
        attrs["risque_gazon_raisons"] = list(raisons) if raisons else ["aucun motif fourni"]
        # LOT E — risque fongique
        fungal_level = data.get("fungal_risk_level")
        if fungal_level is not None:
            attrs["fungal_risk_level"] = fungal_level
        fungal_score = data.get("fungal_risk_score")
        if fungal_score is not None:
            attrs["fungal_risk_score"] = fungal_score
        fungal_reasons = data.get("fungal_risk_reasons")
        if fungal_reasons is not None:
            attrs["fungal_risk_reasons"] = fungal_reasons
        attrs["fungal_risk_evening_block"] = bool(data.get("fungal_risk_evening_block") or False)
        attrs["fungal_risk_reduce_watering"] = bool(data.get("fungal_risk_reduce_watering") or False)
        # LOT A — santé capteurs
        sensor_health = data.get("sensor_health")
        if isinstance(sensor_health, dict):
            attrs["sensor_health"] = sensor_health
        return attrs or None
