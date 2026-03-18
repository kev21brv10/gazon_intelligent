from __future__ import annotations

"""Objets typés pour le moteur de décision."""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from .const import DEFAULT_TYPE_SOL


@dataclass
class DecisionContext:
    """Contexte complet d'une décision métier."""

    history: list[dict[str, Any]]
    today: date
    hour_of_day: int | None = None
    temperature: float | None = None
    pluie_24h: float | None = None
    pluie_demain: float | None = None
    humidite: float | None = None
    type_sol: str = DEFAULT_TYPE_SOL
    etp_capteur: float | None = None
    humidite_sol: float | None = None
    vent: float | None = None
    rosee: float | None = None
    hauteur_gazon: float | None = None
    retour_arrosage: float | None = None
    pluie_source: str = "capteur_pluie_24h"
    weather_profile: dict[str, Any] = field(default_factory=dict)
    soil_balance: dict[str, Any] | None = None
    memory: dict[str, Any] | None = None
    config: dict[str, Any] = field(default_factory=dict)
    weather_today: dict[str, Any] = field(default_factory=dict)
    weather_tomorrow: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_legacy_args(
        cls,
        history: list[dict[str, Any]],
        today: date | None = None,
        hour_of_day: int | None = None,
        temperature: float | None = None,
        pluie_24h: float | None = None,
        pluie_demain: float | None = None,
        humidite: float | None = None,
        type_sol: str = DEFAULT_TYPE_SOL,
        etp_capteur: float | None = None,
        humidite_sol: float | None = None,
        vent: float | None = None,
        rosee: float | None = None,
        hauteur_gazon: float | None = None,
        retour_arrosage: float | None = None,
        pluie_source: str = "capteur_pluie_24h",
        weather_profile: dict[str, Any] | None = None,
        soil_balance: dict[str, Any] | None = None,
    ) -> "DecisionContext":
        today = today or date.today()
        weather_profile = weather_profile or {}
        return cls(
            history=[item for item in history if isinstance(item, dict)],
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
            soil_balance=soil_balance,
            config={"type_sol": type_sol},
            weather_today={
                "date": today.isoformat(),
                "temperature": temperature,
                "pluie_24h": pluie_24h,
                "humidite": humidite,
                "etp_capteur": etp_capteur,
            },
            weather_tomorrow={
                "date": (today + timedelta(days=1)).isoformat(),
                "pluie_demain": pluie_demain,
            },
        )


@dataclass
class DecisionResult:
    """Résultat final de décision, sérialisable en snapshot HA."""

    phase_dominante: str
    sous_phase: str
    action_recommandee: str
    action_a_eviter: str
    niveau_action: str
    fenetre_optimale: str
    risque_gazon: str
    objectif_arrosage: float
    tonte_autorisee: bool
    conseil_principal: str = ""
    tonte_statut: str = "a_surveiller"
    arrosage_recommande: bool = False
    arrosage_auto_autorise: bool = False
    type_arrosage: str = "personnalise"
    arrosage_conseille: str = "personnalise"
    phase_dominante_source: str | None = None
    sous_phase_detail: str | None = None
    sous_phase_age_days: int | None = None
    sous_phase_progression: int | None = None
    prochaine_reevaluation: str | None = None
    urgence: str | None = None
    raison_decision: str | None = None
    score_hydrique: int | None = None
    score_stress: int | None = None
    score_tonte: int | None = None
    decision_resume: dict[str, Any] | None = None
    advanced_context: dict[str, Any] | None = None
    water_balance: dict[str, Any] | None = None
    phase_context: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_snapshot(self) -> dict[str, Any]:
        """Sérialise le résultat au format attendu par les entités."""
        payload: dict[str, Any] = {
            "mode": self.phase_dominante,
            "phase_active": self.phase_dominante,
            "phase_dominante": self.phase_dominante,
            "phase_dominante_source": self.phase_dominante_source,
            "sous_phase": self.sous_phase,
            "sous_phase_detail": self.sous_phase_detail,
            "sous_phase_age_days": self.sous_phase_age_days,
            "sous_phase_progression": self.sous_phase_progression,
            "objectif_mm": self.objectif_arrosage,
            "objectif_arrosage": self.objectif_arrosage,
            "tonte_autorisee": self.tonte_autorisee,
            "tonte_statut": self.tonte_statut,
            "arrosage_recommande": self.arrosage_recommande,
            "arrosage_auto_autorise": self.arrosage_auto_autorise,
            "type_arrosage": self.type_arrosage,
            "arrosage_conseille": self.arrosage_conseille,
            "conseil_principal": self.conseil_principal,
            "action_recommandee": self.action_recommandee,
            "action_a_eviter": self.action_a_eviter,
            "niveau_action": self.niveau_action,
            "fenetre_optimale": self.fenetre_optimale,
            "risque_gazon": self.risque_gazon,
            "urgence": self.urgence,
            "prochaine_reevaluation": self.prochaine_reevaluation,
            "raison_decision": self.raison_decision,
            "score_hydrique": self.score_hydrique,
            "score_stress": self.score_stress,
            "score_tonte": self.score_tonte,
            "decision_resume": self.decision_resume,
            "advanced_context": self.advanced_context,
            "water_balance": self.water_balance,
            "phase_context": self.phase_context,
        }
        if self.phase_context:
            payload.setdefault("date_action", self.phase_context.get("date_action"))
            payload.setdefault("date_fin", self.phase_context.get("date_fin"))
            payload.setdefault("phase_age_days", self.phase_context.get("phase_age_days"))
            payload.setdefault("jours_restants", self.phase_context.get("jours_restants"))
        payload.update(self.extra)
        return {key: value for key, value in payload.items() if value is not None}
