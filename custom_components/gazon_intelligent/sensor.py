from __future__ import annotations

from datetime import date, datetime

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.helpers.entity import EntityCategory

from .assistant import build_assistant_decision
from .const import DOMAIN
from .entity_base import GazonEntityBase
from .intervention_recommendation import build_intervention_recommendation
from .memory import compute_application_state, normalize_post_application_status


def _human_datetime_text(value: object) -> str | None:
    if value in (None, "", [], {}):
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
            local_tz = datetime.now().astimezone().tzinfo
            if local_tz is not None:
                dt = dt.replace(tzinfo=local_tz)
        return dt.astimezone().strftime("%d/%m/%Y à %H:%M")
    return None


def _human_date_text(value: object) -> str | None:
    if value in (None, "", [], {}):
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


def _hydric_balance_level(balance_mm: float | None, deficit_3j: float | None, deficit_7j: float | None) -> str | None:
    if balance_mm is None and deficit_3j is None and deficit_7j is None:
        return None
    balance_mm = float(balance_mm or 0.0)
    deficit_3j = float(deficit_3j or 0.0)
    deficit_7j = float(deficit_7j or 0.0)
    stress = max(deficit_3j, deficit_7j)
    if balance_mm >= 2.0 and stress <= 1.0:
        return "excédentaire"
    if balance_mm >= 0.5 and stress <= 2.0:
        return "équilibré"
    if balance_mm >= -0.5 and stress <= 4.0:
        return "léger déficit"
    if balance_mm >= -2.0 or stress <= 8.0:
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


def _score_level_and_tone(score: object) -> tuple[str | None, str]:
    try:
        value = float(score)
    except (TypeError, ValueError):
        return None, "neutral"
    if value <= 30.0:
        return "faible", "neutral"
    if value <= 70.0:
        return "moyen", "warning"
    return "élevé", "success"


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
    labels = {
        "pluie_prevue_suffisante": "Pluie prévue suffisante",
        "temperature_trop_basse": "Température trop basse",
        "arrosage_recent": "Arrosage récent",
        "sol_deja_humide": "Sol déjà humide",
        "pluie_probabilite_elevee": "Pluie probable élevée",
        "surface_non_seche": "Surface non sèche",
        "cooldown_24h": "Cooldown 24 h",
        "humidite_excessive": "Humidité excessive",
        "humidite_elevee": "Humidité élevée",
        "garde_fou_hebdomadaire": "Garde-fou hebdomadaire",
        "mode_bloque": "Mode bloqué",
        "pluie_active": "Pluie active",
        "bloque": "Bloqué",
    }
    return labels.get(normalized, normalized.replace("_", " "))


async def async_setup_entry(hass, entry, async_add_entities):
    await _async_ensure_assistant_entity_id(hass, entry)
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            GazonAssistantSensor(coordinator),
            GazonTonteEtatSensor(coordinator),
            GazonHauteurTonteSensor(coordinator),
            GazonConseilPrincipalSensor(coordinator),
            GazonActionRecommandeeSensor(coordinator),
            GazonActionAEviterSensor(coordinator),
            GazonNiveauActionSensor(coordinator),
            GazonFenetreOptimaleSensor(coordinator),
            GazonRisqueGazonSensor(coordinator),
            GazonPhaseActiveSensor(coordinator),
            GazonSousPhaseSensor(coordinator),
            GazonObjectifMmSensor(coordinator),
            GazonTypeArrosageSensor(coordinator),
            GazonPlanArrosageSensor(coordinator),
            GazonArrosageEnCoursSensor(coordinator),
            GazonDernierArrosageDetecteSensor(coordinator),
            GazonDerniereApplicationSensor(coordinator),
            GazonDerniereActionUtilisateurSensor(coordinator),
            GazonCatalogueProduitsSensor(coordinator),
            GazonInterventionRecommendationSensor(coordinator),
            GazonDebugInterventionSensor(coordinator),
            GazonScoreNiveauSensor(coordinator),
            GazonProchaineFenetreOptimaleSensor(coordinator),
            GazonProchainBlocageAttenduSensor(coordinator),
        ]
    )


