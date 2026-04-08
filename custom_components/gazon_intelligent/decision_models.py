from __future__ import annotations

"""Objets typés pour le moteur de décision."""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from .const import DEFAULT_TYPE_SOL
from .phases import PHASE_DURATIONS_DAYS, SUBPHASE_RULES

POSSIBLE_PHASE_DOMINANTE_VALUES: tuple[str, ...] = tuple(PHASE_DURATIONS_DAYS.keys())
POSSIBLE_SOUS_PHASE_VALUES: tuple[str, ...] = tuple(
    dict.fromkeys(
        label
        for rules in SUBPHASE_RULES.values()
        for _, label in rules
    )
)
POSSIBLE_NIVEAU_ACTION_VALUES: tuple[str, ...] = (
    "aucune_action",
    "surveiller",
    "a_faire",
    "critique",
)
POSSIBLE_TONTE_STATUT_VALUES: tuple[str, ...] = (
    "autorisee",
    "autorisee_avec_precaution",
    "a_surveiller",
    "deconseillee",
    "interdite",
)
POSSIBLE_FENETRE_OPTIMALE_VALUES: tuple[str, ...] = (
    "maintenant",
    "ce_matin",
    "demain_matin",
    "apres_pluie",
    "soir",
    "attendre",
)
POSSIBLE_TYPE_ARROSAGE_VALUES: tuple[str, ...] = (
    "aucune_action",
    "bloque",
    "personnalise",
    "manuel_frequent",
    "fractionne",
    "application_technique",
    "auto",
)

TYPE_ARROSAGE_DISPLAY_LABELS: dict[str, str] = {
    "aucune_action": "Aucune action",
    "bloque": "Arrosage bloqué",
    "personnalise": "Réglage personnalisé",
    "manuel_frequent": "Arrosage manuel fréquent",
    "fractionne": "Arrosage fractionné",
    "application_technique": "Arrosage technique",
    "auto": "Arrosage automatique",
}


