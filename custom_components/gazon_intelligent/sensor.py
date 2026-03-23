from __future__ import annotations

from datetime import date, datetime, timedelta

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN
from .entity_base import GazonEntityBase
from .memory import compute_application_state


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


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
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
        ]
    )


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
                configuration = extra.get("configuration")
                if isinstance(configuration, dict) and configuration:
                    attrs["configuration"] = configuration
                pluie_demain_source = extra.get("pluie_demain_source")
                if pluie_demain_source is not None:
                    if pluie_demain_source == "indisponible":
                        pluie_demain_source = "non disponible"
                    attrs["pluie_demain_source"] = pluie_demain_source
        if attrs:
            return attrs
        return self.coordinator.get_used_entities_attributes()


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
        return self._attrs_from_result(*self._objective_attrs_keys())


class GazonTypeArrosageSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Type d'arrosage"
    _attr_has_entity_name = True
    _attr_icon = "mdi:sprinkler"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_type_arrosage"

    @property
    def native_value(self):
        result = self.decision_result
        if result is not None:
            return result.display_label_for("type_arrosage")
        return self._decision_value("type_arrosage")

    @property
    def extra_state_attributes(self):
        result = self.decision_result
        if result is None:
            return self._possible_values_attr("type_arrosage")
        possible_values = result.possible_display_values_for("type_arrosage")
        if not possible_values:
            return None
        return {"possible_values": list(possible_values)}


class GazonDernierArrosageDetecteSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Dernier arrosage détecté"
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
        for key in ("objectif_mm", "total_mm", "session_total_mm"):
            if session.get(key) is not None:
                attrs[key] = session.get(key)
        total_mm = session.get("total_mm") or session.get("session_total_mm") or session.get("objectif_mm") or 0.0
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
                "objectif_mm": 0.0,
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
        for key in ("declared_at", "date", "recorded_at"):
            value = summary.get(key)
            human = _human_datetime_text(value)
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
    _attr_name = "Dernière action utilisateur"
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
        attrs = {
            key: value
            for key, value in summary.items()
            if key != "state" and value not in (None, "", [], {})
        }
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
        details: list[str] = [f"Dernière action: {action}"]
        if when_text:
            details.append(f"le {when_text}")
        if state:
            details.append(f"état {state}")
        return " - ".join(details)

    @property
    def native_value(self):
        summary = self._latest_action()
        if not summary:
            return "none"
        return summary.get("state")

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


class GazonPlanArrosageSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Plan d'arrosage"
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
                "zones": [],
                "zone_count": 0,
                "total_duration_min": 0.0,
                "duration_human": _duration_human(0.0),
                "min_duration_min": 0.0,
                "max_duration_min": 0.0,
                "fractionation": False,
                "passages": self._watering_passages(),
                "pause_between_passages_minutes": self._watering_pause_minutes(),
                "source": "no_plan",
                "reason": reason,
                "plan_type": "no_plan",
                "summary": "Aucun plan d'arrosage",
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
        max_minutes = 0.0
        min_minutes = 99999.0
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
            max_minutes = max(max_minutes, rounded_duration)
            min_minutes = min(min_minutes, rounded_duration)
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
            "zones": zones,
            "zone_count": len(zones),
            "total_duration_min": total_duration_min,
            "duration_human": _duration_human(total_duration_min),
            "min_duration_min": round(min_minutes, 1),
            "max_duration_min": round(max_minutes, 1),
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


class GazonConseilPrincipalSensor(GazonEntityBase, SensorEntity):
    _attr_name = "Conseil principal"
    _attr_has_entity_name = True
    _attr_icon = "mdi:message-text-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_conseil_principal"

    @property
    def native_value(self):
        decision_resume = self._decision_value("decision_resume")
        if isinstance(decision_resume, dict):
            action = str(decision_resume.get("action") or "").strip()
            if action:
                return action
        conseil = self._decision_value("conseil_principal")
        if conseil is None:
            return None
        if isinstance(conseil, str):
            lower = conseil.lower()
            if "arros" in lower:
                return "arrosage"
            if "tont" in lower:
                return "tonte"
            if "surveill" in lower:
                return "surveillance"
        return conseil

    @property
    def extra_state_attributes(self):
        attrs = self._attrs_from_result(
            "conseil_principal",
            "action_recommandee",
            "action_a_eviter",
            "niveau_action",
            "fenetre_optimale",
            "risque_gazon",
        )
        if attrs is None:
            attrs = self._attrs_from_data(
                "conseil_principal",
                "action_recommandee",
                "action_a_eviter",
                "niveau_action",
                "fenetre_optimale",
                "risque_gazon",
            ) or {}

        decision_resume = self._decision_value("decision_resume")
        if isinstance(decision_resume, dict):
            if decision_resume.get("action") is not None:
                attrs["decision_action"] = decision_resume.get("action")
            if decision_resume.get("moment") is not None:
                attrs["decision_moment"] = decision_resume.get("moment")
            if decision_resume.get("objectif_mm") is not None:
                attrs["decision_objectif_mm"] = decision_resume.get("objectif_mm")
            if decision_resume.get("type_arrosage") is not None:
                attrs["decision_type_arrosage"] = decision_resume.get("type_arrosage")

        conseil = self._decision_value("conseil_principal")
        if conseil not in (None, "", [], {}):
            attrs["summary"] = conseil
            attrs.setdefault("conseil_principal", conseil)
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
        return self._decision_value("niveau_action")

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
        application_label = "Arrosage"
        display_window = watering_window.replace("_", " ").strip()
        application_summary = extra.get("derniere_application")
        if isinstance(application_summary, dict) and application_summary:
            application_label = str(
                application_summary.get("libelle")
                or application_summary.get("produit")
                or application_summary.get("type")
                or application_label
            )

        today = date.today().isoformat()
        if application_summary and not application_type_known:
            return {
                "status": "bloque",
                "next_action": "Vérifier le type d'application",
                "summary": f"{application_label} bloqué: type d'application inconnu",
            }

        if application_block_active or type_arrosage == "bloque":
            return {
                "status": "bloque",
                "next_action": "Attendre la fin du bloc",
                "summary": f"Arrosage bloqué ({application_label})",
            }

        if application_requires and not application_pending:
            return {
                "status": "en_attente",
                "next_action": "Attendre la fin du délai applicatif",
                "summary": f"Arrosage technique en attente ({application_label})",
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

    def _base_watering_attributes(self) -> dict[str, object] | None:
        attrs = self._attrs_from_result(
            "watering_target_date",
            "watering_window_start_minute",
            "watering_window_end_minute",
            "watering_evening_start_minute",
            "watering_evening_end_minute",
            "watering_window_profile",
            "watering_evening_allowed",
            "auto_irrigation_enabled",
            "forecast_pluie_j2",
            "forecast_pluie_3j",
            "forecast_probabilite_max_3j",
        )
        if attrs:
            return attrs
        return self._attrs_from_data(
            "watering_target_date",
            "watering_window_start_minute",
            "watering_window_end_minute",
            "watering_evening_start_minute",
            "watering_evening_end_minute",
            "watering_window_profile",
            "watering_evening_allowed",
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
