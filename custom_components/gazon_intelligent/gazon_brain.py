from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from .const import DEFAULT_AUTO_IRRIGATION_ENABLED, DEFAULT_MODE, INTERVENTIONS_ACTIONS
from .assistant import build_assistant_decision
from .decision import (
    DecisionContext,
    build_decision_result,
    compute_etp,
    compute_memory,
    compute_recent_watering_mm,
    phase_duration_days,
)
from .decision_models import DecisionResult
from .memory import (
    APPLICATION_DEFAULTS,
    _normalize_user_action_summary,
    normalize_product_id,
    normalize_product_record,
)
from .soil_balance import normalize_soil_balance_state, update_soil_balance
from .water import build_watering_session_summary


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
            "date_derniere_mise_a_jour": None,
            "auto_irrigation_enabled": DEFAULT_AUTO_IRRIGATION_ENABLED,
        }
        self.products: dict[str, dict[str, Any]] = {}
        self.soil_balance: dict[str, Any] = {}
        self.last_result: DecisionResult | None = None

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

    def load_state(self, data: dict[str, Any] | None) -> None:
        state = data or {}
        mode = state.get("mode")
        if mode:
            self.mode = str(mode)
        date_str = state.get("date_action")
        if date_str:
            try:
                self.date_action = date.fromisoformat(str(date_str))
            except ValueError:
                self.date_action = None
        history = state.get("history")
        if isinstance(history, list):
            self.history = [item for item in history if isinstance(item, dict)]
        else:
            self.history = []
        products = state.get("products")
        if isinstance(products, dict):
            self.products = {}
            for key, value in products.items():
                if not isinstance(key, str) or not isinstance(value, dict):
                    continue
                cleaned = dict(value)
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
        memory = state.get("memory")
        if isinstance(memory, dict):
            self.memory = memory
        else:
            self.memory = {
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
                "date_derniere_mise_a_jour": None,
                "auto_irrigation_enabled": DEFAULT_AUTO_IRRIGATION_ENABLED,
            }
        self.memory.setdefault("historique_total", len(self.history))
        self.memory.setdefault("derniere_phase_active", self.mode)
        self.memory.setdefault("catalogue_produits", len(self.products))
        self.memory.setdefault("derniere_action_utilisateur", None)
        self.memory.setdefault("auto_irrigation_enabled", DEFAULT_AUTO_IRRIGATION_ENABLED)
        self.memory.setdefault("feedback_observation", None)
        self.memory["historique_total"] = len(self.history)
        self.memory["catalogue_produits"] = len(self.products)

    def dump_state(self) -> dict[str, Any]:
        self.memory["historique_total"] = len(self.history)
        self.memory["catalogue_produits"] = len(self.products)
        return {
            "mode": self.mode,
            "date_action": self.date_action.isoformat() if self.date_action else None,
            "history": self.history[-300:],
            "products": self.products,
            "soil_balance": self.soil_balance,
            "memory": self.memory,
        }

    def _append_history(self, item: dict[str, Any]) -> None:
        self.history.append(item)
        self.history = self.history[-300:]

    def _resolve_product_record(self, product_id: str | None) -> dict[str, Any] | None:
        normalized = normalize_product_id(product_id)
        if not normalized:
            return None
        product = self.products.get(normalized)
        if not isinstance(product, dict):
            return None
        return product

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
        end = start + timedelta(days=phase_duration_days(item_type))
        return today > end

    def set_mode(self, mode: str) -> None:
        if mode == "Normal":
            self.set_normal()
            return
        self.declare_intervention(mode)

    def set_date_action(self, date_action: date | None = None) -> None:
        target_date = date_action or date.today()
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
        today = date.today()
        self.history = [
            item
            for item in self.history
            if item.get("type") not in INTERVENTIONS_ACTIONS
            or not item.get("date")
            or self._is_history_item_expired(item, today)
        ]
        self.mode = "Normal"
        self.date_action = None

    def declare_intervention(
        self,
        intervention: str,
        date_action: date | None = None,
        produit_id: str | None = None,
        produit: str | None = None,
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
        target_date = date_action or date.today()
        product_record = self._resolve_product_record(produit_id)
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
            item["produit_catalogue"] = product_record
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
            "date": (date_action or date.today()).isoformat(),
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
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": "arrosage",
            "date": (date_action or date.today()).isoformat(),
            "source": source,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        if objectif_mm is not None:
            payload["objectif_mm"] = float(objectif_mm)
        if total_mm is None and objectif_mm is not None:
            total_mm = float(objectif_mm)
        if total_mm is not None:
            payload["total_mm"] = float(total_mm)
            payload["session_total_mm"] = float(total_mm)
        if zones:
            payload.update(build_watering_session_summary(zones, source=source))
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
        reapplication_after_days: int | None = None,
        delai_avant_tonte_jours: int | None = None,
        phase_compatible: str | None = None,
        application_type: str | None = None,
        application_requires_watering_after: bool | None = None,
        application_post_watering_mm: float | None = None,
        application_irrigation_block_hours: float | None = None,
        application_irrigation_delay_minutes: float | None = None,
        application_irrigation_mode: str | None = None,
        application_label_notes: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        record = normalize_product_record(
            product_id,
            {
                "nom": nom,
                "type": type_produit,
                "dose_conseillee": dose_conseillee,
                "reapplication_after_days": reapplication_after_days,
                "delai_avant_tonte_jours": delai_avant_tonte_jours,
                "phase_compatible": phase_compatible,
                "application_type": application_type,
                "application_requires_watering_after": application_requires_watering_after,
                "application_post_watering_mm": application_post_watering_mm,
                "application_irrigation_block_hours": application_irrigation_block_hours,
                "application_irrigation_delay_minutes": application_irrigation_delay_minutes,
                "application_irrigation_mode": application_irrigation_mode,
                "application_label_notes": application_label_notes,
                "note": note,
            },
        )
        if record is None:
            raise ValueError("Identifiant ou produit invalide.")
        self.products[record["id"]] = record
        self.memory["catalogue_produits"] = len(self.products)
        return record

    def remove_product(self, product_id: str) -> str:
        normalized = normalize_product_id(product_id)
        if not normalized:
            raise ValueError("Identifiant produit invalide.")
        self.products.pop(normalized, None)
        self.memory["catalogue_produits"] = len(self.products)
        return normalized

    def compute_snapshot(
        self,
        *,
        today: date,
        temperature: float | None,
        forecast_temperature_today: float | None = None,
        temperature_source: str | None = None,
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
    ) -> dict[str, Any]:
        weather_profile = weather_profile or {}
        etp = compute_etp(
            temperature=temperature,
            pluie_24h=pluie_24h,
            etp_capteur=etp_capteur,
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
            hauteur_min_tondeuse_cm=hauteur_min_tondeuse_cm,
            hauteur_max_tondeuse_cm=hauteur_max_tondeuse_cm,
        )
        result = build_decision_result(context)
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
        self.date_action = snapshot.get("date_action")
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
        self.memory["hauteur_tonte_recommandee_cm"] = snapshot.get("hauteur_tonte_recommandee_cm")
        self.memory["hauteur_tonte_recommandee_date"] = today.isoformat()
        self.memory["catalogue_produits"] = len(self.products)
        snapshot["assistant"] = build_assistant_decision(snapshot)
        return snapshot
