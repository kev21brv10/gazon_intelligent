from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity

from .const import (
    APPLICATION_INTERVENTIONS,
    BLOCK_REASON_DISPLAY_LABELS,
    DOMAIN,
    IRRIGATION_ACTION_LABEL_AUTO,
    IRRIGATION_ACTION_LABEL_NONE,
    IRRIGATION_ACTION_LABEL_NOW,
    IRRIGATION_ACTION_LABEL_POST_APPLICATION,
    IRRIGATION_ACTION_LABEL_WAIT,
    IRRIGATION_REASON_KIND_BLOCKED,
    IRRIGATION_REASON_KIND_BLOCKED_DUE_TO_CONDITIONS,
    IRRIGATION_REASON_KIND_HYDRIC_NEED,
    IRRIGATION_REASON_KIND_NO_NEED,
    IRRIGATION_REASON_KIND_PHASE_SUPPORT,
    IRRIGATION_REASON_KIND_POST_APPLICATION,
    IRRIGATION_REASON_KIND_WAITING,
)
from .entity_base import GazonEntityBase
from .entity_ids import public_entity_id
from .intervention_recommendation import public_intervention_ui
from .memory import compute_application_state, normalize_post_application_status

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
# ⚠️ HOMONYME VOLONTAIREMENT DIFFÉRENT de `sensor._APPLICATION_STATUS_ATTR_KEYS`, qui ne
# porte PAS `auto_irrigation_enabled` (il l'expose par un autre chemin). Toute clé ajoutée
# ici « par symétrie » creuserait un écart de contrat public que ni les tests ni la CI ne
# verraient — les deux listes sont lues séparément.
_APPLICATION_STATUS_ATTR_KEYS = (
    "application_block_active",
    "application_block_remaining_minutes",
    "application_post_watering_pending",
    "application_post_watering_delay_remaining_minutes",
    "application_post_watering_ready",
    "application_post_watering_remaining_mm",
    "auto_irrigation_enabled",
)


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


