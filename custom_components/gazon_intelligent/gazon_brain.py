from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .const import DEFAULT_MODE, DEFAULT_TYPE_SOL, INTERVENTIONS_ACTIONS
from .decision import (
    build_decision_snapshot,
    compute_etp,
    compute_memory,
    compute_recent_watering_mm,
    phase_duration_days,
)
from .memory import normalize_product_id, normalize_product_record
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
            "derniere_application": None,
            "prochaine_reapplication": None,
            "catalogue_produits": 0,
            "date_derniere_mise_a_jour": None,
        }
        self.products: dict[str, dict[str, Any]] = {}
        self.soil_balance: dict[str, Any] = {}

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
                "derniere_application": None,
                "prochaine_reapplication": None,
                "catalogue_produits": len(self.products),
                "date_derniere_mise_a_jour": None,
            }
        self.memory.setdefault("historique_total", len(self.history))
        self.memory.setdefault("derniere_phase_active", self.mode)
        self.memory.setdefault("catalogue_produits", len(self.products))
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
        item: dict[str, Any] = {
            "type": intervention,
            "date": target_date.isoformat(),
            "source": "service",
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

    def register_product(
        self,
        product_id: str,
        nom: str,
        type_produit: str,
        dose_conseillee: str | None = None,
        reapplication_after_days: int | None = None,
        delai_avant_tonte_jours: int | None = None,
        phase_compatible: str | None = None,
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
        weather_profile: dict[str, Any] | None,
        hour_of_day: int | None = None,
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
        snapshot = build_decision_snapshot(
            history=self.history,
            today=today,
            hour_of_day=hour_of_day,
            temperature=temperature,
            pluie_24h=pluie_24h,
            pluie_demain=pluie_demain,
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
        self.memory["catalogue_produits"] = len(self.products)
        return snapshot
