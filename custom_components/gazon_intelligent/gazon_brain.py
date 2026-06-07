from __future__ import annotations

import copy
from datetime import date, datetime, timedelta, timezone
from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    APPLICATION_INTERVENTIONS,
    DEFAULT_AUTO_IRRIGATION_ENABLED,
    DEFAULT_MOWER_COORDINATION_ENABLED,
    DEFAULT_MODE,
    INTERVENTIONS_ACTIONS,
)
from .assistant import build_assistant_decision
from .decision import DecisionContext, build_decision_result
from .decision_models import DecisionResult
from .intervention_recommendation import build_intervention_recommendation
from .memory import (
    APPLICATION_DEFAULTS,
    _normalize_user_action_summary,
    compute_memory,
    normalize_product_id,
    normalize_product_record,
)
from .phases import phase_duration_days
from .soil_balance import normalize_soil_balance_state, update_soil_balance
from .water import compute_etp, compute_recent_watering_mm, build_watering_session_summary
from .decision_risk import compute_fungal_risk


class GazonBrain:
    """Cerveau métier de Gazon Intelligent."""

    def __init__(self) -> None:
        self.mode: str = DEFAULT_MODE
        self.date_action: date | None = None
        self.history: list[dict[str, Any]] = []
        self.memory: dict[str, Any] = {
            "historique_total": 0,
            "derniere_tonte": None,
            "dernier_arrosage": None,
            "dernier_arrosage_significatif": None,
            "derniere_phase_active": DEFAULT_MODE,
            "dernier_conseil": None,
            "derniere_action_utilisateur": None,
            "derniere_application": None,
            "feedback_observation": None,
            "prochaine_reapplication": None,
            "catalogue_produits": 0,
            "selected_product_id": None,
            "date_derniere_mise_a_jour": None,
            "auto_irrigation_enabled": DEFAULT_AUTO_IRRIGATION_ENABLED,
            "mower_coordination_enabled": DEFAULT_MOWER_COORDINATION_ENABLED,
        }
        self.products: dict[str, dict[str, Any]] = {}
        self.soil_balance: dict[str, Any] = {}
        self.last_result: DecisionResult | None = None

    @staticmethod
    def _coerce_date(value: Any) -> date | None:
        if isinstance(value, date):
            return value
        if value in (None, ""):
            return None
        try:
            return date.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _build_temperature_note(
        *,
        temperature: float | None,
        forecast_temperature_today: float | None,
        temperature_source: str | None,
        arrosage_recommande: bool,
    ) -> str | None:
        """Construit une note courte pour distinguer réel et prévision."""
        if forecast_temperature_today is None or not arrosage_recommande:
            return None
        if temperature_source == "meteo_forecast":
            if temperature is not None:
                return f"température issue de la prévision du jour {temperature:.1f}°C"
            return f"prévision du jour {forecast_temperature_today:.1f}°C"
        if temperature is None:
            return f"prévision du jour {forecast_temperature_today:.1f}°C"
        return f"température réelle {temperature:.1f}°C, prévision du jour {forecast_temperature_today:.1f}°C"

    @staticmethod
    def _result_float_value(result: DecisionResult | None, key: str) -> float | None:
        if result is None:
            return None
        value = getattr(result, key, None)
        if value is None:
            extra = getattr(result, "extra", None)
            if isinstance(extra, dict):
                value = extra.get(key)
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _preserve_last_valid_hydric_metrics(
        self,
        *,
        result: DecisionResult,
        previous_result: DecisionResult | None,
        etp: float | None,
    ) -> None:
        """Conserve ET0/ETc précédents si le refresh courant n'a pas encore de météo exploitable."""
        if etp is not None or previous_result is None:
            previous_et0 = None if etp is not None else self._memory_float_value("last_valid_et0_mm")
            previous_etc = None if etp is not None else self._memory_float_value("last_valid_etc_mm")
        else:
            previous_et0 = self._result_float_value(previous_result, "et0_mm")
            previous_etc = self._result_float_value(previous_result, "etc_mm")
            if previous_et0 is None or previous_et0 <= 0:
                previous_et0 = self._memory_float_value("last_valid_et0_mm")
            if previous_etc is None or previous_etc <= 0:
                previous_etc = self._memory_float_value("last_valid_etc_mm")

        if etp is not None:
            return

        current_et0 = self._result_float_value(result, "et0_mm")
        current_etc = self._result_float_value(result, "etc_mm")

        if previous_et0 is not None and previous_et0 > 0 and (current_et0 is None or current_et0 <= 0):
            result.extra["et0_mm"] = previous_et0
            if isinstance(result.water_balance, dict):
                result.water_balance["et0_mm"] = previous_et0

        if previous_etc is not None and previous_etc > 0 and (current_etc is None or current_etc <= 0):
            result.extra["etc_mm"] = previous_etc

    def _memory_float_value(self, key: str) -> float | None:
        try:
            value = self.memory.get(key)
        except AttributeError:
            return None
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _default_memory_state(self) -> dict[str, Any]:
        return {
            "historique_total": len(self.history),
            "derniere_tonte": None,
            "dernier_arrosage": None,
            "dernier_arrosage_significatif": None,
            "derniere_phase_active": self.mode,
            "dernier_conseil": None,
            "derniere_action_utilisateur": None,
            "derniere_application": None,
            "feedback_observation": None,
            "prochaine_reapplication": None,
            "catalogue_produits": len(self.products),
            "selected_product_id": None,
            "date_derniere_mise_a_jour": None,
            "auto_irrigation_enabled": DEFAULT_AUTO_IRRIGATION_ENABLED,
            "mower_coordination_enabled": DEFAULT_MOWER_COORDINATION_ENABLED,
        }

    def _normalize_loaded_memory(self, memory: Any) -> dict[str, Any]:
        normalized = self._default_memory_state()
        if isinstance(memory, dict):
            normalized.update(copy.deepcopy(memory))
        if not isinstance(normalized.get("auto_irrigation_enabled"), bool):
            normalized["auto_irrigation_enabled"] = DEFAULT_AUTO_IRRIGATION_ENABLED
        if not isinstance(normalized.get("mower_coordination_enabled"), bool):
            normalized["mower_coordination_enabled"] = DEFAULT_MOWER_COORDINATION_ENABLED
        normalized["historique_total"] = len(self.history)
        normalized["catalogue_produits"] = len(self.products)
        normalized["derniere_phase_active"] = normalized.get("derniere_phase_active") or self.mode
        normalized.setdefault("selected_product_id", None)
        normalized.setdefault("derniere_action_utilisateur", None)
        normalized.setdefault("feedback_observation", None)
        return normalized

    def load_state(self, data: dict[str, Any] | None, *, shared_products: dict[str, dict[str, Any]] | None = None) -> None:
        state = data or {}
        mode = state.get("mode")
        if mode:
            self.mode = str(mode)
        self.date_action = self._coerce_date(state.get("date_action"))
        history = state.get("history")
        if isinstance(history, list):
            self.history = [copy.deepcopy(item) for item in history if isinstance(item, dict)]
        else:
            self.history = []
        products = state.get("products")
        if shared_products is not None:
            self.products = shared_products
            if not self.products and isinstance(products, dict):
                for key, value in products.items():
                    if not isinstance(key, str) or not isinstance(value, dict):
                        continue
                    cleaned = copy.deepcopy(value)
                    cleaned.pop("sol_compatible", None)
                    self.products[key] = cleaned
        elif isinstance(products, dict):
            self.products = {}
            for key, value in products.items():
                if not isinstance(key, str) or not isinstance(value, dict):
                    continue
                cleaned = copy.deepcopy(value)
                cleaned.pop("sol_compatible", None)
                self.products[key] = cleaned
        else:
            self.products = {}
        soil_balance = state.get("soil_balance")
        if isinstance(soil_balance, dict):
            self.soil_balance = normalize_soil_balance_state(soil_balance)
        else:
            self.soil_balance = {}
        self.last_result = None
        self.memory = self._normalize_loaded_memory(state.get("memory"))
        self._normalize_selected_product_id()

    def dump_state(self) -> dict[str, Any]:
        self.memory["historique_total"] = len(self.history)
        self.memory["catalogue_produits"] = len(self.products)
        self._normalize_selected_product_id()
        return {
            "mode": self.mode,
            "date_action": self._coerce_date(self.date_action).isoformat() if self._coerce_date(self.date_action) else None,
            "history": copy.deepcopy(self.history[-300:]),
            "products": copy.deepcopy(self.products),
            "soil_balance": copy.deepcopy(self.soil_balance),
            "memory": copy.deepcopy(self.memory),
        }

    def _append_history(self, item: dict[str, Any]) -> None:
        self.history.append(item)
        self.history = self.history[-300:]

    def _single_product_record(self) -> dict[str, Any] | None:
        if len(self.products) != 1:
            return None
        only_product = next(iter(self.products.values()))
        if isinstance(only_product, dict):
            return only_product
        return None

    @property
    def selected_product_id(self) -> str | None:
        value = normalize_product_id(self.memory.get("selected_product_id"))
        if value and value in self.products:
            return value
        if len(self.products) == 1:
            single_product = self._single_product_record()
            if single_product is not None:
                return normalize_product_id(single_product.get("id"))
        return None

    @selected_product_id.setter
    def selected_product_id(self, value: str | None) -> None:
        self.memory["selected_product_id"] = normalize_product_id(value)
        self._normalize_selected_product_id()

    @property
    def selected_product_name(self) -> str | None:
        selected_id = self.selected_product_id
        if not selected_id:
            return None
        product = self.products.get(selected_id)
        if not isinstance(product, dict):
            return None
        name = str(product.get("nom") or product.get("id") or "").strip()
        return name or None

    def _normalize_selected_product_id(self) -> None:
        selected_product_id = normalize_product_id(self.memory.get("selected_product_id"))
        if selected_product_id and selected_product_id in self.products:
            self.memory["selected_product_id"] = selected_product_id
            return
        single_product = self._single_product_record()
        if single_product is not None:
            self.memory["selected_product_id"] = normalize_product_id(single_product.get("id"))
            return
        self.memory["selected_product_id"] = None

    def _latest_intervention_history_item(self) -> dict[str, Any] | None:
        for item in reversed(self.history):
            if not isinstance(item, dict):
                continue
            if item.get("type") in INTERVENTIONS_ACTIONS:
                return item
        return None

    def _is_application_history_item(self, item: dict[str, Any]) -> bool:
        if not isinstance(item, dict):
            return False
        item_type = item.get("type")
        if item_type in APPLICATION_INTERVENTIONS:
            return True
        return any(
            item.get(key) not in (None, "", [], {})
            for key in (
                "application_type",
                "application_requires_watering_after",
                "application_post_watering_mm",
                "application_irrigation_block_hours",
                "application_irrigation_delay_minutes",
                "application_irrigation_mode",
                "application_label_notes",
                "produit",
                "dose",
                "reapplication_after_days",
            )
        )

    def _sync_mode_from_history(self) -> None:
        latest = self._latest_intervention_history_item()
        if latest is None:
            self.mode = DEFAULT_MODE
            self.date_action = None
            return

        latest_mode = str(latest.get("type") or DEFAULT_MODE).strip() or DEFAULT_MODE
        self.mode = latest_mode
        raw_date = latest.get("date")
        if not raw_date:
            self.date_action = None
            return
        try:
            self.date_action = date.fromisoformat(str(raw_date))
        except ValueError:
            self.date_action = None

    def _resolve_product_record(
        self,
        product_id: str | None,
        product_name: str | None = None,
    ) -> dict[str, Any] | None:
        normalized_id = normalize_product_id(product_id)
        if normalized_id:
            product = self.products.get(normalized_id)
            if isinstance(product, dict):
                return product
        normalized_name = normalize_product_id(product_name)
        if normalized_name:
            matches = [
                product
                for product in self.products.values()
                if isinstance(product, dict)
                and (
                    normalize_product_id(product.get("id")) == normalized_name
                    or normalize_product_id(product.get("nom")) == normalized_name
                )
            ]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                return None
        if not normalized_id and not normalized_name and len(self.products) == 1:
            return self._single_product_record()
        return None

    def _is_history_item_expired(self, item: dict[str, Any], today: date) -> bool:
        item_type = item.get("type")
        if item_type not in INTERVENTIONS_ACTIONS:
            return False
        raw_date = item.get("date")
        if not raw_date:
            return False
        try:
            start = date.fromisoformat(str(raw_date))
        except ValueError:
            return False
        duration_days = max(phase_duration_days(item_type), 0)
        end = start + timedelta(days=max(duration_days - 1, 0))
        return today > end

    def set_mode(self, mode: str) -> None:
        if mode == "Normal":
            self.set_normal()
            return
        self.mode = mode
        self.date_action = dt_util.now().date()
        self._append_history(
            {
                "type": mode,
                "date": self.date_action.isoformat(),
            }
        )

    def set_date_action(self, date_action: date | None = None) -> None:
        target_date = date_action or dt_util.now().date()
        updated = False
        for idx in range(len(self.history) - 1, -1, -1):
            item_type = self.history[idx].get("type")
            if item_type in INTERVENTIONS_ACTIONS:
                self.history[idx]["date"] = target_date.isoformat()
                updated = True
                break
        if not updated and self.mode in INTERVENTIONS_ACTIONS:
            self._append_history(
                {
                    "type": self.mode,
                    "date": target_date.isoformat(),
                }
            )
        self.date_action = target_date

    def set_normal(self) -> None:
        today = dt_util.now().date()
        self.history = [
            item
            for item in self.history
            if item.get("type") not in INTERVENTIONS_ACTIONS
            or not item.get("date")
            or self._is_history_item_expired(item, today)
        ]
        self.mode = "Normal"
        self.date_action = None

    def remove_last_application(self) -> dict[str, Any]:
        for idx in range(len(self.history) - 1, -1, -1):
            item = self.history[idx]
            if not self._is_application_history_item(item):
                continue
            removed = self.history.pop(idx)
            self.history = self.history[-300:]
            self._sync_mode_from_history()
            updated_memory = compute_memory(
                history=self.history,
                current_phase=self.mode,
                previous_memory=self.memory,
                today=dt_util.now().date(),
            )
            self.memory.update(updated_memory)
            self.memory["historique_total"] = len(self.history)
            self.memory["catalogue_produits"] = len(self.products)
            self._normalize_selected_product_id()
            return removed
        raise ValueError("Aucune application enregistrée à supprimer.")

    def declare_intervention(
        self,
        intervention: str,
        date_action: date | None = None,
        produit_id: str | None = None,
        produit: str | None = None,
        selected_product_id: str | None = None,
        dose: str | None = None,
        zone: str | None = None,
        reapplication_after_days: int | None = None,
        application_type: str | None = None,
        application_requires_watering_after: bool | None = None,
        application_post_watering_mm: float | None = None,
        application_irrigation_block_hours: float | None = None,
        application_irrigation_delay_minutes: float | None = None,
        application_irrigation_mode: str | None = None,
        application_label_notes: str | None = None,
        note: str | None = None,
        ) -> dict[str, Any]:
        if intervention not in INTERVENTIONS_ACTIONS:
            raise ValueError(f"Intervention non supportée: {intervention}")
        target_date = date_action or dt_util.now().date()
        product_query = normalize_product_id(produit_id) or normalize_product_id(produit)
        product_record = self._resolve_product_record(produit_id, produit)
        selected_product_id = normalize_product_id(selected_product_id) or self.selected_product_id
        if product_query and selected_product_id and product_record:
            if normalize_product_id(product_record.get("id")) != selected_product_id:
                raise ValueError(
                    "Le produit sélectionné dans l'UI ne correspond pas au produit explicitement fourni. "
                    "Choisis une seule source de vérité."
                )
        if product_query and product_record is None:
            raise ValueError(
                "Produit introuvable ou ambigu. Utilise l'ID exact ou le nom exact d'un produit enregistré."
            )
        if not product_query and product_record is None:
            if selected_product_id:
                product_record = self._resolve_product_record(selected_product_id)
        if not product_query and product_record is None:
            product_record = self._single_product_record()
        if not product_query and product_record is None and len(self.products) > 1:
            raise ValueError(
                "Plusieurs produits sont enregistrés. Sélectionne un produit enregistré par ID ou nom exact."
            )
        if product_record:
            produit = produit or product_record.get("nom")
            if dose is None:
                dose_conseillee = product_record.get("dose_conseillee")
                if dose_conseillee not in (None, ""):
                    dose = str(dose_conseillee)
            if reapplication_after_days is None:
                reapplication_after_days = product_record.get("reapplication_after_days")
            if application_type is None:
                application_type = product_record.get("application_type")
            if application_requires_watering_after is None:
                application_requires_watering_after = product_record.get("application_requires_watering_after")
            if application_post_watering_mm is None:
                application_post_watering_mm = product_record.get("application_post_watering_mm")
            if application_irrigation_block_hours is None:
                application_irrigation_block_hours = product_record.get("application_irrigation_block_hours")
            if application_irrigation_delay_minutes is None:
                application_irrigation_delay_minutes = product_record.get("application_irrigation_delay_minutes")
            if application_irrigation_mode is None:
                application_irrigation_mode = product_record.get("application_irrigation_mode")
            if application_label_notes is None:
                application_label_notes = product_record.get("application_label_notes")
        defaults = APPLICATION_DEFAULTS.get(intervention, {})
        if application_type is None:
            application_type = defaults.get("application_type")
        if application_requires_watering_after is None:
            application_requires_watering_after = defaults.get("application_requires_watering_after")
        if application_post_watering_mm is None:
            application_post_watering_mm = defaults.get("application_post_watering_mm")
        if application_irrigation_block_hours is None:
            application_irrigation_block_hours = defaults.get("application_irrigation_block_hours")
        if application_irrigation_delay_minutes is None:
            application_irrigation_delay_minutes = defaults.get("application_irrigation_delay_minutes")
        if application_irrigation_mode is None:
            application_irrigation_mode = defaults.get("application_irrigation_mode")
        if application_label_notes is None:
            application_label_notes = defaults.get("application_label_notes")
        item: dict[str, Any] = {
            "type": intervention,
            "date": target_date.isoformat(),
            "source": "service",
            "declared_at": datetime.now(timezone.utc).isoformat(),
        }
        if product_record:
            item["produit_id"] = product_record.get("id")
            item["produit_catalogue"] = copy.deepcopy(product_record)
        if produit:
            item["produit"] = produit
        if dose is not None:
            item["dose"] = dose
        if zone:
            item["zone"] = zone
        if reapplication_after_days is not None:
            item["reapplication_after_days"] = int(reapplication_after_days)
        if application_type not in (None, ""):
            item["application_type"] = str(application_type)
        if application_requires_watering_after is not None:
            item["application_requires_watering_after"] = bool(application_requires_watering_after)
        if application_post_watering_mm is not None:
            item["application_post_watering_mm"] = float(application_post_watering_mm)
        if application_irrigation_block_hours is not None:
            item["application_irrigation_block_hours"] = float(application_irrigation_block_hours)
        if application_irrigation_delay_minutes is not None:
            item["application_irrigation_delay_minutes"] = float(application_irrigation_delay_minutes)
        if application_irrigation_mode not in (None, ""):
            item["application_irrigation_mode"] = str(application_irrigation_mode)
        if application_label_notes not in (None, ""):
            item["application_label_notes"] = str(application_label_notes)
        if note:
            item["note"] = note
        self._append_history(item)
        self.mode = intervention
        self.date_action = target_date
        return item

    def record_mowing(self, date_action: date | None = None) -> dict[str, Any]:
        item = {
            "type": "tonte",
            "date": (date_action or dt_util.now().date()).isoformat(),
        }
        self._append_history(item)
        return item

    def record_watering(
        self,
        date_action: date | None = None,
        objectif_mm: float | None = None,
        total_mm: float | None = None,
        zones: list[dict[str, Any]] | None = None,
        source: str = "service",
        watering_cause: str | None = None,
        mm_scope: str | None = None,
        mm_interpretation: str | None = None,
        watering_strategy: str | None = None,
        objective_scope: str | None = None,
        watering_stage: str | None = None,
        surface_cycle_mm: float | None = None,
        daily_cycles_target: int | None = None,
        cycle_spacing_minutes: int | None = None,
        surface_moisture_target: str | None = None,
        surface_dryness_risk: str | None = None,
        runoff_risk: str | None = None,
        seeding_transition_ready: bool | None = None,
        seeding_block_reason: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": "arrosage",
            "date": (date_action or dt_util.now().date()).isoformat(),
            "source": source,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        if watering_cause in {"hydrique", "post_application"}:
            payload["watering_cause"] = str(watering_cause)
        if mm_scope not in (None, ""):
            payload["mm_scope"] = str(mm_scope)
        if mm_interpretation not in (None, ""):
            payload["mm_interpretation"] = str(mm_interpretation)
        if watering_strategy not in (None, ""):
            payload["watering_strategy"] = str(watering_strategy)
        if objective_scope not in (None, ""):
            payload["objective_scope"] = str(objective_scope)
        if watering_stage not in (None, ""):
            payload["watering_stage"] = str(watering_stage)
        if surface_cycle_mm is not None:
            try:
                payload["surface_cycle_mm"] = float(surface_cycle_mm)
            except (TypeError, ValueError):
                pass
        if daily_cycles_target is not None:
            try:
                payload["daily_cycles_target"] = int(daily_cycles_target)
            except (TypeError, ValueError):
                pass
        if cycle_spacing_minutes is not None:
            try:
                payload["cycle_spacing_minutes"] = int(cycle_spacing_minutes)
            except (TypeError, ValueError):
                pass
        if surface_moisture_target not in (None, ""):
            payload["surface_moisture_target"] = str(surface_moisture_target)
        if surface_dryness_risk not in (None, ""):
            payload["surface_dryness_risk"] = str(surface_dryness_risk)
        if runoff_risk not in (None, ""):
            payload["runoff_risk"] = str(runoff_risk)
        if seeding_transition_ready is not None:
            payload["seeding_transition_ready"] = bool(seeding_transition_ready)
        if seeding_block_reason not in (None, ""):
            payload["seeding_block_reason"] = str(seeding_block_reason)
        objective_mm: float | None = None
        if objectif_mm is not None:
            try:
                objective_mm = float(objectif_mm)
            except (TypeError, ValueError):
                objective_mm = None
        if objective_mm is None and zones:
            from .water import _zone_session_surface_mm

            objective_mm = _zone_session_surface_mm(zones)
        if objective_mm is None and total_mm is not None and not zones:
            try:
                objective_mm = float(total_mm)
            except (TypeError, ValueError):
                objective_mm = None
        if zones:
            payload.update(build_watering_session_summary(zones, source=source, objective_mm=objective_mm))
        if objective_mm is not None:
            payload["objectif_mm"] = float(objective_mm)
            payload["objective_mm"] = float(objective_mm)
            payload["total_mm"] = float(objective_mm)
            payload["session_total_mm"] = float(objective_mm)
        elif total_mm is not None:
            payload["total_mm"] = float(total_mm)
            payload["session_total_mm"] = float(total_mm)
        self._append_history(payload)
        return payload

    def record_user_action(
        self,
        action: str,
        state: str,
        reason: str | None = None,
        plan_type: str | None = None,
        zone_count: int | None = None,
        passages: int | None = None,
        triggered_at: datetime | None = None,
    ) -> dict[str, Any]:
        summary = _normalize_user_action_summary(
            {
                "state": state,
                "action": action,
                "triggered_at": (triggered_at or datetime.now(timezone.utc)).isoformat(),
                "reason": reason,
                "plan_type": plan_type,
                "zone_count": zone_count,
                "passages": passages,
            }
        )
        if summary is None:
            summary = {
                "state": "refuse",
                "action": str(action),
                "triggered_at": (triggered_at or datetime.now(timezone.utc)).isoformat(),
            }
            if reason not in (None, ""):
                summary["reason"] = str(reason)
        self.memory["derniere_action_utilisateur"] = summary
        return summary

    def register_product(
        self,
        product_id: str,
        nom: str,
        type_produit: str,
        dose_conseillee: str | None = None,
        usage_mode: str | None = None,
        max_applications_per_year: int | None = None,
        reapplication_after_days: int | None = None,
        delai_avant_tonte_jours: int | None = None,
        phase_compatible: str | list[str] | None = None,
        application_months: str | list[int] | None = None,
        application_type: str | None = None,
        application_requires_watering_after: bool | None = None,
        application_post_watering_mm: float | None = None,
        application_irrigation_block_hours: float | None = None,
        application_irrigation_delay_minutes: float | None = None,
        application_irrigation_mode: str | None = None,
        application_label_notes: str | None = None,
        note: str | None = None,
        temperature_min: float | None = None,
        temperature_max: float | None = None,
    ) -> dict[str, Any]:
        record = normalize_product_record(
            product_id,
            {
                "nom": nom,
                "type": type_produit,
                "dose_conseillee": dose_conseillee,
                "usage_mode": usage_mode,
                "max_applications_per_year": max_applications_per_year,
                "reapplication_after_days": reapplication_after_days,
                "delai_avant_tonte_jours": delai_avant_tonte_jours,
                "phase_compatible": phase_compatible,
                "application_months": application_months,
                "application_type": application_type,
                "application_requires_watering_after": application_requires_watering_after,
                "application_post_watering_mm": application_post_watering_mm,
                "application_irrigation_block_hours": application_irrigation_block_hours,
                "application_irrigation_delay_minutes": application_irrigation_delay_minutes,
                "application_irrigation_mode": application_irrigation_mode,
                "application_label_notes": application_label_notes,
                "note": note,
                "temperature_min": temperature_min,
                "temperature_max": temperature_max,
            },
        )
        if record is None:
            raise ValueError("Identifiant ou produit invalide.")
        self.products[record["id"]] = record
        self.memory["catalogue_produits"] = len(self.products)
        self._normalize_selected_product_id()
        return record

    def remove_product(self, product_id: str) -> str:
        normalized = normalize_product_id(product_id)
        if not normalized:
            raise ValueError("Identifiant produit invalide.")
        self.products.pop(normalized, None)
        self.memory["catalogue_produits"] = len(self.products)
        self._normalize_selected_product_id()
        return normalized

    def compute_snapshot(
        self,
        *,
        today: date,
        temperature: float | None,
        forecast_temperature_today: float | None = None,
        temperature_source: str | None = None,
        temperature_reference_hydrique: float | None = None,
        pluie_24h: float | None,
        pluie_demain: float | None,
        humidite: float | None,
        type_sol: str,
        etp_capteur: float | None,
        humidite_sol: float | None,
        vent: float | None,
        rosee: float | None,
        hauteur_gazon: float | None,
        retour_arrosage: float | None,
        pluie_source: str,
        pluie_demain_source: str | None,
        weather_profile: dict[str, Any] | None,
        hauteur_min_tondeuse_cm: float | None = None,
        hauteur_max_tondeuse_cm: float | None = None,
        hour_of_day: int | None = None,
        pluie_j2: float | None = None,
        pluie_3j: float | None = None,
        pluie_probabilite_max_3j: float | None = None,
        et0_source: str | None = None,
        sun_context: dict[str, Any] | None = None,
        mower_context: dict[str, Any] | None = None,
        runtime_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        weather_profile = weather_profile or {}
        etp = compute_etp(
            temperature=temperature,
            pluie_24h=pluie_24h,
            etp_capteur=etp_capteur,
            temperature_reference_hydrique=temperature_reference_hydrique,
            weather_profile=weather_profile,
        )
        arrosage_reel_jour = compute_recent_watering_mm(self.history, today=today, days=0)
        self.soil_balance = update_soil_balance(
            self.soil_balance,
            today=today,
            pluie_mm=pluie_24h,
            arrosage_mm=arrosage_reel_jour,
            etp_mm=etp,
            type_sol=type_sol,
        )
        context = DecisionContext.from_legacy_args(
            history=self.history,
            today=today,
            hour_of_day=hour_of_day,
            temperature=temperature,
            forecast_temperature_today=forecast_temperature_today,
            temperature_source=temperature_source,
            temperature_reference_hydrique=temperature_reference_hydrique,
            et0_source=et0_source,
            pluie_24h=pluie_24h,
            pluie_demain=pluie_demain,
            pluie_j2=pluie_j2,
            pluie_3j=pluie_3j,
            pluie_probabilite_max_3j=pluie_probabilite_max_3j,
            humidite=humidite,
            type_sol=type_sol,
            etp_capteur=etp_capteur,
            humidite_sol=humidite_sol,
            vent=vent,
            rosee=rosee,
            hauteur_gazon=hauteur_gazon,
            retour_arrosage=retour_arrosage,
            pluie_source=pluie_source,
            weather_profile=weather_profile,
            soil_balance=self.soil_balance,
            memory=self.memory,
            sun_context=sun_context,
            hauteur_min_tondeuse_cm=hauteur_min_tondeuse_cm,
            hauteur_max_tondeuse_cm=hauteur_max_tondeuse_cm,
            mower_context=mower_context,
            runtime_context=runtime_context,
        )
        previous_result = self.last_result
        result = build_decision_result(context)
        self._preserve_last_valid_hydric_metrics(
            result=result,
            previous_result=previous_result,
            etp=etp,
        )
        temperature_note = self._build_temperature_note(
            temperature=temperature,
            forecast_temperature_today=forecast_temperature_today,
            temperature_source=temperature_source,
            arrosage_recommande=result.arrosage_recommande,
        )
        if temperature_note:
            conseil = result.conseil_principal.strip()
            if conseil.endswith((".", "!", "?")):
                conseil = conseil[:-1].rstrip()
            if conseil:
                result.conseil_principal = f"{conseil} ({temperature_note})."
            else:
                result.conseil_principal = temperature_note
            result.extra.setdefault("temperature_note", temperature_note)
        result.extra.setdefault(
            "configuration",
            {
                "type_sol": type_sol,
            },
        )
        result.extra.setdefault("type_sol", type_sol)
        result.extra.setdefault("forecast_temperature_today", forecast_temperature_today)
        result.extra.setdefault("temperature_source", temperature_source)
        result.extra.setdefault("temperature_reference_hydrique", temperature_reference_hydrique)
        result.extra.setdefault("et0_source", et0_source)
        if pluie_demain_source is not None:
            result.extra.setdefault("pluie_demain_source", pluie_demain_source)
        self.last_result = result
        snapshot = result.to_snapshot()
        advanced_context = result.advanced_context or {}
        water_balance = result.water_balance or {}
        phase_context = result.phase_context or {}
        snapshot.update(
            {
                "mode": snapshot["phase_active"],
                "phase_active": snapshot["phase_active"],
                "date_action": phase_context.get("date_action"),
                "date_fin": phase_context.get("date_fin"),
                "phase_age_days": phase_context.get("phase_age_days"),
                "jours_restants": phase_context.get("jours_restants"),
                "etp": etp,
                "humidite_sol": advanced_context.get("humidite_sol"),
                "vent": advanced_context.get("vent"),
                "rosee": advanced_context.get("rosee"),
                "hauteur_gazon": advanced_context.get("hauteur_gazon"),
                "retour_arrosage": advanced_context.get("retour_arrosage"),
                "pluie_source": advanced_context.get("pluie_source"),
                "forecast_pluie_j2": pluie_j2,
                "forecast_pluie_3j": pluie_3j,
                "forecast_probabilite_max_3j": pluie_probabilite_max_3j,
                "forecast_temperature_today": forecast_temperature_today,
                "temperature_source": temperature_source,
                "temperature_reference_hydrique": temperature_reference_hydrique,
                "et0_source": et0_source,
                "water_balance": water_balance,
                "deficit_jour": water_balance.get("deficit_jour"),
                "deficit_3j": water_balance.get("deficit_3j"),
                "deficit_7j": water_balance.get("deficit_7j"),
                "bilan_hydrique_journalier_mm": water_balance.get("bilan_hydrique_journalier_mm"),
                "bilan_hydrique_precedent_mm": water_balance.get("bilan_hydrique_precedent_mm"),
                "soil_balance": water_balance.get("soil_balance"),
                "pluie_efficace": water_balance.get("pluie_efficace"),
                "arrosage_recent": water_balance.get("arrosage_recent"),
                "arrosage_recent_jour": water_balance.get("arrosage_recent_jour"),
                "arrosage_recent_3j": water_balance.get("arrosage_recent_3j"),
                "arrosage_recent_7j": water_balance.get("arrosage_recent_7j"),
                "bilan_hydrique_mm": water_balance.get("bilan_hydrique_mm"),
                "bilan_hydrique_3j": water_balance.get("bilan_hydrique_3j"),
                "bilan_hydrique_7j": water_balance.get("bilan_hydrique_7j"),
                "objectif_mm": water_balance.get("objectif_mm", snapshot.get("objectif_mm")),
                "score_hydrique": snapshot.get("score_hydrique"),
                "score_stress": snapshot.get("score_stress"),
                "score_tonte": snapshot.get("score_tonte"),
                "tonte_autorisee": snapshot.get("tonte_autorisee"),
                "tonte_statut": snapshot.get("tonte_statut"),
                "arrosage_auto_autorise": snapshot.get("arrosage_auto_autorise"),
                "arrosage_recommande": snapshot.get("arrosage_recommande"),
                "type_arrosage": snapshot.get("type_arrosage"),
                "arrosage_conseille": snapshot.get("arrosage_conseille"),
                "raison_decision": snapshot.get("raison_decision"),
                "conseil_principal": snapshot.get("conseil_principal"),
                "action_recommandee": snapshot.get("action_recommandee"),
                "action_a_eviter": snapshot.get("action_a_eviter"),
                "niveau_action": snapshot.get("niveau_action"),
                "fenetre_optimale": snapshot.get("fenetre_optimale"),
                "risque_gazon": snapshot.get("risque_gazon"),
                "urgence": snapshot.get("urgence"),
                "prochaine_reevaluation": snapshot.get("prochaine_reevaluation"),
                "decision_resume": snapshot.get("decision_resume"),
                "pluie_demain_source": pluie_demain_source,
            }
        )
        self.mode = snapshot["phase_active"]
        self.date_action = self._coerce_date(snapshot.get("date_action"))
        self.memory = compute_memory(
            history=self.history,
            current_phase=snapshot["phase_active"],
            decision=snapshot,
            previous_memory=self.memory,
            today=today,
        )
        snapshot["feedback_observation"] = self.memory.get("feedback_observation")
        if self.last_result is not None:
            self.last_result.extra["feedback_observation"] = self.memory.get("feedback_observation")
        et0_snapshot = snapshot.get("et0_mm")
        etc_snapshot = snapshot.get("etc_mm")
        try:
            if et0_snapshot is not None and float(et0_snapshot) > 0:
                self.memory["last_valid_et0_mm"] = round(float(et0_snapshot), 1)
        except (TypeError, ValueError):
            pass
        try:
            if etc_snapshot is not None and float(etc_snapshot) > 0:
                self.memory["last_valid_etc_mm"] = round(float(etc_snapshot), 1)
        except (TypeError, ValueError):
            pass
        self.memory["hauteur_tonte_recommandee_cm"] = snapshot.get("hauteur_tonte_recommandee_cm")
        self.memory["hauteur_tonte_recommandee_date"] = today.isoformat()
        self.memory["catalogue_produits"] = len(self.products)
        fungal_risk = compute_fungal_risk(
            temperature=temperature,
            humidite=humidite,
            rosee=rosee,
            pluie_24h=pluie_24h,
            pluie_demain=pluie_demain,
            hour_of_day=hour_of_day if hour_of_day is not None else 12,
        )
        snapshot.update(fungal_risk)
        snapshot["assistant"] = build_assistant_decision(snapshot)
        snapshot["intervention_recommendation"] = build_intervention_recommendation(
            today=today,
            phase_active=snapshot.get("phase_active"),
            phase_source=snapshot.get("phase_dominante_source"),
            sous_phase=snapshot.get("sous_phase"),
            selected_product_id=self.selected_product_id,
            selected_product_name=self.selected_product_name,
            products=self.products,
            history=self.history,
            application_state=snapshot,
            temperature=temperature,
            forecast_temperature_today=forecast_temperature_today,
            temperature_source=temperature_source,
        )
        return snapshot