def _objective_mm_value(entity: GazonEntityBase) -> float:
    try:
        return float(entity._decision_value("objectif_mm", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _requested_mm_value(entity: GazonEntityBase) -> float:
    for key in ("mm_requested", "mm_cible", "objectif_legacy_mm", "objectif_legacy"):
        try:
            value = float(entity._decision_value(key, 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if value > 0.0:
            return value
    return 0.0


def _irrigation_block_active(entity: GazonEntityBase) -> bool:
    type_arrosage = _normalized_public_type_arrosage(entity)
    block_reason = str(entity._decision_value("block_reason") or "").strip()
    return bool(
        type_arrosage == "bloque"
        or block_reason
        or entity._decision_value("watering_blocked_by_mower", False)
        or entity._decision_value("irrigation_blocked", False)
    )


def _block_reason_display_label(value: object) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    return BLOCK_REASON_DISPLAY_LABELS.get(normalized, normalized.replace("_", " "))


def _fallback_machine_unavailable_label_from_attrs(attrs: dict[str, object]) -> str | None:
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


def _apply_public_mower_aliases(attrs: dict[str, object]) -> dict[str, object]:
    tondeuse_erreur = attrs.get("tondeuse_erreur")
    if tondeuse_erreur not in (None, "", [], {}):
        attrs.setdefault("tondeuse_erreur_code", tondeuse_erreur)
        attrs.setdefault("mower_error", tondeuse_erreur)
    mower_operation_state = attrs.get("mower_operation_state")
    if mower_operation_state not in (None, "", [], {}):
        attrs.setdefault("mower_activity_code", mower_operation_state)
    return attrs


def _apply_precise_machine_unavailable_fallbacks(attrs: dict[str, object]) -> dict[str, object]:
    block_reason = str(attrs.get("raison_blocage_code") or attrs.get("mowing_block_reason_code") or "").strip()
    if block_reason != "machine_unavailable":
        return attrs
    machine_label = str(attrs.get("mowing_machine_unavailable_label") or "").strip()
    if not machine_label:
        machine_label = _fallback_machine_unavailable_label_from_attrs(attrs) or ""
    if not machine_label:
        return attrs
    attrs["mowing_machine_unavailable_label"] = machine_label
    for key in ("mowing_window_reason", "mowing_block_reason_label", "raison_blocage_tonte"):
        current = str(attrs.get(key) or "").strip()
        if not current or current == "Robot indisponible: attendre qu'elle soit prête.":
            attrs[key] = machine_label
    return attrs


def _phase_support_phase(entity: GazonEntityBase) -> str | None:
    phase = str(
        entity._decision_value("phase_dominante")
        or entity._decision_value("phase_active")
        or ""
    ).strip()
    if phase in APPLICATION_INTERVENTIONS:
        return phase
    return None


def _is_phase_support_irrigation_context(entity: GazonEntityBase) -> bool:
    if _objective_mm_value(entity) <= 0.0 or not bool(entity._decision_value("arrosage_recommande", False)):
        return False
    if _phase_support_phase(entity) is None:
        return False

    hydric_state = str(entity._decision_value("hydric_state") or "").strip().lower()
    if hydric_state in {"plein", "confort"}:
        return True

    for key, threshold in (("depletion_ratio", 0.10), ("reserve_available_ratio", 0.95)):
        try:
            value = float(entity._decision_value(key))
        except (TypeError, ValueError):
            continue
        if key == "depletion_ratio" and value <= threshold:
            return True
        if key == "reserve_available_ratio" and value >= threshold:
            return True
    return False


def _irrigation_reason_kind(entity: GazonEntityBase) -> str:
    post_status = normalize_post_application_status(entity._decision_value("application_post_watering_status"))
    objective_mm = _objective_mm_value(entity)
    requested_mm = _requested_mm_value(entity)
    hydric_actionable = bool(entity._decision_value("arrosage_recommande", False))
    type_arrosage = _normalized_public_type_arrosage(entity)
    block_reason = str(entity._decision_value("block_reason") or "").strip()

    if post_status == "autorise":
        return IRRIGATION_REASON_KIND_POST_APPLICATION
    if _irrigation_block_active(entity) or type_arrosage == "bloque" or block_reason:
        if objective_mm <= 0.0 and requested_mm <= 0.0 and _phase_support_phase(entity) is None:
            return IRRIGATION_REASON_KIND_BLOCKED_DUE_TO_CONDITIONS
        if requested_mm > 0.0 or objective_mm > 0.0 or _phase_support_phase(entity) is not None:
            return IRRIGATION_REASON_KIND_BLOCKED
        return IRRIGATION_REASON_KIND_BLOCKED
    if hydric_actionable and _is_phase_support_irrigation_context(entity):
        return IRRIGATION_REASON_KIND_PHASE_SUPPORT
    if hydric_actionable:
        return IRRIGATION_REASON_KIND_HYDRIC_NEED
    if objective_mm <= 0.0 and post_status in {"indisponible", "non_requis", "termine"}:
        return IRRIGATION_REASON_KIND_NO_NEED
    if post_status == "bloque":
        if objective_mm <= 0.0 and requested_mm <= 0.0:
            return IRRIGATION_REASON_KIND_BLOCKED_DUE_TO_CONDITIONS
        return IRRIGATION_REASON_KIND_BLOCKED
    if post_status == "en_attente":
        return IRRIGATION_REASON_KIND_WAITING
    if objective_mm > 0.0:
        if type_arrosage == "bloque" or block_reason:
            return IRRIGATION_REASON_KIND_BLOCKED
        return IRRIGATION_REASON_KIND_WAITING
    return IRRIGATION_REASON_KIND_NO_NEED


def _irrigation_action_label(entity: GazonEntityBase, reason_kind: str) -> str:
    if reason_kind == IRRIGATION_REASON_KIND_POST_APPLICATION:
        return IRRIGATION_ACTION_LABEL_POST_APPLICATION
    if reason_kind in {IRRIGATION_REASON_KIND_HYDRIC_NEED, IRRIGATION_REASON_KIND_PHASE_SUPPORT}:
        type_arrosage = _normalized_public_type_arrosage(entity)
        if type_arrosage == "auto":
            return IRRIGATION_ACTION_LABEL_AUTO
        return IRRIGATION_ACTION_LABEL_NOW
    if reason_kind in {IRRIGATION_REASON_KIND_WAITING, IRRIGATION_REASON_KIND_BLOCKED}:
        return IRRIGATION_ACTION_LABEL_WAIT
    return IRRIGATION_ACTION_LABEL_NONE


def _irrigation_window_is_actionable_now(entity: GazonEntityBase) -> bool:
    window_value = str(entity._decision_value("fenetre_optimale") or "").strip().lower()
    if not window_value:
        return True
    if window_value in {"maintenant", "ce_matin"}:
        return True
    if window_value in {"demain_matin", "apres_pluie", "soir", "attendre"}:
        return False
    return True


def _normalize_intervention_payload(payload: dict[str, object]) -> dict[str, object]:
    if not isinstance(payload, dict) or not payload:
        return payload
    normalized = dict(payload)
    status = str(normalized.get("status") or "").strip().lower()
    if status == "possible":
        normalized["status"] = "preparation"
    return normalized


def _compact_application_summary(summary: object) -> dict[str, object] | None:
    if not isinstance(summary, dict) or not summary:
        return None
    compact = {
        key: summary.get(key)
        for key in _APPLICATION_SUMMARY_PUBLIC_KEYS
        if summary.get(key) not in (None, "", [], {})
    }
    return compact or None


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        return
    async_add_entities(
        [
            GazonTonteAutoriseeBinarySensor(coordinator),
            GazonArrosageRecommandeBinarySensor(coordinator),
            GazonApplicationArrosageAutoriseBinarySensor(coordinator),
            GazonSignalIrrigationBinarySensor(coordinator),
            GazonSignalInterventionBinarySensor(coordinator),
        ]
    )


class GazonTonteAutoriseeBinarySensor(GazonEntityBase, BinarySensorEntity):
    _attr_name = "Tonte autorisée"
    _attr_has_entity_name = True
    _attr_icon = "mdi:content-cut"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("binary_sensor", "tonte_autorisee")

    @property
    def is_on(self):
        return bool(self._public_mowing_value("tonte_autorisee", self._decision_value("tonte_autorisee", False)))

    @property
    def extra_state_attributes(self):
        attrs = self._attrs_from_result(
            "phase_active",
            "tonte_statut",
            "risque_gazon",
            "hauteur_tonte_recommandee_cm",
            "hauteur_tonte_min_cm",
            "hauteur_tonte_max_cm",
            "hauteur_tonte_garde_fou_label",
            "mowing_frequency_target_per_week",
            "mowing_frequency_label",
            "mowing_window_state",
            "mowing_window_label",
            "mowing_window_reason",
            "mowing_daily_session_limit",
            "mowing_daily_session_policy",
            "next_mowing_date",
            "next_mowing_display",
            "raison_blocage_tonte",
            "raison_blocage_code",
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
            "mowing_blocked_by_watering",
            "mowing_blocked",
            "mowing_block_reason_code",
            "mowing_block_reason_label",
            "mowing_block_reason",
            "mowing_machine_unavailable_detail",
            "mowing_machine_unavailable_label",
            "mowing_cooldown_remaining_minutes",
            "mowing_post_application_active",
        )
        if attrs is None:
            attrs = {}
        facade = self._public_mowing_facade()
        for key in (
            "tonte_statut",
            "tonte_autorisee",
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
        ):
            if facade.get(key) is not None:
                attrs[key] = facade.get(key)
        attrs["gazon_permet_tonte"] = bool(self._public_mowing_value("tonte_autorisee", self._decision_value("tonte_autorisee", False)))
        attrs["machine_permet_tonte"] = (
            bool(self._decision_value("tondeuse_prete", False))
            and self._decision_value("mower_coordination_enabled", True) is not False
            and self._decision_value("mower_coordination_ready", True) is not False
        )
        attrs["mowing_blocked"] = bool(self._public_mowing_value("mowing_blocked", self._decision_value("mowing_blocked", False)))
        attrs["action_possible"] = attrs["gazon_permet_tonte"] and attrs["machine_permet_tonte"] and not attrs["mowing_blocked"]
        attrs = _apply_public_mower_aliases(attrs)
        attrs = _apply_precise_machine_unavailable_fallbacks(attrs)
        return attrs


class GazonArrosageRecommandeBinarySensor(GazonEntityBase, BinarySensorEntity):
    _attr_name = "Irrigation"
    _attr_has_entity_name = True
    _attr_icon = "mdi:water-check"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("binary_sensor", "arrosage_recommande")

    @property
    def is_on(self):
        if _irrigation_block_active(self):
            return False
        execution_allowed = self._decision_value("irrigation_execution_allowed")
        if execution_allowed is not None:
            return bool(execution_allowed)
        return bool(self._decision_value("arrosage_recommande", False)) and not _irrigation_block_active(self)

    @property
    def extra_state_attributes(self):
        attrs = self._attrs_from_result(
            "objectif_mm",
            "irrigation_agronomic_recommendation",
            "irrigation_blocked",
            "irrigation_execution_allowed",
            "arrosage_recommande",
            "arrosage_auto_autorise",
            "type_arrosage",
            "block_reason",
            "watering_cause",
            "watering_blocked_by_mower",
            "watering_block_reason_code",
            "watering_block_reason_label",
            "tondeuse_resolution_state",
            "tondeuse_resolution_reason",
            "tondeuse_resolution_candidate_count",
            "mower_resolution_state",
            "mower_resolution_reason",
            "mower_resolution_candidate_count",
        ) or {}
        if "type_arrosage" in attrs:
            attrs["type_arrosage"] = _normalized_public_type_arrosage(self, attrs.get("type_arrosage")) or None
        attrs["watering_cause"] = _watering_cause_value(self, attrs.get("watering_cause"))
        # `irrigation_need_mm` était lue ici avec repli silencieux sur `objectif_mm`, mais elle
        # n'a JAMAIS eu de producteur : `decision_watering` ne l'émet pas, donc elle valait None
        # et disparaissait du snapshot (to_snapshot filtre les None). Le repli était donc le seul
        # chemin réel — on l'écrit franchement. Valeur exposée strictement inchangée (0.0 si vide).
        attrs["besoin_hydrique_mm"] = attrs.get("objectif_mm", 0.0)
        attrs["recommendation_agronomique"] = bool(
            attrs.get(
                "irrigation_agronomic_recommendation",
                attrs.get("arrosage_recommande", False),
            )
        )
        attrs["blocage_actif"] = _irrigation_block_active(self)
        attrs["execution_autorisee"] = bool(
            attrs.get(
                "irrigation_execution_allowed",
                attrs["recommendation_agronomique"] and not attrs["blocage_actif"],
            )
        ) and not attrs["blocage_actif"]
        return attrs or None


class GazonApplicationArrosageAutoriseBinarySensor(GazonEntityBase, BinarySensorEntity):
    _attr_name = "Irrigation post-application"
    _attr_has_entity_name = True
    _attr_icon = "mdi:water-check"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("binary_sensor", "arrosage_apres_application_autorise")

    @staticmethod
    def _empty_application_state() -> dict[str, object]:
        return {
            "derniere_application": None,
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
            "application_post_watering_delay_remaining_minutes": 0.0,
            "application_post_watering_ready": False,
            "application_post_watering_remaining_mm": 0.0,
            "auto_irrigation_enabled": False,
        }

    def _application_state_keys(self) -> tuple[str, ...]:
        # Unpacking et non `+` : si l'une de ces constantes passait un jour en liste (édition
        # anodine), `tuple + list` lèverait un TypeError AU DÉMARRAGE de Home Assistant,
        # pendant la restauration d'état — pas en test.
        return ("derniere_application", *_APPLICATION_PUBLIC_ATTR_KEYS, *_APPLICATION_STATUS_ATTR_KEYS)

    def _state_from_memory(self, memory: dict[str, object]) -> dict[str, object]:
        state = {
            key: memory.get(key)
            for key in self._application_state_keys()
        }
        state["application_post_watering_status"] = normalize_post_application_status(
            state.get("application_post_watering_status")
        )
        summary = state.get("derniere_application")
        if isinstance(summary, dict) and summary:
            return state
        return {}

    def _application_state(self) -> dict[str, object]:
        memory = getattr(self.coordinator, "memory", None)
        if isinstance(memory, dict):
            state = self._state_from_memory(memory)
            if state:
                return state
        else:
            memory = None
        history = getattr(self.coordinator, "history", None)
        if isinstance(history, list):
            state = compute_application_state(history)
            if isinstance(memory, dict):
                state["auto_irrigation_enabled"] = memory.get(
                    "auto_irrigation_enabled",
                    state.get("auto_irrigation_enabled", False),
                )
            return state
        state = self._empty_application_state()
        if isinstance(memory, dict):
            state["auto_irrigation_enabled"] = memory.get("auto_irrigation_enabled", False)
        return state

    @property
    def is_on(self):
        state = self._application_state()
        # Inconnu (clé absente OU présente à None) → on suppose l'auto activé : ce capteur dit si
        # l'arrosage post-application est AUTORISÉ, il reste permissif tant que l'auto n'est pas
        # explicitement désactivé. Traite absent et None pareil (sinon incohérence selon la source).
        _auto_enabled = state.get("auto_irrigation_enabled")
        auto_irrigation_enabled = True if _auto_enabled is None else bool(_auto_enabled)
        application_type = state.get("application_type")
        application_mode = str(state.get("application_irrigation_mode") or "").strip().lower()
        application_post_watering_status = normalize_post_application_status(
            state.get("application_post_watering_status")
        )
        return bool(
            application_type == "sol"
            and application_mode == "auto"
            and application_post_watering_status == "autorise"
            and auto_irrigation_enabled
        )

    @property
    def extra_state_attributes(self):
        state = self._application_state()
        attrs: dict[str, object] = {}
        compact_summary = _compact_application_summary(state.get("derniere_application"))
        if compact_summary:
            attrs["derniere_application"] = compact_summary
        for key in self._application_state_keys():
            if key == "derniere_application":
                continue
            value = state.get(key)
            if value not in (None, "", [], {}):
                attrs[key] = value
        return attrs or None


class GazonSignalIrrigationBinarySensor(GazonEntityBase, BinarySensorEntity):
    _attr_name = "Signal irrigation"
    _attr_has_entity_name = True
    _attr_icon = "mdi:sprinkler"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("binary_sensor", "signal_irrigation")

    @property
    def is_on(self):
        post_status = normalize_post_application_status(
            self._decision_value("application_post_watering_status")
        )
        if post_status == "en_attente":
            return False
        reason_kind = _irrigation_reason_kind(self)
        if reason_kind == IRRIGATION_REASON_KIND_POST_APPLICATION:
            return True
        if reason_kind in {IRRIGATION_REASON_KIND_HYDRIC_NEED, IRRIGATION_REASON_KIND_PHASE_SUPPORT}:
            return _irrigation_window_is_actionable_now(self)
        return False

    @property
    def extra_state_attributes(self):
        post_status = normalize_post_application_status(
            self._decision_value("application_post_watering_status")
        )
        type_arrosage = _normalized_public_type_arrosage(self)
        watering_cause = _watering_cause_value(self)
        reason_kind = _irrigation_reason_kind(self)
        waiting_post_application = post_status == "en_attente"
        if waiting_post_application:
            trigger_kind = "waiting"
            source_status = post_status
        elif reason_kind == IRRIGATION_REASON_KIND_POST_APPLICATION:
            trigger_kind = "post_application"
            source_status = post_status
        elif reason_kind in {IRRIGATION_REASON_KIND_HYDRIC_NEED, IRRIGATION_REASON_KIND_PHASE_SUPPORT} and not _irrigation_window_is_actionable_now(self):
            trigger_kind = "waiting"
            source_status = type_arrosage or str(self._decision_value("fenetre_optimale") or "").strip().lower() or "attendre"
        elif reason_kind == IRRIGATION_REASON_KIND_WAITING:
            trigger_kind = "waiting"
            source_status = post_status or type_arrosage or "attendre"
        elif reason_kind in {IRRIGATION_REASON_KIND_HYDRIC_NEED, IRRIGATION_REASON_KIND_PHASE_SUPPORT}:
            trigger_kind = "hydrique"
            source_status = type_arrosage or "on"
        elif reason_kind == IRRIGATION_REASON_KIND_BLOCKED_DUE_TO_CONDITIONS:
            trigger_kind = "blocked_due_to_conditions"
            source_status = type_arrosage or post_status or "bloque"
        elif reason_kind == IRRIGATION_REASON_KIND_BLOCKED:
            trigger_kind = "blocked"
            source_status = type_arrosage or post_status or "bloque"
        else:
            trigger_kind = "none"
            source_status = post_status if post_status != "indisponible" else "off"
        summary_map = {
            "post_application": "Arrosage post-produit autorisé",
            "waiting": "Arrosage en attente",
            "hydrique": "Irrigation hydrique actionnable",
            "blocked_due_to_conditions": "Arrosage bloqué par conditions",
            "blocked": "Irrigation bloquée",
            "none": "Aucune irrigation actionnable",
        }
        if reason_kind == IRRIGATION_REASON_KIND_PHASE_SUPPORT:
            summary_map["hydrique"] = "Irrigation de soutien actionnable"
        if trigger_kind == "waiting" and watering_cause == "post_application":
            summary_map["waiting"] = "Arrosage post-produit en attente"
        elif trigger_kind == "waiting":
            summary_map["waiting"] = "Irrigation en attente"
        if trigger_kind == "blocked":
            block_label = _block_reason_display_label(self._decision_value("block_reason"))
            if watering_cause == "post_application" and block_label:
                summary_map["blocked"] = f"Arrosage post-produit bloqué : {block_label}"
            elif watering_cause == "post_application":
                summary_map["blocked"] = "Arrosage post-produit bloqué"
            elif block_label:
                summary_map["blocked"] = f"Irrigation bloquée : {block_label}"
        if reason_kind == IRRIGATION_REASON_KIND_BLOCKED_DUE_TO_CONDITIONS:
            block_label = _block_reason_display_label(self._decision_value("block_reason"))
            # Contrairement au cas « blocked » ci-dessus, le motif post-application ne change PAS le
            # texte ici : les deux branches d'origine (`post_application and block_label` / `block_label`)
            # produisaient la MÊME chaîne. Simplifié en un seul test — comportement identique.
            if block_label:
                summary_map["blocked_due_to_conditions"] = f"Arrosage bloqué par conditions : {block_label}"
        action_label = (
            IRRIGATION_ACTION_LABEL_WAIT if trigger_kind == "waiting" else _irrigation_action_label(self, reason_kind)
        )
        attrs = {
            "source_entities": [
                public_entity_id("binary_sensor", "arrosage_apres_application_autorise", instance_slug=self.instance_slug),
                public_entity_id("binary_sensor", "arrosage_recommande", instance_slug=self.instance_slug),
            ],
            "source_status": source_status,
            "application_post_watering_status": post_status,
            "watering_cause": watering_cause,
            "type_arrosage": type_arrosage or None,
            "watering_blocked_by_mower": bool(self._decision_value("watering_blocked_by_mower", False)),
            "watering_block_reason_code": self._decision_value("watering_block_reason_code"),
            "watering_block_reason_label": self._decision_value("watering_block_reason_label"),
            "tondeuse_resolution_state": self._decision_value("tondeuse_resolution_state"),
            "tondeuse_resolution_reason": self._decision_value("tondeuse_resolution_reason"),
            "tondeuse_resolution_candidate_count": self._decision_value("tondeuse_resolution_candidate_count"),
            "mower_resolution_state": self._decision_value("mower_resolution_state"),
            "mower_resolution_reason": self._decision_value("mower_resolution_reason"),
            "mower_resolution_candidate_count": self._decision_value("mower_resolution_candidate_count"),
            "trigger_kind": trigger_kind,
            "execution_state": "executable"
            if trigger_kind in {"post_application", "hydrique"}
            else "waiting"
            if trigger_kind == "waiting"
            else "blocked"
            if trigger_kind in {"blocked", "blocked_due_to_conditions"}
            else "none",
            "action_executable": trigger_kind in {"post_application", "hydrique"} and not waiting_post_application,
            "reason_kind": reason_kind,
            "support_phase": _phase_support_phase(self),
            "action_label": action_label,
            "summary": summary_map[trigger_kind],
        }
        return {key: value for key, value in attrs.items() if value not in (None, "", [], {})}


class GazonSignalInterventionBinarySensor(GazonEntityBase, BinarySensorEntity):
    _attr_name = "Signal intervention"
    _attr_has_entity_name = True
    _attr_icon = "mdi:signal"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._set_entity_identity("binary_sensor", "signal_intervention")

    def _intervention_payload(self) -> dict[str, object]:
        payload = self._decision_value("intervention_recommendation")
        if isinstance(payload, dict) and payload:
            return _normalize_intervention_payload(payload)
        data = getattr(self.coordinator, "data", None)
        if isinstance(data, dict):
            payload = data.get("intervention_recommendation")
            if isinstance(payload, dict) and payload:
                return _normalize_intervention_payload(payload)
        return {}

    @property
    def is_on(self):
        payload = self._intervention_payload()
        status = str(payload.get("status") or "").strip().lower()
        ready_to_declare = bool(payload.get("ready_to_declare"))
        return ready_to_declare or status == "recommended"

    @property
    def extra_state_attributes(self):
        payload = self._intervention_payload()
        if not payload:
            return None
        status = str(payload.get("status") or "unavailable").strip().lower()
        ready_to_declare = bool(payload.get("ready_to_declare"))
        selected_product_ready = bool(payload.get("selected_product_ready"))
        trigger_kind = "none"
        if ready_to_declare:
            trigger_kind = "ready"
        elif status == "recommended":
            trigger_kind = "recommended"
        elif status == "preparation":
            trigger_kind = "soft"
        product = payload.get("product")
        if not isinstance(product, dict):
            product = {}
        ui = public_intervention_ui(payload)
        summary = ui.get("summary") or {
            "recommended": "Recommandé",
            "preparation": "À préparer",
            "blocked": "Bloqué",
            "unavailable": "Non disponible",
        }.get(status, "Non disponible")
        attrs = {
            "source_entity": public_entity_id("sensor", "prochaine_intervention", instance_slug=self.instance_slug),
            "source_status": status,
            "recommended_action": payload.get("recommended_action"),
            "product_id": product.get("id"),
            "product_name": product.get("name"),
            "ready_to_declare": ready_to_declare,
            "selected_product_ready": selected_product_ready,
            "trigger_kind": trigger_kind,
            "summary": summary,
        }
        return {key: value for key, value in attrs.items() if value not in (None, "", [], {})}