async def _async_ensure_assistant_entity_id(hass, entry) -> None:
    from homeassistant.helpers import entity_registry as er

    desired_entity_id = f"sensor.{DOMAIN}_assistant"
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
        self._attr_unique_id = f"{coordinator.entry.entry_id}_phase_active"

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
                    if pluie_demain_source == "indisponible":
                        pluie_demain_source = "non disponible"
                    attrs["pluie_demain_source"] = pluie_demain_source
        if attrs:
            return attrs
        fallback_attrs = self.coordinator.get_used_entities_attributes() or {}
        configuration = fallback_attrs.pop("configuration", None)
        if isinstance(configuration, dict):
            type_sol = configuration.get("type_sol")
            if type_sol not in (None, "", [], {}):
                fallback_attrs["type_sol"] = type_sol
        return fallback_attrs or None


class GazonHauteurTonteSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Hauteur de tonte conseillée"
    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "cm"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:content-cut"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_hauteur_tonte"

    @property
    def native_value(self):
        return self._decision_value("hauteur_tonte_recommandee_cm")

    @property
    def extra_state_attributes(self):
        attrs = self._attrs_from_result(
            "hauteur_tonte_min_cm",
            "hauteur_tonte_max_cm",
            "tonte_statut",
            "phase_active",
        )
        return attrs or None


class GazonSousPhaseSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Sous-phase"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:sprout"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_sous_phase"

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
        return attrs or None


class GazonObjectifMmSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Objectif d'arrosage"
    _attr_native_unit_of_measurement = "mm"
    _attr_has_entity_name = True
    _attr_icon = "mdi:water"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_objectif_mm"
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
        )

    @property
    def extra_state_attributes(self):
        attrs = self._attrs_from_result(*self._objective_attrs_keys()) or {}
        hydric_balance_level = _hydric_balance_level(
            attrs.get("bilan_hydrique_mm"),
            attrs.get("deficit_3j"),
            attrs.get("deficit_7j"),
        )
        hydric_strategy = _hydric_strategy(
            attrs.get("bilan_hydrique_mm"),
            attrs.get("deficit_3j"),
            attrs.get("deficit_7j"),
        )
        if hydric_balance_level is not None:
            attrs["hydric_balance_level"] = hydric_balance_level
        if hydric_strategy is not None:
            attrs["hydric_strategy"] = hydric_strategy
        return attrs or None


class GazonTypeArrosageSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Profil d'arrosage"
    _attr_has_entity_name = True
    _attr_icon = "mdi:sprinkler"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_type_arrosage"

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
        return self._decision_value("type_arrosage")

    @property
    def extra_state_attributes(self):
        result = self.decision_result
        if result is None:
            return self._possible_values_attr("type_arrosage")
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
            and "Aucune action" not in possible_values
        ):
            possible_values.insert(0, "Aucune action")
        if not possible_values:
            return None
        return {"possible_values": possible_values}


class GazonDernierArrosageDetecteSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Dernière session détectée"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = "mm"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:water-check"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_dernier_arrosage_detecte"

    def _latest_zone_session(self) -> dict[str, object] | None:
        history = getattr(self.coordinator, "history", None)
        if not isinstance(history, list):
            return None
        for item in reversed(history):
            if not isinstance(item, dict):
                continue
            if item.get("type") == "arrosage" and item.get("source") == "zone_session":
                return item
        return None

    @staticmethod
    def _zone_detail_keys() -> tuple[str, ...]:
        return ("order", "zone", "entity_id", "rate_mm_h", "duration_min", "duration_seconds", "mm")

    @staticmethod
    def _session_when_text(session: dict[str, object]) -> str | None:
        for key in ("detected_at", "recorded_at", "date"):
            value = session.get(key)
            human = _human_datetime_text(value)
            if human:
                return human
        return None

    def _zone_session_attributes(self, session: dict[str, object]) -> dict[str, object] | None:
        zones = session.get("zones")
        zone_details: list[dict[str, object]] = []
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

        attrs: dict[str, object] = {
            "date_action": session.get("date"),
            "source": session.get("source"),
            "last_watering_when": self._session_when_text(session),
            "zone_count": session.get("zone_count") if session.get("zone_count") is not None else len(zone_details),
            "zones_used": zones_used,
            "zones": zone_details,
        }
        total_mm = session.get("total_mm") or session.get("session_total_mm") or session.get("objectif_mm") or 0.0
        if total_mm is not None:
            attrs["total_mm"] = total_mm
        when_text = self._session_when_text(session)
        source = str(session.get("source") or "").strip()
        raw_detected_at = session.get("detected_at") or session.get("date")
        if raw_detected_at not in (None, "", [], {}):
            attrs["detected_at_utc"] = raw_detected_at
            attrs["detected_at"] = when_text or raw_detected_at
        elif when_text:
            attrs["detected_at"] = when_text
        if when_text:
            attrs["summary"] = (
                f"Dernier arrosage: {float(total_mm or 0.0):.1f} mm le {when_text}"
                + (f" ({source})" if source else "")
            )
        else:
            attrs["summary"] = f"Dernier arrosage: {float(total_mm or 0.0):.1f} mm"
        clean = {key: value for key, value in attrs.items() if value not in (None, "", [], {})}
        return clean or None

    @property
    def native_value(self):
        session = self._latest_zone_session()
        if not session:
            return 0.0
        for key in ("total_mm", "session_total_mm", "objectif_mm"):
            value = session.get(key)
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return 0.0

    @property
    def extra_state_attributes(self):
        session = self._latest_zone_session()
        if not session:
            return {
                "source": "none",
                "zone_count": 0,
                "total_mm": 0.0,
                "summary": "Aucun arrosage détecté",
            }
        return self._zone_session_attributes(session)


class GazonDerniereApplicationSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Dernière application"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:spray-bottle"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_derniere_application"

    @staticmethod
    def _empty_application_state() -> dict[str, object]:
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
    def _application_when_text(summary: dict[str, object]) -> str | None:
        for key in ("date_action", "date", "declared_at", "recorded_at"):
            value = summary.get(key)
            human = _human_date_text(value) if key in {"date_action", "date"} else _human_datetime_text(value)
            if human:
                return human
        return None

    def _application_state(self) -> dict[str, object]:
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
        return (
            "application_type",
            "application_requires_watering_after",
            "application_post_watering_mm",
            "application_irrigation_block_hours",
            "application_irrigation_delay_minutes",
            "application_irrigation_mode",
            "application_label_notes",
            "application_post_watering_status",
            "declared_at",
            "application_block_until",
            "application_block_active",
            "application_block_remaining_minutes",
            "application_post_watering_pending",
            "application_post_watering_ready_at",
            "application_post_watering_delay_remaining_minutes",
            "application_post_watering_ready",
            "application_post_watering_remaining_mm",
        )

    def _application_extra_attributes(self, state: dict[str, object]) -> dict[str, object] | None:
        summary = state.get("derniere_application")
        attrs: dict[str, object] = {}
        if isinstance(summary, dict) and summary:
            attrs.update(summary)
        for key in self._application_attr_keys():
            value = state.get(key)
            if value not in (None, "", [], {}):
                attrs[key] = value
        if isinstance(summary, dict) and summary:
            when_text = self._application_when_text(summary)
            if when_text:
                attrs["last_application_when"] = when_text
            label = str(
                summary.get("libelle")
                or summary.get("produit")
                or summary.get("type")
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
        attrs.setdefault("source", "none" if not summary else summary.get("source"))
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
        self._attr_unique_id = f"{coordinator.entry.entry_id}_derniere_action_utilisateur"

    def _latest_action(self) -> dict[str, object] | None:
        memory = getattr(self.coordinator, "memory", None)
        if not isinstance(memory, dict):
            return None
        summary = memory.get("derniere_action_utilisateur")
        if isinstance(summary, dict) and summary:
            return summary
        return None

    @staticmethod
    def _clean_action_summary(summary: dict[str, object]) -> dict[str, object] | None:
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
        attrs.pop("state", None)
        return attrs or None

    @staticmethod
    def _action_when_text(summary: dict[str, object]) -> str | None:
        for key in ("triggered_at", "date", "recorded_at"):
            value = summary.get(key)
            human = _human_datetime_text(value)
            if human:
                return human
        return None

    @staticmethod
    def _action_summary_text(summary: dict[str, object]) -> str:
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
        self._attr_unique_id = f"{coordinator.entry.entry_id}_catalogue_produits"

    def _products(self) -> list[dict[str, object]]:
        products = getattr(self.coordinator, "products", None)
        if not isinstance(products, dict):
            return []
        ordered: list[dict[str, object]] = []
        for product_id in sorted(products.keys()):
            product = products.get(product_id)
            if isinstance(product, dict):
                ordered.append(product)
        return ordered

    @staticmethod
    def _compact_product(product: dict[str, object]) -> dict[str, object]:
        keys = (
            "id",
            "nom",
            "type",
            "dose_conseillee",
            "usage_mode",
            "max_applications_per_year",
            "reapplication_after_days",
            "delai_avant_tonte_jours",
            "phase_compatible",
            "application_months",
            "application_months_label",
            "application_type",
            "application_requires_watering_after",
            "application_post_watering_mm",
            "application_irrigation_block_hours",
            "application_irrigation_delay_minutes",
            "application_irrigation_mode",
            "application_label_notes",
            "temperature_min",
            "temperature_max",
            "note",
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
                "products_summary": [],
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
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:spray-bottle"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_prochaine_intervention"

    def _recommendation_payload(self) -> dict[str, object]:
        recommendation = self._decision_value("intervention_recommendation")
        if isinstance(recommendation, dict) and recommendation:
            return recommendation
        snapshot = getattr(self.coordinator, "data", None)
        if isinstance(snapshot, dict):
            recommendation = build_intervention_recommendation(
                today=date.today(),
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
                return recommendation
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
                "current_month": date.today().month,
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
        }

    @property
    def native_value(self):
        return str(self._recommendation_payload().get("status") or "unavailable")

    @property
    def extra_state_attributes(self):
        payload = self._recommendation_payload()
        return {"payload": payload}


class GazonDebugInterventionSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Debug intervention"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:bug-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_debug_intervention"

    def _debug_payload(self) -> dict[str, object]:
        payload = self._decision_value("intervention_recommendation")
        if isinstance(payload, dict) and payload:
            return payload
        snapshot = getattr(self.coordinator, "data", None)
        if isinstance(snapshot, dict):
            payload = snapshot.get("intervention_recommendation")
            if isinstance(payload, dict) and payload:
                return payload
        return {}

    @staticmethod
    def _constraint_impact(constraint: dict[str, object]) -> str:
        if bool(constraint.get("blocking")):
            return "bloquant"
        if constraint.get("met") is False:
            return "dégradant"
        return "neutre"

    def _constraint_view(self, constraint: dict[str, object]) -> dict[str, object]:
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
        blocking_constraints = [constraint for constraint in normalized_constraints if constraint["impact"] == "bloquant"]
        non_blocking_constraints = [constraint for constraint in normalized_constraints if constraint["impact"] != "bloquant"]
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
            "blocking_constraints": blocking_constraints,
            "non_blocking_constraints": non_blocking_constraints,
            "reasons": payload.get("reasons") or [],
            "missing_requirements": payload.get("missing_requirements") or [],
            "context": cleaned_context,
            "summary": summary,
            "reason": payload.get("reason"),
            "why_now": payload.get("why_now"),
            "ready_to_declare": payload.get("ready_to_declare"),
            "selected_product_ready": payload.get("selected_product_ready"),
            "selection": payload.get("selection") or {},
            "ui_summary": ui.get("summary"),
            "ui_hint": ui.get("hint"),
        }


class GazonScoreNiveauSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Niveau de pertinence"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:signal"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_score_niveau"

    def _score_payload(self) -> dict[str, object]:
        payload = self._decision_value("intervention_recommendation")
        if isinstance(payload, dict) and payload:
            return payload
        data = getattr(self.coordinator, "data", None)
        if isinstance(data, dict):
            payload = data.get("intervention_recommendation")
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
            "summary": f"Pertinence {level} ({score_value}/100)",
            "tone": tone,
            "source_entity": f"sensor.{DOMAIN}_prochaine_intervention",
        }


class GazonProchaineFenetreOptimaleSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Prochaine fenêtre optimale"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:clock-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_prochaine_fenetre_optimale"

    def _window_context(self) -> dict[str, object]:
        payload = self._decision_value("intervention_recommendation")
        context = payload.get("context") if isinstance(payload, dict) else {}
        if not isinstance(context, dict):
            context = {}
        data = getattr(self.coordinator, "data", None)
        if not isinstance(data, dict):
            data = {}
        return {
            "source_state": str(self._decision_value("fenetre_optimale") or "attendre").strip().lower() or "attendre",
            "block_reason": str(self._decision_value("block_reason") or "").strip() or None,
            "confidence_score": self._decision_value("confidence_score"),
            "phase": context.get("current_phase") or self._decision_value("phase_active"),
            "month": context.get("current_month") or date.today().month,
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
            "source_entity": f"sensor.{DOMAIN}_fenetre_optimale",
            "source_state": source_state,
            "block_reason": context.get("block_reason"),
            "confidence_score": context.get("confidence_score"),
            "phase": context.get("phase"),
            "month": context.get("month"),
            "temperature": context.get("temperature"),
            "summary": f"Prochaine fenêtre: {summary_label}",
        }
        return {key: value for key, value in attrs.items() if value not in (None, "", [], {})}


class GazonProchainBlocageAttenduSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Prochain blocage attendu"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_prochain_blocage_attendu"

    def _source_context(self) -> dict[str, object]:
        payload = self._decision_value("intervention_recommendation")
        context = payload.get("context") if isinstance(payload, dict) else {}
        if not isinstance(context, dict):
            context = {}
        block_reason = str(self._decision_value("block_reason") or "").strip() or None
        source_status = "bloque" if block_reason else str(self._decision_value("fenetre_optimale") or "").strip().lower() or "attendre"
        return {
            "source_status": source_status,
            "block_reason": block_reason,
            "confidence_score": self._decision_value("confidence_score"),
            "phase": context.get("current_phase") or self._decision_value("phase_active"),
            "month": context.get("current_month") or date.today().month,
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
        return None

    @property
    def extra_state_attributes(self):
        context = self._source_context()
        block_reason = str(context.get("block_reason") or "").strip()
        source_status = str(context.get("source_status") or "").strip().lower()
        block_label = _block_reason_display_label(block_reason or source_status)
        summary = "Aucun blocage attendu"
        if block_label:
            summary = f"Blocage attendu: {block_label}"
        attrs = {
            "source_entity": f"sensor.{DOMAIN}_fenetre_optimale",
            "source_status": source_status or None,
            "block_reason": block_reason or None,
            "block_label": block_label,
            "confidence_score": context.get("confidence_score"),
            "phase": context.get("phase"),
            "month": context.get("month"),
            "temperature": context.get("temperature"),
            "summary": summary,
        }
        return {key: value for key, value in attrs.items() if value not in (None, "", [], {})}


class GazonPlanArrosageSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Cycle calculé"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:timer-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_plan_arrosage"

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
        return self._int_setting("watering_pause_minutes", default=0, minimum=0)

    def _build_plan(self) -> dict[str, object] | None:
        objective = self._latest_objective()

        def _duration_human(total_minutes: float) -> str:
            total_seconds = max(0, int(round(total_minutes * 60.0)))
            minutes, seconds = divmod(total_seconds, 60)
            if seconds == 0:
                return f"{minutes} min"
            return f"{minutes} min {seconds:02d}"

        def _empty_plan(reason: str) -> dict[str, object]:
            return {
                "objective_mm": round(max(0.0, objective or 0.0), 1),
                "objectif_mm": round(max(0.0, objective or 0.0), 1),
                "zones": [],
                "zone_count": 0,
                "total_duration_min": 0.0,
                "duration_human": _duration_human(0.0),
                "fractionation": False,
                "passages": self._watering_passages(),
                "pause_between_passages_minutes": self._watering_pause_minutes(),
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

        zones: list[dict[str, object]] = []
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
            duration_min = (objective / rate_mm_h) * 60.0
            if duration_min <= 0:
                continue
            rounded_duration = max(0.5, round(duration_min * 2.0) / 2.0)
            rounded_duration = min(rounded_duration, 180.0)
            zones.append(
                {
                    "zone": entity_id,
                    "rate_mm_h": round(rate_mm_h, 1),
                    "objectif_mm": round(objective, 1),
                    "duration_min": round(rounded_duration, 1),
                    "duration_seconds": int(round(rounded_duration * 60.0)),
                }
            )

        if not zones:
            return _empty_plan("no_valid_zones")

        total_duration_min = round(sum(float(zone["duration_min"]) for zone in zones), 1)
        if total_duration_min <= 0:
            return _empty_plan("non_positive_total_duration")

        return {
            "objective_mm": round(objective, 1),
            "objectif_mm": round(objective, 1),
            "zones": zones,
            "zone_count": len(zones),
            "total_duration_min": total_duration_min,
            "duration_human": _duration_human(total_duration_min),
            "fractionation": self._watering_passages() > 1,
            "passages": self._watering_passages(),
            "pause_between_passages_minutes": self._watering_pause_minutes(),
            "source": "calculated_from_objective",
            "plan_type": "multi_zone" if len(zones) > 1 else "single_zone",
            "summary": (
                f"{len(zones)} zone{'s' if len(zones) != 1 else ''} • "
                f"{round(objective, 1):.1f} mm • {_duration_human(total_duration_min)}"
            ),
        }

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
        self._attr_unique_id = f"{coordinator.entry.entry_id}_arrosage_en_cours"

    @staticmethod
    def _current_session(coordinator) -> dict[str, object] | None:
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

    def _progress_state(self) -> dict[str, object]:
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
        now = datetime.now(started_at.tzinfo) if isinstance(started_at, datetime) and started_at.tzinfo else datetime.now()
        elapsed_seconds = 0.0
        if isinstance(started_at, datetime):
            elapsed_seconds = max((now - started_at).total_seconds(), 0.0)

        active_zones = session.get("active_zones")
        active_zone_count = len(active_zones) if isinstance(active_zones, dict) else 0
        zones = session.get("zones")
        zone_count = len(zones) if isinstance(zones, dict) else active_zone_count
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
        return {
            "active": True,
            "summary": summary,
            "detail": " · ".join(detail_parts) if detail_parts else "Session en cours",
            "progress_percent": progress_percent,
            "elapsed_seconds": elapsed_seconds,
            "planned_total_seconds": planned_total_seconds,
            "active_zone_count": active_zone_count,
            "zone_count": zone_count,
            "started_at": started_text,
            "started_at_utc": started_at.isoformat() if isinstance(started_at, datetime) else None,
            "last_activity_at": last_activity,
            "last_activity_at_utc": session.get("last_activity_at").isoformat() if isinstance(session.get("last_activity_at"), datetime) else None,
            "active_zones": [str(zone_id) for zone_id in active_zones.keys()] if isinstance(active_zones, dict) else [],
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
            }
        return progress


class GazonTonteEtatSensor(GazonEntityBase, SensorEntity):
    _attr_name = "État de tonte"
    _attr_has_entity_name = True
    _attr_icon = "mdi:content-cut"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_tonte_etat"

    @property
    def native_value(self):
        return self._decision_value("tonte_statut")

    @staticmethod
    def _mowing_height_keys() -> tuple[str, ...]:
        return (
            "hauteur_tonte_recommandee_cm",
            "hauteur_tonte_min_cm",
            "hauteur_tonte_max_cm",
        )

    def _mowing_height_attributes(self) -> dict[str, object] | None:
        attrs = self._attrs_from_result(*self._mowing_height_keys())
        if attrs:
            return attrs
        return self._attrs_from_data(*self._mowing_height_keys())

    @property
    def extra_state_attributes(self):
        attrs = self._mowing_height_attributes() or {}
        possible_values = self._possible_values_attr("tonte_statut")
        if possible_values:
            attrs.update(possible_values)
        return attrs or None


class GazonAssistantSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Assistant"
    _attr_has_entity_name = True
    _attr_icon = "mdi:account-tie-hat-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_assistant"

    def _assistant_payload(self) -> dict[str, object]:
        assistant = self._decision_value("assistant")
        if isinstance(assistant, dict) and assistant:
            return assistant

        snapshot = getattr(self.coordinator, "data", None)
        if isinstance(snapshot, dict):
            assistant = build_assistant_decision(snapshot)
            if isinstance(assistant, dict) and assistant:
                return assistant

        return {
            "action": "none",
            "moment": "none",
            "quantity_mm": 0.0,
            "status": "ok",
            "reason": "conditions optimales",
        }

    @property
    def native_value(self):
        action = str(self._assistant_payload().get("action") or "none").strip() or "none"
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
        status = str(payload.get("status") or "ok").strip() or "ok"
        reason = str(payload.get("reason") or "").strip()
        try:
            quantity_mm = round(float(payload.get("quantity_mm") or 0.0), 1)
        except (TypeError, ValueError):
            quantity_mm = 0.0
        if not reason:
            if action == "none":
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
        target_date = (
            payload.get("next_action_date")
            or payload.get("watering_target_date")
            or self._decision_value("next_action_date")
            or self._decision_value("watering_target_date")
        )
        if target_date not in (None, "", [], {}):
            attrs["next_action_date"] = target_date
            display_date = payload.get("next_action_display") or payload.get("watering_target_display")
            if display_date in (None, "", [], {}):
                display_date = self._decision_value("next_action_display")
            if display_date in (None, "", [], {}):
                display_date = self._decision_value("watering_target_display")
            if display_date in (None, "", [], {}):
                display_date = _human_date_text(target_date)
            if display_date not in (None, "", [], {}):
                attrs["next_action_display"] = display_date
        return attrs


class GazonConseilPrincipalSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Conseil principal"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:message-text-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_conseil_principal"

    @property
    def native_value(self):
        conseil = self._decision_value("conseil_principal")
        if conseil is None:
            return None
        return str(conseil).strip() or None

    @property
    def extra_state_attributes(self):
        attrs = self._attrs_from_result(
            "action_recommandee",
            "action_a_eviter",
            "niveau_action",
            "fenetre_optimale",
            "risque_gazon",
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
                "next_action_date",
                "next_action_display",
            ) or {}
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
        if isinstance(decision_resume, dict):
            if decision_resume.get("action") is not None:
                attrs["action_type"] = decision_resume.get("action")
            if decision_resume.get("moment") is not None:
                attrs["action_moment"] = decision_resume.get("moment")
            if decision_resume.get("objectif_mm") is not None:
                attrs["objectif_mm"] = decision_resume.get("objectif_mm")
            if decision_resume.get("type_arrosage") is not None:
                attrs["type_arrosage"] = decision_resume.get("type_arrosage")

        conseil = self._decision_value("conseil_principal")
        if conseil not in (None, "", [], {}):
            attrs["summary"] = conseil
        return attrs or None


class GazonActionRecommandeeSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Action recommandée"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:check-circle-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_action_recommandee"

    @property
    def native_value(self):
        return self._decision_value("action_recommandee")


class GazonActionAEviterSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Action à éviter"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_action_a_eviter"

    @property
    def native_value(self):
        return self._decision_value("action_a_eviter")


class GazonNiveauActionSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Niveau d'action"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:signal"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_niveau_action"

    @property
    def native_value(self):
        niveau_action = self._decision_value("niveau_action")
        decision_resume = self._decision_value("decision_resume")
        objectif_mm = self._decision_value("objectif_mm", 0.0)
        try:
            objectif_mm = float(objectif_mm or 0.0)
        except (TypeError, ValueError):
            objectif_mm = 0.0
        if (
            niveau_action == "surveiller"
            and objectif_mm <= 0.0
            and isinstance(decision_resume, dict)
            and str(decision_resume.get("action") or "").strip() in {"aucune_action", "none"}
        ):
            return "aucune_action"
        return niveau_action

    @property
    def extra_state_attributes(self):
        return self._possible_values_attr("niveau_action")


class GazonFenetreOptimaleSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Fenêtre optimale"
    _attr_has_entity_name = True
    _attr_icon = "mdi:clock-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_fenetre_optimale"

    @property
    def native_value(self):
        return self._decision_value("fenetre_optimale")

    def _contextual_watering_state(self) -> dict[str, object] | None:
        result = self.decision_result
        if result is None:
            return None

        extra = getattr(result, "extra", None)
        if not isinstance(extra, dict):
            extra = {}

        objective = self._decision_value("objectif_mm", 0.0)
        try:
            objective = float(objective or 0.0)
        except (TypeError, ValueError):
            objective = 0.0

        target_date = str(extra.get("watering_target_date") or "").strip()
        watering_window = str(self._decision_value("fenetre_optimale", "") or "").strip()
        application_mode = str(extra.get("application_irrigation_mode") or "").strip().lower()
        type_arrosage = str(self._decision_value("type_arrosage", "") or "").strip().lower()
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

        today = date.today().isoformat()
        if application_summary and not application_type_known:
            return {
                "status": "bloque",
                "next_action": "Vérifier le type d'application",
                "summary": f"{application_label} bloqué: type d'application inconnu",
            }

        if post_status == "bloque" or application_block_active or type_arrosage == "bloque":
            summary = "Arrosage bloqué"
            show_application_label = bool(application_summary) and (application_block_active or post_status == "bloque")
            if show_application_label:
                summary = f"Arrosage bloqué ({application_label})"
            if block_reason:
                if show_application_label:
                    summary = f"Arrosage bloqué ({application_label}): {block_reason}"
                else:
                    summary = f"Arrosage bloqué: {block_reason}"
            return {
                "status": "bloque",
                "next_action": "Attendre la fin du bloc",
                "summary": summary,
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
            }

        if post_status == "autorise":
            if auto_irrigation_enabled and application_mode == "auto" and auto_autorise:
                summary = "Irrigation post-application autorisée"
                if application_label_active:
                    summary = f"{summary} ({application_label})"
                return {
                    "status": "auto",
                    "next_action": "Aucune action requise",
                    "summary": summary,
                }
            summary = "Irrigation post-application autorisée"
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
            }

        if not auto_irrigation_enabled:
            return {
                "status": "bloque",
                "next_action": "Réactiver l'arrosage automatique",
                "summary": "Arrosage automatique désactivé",
                "auto_irrigation_enabled": False,
            }

        if objective <= 0 or not arrosage_recommande:
            return {
                "status": "en_attente",
                "next_action": "Aucun arrosage nécessaire",
                "summary": "Aucun arrosage nécessaire",
            }

        if application_mode == "manuel":
            return {
                "status": "en_attente",
                "next_action": "Arrosage manuel immédiat",
                "summary": f"Arrosage prévu {display_window or 'plus tard'} (manuel)",
            }

        if application_mode == "suggestion":
            return {
                "status": "en_attente",
                "next_action": "Décider manuellement",
                "summary": f"Arrosage suggéré {display_window or 'plus tard'} (suggestion)",
            }

        if target_date and target_date > today:
            return {
                "status": "en_attente",
                "next_action": "Attendre le créneau prévu",
                "summary": f"Arrosage prévu {display_window or 'plus tard'} (auto)",
            }

        if auto_autorise:
            return {
                "status": "auto",
                "next_action": "Aucune action requise",
                "summary": f"Arrosage prévu {display_window or 'maintenant'} (auto)",
            }

        return {
            "status": "en_attente",
            "next_action": "Attendre le prochain créneau",
            "summary": f"Arrosage en attente {display_window or 'plus tard'}",
        }

    def _next_action_date_attributes(self) -> dict[str, object] | None:
        result = self.decision_result
        if result is None:
            return None

        extra = getattr(result, "extra", None)
        if not isinstance(extra, dict):
            extra = {}

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

        attrs: dict[str, object] = {}
        if target_date:
            attrs["next_action_date"] = target_date
        if display_date:
            attrs["next_action_display"] = display_date
        return attrs or None

    def _base_watering_attributes(self) -> dict[str, object] | None:
        attrs = self._attrs_from_result(
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
        next_action_date_attrs = self._next_action_date_attributes()
        if next_action_date_attrs:
            attrs = attrs or {}
            attrs.update(next_action_date_attrs)
        if attrs:
            possible_values = self._possible_values_attr("fenetre_optimale")
            if possible_values:
                attrs.update(possible_values)
            return attrs
        return attrs


class GazonRisqueGazonSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Risque gazon"
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:shield-alert-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_risque_gazon"

    @property
    def native_value(self):
        return self._decision_value("risque_gazon")