@dataclass
class DecisionContext:
    """Contexte complet d'une décision métier."""

    history: list[dict[str, Any]]
    today: date
    hour_of_day: int | None = None
    temperature: float | None = None
    forecast_temperature_today: float | None = None
    temperature_source: str | None = None
    temperature_reference_hydrique: float | None = None
    et0_source: str | None = None
    pluie_24h: float | None = None
    pluie_demain: float | None = None
    pluie_j2: float | None = None
    pluie_3j: float | None = None
    pluie_probabilite_max_3j: float | None = None
    humidite: float | None = None
    type_sol: str = DEFAULT_TYPE_SOL
    hauteur_min_tondeuse_cm: float | None = None
    hauteur_max_tondeuse_cm: float | None = None
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
        forecast_temperature_today: float | None = None,
        temperature_source: str | None = None,
        temperature_reference_hydrique: float | None = None,
        et0_source: str | None = None,
        pluie_24h: float | None = None,
        pluie_demain: float | None = None,
        pluie_j2: float | None = None,
        pluie_3j: float | None = None,
        pluie_probabilite_max_3j: float | None = None,
        humidite: float | None = None,
        type_sol: str = DEFAULT_TYPE_SOL,
        hauteur_min_tondeuse_cm: float | None = None,
        hauteur_max_tondeuse_cm: float | None = None,
        etp_capteur: float | None = None,
        humidite_sol: float | None = None,
        vent: float | None = None,
        rosee: float | None = None,
        hauteur_gazon: float | None = None,
        retour_arrosage: float | None = None,
        pluie_source: str = "capteur_pluie_24h",
        weather_profile: dict[str, Any] | None = None,
        soil_balance: dict[str, Any] | None = None,
        memory: dict[str, Any] | None = None,
    ) -> "DecisionContext":
        today = today or dt_util.now().date()
        weather_profile = weather_profile or {}
        return cls(
            history=[item for item in history if isinstance(item, dict)],
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
            hauteur_min_tondeuse_cm=hauteur_min_tondeuse_cm,
            hauteur_max_tondeuse_cm=hauteur_max_tondeuse_cm,
            etp_capteur=etp_capteur,
            humidite_sol=humidite_sol,
            vent=vent,
            rosee=rosee,
            hauteur_gazon=hauteur_gazon,
            retour_arrosage=retour_arrosage,
            pluie_source=pluie_source,
            weather_profile=weather_profile,
            soil_balance=soil_balance,
            memory=memory,
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
    hauteur_tonte_recommandee_cm: float | None = None
    hauteur_tonte_min_cm: float | None = None
    hauteur_tonte_max_cm: float | None = None
    conseil_principal: str = ""
    tonte_statut: str = "a_surveiller"
    arrosage_recommande: bool = False
    arrosage_auto_autorise: bool = False
    type_arrosage: str = "personnalise"
    arrosage_conseille: str = "personnalise"
    watering_passages: int = 1
    watering_pause_minutes: int = 25
    deficit_brut_mm: float | None = None
    deficit_mm_ajuste: float | None = None
    mm_cible: float | None = None
    mm_final_recommande: float | None = None
    mm_final: float | None = None
    fractionnement: dict[str, Any] | None = None
    niveau_confiance: str | None = None
    heat_stress_level: str | None = None
    phase_dominante_source: str | None = None
    sous_phase_detail: str | None = None
    sous_phase_age_days: int | None = None
    sous_phase_progression: float | None = None
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

    @property
    def mode(self) -> str:
        """Alias de compatibilité pour l'ancien snapshot."""
        return self.phase_dominante

    @property
    def phase_active(self) -> str:
        """Alias de compatibilité pour l'ancien snapshot."""
        return self.phase_dominante

    @property
    def objectif_mm(self) -> float:
        """Alias de compatibilité pour l'ancien snapshot."""
        return self.objectif_arrosage

    @property
    def mm_a_appliquer(self) -> float | None:
        """Alias lisible pour le moteur d'arrosage refondu."""
        if self.mm_final is not None:
            return self.mm_final
        if self.mm_final_recommande is not None:
            return self.mm_final_recommande
        return self.objectif_arrosage

    @property
    def possible_values(self) -> dict[str, tuple[str, ...]]:
        """Liste des valeurs possibles exposées à l'UI pour l'aide utilisateur."""
        return {
            "phase_dominante": POSSIBLE_PHASE_DOMINANTE_VALUES,
            "sous_phase": POSSIBLE_SOUS_PHASE_VALUES,
            "niveau_action": POSSIBLE_NIVEAU_ACTION_VALUES,
            "tonte_statut": POSSIBLE_TONTE_STATUT_VALUES,
            "fenetre_optimale": POSSIBLE_FENETRE_OPTIMALE_VALUES,
            "type_arrosage": POSSIBLE_TYPE_ARROSAGE_VALUES,
        }

    def possible_values_for(self, key: str) -> tuple[str, ...] | None:
        """Retourne les valeurs possibles pour un attribut métier donné."""
        return self.possible_values.get(key)

    def display_label_for(self, key: str) -> str:
        """Retourne un libellé utilisateur lisible pour une valeur métier."""
        value = getattr(self, key, None)
        if value is None:
            extra = getattr(self, "extra", None)
            if isinstance(extra, dict):
                value = extra.get(key)
        if key == "type_arrosage" and value is not None:
            return TYPE_ARROSAGE_DISPLAY_LABELS.get(str(value), str(value))
        if value is None:
            return ""
        return str(value)

    def possible_display_values_for(self, key: str) -> tuple[str, ...] | None:
        """Retourne les valeurs possibles sous forme lisible par l'utilisateur."""
        if key == "type_arrosage":
            return tuple(TYPE_ARROSAGE_DISPLAY_LABELS.get(value, value) for value in POSSIBLE_TYPE_ARROSAGE_VALUES)
        return self.possible_values_for(key)

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
            "hauteur_tonte_recommandee_cm": self.hauteur_tonte_recommandee_cm,
            "hauteur_tonte_min_cm": self.hauteur_tonte_min_cm,
            "hauteur_tonte_max_cm": self.hauteur_tonte_max_cm,
            "tonte_statut": self.tonte_statut,
            "arrosage_recommande": self.arrosage_recommande,
            "arrosage_auto_autorise": self.arrosage_auto_autorise,
            "type_arrosage": self.type_arrosage,
            "arrosage_conseille": self.arrosage_conseille,
            "watering_passages": self.watering_passages,
            "watering_pause_minutes": self.watering_pause_minutes,
            "deficit_brut_mm": self.deficit_brut_mm,
            "deficit_mm_ajuste": self.deficit_mm_ajuste,
            "mm_cible": self.mm_cible,
            "mm_final_recommande": self.mm_final_recommande,
            "mm_final": self.mm_final,
            "fractionnement": self.fractionnement,
            "niveau_confiance": self.niveau_confiance,
            "heat_stress_level": self.heat_stress_level,
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
