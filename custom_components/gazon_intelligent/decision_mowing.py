from __future__ import annotations

"""Logique pure liée à la tonte."""

import math
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from .const import (
    DEFAULT_HAUTEUR_MAX_TONDEUSE_CM,
    DEFAULT_HAUTEUR_MIN_TONDEUSE_CM,
)
try:
    from homeassistant.util import dt as dt_util
except Exception:  # pragma: no cover - repli hors Home Assistant (tests, environnement allégé)
    dt_util = None

from .decision_models import DecisionContext
from .guidance import compute_tonte_statut, is_active_rain_weather
from .memory import compute_application_state
from .water import (
    HISTORY_DATE_ONLY_FALLBACK_HOUR,
    resolve_history_moment,
)
from .scores import classify_stress_level

_MOWER_STEP_CM = 0.5
_MOWING_BLOCK_PRIORITIES = {
    "post_application_active": 1,
    "watering_in_progress": 2,
    "watering_cooldown": 3,
    "mowing_spacing": 4,
    "mowing_night": 5,
    "pluie_active": 20,
    "vent_fort": 21,
    "hauteur_trop_faible": 30,
    "regle_tiers_impossible": 31,
    "regle_tiers": 32,
    "rosee": 40,
    "humidite_elevee": 50,
    "pluie_recente": 51,
    "pluie_proche": 52,
    "pluie_annoncee": 53,
    "sol_humide_post_arrosage": 54,
    "stress_thermique": 60,
    "conditions_defavorables": 70,
}
_MOWING_FREQUENCY_BY_MONTH = {
    1: (0.0, "0 / semaine"),
    2: (0.0, "0 / semaine"),
    3: (2.5, "2 à 3 / semaine"),
    4: (2.5, "2 à 3 / semaine"),
    5: (5.0, "4 à 6 / semaine"),
    6: (5.0, "4 à 6 / semaine"),
    7: (3.0, "2 à 4 / semaine"),
    8: (3.0, "2 à 4 / semaine"),
    9: (5.0, "4 à 6 / semaine"),
    10: (5.0, "4 à 6 / semaine"),
    11: (1.5, "1 à 2 / semaine"),
    12: (0.0, "0 / semaine"),
}
_MOWING_WINDOW_LABELS = {
    "ideal": "Fenêtre idéale",
    "acceptable": "Fenêtre acceptable",
    "discouraged": "À éviter",
    "blocked": "Bloqué",
}
_MOWING_WINDOW_IDEAL_START = 10
_MOWING_WINDOW_IDEAL_END = 12
# FENÊTRE DU SOIR — ANCRÉE SUR LE COUCHER DU SOLEIL, pas sur une heure figée.
# Demandé par Kévin le 30/07/2026 : « il peut tondre plus tard, comme le soleil se couche plus
# tard ». Le créneau valait 17-19 h toute l'année. En juillet (coucher ~21 h 45) il s'arrêtait
# 2 h 45 trop tôt ; en décembre (coucher ~17 h) il tombait ENTIÈREMENT après la nuit — le gazon
# se serait fait tondre dans le noir si les autres gardes ne l'avaient pas rattrapé.
# On termine 90 min avant le coucher, la même marge de ressuyage que l'arrosage du soir
# (`guidance.EVENING_DRYING_MARGIN_MIN`) : une herbe coupée puis laissée humide toute la nuit
# est une porte ouverte aux maladies. Et on ouvre 3 h avant cette fin.
_MOWING_EVENING_END_BEFORE_SUNSET_MIN = 90
_MOWING_EVENING_WINDOW_MIN = 180
# Repli quand le coucher est inconnu (sun.sun absent au démarrage) : les anciennes bornes fixes.
# Volontairement conservateur — cf. la falaise de minuit, où un repli optimiste a coûté cher.
_MOWING_WINDOW_ACCEPTABLE_START = 17
_MOWING_WINDOW_ACCEPTABLE_END = 19
_MOWING_WINDOW_NIGHT_END = 22
_MOWING_WINDOW_DISCOURAGED_WIND = 20
_MOWING_WINDOW_BLOCK_WIND = 40
_MOWING_WINDOW_DISCOURAGED_TEMP_MIN = 25
_MOWING_WINDOW_BLOCK_TEMP_MIN = 30
_MOWING_WINDOW_BLOCK_HUMIDITY = 90
_MOWING_BUNDLE_CORE_KEYS = (
    "tonte_autorisee",
    "tonte_statut",
    "tonte_reason",
    "raison_blocage_code",
    "next_mowing_date",
    "next_mowing_display",
    "score_tonte",
    "score_stress",
    "hauteur_tonte_recommandee_cm",
    "hauteur_tonte_min_cm",
    "hauteur_tonte_max_cm",
    "hauteur_tonte_garde_fou_label",
    "mowing_blocked_by_watering",
    "mowing_blocked",
    "mowing_block_reason_code",
    "mowing_block_reason_label",
    "mowing_cooldown_remaining_minutes",
    "mowing_post_application_active",
    "mowing_is_overdue",
    "mowing_overdue_days",
    "mowing_overdue_factor",
    "gazon_hauteur_estimee_cm",
    "gazon_pousse_jour_cm",
    "gazon_pousse_state",
    "pluie_state",
    "mowing_watering_coordination",
    "mowing_watering_coordination_msg",
)
_OVERDUE_SOFT_OVERRIDE_CODES = {"conditions_defavorables", "stress_thermique"}


def _mowing_height_settings(context: DecisionContext) -> tuple[float, float, float]:
    """Retourne les bornes et le pas de la tondeuse, avec valeurs sûres par défaut."""
    min_height = context.hauteur_min_tondeuse_cm
    max_height = context.hauteur_max_tondeuse_cm
    try:
        min_height = float(min_height) if min_height is not None else DEFAULT_HAUTEUR_MIN_TONDEUSE_CM
    except (TypeError, ValueError):
        min_height = DEFAULT_HAUTEUR_MIN_TONDEUSE_CM
    try:
        max_height = float(max_height) if max_height is not None else DEFAULT_HAUTEUR_MAX_TONDEUSE_CM
    except (TypeError, ValueError):
        max_height = DEFAULT_HAUTEUR_MAX_TONDEUSE_CM

    if min_height > max_height:
        min_height, max_height = max_height, min_height
    min_height = _round_to_step(min_height)
    max_height = _round_to_step(max_height)
    if min_height > max_height:
        min_height, max_height = max_height, min_height
    return min_height, max_height, _MOWER_STEP_CM


def _round_to_step(value: float) -> float:
    """Arrondit à 0,5 cm près."""
    return round(round(value / _MOWER_STEP_CM) * _MOWER_STEP_CM, 2)


def _seasonal_base_height(month: int) -> float:
    """Retourne une hauteur de coupe prudente selon la saison."""
    if month in {1, 2, 11, 12}:
        return 5.0
    if month in {3, 4}:
        return 5.8
    if month in {5, 6}:
        return 5.0
    if month in {7, 8}:
        return 6.2
    if month in {9, 10}:
        return 5.0
    return 5.5


def _seasonal_mowing_frequency(month: int) -> tuple[float, str]:
    return _MOWING_FREQUENCY_BY_MONTH.get(month, (3.0, "2 à 4 / semaine"))


def _phase_adjusted_mowing_frequency(
    phase_bundle: dict[str, Any],
    month: int,
) -> tuple[float, str]:
    phase_dominante = str(phase_bundle.get("phase_dominante") or "")
    sous_phase = str(phase_bundle.get("sous_phase") or "")
    if phase_dominante != "Sursemis":
        return _seasonal_mowing_frequency(month)
    if sous_phase in {"Germination", "Enracinement"}:
        return 0.0, "0 / semaine"
    if sous_phase == "Reprise":
        return 1.0, "1 / semaine"
    if sous_phase == "Stabilisation":
        return 2.0, "2 / semaine"
    return 1.0, "1 / semaine"


_SURSEMIS_MOWING_BLOCKED_SUBPHASES = {"Germination", "Enracinement"}


def _mowing_window_label(state: str) -> str:
    return _MOWING_WINDOW_LABELS.get(str(state or "").strip().lower(), "À éviter")


def _round_up_to_step(value: float, minimum: float, step: float) -> float:
    """Arrondit vers le haut en respectant un pas donné."""
    if step <= 0:
        return round(value, 2)
    if value <= minimum:
        return round(minimum, 2)
    steps = math.ceil((value - minimum) / step - 1e-9)
    return round(minimum + (steps * step), 2)


def _round_down_to_step(value: float, minimum: float, step: float) -> float:
    """Arrondit vers le bas en respectant un pas donné."""
    if step <= 0:
        return round(value, 2)
    if value <= minimum:
        return round(minimum, 2)
    steps = math.floor((value - minimum) / step + 1e-9)
    return round(minimum + (steps * step), 2)


def _previous_recommended_height(context: DecisionContext) -> float | None:
    """Retourne la dernière hauteur recommandée persistée si elle existe."""
    memory = context.memory or {}
    value = memory.get("hauteur_tonte_recommandee_cm")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _last_sursemis_age_days(context: DecisionContext) -> int | None:
    """Estime l'âge du dernier sursemis pour piloter la reprise progressive."""
    for item in reversed(context.history):
        if item.get("type") != "Sursemis":
            continue
        raw_date = item.get("date")
        if not raw_date:
            continue
        try:
            return max((context.today - date.fromisoformat(str(raw_date))).days, 0)
        except ValueError:
            continue
    return None


def _parse_history_timestamp(item: dict[str, Any], today: date) -> datetime:
    """Retourne le meilleur horodatage disponible pour une entrée d'historique.

    Délègue à `water.resolve_history_moment`, SOURCE UNIQUE partagée avec l'arrosage depuis le
    29/07/2026 : avant, les deux sous-systèmes dataient le même arrosage déclaré à la main à 6 h
    d'écart. Cette fonction avait en plus un défaut propre : `declared_at` primait sur la date, si
    bien qu'une déclaration rétroactive (« j'ai arrosé avant-hier ») était datée du jour de saisie.
    Le résolveur partagé n'honore `declared_at` que s'il tombe le jour déclaré.

    Ne retourne jamais None, contrairement au résolveur : une entrée non datable retombe sur
    `today` — comportement historique de la tonte, conservé.
    """
    resolved = resolve_history_moment(item)
    if resolved is not None:
        return resolved
    return datetime.combine(
        today, time(HISTORY_DATE_ONLY_FALLBACK_HOUR % 24, 0), tzinfo=timezone.utc
    )


def _reference_now_utc(context: DecisionContext) -> datetime:
    """Instant courant, en UTC réel, pour mesurer un délai depuis un arrosage.

    Les horodatages d'arrosage (`ended_at`, `started_at`…) sont des instants UTC réels écrits par
    le coordinateur. Les comparer exige donc un « maintenant » lui aussi en UTC réel.

    `context.hour_of_day` est une heure LOCALE (`dt_util.now().hour`, Europe/Paris). La reconstruire
    en `tzinfo=timezone.utc` décalait l'instant de l'offset local — 2 h en été — et faisait donc
    expirer cooldown de tonte et délai de ressuyage 1 à 2 h trop tôt. On privilégie l'instant fourni
    par le coordinateur (`runtime_context["now_utc"]`) ; la reconstruction locale n'est qu'un repli
    pour les appels hors runtime (tests, calculs sur une journée passée).
    """
    runtime_context = context.runtime_context if isinstance(context.runtime_context, dict) else {}
    raw_now = runtime_context.get("now_utc")
    if raw_now:
        if isinstance(raw_now, datetime):
            parsed = raw_now
        else:
            try:
                parsed = datetime.fromisoformat(str(raw_now).replace("Z", "+00:00"))
            except ValueError:
                parsed = None
        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
    reference_hour = context.hour_of_day if context.hour_of_day is not None else 6
    # `time()` exige un entier : l'heure du contexte est décimale depuis la 0.31.5.
    return datetime.combine(context.today, time(int(reference_hour) % 24, 0), tzinfo=timezone.utc)


def _elapsed_minutes_since_watering(context: DecisionContext) -> int:
    """Minutes écoulées depuis le dernier arrosage, bornées à 0."""
    delta = _reference_now_utc(context) - _latest_watering_timestamp(context)
    return max(0, int(delta.total_seconds() // 60))


def _latest_watering_timestamp(context: DecisionContext) -> datetime:
    """Retourne l'horodatage du dernier arrosage détecté ou la date du jour."""
    runtime_context = context.runtime_context if isinstance(context.runtime_context, dict) else {}
    last_execution = runtime_context.get("last_irrigation_execution")
    if isinstance(last_execution, dict):
        parsed = _parse_history_timestamp(last_execution, context.today)
        if parsed:
            return parsed
    for item in reversed(context.history):
        if item.get("type") != "arrosage":
            continue
        return _parse_history_timestamp(item, context.today)
    return datetime.combine(context.today, time(6, 0), tzinfo=timezone.utc)


def _active_irrigation_session(context: DecisionContext) -> dict[str, Any] | None:
    runtime_context = context.runtime_context if isinstance(context.runtime_context, dict) else {}
    session = runtime_context.get("active_irrigation_session")
    if not isinstance(session, dict):
        return None
    if session.get("status") in {"completed", "cancelled", "failed"}:
        return None
    return session


def _mowing_cooldown_state(context: DecisionContext) -> tuple[bool, int]:
    runtime_context = context.runtime_context if isinstance(context.runtime_context, dict) else {}
    raw_minutes = runtime_context.get("mowing_cooldown_after_watering_minutes", 0)
    try:
        cooldown_minutes = max(0, int(float(raw_minutes)))
    except (TypeError, ValueError):
        cooldown_minutes = 0
    if cooldown_minutes <= 0:
        return False, 0
    # SANS ARROSAGE, PAS DE COOLDOWN. `_latest_watering_timestamp` fabrique un repli
    # « aujourd'hui 06:00 UTC » quand aucun arrosage ne correspond : le cooldown se déclenchait
    # donc tout seul, chaque matin, sur une instance qui n'avait JAMAIS arrosé — et annonçait
    # « Arrosage récent : attends encore 180 min ». Effet mesuré : tonte refusée de 08:00 à 11:00
    # locales, soit exactement la fenêtre idéale, avec un motif mensonger.
    if not _has_recent_watering_history(context):
        return False, 0

    elapsed_minutes = _elapsed_minutes_since_watering(context)
    remaining_minutes = max(0, cooldown_minutes - elapsed_minutes)
    return remaining_minutes > 0, remaining_minutes


def _has_recent_watering_history(context: DecisionContext) -> bool:
    runtime_context = context.runtime_context if isinstance(context.runtime_context, dict) else {}
    last_execution = runtime_context.get("last_irrigation_execution")
    if isinstance(last_execution, dict):
        return True
    return any(
        isinstance(item, dict) and item.get("type") == "arrosage"
        for item in context.history
    )


def _upcoming_watering_coordination(
    context: DecisionContext,
    water_bundle: dict[str, Any],
) -> tuple[str, str | None]:
    """Retourne (niveau, message) si un arrosage est prévu et pas encore fait.

    niveau : "block" (< 30 min), "discourage" (< 2 h), ou "none".
    Message None si aucune action recommandée.
    """
    if not water_bundle.get("arrosage_recommande", False):
        return "none", None
    if _has_recent_watering_history(context):
        return "none", None
    start_minute = water_bundle.get("watering_window_start_minute")
    if start_minute is None:
        return "none", None
    current_minute = (context.hour_of_day or 0) * 60
    minutes_until = int(start_minute) - current_minute
    if minutes_until <= 0:
        # La fenêtre a déjà démarré ou est passée — arrosage peut survenir à tout moment.
        # Le moment affiché suit l'heure réelle : `minutes_until <= 0` couvre TOUTE la fin de
        # journée (dont la fenêtre du soir de canicule), pas seulement la matinée.
        hour = context.hour_of_day if context.hour_of_day is not None else 0
        moment = "ce matin" if hour < 12 else "cet après-midi" if hour < 18 else "ce soir"
        return "discourage", f"Arrosage recommandé {moment} — arrose avant de tondre si possible."
    if minutes_until <= 30:
        return "block", (
            f"Arrosage imminent dans ~{minutes_until} min: "
            "inutile de tondre maintenant, attends la fin de l'arrosage."
        )
    if minutes_until <= 120:
        h, m = divmod(minutes_until, 60)
        time_str = f"{h}h{m:02d}" if h > 0 else f"{m} min"
        return "discourage", f"Arrosage prévu dans ~{time_str} — tonds avant ou patiente après."
    return "none", None


def _watering_related_mowing_block(
    context: DecisionContext,
    phase_bundle: dict[str, Any],
    water_bundle: dict[str, Any],
) -> tuple[bool, str | None, str | None]:
    if not _has_recent_watering_history(context):
        return False, None, None

    elapsed_minutes = _elapsed_minutes_since_watering(context)
    ressuyage_hours = _estimate_mowing_ressuyage_hours(context, phase_bundle, water_bundle)
    ressuyage_minutes = int(ressuyage_hours * 60)
    if elapsed_minutes < ressuyage_minutes:
        remaining_h = max(1, (ressuyage_minutes - elapsed_minutes) // 60)
        return True, "recent_watering", f"Arrosage récent: attendre encore ~{remaining_h}h avant de tondre."

    humidite_sol = water_bundle["advanced_context"].get("humidite_sol")
    if humidite_sol is None:
        humidite_sol = context.humidite_sol
    if humidite_sol is not None:
        try:
            humidite_sol_value = float(humidite_sol)
        except (TypeError, ValueError):
            humidite_sol_value = None
        if humidite_sol_value is not None and humidite_sol_value >= 70:
            return True, "soil_wet", "Sol humide: attendre le ressuyage."

    if float(context.humidite or 0.0) >= _MOWING_WINDOW_BLOCK_HUMIDITY:
        return True, "soil_wet", "Sol humide: attendre le ressuyage."

    return False, None, None


def _resolve_mowing_window(
    context: DecisionContext,
    *,
    weather_profile: dict[str, Any],
) -> tuple[str, str | None]:
    hour = context.hour_of_day
    if hour is None:
        return "blocked", "Heure de tonte inconnue."

    # Température ABSENTE ≠ 0 °C — MÊME défaut que celui déjà corrigé dans `_resolve_mowing_block`
    # (voir le commentaire là-bas) : le correctif n'avait pas été reporté ici. Les trois sources
    # peuvent tomber ensemble au redémarrage de Home Assistant ; le `or 0.0` transformait alors
    # l'absence de mesure en gel fictif, et la tonte était refusée EN PLEIN JUILLET avec le motif
    # mensonger « Température trop basse pour tondre. », sans rien dans les journaux.
    temperature = context.temperature
    # Vent ABSENT ≠ vent nul — même famille que la température ci-dessus, mais dans l'AUTRE sens :
    # l'absence n'y bloquait pas à tort, elle AUTORISAIT à tort. `or 0.0` faisait passer un vent
    # inconnu pour un air parfaitement calme, et la fenêtre remontait de « à éviter » à « idéal ».
    # Aggravant : `_resolve_mowing_block` lisait DÉJÀ le repli météo (`weather_wind_speed`) alors
    # que cette fonction-ci ne le faisait pas — deux lectures du vent divergentes dans le même
    # fichier, celle qui pilote la fenêtre étant la plus aveugle des deux.
    vent_brut = context.vent
    if vent_brut is None:
        vent_brut = weather_profile.get("weather_wind_speed")
    try:
        vent = float(vent_brut) if vent_brut is not None else None
    except (TypeError, ValueError):
        vent = None
    rosee = context.rosee
    month = context.today.month

    # Bornes du soir, recalculées chaque jour depuis le coucher réel.
    soir_debut: float = float(_MOWING_WINDOW_ACCEPTABLE_START)
    soir_fin: float = float(_MOWING_WINDOW_ACCEPTABLE_END)
    sunset_minute = weather_profile.get("sunset_minute") if isinstance(weather_profile, dict) else None
    try:
        sunset = float(sunset_minute) if sunset_minute is not None else None
    except (TypeError, ValueError):
        sunset = None
    if sunset is not None and 0 <= sunset <= 24 * 60:
        fin_min = sunset - _MOWING_EVENING_END_BEFORE_SUNSET_MIN
        deb_min = fin_min - _MOWING_EVENING_WINDOW_MIN
        # La fenêtre du soir ne doit jamais mordre sur celle du matin ni descendre sous elle.
        if deb_min / 60.0 > _MOWING_WINDOW_IDEAL_END:
            soir_debut, soir_fin = deb_min / 60.0, fin_min / 60.0

    if is_active_rain_weather(weather_profile):
        return "blocked", "Pluie en cours ou imminente."
    if rosee is not None and float(rosee) > 0:
        return "blocked", "Rosée présente: attendre le ressuyage du feuillage."
    # On ne bloque plus sur une donnée qu'on n'a pas : sans mesure, la fenêtre reste ouverte et
    # les autres garde-fous (pluie, rosée, horaire) continuent de s'appliquer.
    if temperature is not None and float(temperature) < 8:
        return "blocked", "Température trop basse pour tondre."
    if temperature is not None and float(temperature) > _MOWING_WINDOW_BLOCK_TEMP_MIN:
        return "blocked", "Température trop élevée pour tondre."
    if vent is not None and vent > _MOWING_WINDOW_BLOCK_WIND:
        return "blocked", "Vent trop fort pour tondre."
    if vent is not None and vent >= _MOWING_WINDOW_DISCOURAGED_WIND:
        return "discouraged", "Vent soutenu: à éviter."
    if (
        temperature is not None
        and _MOWING_WINDOW_DISCOURAGED_TEMP_MIN <= float(temperature) <= _MOWING_WINDOW_BLOCK_TEMP_MIN
    ):
        return "discouraged", "Température élevée: à éviter."
    if hour < _MOWING_WINDOW_IDEAL_START:
        return "blocked", "Matin trop tôt: attendre le ressuyage."
    if _MOWING_WINDOW_IDEAL_START <= hour < _MOWING_WINDOW_IDEAL_END:
        return "ideal", "Fenêtre idéale du matin."
    if soir_debut <= hour < soir_fin:
        if month in {7, 8} and temperature is not None and float(temperature) >= 28:
            return "discouraged", "Fin de journée chaude: à éviter."
        return "acceptable", "Fenêtre acceptable de fin de journée."
    if _MOWING_WINDOW_IDEAL_END <= hour < soir_debut:
        if month in {7, 8} and temperature is not None and float(temperature) >= 28:
            return "discouraged", "Plein après-midi en été: à éviter."
        return "discouraged", "Créneau intermédiaire: à éviter."
    if soir_fin <= hour < _MOWING_WINDOW_NIGHT_END:
        return "discouraged", "Fin de journée tardive: à éviter."
    return "blocked", "Nuit: attendre le lever du soleil."


def _soil_is_wet(advanced_context: dict[str, Any], context: DecisionContext) -> bool:
    humidite_sol = advanced_context.get("humidite_sol")
    if humidite_sol is None:
        humidite_sol = context.humidite_sol
    if humidite_sol is None:
        return False
    try:
        return float(humidite_sol) >= 70
    except (TypeError, ValueError):
        return False


def _post_application_mowing_block(context: DecisionContext) -> tuple[bool, str | None, str | None]:
    application_state = compute_application_state(context.history, today=context.today)
    status = str(application_state.get("application_post_watering_status") or "").strip().lower()
    if status not in {"bloque", "en_attente", "autorise"}:
        return False, None, None
    return True, "post_application_active", "Post-produit actif: attends la fin du post-arrosage."


# Sentinelles « pas d'erreur » : valeurs de capteur à NE PAS interpréter comme une panne
# (l'adapter neutralise déjà `no_error` en amont ; garde défensive contre une valeur brute).
_NO_ERROR_CODES = frozenset(
    {
        "", "no_error", "no error", "none", "ok", "aucune", "aucune_erreur", "aucune erreur",
        # « Pas de mesure » n'est PAS une panne (cf. mower_adapter._NO_ERROR_VALUES) : un capteur
        # d'erreur indisponible bloquait la tonte avec « Robot en erreur : défaut signalé ».
        "unavailable", "unknown",
    }
)


def _machine_unavailable_detail(
    mower_context: dict[str, Any],
) -> tuple[str, str] | None:
    mower_operation_state = str(mower_context.get("mower_operation_state") or "").strip().lower()
    mower_reason_code = str(mower_context.get("mower_reason_code") or "").strip().lower()
    mower_is_mowing = bool(mower_context.get("mower_is_mowing")) or mower_operation_state in {"tonte", "mowing"}
    mower_is_returning = bool(mower_context.get("mower_is_returning")) or mower_operation_state in {"transit", "retour", "retour_station"}
    mower_is_ready = mower_context.get("mower_coordination_ready") is not False and mower_context.get("tondeuse_prete") is not False
    mower_is_connected = mower_context.get("tondeuse_connectee") is not False
    mower_is_charging = bool(mower_context.get("tondeuse_en_charge"))

    # Erreur/panne du robot : libellé précis prioritaire sur « hors ligne »/générique.
    mower_status = str(mower_context.get("tondeuse_statut") or "").strip().lower()
    mower_error_code = str(
        mower_context.get("tondeuse_erreur")
        or mower_context.get("mower_error")
        or mower_context.get("tondeuse_erreur_code")
        or ""
    ).strip().lower()
    mower_in_error = (
        mower_operation_state in {"error", "erreur"}
        or mower_status == "erreur"
        or mower_reason_code == "error"
        or (mower_error_code not in _NO_ERROR_CODES)
    )
    if mower_in_error:
        message = (
            str(mower_context.get("mower_reason_label") or "").strip()
            or str(mower_context.get("tondeuse_erreur_libelle") or "").strip()
            or "défaut signalé, vérifier le robot"
        )
        return "error", f"Robot en erreur: {message}"

    if not mower_is_connected:
        return "offline", "Robot hors ligne: attendre qu'elle redevienne joignable."
    if mower_is_charging:
        return "charging", "Robot en charge: attendre qu'elle soit prête."
    if mower_is_mowing or mower_reason_code == "mower_mowing":
        return "mowing", "Robot déjà en tonte: attendre la fin du cycle en cours."
    if mower_is_returning or mower_reason_code == "mower_returning":
        return "returning", "Robot en retour station: attendre qu'elle soit prête."
    if mower_reason_code == "mower_starting":
        return "starting", "Robot en démarrage: attendre qu'elle soit prête."
    if mower_reason_code == "mower_zoning":
        return "zoning", "Robot en changement de zone: attendre qu'elle soit prête."
    if mower_reason_code == "mower_searching_zone":
        return "searching_zone", "Robot en recherche de zone: attendre qu'elle soit prête."
    if mower_reason_code == "mower_escaped_digital_fence":
        return "escaped_digital_fence", "Robot hors périmètre: intervention requise."
    if mower_reason_code == "mower_rain_delayed":
        return "rain_delayed", "Robot en pause pluie: attendre qu'elle soit prête."
    # Le code émis par la coordination est `unreliable` ; `mower_unreliable` est le code côté
    # ARROSAGE (decision_watering), pas côté tonte. La comparaison portait donc sur une valeur
    # qui n'arrivait jamais : ce message spécifique était inatteignable et tout retombait sur le
    # générique « Robot indisponible » de la ligne suivante.
    if mower_reason_code == "unreliable":
        return "unreliable", "Robot instable: vérifie sa disponibilité avant de reprendre."
    if not mower_is_ready:
        return "not_ready", "Robot indisponible: attendre qu'elle soit prête."
    return None


_PLUIE_STATE_KEY = "derniere_pluie_active"


def _minutes_depuis_derniere_pluie(context: DecisionContext) -> float | None:
    """Minutes écoulées depuis la dernière pluie CONSTATÉE, ou None si inconnue.

    ⚠️ `is_active_rain_weather` ne regarde que la météo de l'INSTANT : il n'existait donc
    aucun délai de ressuyage après une averse, alors qu'un arrosage en impose 180. Le libellé
    promettait pourtant « pluie en cours ou récente ». On horodate désormais chaque constat de
    pluie dans la mémoire persistée, ce qui permet enfin de mesurer « récente ».
    """
    memoire = context.memory if isinstance(context.memory, dict) else {}
    stamp = memoire.get(_PLUIE_STATE_KEY)
    if not isinstance(stamp, dict):
        return None
    try:
        jour = date.fromisoformat(str(stamp.get("date")))
        heure = float(stamp.get("heure") or 0.0)
    except (TypeError, ValueError):
        return None
    if context.hour_of_day is None:
        return None
    ecart_jours = (context.today - jour).days
    if ecart_jours < 0 or ecart_jours > 1:
        return None
    return (ecart_jours * 24.0 + float(context.hour_of_day) - heure) * 60.0


def _etat_pluie(context: DecisionContext, il_pleut: bool) -> dict[str, Any] | None:
    """Horodatage à persister : mis à jour tant qu'il pleut, conservé ensuite."""
    if il_pleut and context.hour_of_day is not None:
        return {"date": context.today.isoformat(), "heure": round(float(context.hour_of_day), 3)}
    memoire = context.memory if isinstance(context.memory, dict) else {}
    precedent = memoire.get(_PLUIE_STATE_KEY)
    return dict(precedent) if isinstance(precedent, dict) else None


def _resolve_mowing_block(
    context: DecisionContext,
    phase_bundle: dict[str, Any],
    water_bundle: dict[str, Any],
) -> tuple[bool, str | None, str | None, str | None, str | None]:
    """Résout le blocage réel prioritaire, indépendant de la fenêtre métier."""
    post_application_active, post_application_code, post_application_label = _post_application_mowing_block(context)
    if post_application_active:
        return True, post_application_code, post_application_label, None, None

    mower_context = context.mower_context if isinstance(context.mower_context, dict) else {}
    if mower_context:
        machine_detail = _machine_unavailable_detail(mower_context)
        if machine_detail is not None:
            detail_code, detail_label = machine_detail
            return True, "machine_unavailable", "Robot indisponible: attendre qu'elle soit prête.", detail_code, detail_label

    # Température ABSENTE ≠ 0 °C. Les trois sources (capteur, entité météo, prévision) peuvent
    # toutes tomber en même temps (redémarrage de Home Assistant, station hors ligne) ; le
    # `or 0.0` transformait alors l'absence de mesure en un gel fictif → « Température extrême »
    # et tonte bloquée sans raison. On ne bloque plus sur une donnée qu'on n'a pas.
    if context.temperature is not None:
        temperature = float(context.temperature)
        # Le CODE reste `temp_extreme` (contrat public consommé par la carte et les automatisations),
        # mais le LIBELLÉ distingue enfin le trop-froid du trop-chaud : les deux renvoyaient
        # « Température extrême » et rien ne permettait de savoir lequel, ni à quel seuil.
        # ⚠️ `.1f` et NON `.0f` : à 30,2 °C, l'arrondi affichait « 30 °C, seuil 30 °C » — un
        # blocage juste (30,2 > 30) qui se lit comme une erreur de comparaison. Vu en direct le
        # 30/07/2026. Un message qui contredit la logique fait chasser un bug qui n'existe pas.
        # ⚠️ VIRGULE décimale, pas un point : c'est la graphie française, ET un point décimal
        # crée une fausse fin de phrase pour tout consommateur qui coupe le motif à la première
        # phrase (la carte le faisait — « pour tondre (32 »). Corrigé des deux côtés.
        if temperature > _MOWING_WINDOW_BLOCK_TEMP_MIN:
            return (
                True,
                "temp_extreme",
                f"Trop chaud pour tondre ({temperature:.1f}".replace(".", ",")
                + f" °C, seuil {_MOWING_WINDOW_BLOCK_TEMP_MIN:.0f} °C) :"
                " attendre une fenêtre plus fraîche.",
                None,
                None,
            )
        if temperature < 8:
            return (
                True,
                "temp_extreme",
                f"Trop froid pour tondre ({temperature:.1f}".replace(".", ",")
                + " °C, seuil 8 °C) : la pousse est à l'arrêt.",
                None,
                None,
            )

    advanced_context = water_bundle.get("advanced_context")
    if not isinstance(advanced_context, dict):
        advanced_context = {}
    rosee = advanced_context.get("rosee")
    if rosee is not None:
        try:
            if float(rosee) > 0:
                return True, "wet_grass", "Herbe mouillée: attendre le ressuyage.", None, None
        except (TypeError, ValueError):
            pass

    _rt = context.runtime_context if isinstance(context.runtime_context, dict) else {}
    try:
        _ressuyage = max(0.0, float(_rt.get("mowing_cooldown_after_watering_minutes", 0) or 0))
    except (TypeError, ValueError):
        _ressuyage = 0.0
    _depuis_pluie = _minutes_depuis_derniere_pluie(context)
    if _depuis_pluie is not None and 0 <= _depuis_pluie < _ressuyage and not is_active_rain_weather(
        context.weather_profile
    ):
        # RESSUYAGE APRÈS PLUIE — même délai que après un arrosage (symétrie voulue par Kévin :
        # « c'est l'intégration qui gère le temps de pause de la tondeuse pendant la pluie »).
        # Il n'existait aucun délai côté pluie, alors que le libellé promettait « ou récente ».
        return (
            True,
            "wet_grass",
            f"Herbe mouillée: ressuyage après la pluie ({int(_ressuyage - _depuis_pluie)} min restantes).",
            None,
            None,
        )
    if is_active_rain_weather(context.weather_profile):
        # ⚠️ Le libellé disait « pluie en cours ou RÉCENTE ». C'était faux : `is_active_rain_weather`
        # ne regarde que la météo de l'INSTANT (condition pluvieuse, ou probabilité ≥ 80 %). Aucune
        # persistance, donc aucun délai de ressuyage — contrairement aux 180 min imposées après un
        # arrosage. Le ressuyage après pluie est en pratique couvert par les gardes voisins (rosée,
        # sol humide), mais promettre « récente » envoie chercher un délai qui n'existe pas.
        # Un vrai délai demanderait l'HEURE DE FIN de l'averse, que le contexte ne transporte pas.
        return True, "wet_grass", "Herbe mouillée: il pleut.", None, None
    if _soil_is_wet(advanced_context, context):
        return True, "soil_wet", "Sol humide: attendre le ressuyage.", None, None

    watering_block_active, watering_block_reason_code, watering_block_reason_label = _watering_related_mowing_block(
        context,
        phase_bundle,
        water_bundle,
    )
    if watering_block_active:
        return True, watering_block_reason_code, watering_block_reason_label, None, None

    return False, None, None, None, None



def _as_wall_clock(moment: datetime) -> datetime:
    """Ramène un instant à l'HEURE MURALE de l'utilisateur.

    La projection de tonte raisonne en heures de la vie courante — « pas de tonte après 18 h,
    on reporte à 6 h le lendemain matin ». Ces bornes étaient testées et écrites sur un instant
    UTC : en Europe/Paris l'été, le seuil de 18 h se déclenchait en réalité à 20 h locales et le
    « 6 h » écrit valait 8 h locales. La date renvoyée pouvait donc désigner le mauvais jour pour
    toute projection tombant entre 18 h et 20 h.
    Sans Home Assistant (tests hors runtime), on laisse l'instant tel quel : le comportement
    historique est conservé et aucun test existant ne change.
    """
    if dt_util is None or moment.tzinfo is None:
        return moment
    as_local = getattr(dt_util, "as_local", None)
    return as_local(moment) if callable(as_local) else moment

def _default_projection_anchor(context: DecisionContext) -> datetime:
    """Ancre technique minimale utilisée quand aucune source métier plus précise n'existe."""
    return datetime.combine(context.today, time(6, 0), tzinfo=timezone.utc)


def _estimate_mowing_ressuyage_hours(
    context: DecisionContext,
    phase_bundle: dict[str, Any],
    water_bundle: dict[str, Any],
) -> float:
    """Estime le délai de ressuyage nécessaire avant une tonte sûre."""
    soil_profile = str(water_bundle.get("soil_profile") or context.type_sol or "").strip().lower()
    if soil_profile == "sableux":
        hours = 1.0
    elif soil_profile == "argileux":
        hours = 4.0
    else:
        hours = 2.0

    humidite = float(context.humidite or 0.0)
    temperature = float(context.temperature or 0.0)
    pluie_24h = float(context.pluie_24h or 0.0)
    pluie_demain = float(context.pluie_demain or 0.0)
    rosee = water_bundle["advanced_context"].get("rosee")
    arrosage_recent_jour = float(water_bundle["water_balance"].get("arrosage_recent_jour") or 0.0)

    if humidite >= 85 or (rosee is not None and float(rosee) > 0):
        hours += 2.0
    elif humidite >= 70:
        hours += 1.0

    if pluie_24h >= 5.0 or arrosage_recent_jour > 2.0:
        hours += 2.0
    elif pluie_24h >= 2.0 or arrosage_recent_jour > 0.5:
        hours += 1.0

    if pluie_demain >= 2.0:
        hours += 0.5

    if temperature >= 28 and humidite <= 55:
        hours -= 0.5

    if phase_bundle["phase_dominante"] == "Sursemis":
        hours += 1.0

    return max(0.5, min(hours, 10.0))


def _mowing_projection_forecast_offset_days(
    context: DecisionContext,
    phase_bundle: dict[str, Any],
) -> tuple[int, list[str]]:
    """Décale la projection si la fenêtre sèche des prochains jours reste mauvaise."""
    offsets: list[int] = [0]
    reasons: list[str] = []

    pluie_demain = float(context.pluie_demain or 0.0)
    pluie_j2 = float(context.pluie_j2 or 0.0)
    pluie_3j = float(context.pluie_3j or 0.0)
    pluie_probabilite_max_3j = float(context.pluie_probabilite_max_3j or 0.0)
    humidite = float(context.humidite or 0.0)
    rosee = context.rosee
    weather_profile = context.weather_profile if isinstance(context.weather_profile, dict) else {}
    precip_probability = float(
        weather_profile.get("weather_precipitation_probability")
        or pluie_probabilite_max_3j
        or 0.0
    )
    cloud_coverage = float(weather_profile.get("weather_cloud_coverage") or 0.0)
    wind = float(context.vent or weather_profile.get("weather_wind_speed") or 0.0)
    temperature = float(context.temperature or 0.0)
    phase_dominante = str(phase_bundle.get("phase_dominante") or "")
    sous_phase = str(phase_bundle.get("sous_phase") or "")

    if pluie_demain >= 2.0 or precip_probability >= 85.0:
        offsets.append(1)
        reasons.append("meteo_j1_humide")
    elif pluie_demain >= 1.0 or precip_probability >= 70.0:
        offsets.append(1)
        reasons.append("meteo_j1_incertaine")

    if pluie_j2 >= 2.0:
        offsets.append(2)
        reasons.append("meteo_j2_humide")
    elif pluie_j2 >= 1.0 and precip_probability >= 75.0:
        offsets.append(2)
        reasons.append("meteo_j2_incertaine")

    if pluie_3j >= 6.0:
        offsets.append(3)
        reasons.append("meteo_3j_tres_humide")
    elif pluie_3j >= 3.0 and precip_probability >= 80.0:
        offsets.append(3)
        reasons.append("meteo_3j_humide")

    if humidite >= 88.0 or (rosee is not None and float(rosee) > 0):
        offsets.append(1)
        reasons.append("ressuyage_lent")

    if cloud_coverage >= 90.0 and wind <= 8.0 and temperature <= 16.0:
        offsets.append(1)
        reasons.append("sechage_faible")

    if phase_dominante == "Sursemis" and sous_phase in {"Germination", "Enracinement"}:
        offsets.append(1)
        reasons.append(f"sous_phase={sous_phase.lower()}")
    elif phase_dominante in {"Traitement", "Hivernage"}:
        offsets.append(1)
        reasons.append(f"phase={phase_dominante.lower()}")

    return max(offsets), reasons


def _mowing_projection_application_offset_hours(context: DecisionContext) -> tuple[float, list[str]]:
    """Ajoute une prudence si une application récente peut encore gêner la tonte."""
    application_state = compute_application_state(context.history, today=context.today)
    raw_date = application_state.get("date_action") or application_state.get("date")
    if not raw_date:
        return 0.0, []

    try:
        application_date = date.fromisoformat(str(raw_date))
    except ValueError:
        return 0.0, []

    age_days = max((context.today - application_date).days, 0)
    if age_days > 3:
        return 0.0, []

    application_type = str(application_state.get("application_type") or "").strip().lower()
    requires_watering = bool(application_state.get("application_requires_watering_after"))
    post_status = str(application_state.get("application_post_watering_status") or "").strip().lower()

    hours = 0.0
    reasons: list[str] = []

    if requires_watering or post_status in {"termine", "en_attente", "bloque"}:
        hours = max(hours, 18.0)
        reasons.append("post_application_recent")

    if application_type in {"sol", "foliaire"} and age_days <= 1:
        hours = max(hours, 12.0)
        reasons.append(f"application_{application_type}")

    if age_days == 0:
        hours += 6.0
        reasons.append("application_j0")

    return hours, reasons


def _last_mowing_date(context: DecisionContext) -> date | None:
    """Retourne la date de la dernière tonte déclarée dans l'historique."""
    history = context.history if isinstance(context.history, list) else []
    latest: date | None = None
    for item in history:
        if not isinstance(item, dict) or item.get("type") != "tonte":
            continue
        raw_date = item.get("date")
        if not raw_date:
            continue
        try:
            mowing_date = date.fromisoformat(str(raw_date))
        except ValueError:
            continue
        if latest is None or mowing_date > latest:
            latest = mowing_date
    return latest


def _mowing_overdue_state(
    context: DecisionContext,
    phase_bundle: dict[str, Any],
) -> tuple[bool, float, int]:
    """Retourne (is_overdue, overdue_factor, days_since_last_mowing).

    is_overdue est vrai si le délai depuis la dernière tonte dépasse 1,5× l'intervalle
    cible calculé depuis la fréquence saisonnière/phase.
    Retourne (False, 0.0, 0) si la fréquence cible est nulle ou pas de tonte connue.
    """
    frequency, _ = _phase_adjusted_mowing_frequency(phase_bundle, context.today.month)
    if frequency <= 0:
        return False, 0.0, 0
    last_mowing = _last_mowing_date(context)
    if last_mowing is None:
        return False, 0.0, 0
    interval_days = 7.0 / frequency
    days_since = max((context.today - last_mowing).days, 0)
    overdue_factor = days_since / interval_days
    return overdue_factor >= 1.5, round(overdue_factor, 2), days_since


_GROWTH_RATE_BY_MONTH: dict[int, float] = {
    1: 0.0, 2: 0.0,
    3: 0.3, 4: 0.4,
    5: 0.5, 6: 0.5,
    7: 0.4, 8: 0.35,
    9: 0.35, 10: 0.25,
    11: 0.05, 12: 0.0,
}


# CROISSANCE — répartition de la pousse sur les 24 heures.
#
# ⚠️ CORRIGÉ le 30/07/2026, sur une question de Kévin (« le gazon pousse la nuit ? »). Le modèle
# bornait la pousse à 7 h - 20 h en affirmant que « le gazon ne s'allonge pas la nuit ». C'était
# FAUX, par confusion entre deux mécanismes distincts :
#   - la PHOTOSYNTHÈSE suit la lumière : elle fabrique les sucres, le jour ;
#   - l'ÉLONGATION cellulaire est poussée par la TURGESCENCE, la pression de l'eau dans les
#     cellules — et celle-ci est MAXIMALE LA NUIT. Le jour, la transpiration vide les cellules
#     plus vite que les racines ne les remplissent (surtout aux heures chaudes) et la feuille
#     s'allonge peu ; la nuit, la transpiration cesse, le potentiel hydrique se rétablit, et
#     c'est là que la feuille pousse le plus.
# Sur graminées, le taux d'élongation foliaire culmine donc en fin de nuit et s'effondre au
# zénith — l'inverse exact de ce que faisait le modèle. Conséquence visible : la hauteur restait
# PLATE de 20 h à 7 h, onze heures d'immobilité affichée au moment où le gazon pousse le plus.
#
# La pousse est désormais étalée sur 24 h par une pondération sinusoïdale culminant vers 3 h.
# Le TOTAL du jour est inchangé (l'intégrale de la pondération sur 24 h vaut exactement 1) :
# seule la répartition horaire change.
_GROWTH_PEAK_HOUR = 3.0        # l'élongation foliaire culmine en fin de nuit
_GROWTH_AMPLITUDE = 0.6        # 0 = pousse uniforme · 1 = pousse nulle au creux de midi


def _growth_day_fraction(hour_of_day: int | float | None) -> float:
    """Part de la pousse du jour déjà acquise à cette heure (0 → 1)."""
    if hour_of_day is None:
        return 1.0
    try:
        h = float(hour_of_day)
    except (TypeError, ValueError):
        return 1.0
    h = max(0.0, min(24.0, h))
    # Intégrale de la pondération 1 + A·cos(2π(t − pic)/24) entre 0 et h, divisée par 24.
    # Strictement croissante tant que A < 1, nulle en 0 et égale à 1 en 24 : la hauteur ne
    # recule jamais dans la journée et le total journalier est exactement le taux du jour.
    k = 24.0 / (2.0 * math.pi)
    phase = 2.0 * math.pi * (h - _GROWTH_PEAK_HOUR) / 24.0
    phase0 = 2.0 * math.pi * (0.0 - _GROWTH_PEAK_HOUR) / 24.0
    return (h + _GROWTH_AMPLITUDE * k * (math.sin(phase) - math.sin(phase0))) / 24.0


def _frein_memorise_du_jour(context: DecisionContext) -> float | None:
    """Dernier frein observé AUJOURD'HUI, ou None.

    Sert de plafond quand le bilan hydrique manque (premier cycle après un redémarrage).
    Strictement borné au jour courant : celui d'hier décrirait une autre météo, et le
    reprendre pourrait bloquer la pousse d'une journée fraîche derrière une canicule passée.
    """
    memoire = context.memory if isinstance(context.memory, dict) else {}
    etat = memoire.get(_GROWTH_STATE_KEY)
    if not isinstance(etat, dict):
        return None
    if str(etat.get("date") or "") != context.today.isoformat():
        return None
    return _to_float_safe(etat.get("frein"))


def _growth_modulation(
    context: DecisionContext,
    water_bundle: dict[str, Any] | None,
    *,
    frein_plafond: float | None = None,
) -> float:
    """Facteur 0 → 1 appliqué à la vitesse de croissance selon les conditions du jour.

    Demandé par Kévin le 30/07/2026 : « à certain moment la hauteur peut ne pas bouger et
    c'est normal ». C'est agronomiquement exact — une graminée de saison fraîche cesse de
    s'allonger quand il fait trop chaud ou que le sol est sec. Le modèle ne tenait compte que
    de la phase et du mois : il faisait donc pousser le gazon de 0,3 cm par jour en pleine
    canicule sur un sol vide, ce qui ne se voit jamais sur le terrain.

    Deux freins, multiplicatifs :
    - la TEMPÉRATURE (optimum 15-24 °C pour une saison fraîche, arrêt sous 5 et au-delà de 35) ;
    - l'EAU : sous le seuil de déclenchement d'arrosage, la plante ferme ses stomates et
      privilégie la survie à l'élongation.
    """
    facteur = 1.0

    temperature = context.temperature
    if temperature is not None:
        try:
            t = float(temperature)
        except (TypeError, ValueError):
            t = None
        if t is not None:
            if t < 5.0 or t > 35.0:
                facteur *= 0.0          # gel ou chaleur extrême : arrêt franc
            elif t < 10.0:
                facteur *= 0.35
            elif t < 15.0:
                facteur *= 0.75
            elif t <= 24.0:
                facteur *= 1.0          # optimum
            elif t <= 30.0:
                facteur *= 0.65
            else:
                facteur *= 0.25         # 30-35 °C : la pousse s'arrête presque

    eau_connue = False
    if isinstance(water_bundle, dict):
        reserve = _to_float_safe(water_bundle.get("reserve_hydrique_sol_mm"))
        seuil = _to_float_safe(water_bundle.get("reserve_minimale_mm"))
        if reserve is not None and seuil is not None and seuil > 0:
            eau_connue = True
            if reserve <= 0:
                facteur *= 0.0
            elif reserve < seuil:
                # Entre 0 et le seuil, la pousse décroît linéairement jusqu'à un plancher.
                facteur *= max(0.15, reserve / seuil)

    # ⚠️ EAU INCONNUE ≠ EAU À VOLONTÉ. Sans bilan hydrique, le frein d'eau était simplement
    # sauté : le facteur restait à 1,0 et la pousse repartait comme si le sol était plein.
    # C'est le même piège que le repli « soleil inconnu → fraction 1.0 » de la 0.21.4. On ne
    # peut pas deviner la réserve, mais on peut refuser d'être PLUS optimiste que le dernier
    # état connu du jour.
    if not eau_connue and frein_plafond is not None:
        facteur = min(facteur, float(frein_plafond))

    return max(0.0, min(1.0, facteur))


def _to_float_safe(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _growth_rate_cm_per_day(phase_bundle: dict[str, Any], month: int) -> float:
    """Vitesse de croissance journalière estimée selon la phase et le mois."""
    phase_dominante = str(phase_bundle.get("phase_dominante") or "")
    sous_phase = str(phase_bundle.get("sous_phase") or "")
    if phase_dominante == "Sursemis":
        if sous_phase in {"Germination", "Enracinement"}:
            return 0.0
        if sous_phase == "Reprise":
            return 0.2
    return _GROWTH_RATE_BY_MONTH.get(month, 0.3)


def _estimated_grass_height_cm(
    context: DecisionContext,
    phase_bundle: dict[str, Any],
    water_bundle: dict[str, Any] | None = None,
) -> float | None:
    """Hauteur seule. Le détail (pousse du jour, état à persister) passe par
    `_grass_growth_details` — deux autres appelants n'ont besoin que du nombre."""
    details = _grass_growth_details(context, phase_bundle, water_bundle)
    return details["hauteur_cm"] if details else None


def _grass_growth_details(
    context: DecisionContext,
    phase_bundle: dict[str, Any],
    water_bundle: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Estime la hauteur actuelle du gazon depuis la date de dernière tonte.

    Retourne None si la hauteur de coupe ou la date de dernière tonte est inconnue.
    Ne remplace pas un capteur physique — utilisé comme fallback uniquement.

    Deux corrections du 30/07/2026, demandées par Kévin :
    - la hauteur MONTE AU FIL DE LA JOURNÉE au lieu de sauter d'un cran à minuit. La pousse
      est répartie sur la fenêtre 7 h - 20 h : le gazon ne s'allonge pas la nuit ;
    - elle tient compte des CONDITIONS. Le modèle n'utilisait que la phase et le mois, donc
      il faisait pousser le gazon de 0,3 cm par jour en pleine canicule sur un sol vide.
      Désormais la température et la réserve du sol freinent la pousse — et peuvent
      l'arrêter, ce qui est le comportement réel.
    """
    history = context.history if isinstance(context.history, list) else []
    last_mowing_item: dict | None = None
    last_mowing: date | None = None
    for item in history:
        if not isinstance(item, dict) or item.get("type") != "tonte":
            continue
        raw_date = item.get("date")
        if not raw_date:
            continue
        try:
            mowing_date = date.fromisoformat(str(raw_date))
        except ValueError:
            continue
        if last_mowing is None or mowing_date > last_mowing:
            last_mowing = mowing_date
            last_mowing_item = item
    if last_mowing is None or last_mowing_item is None:
        return None

    # Préférer la hauteur stockée au moment de la tonte; fallback sur la tondeuse courante.
    stored_height_mm = last_mowing_item.get("hauteur_coupe_mm")
    if stored_height_mm is not None:
        try:
            cutting_height_cm = float(stored_height_mm) / 10.0
        except (TypeError, ValueError):
            cutting_height_cm = None
    else:
        mower_context = context.mower_context if isinstance(context.mower_context, dict) else {}
        fallback_mm = mower_context.get("tondeuse_hauteur_coupe_mm")
        try:
            cutting_height_cm = float(fallback_mm) / 10.0 if fallback_mm is not None else None
        except (TypeError, ValueError):
            cutting_height_cm = None

    if cutting_height_cm is None or cutting_height_cm <= 0:
        return None
    jours_pleins = max((context.today - last_mowing).days, 0)
    taux = _growth_rate_cm_per_day(phase_bundle, context.today.month)
    # Au REDÉMARRAGE, le premier cycle tourne sans bilan hydrique : le frein d'eau était
    # silencieusement sauté, donc un frein plus OPTIMISTE et une hauteur trop haute publiée
    # pendant ~1 s (constaté le 01/08/2026 : 6,0 puis 5,9 à 0,9 s d'intervalle, et le même
    # doublet la veille). On borne par le dernier frein connu DU JOUR — jamais celui d'hier,
    # qui décrirait une autre météo.
    frein = _growth_modulation(
        context, water_bundle, frein_plafond=_frein_memorise_du_jour(context)
    )
    # Les jours passés utilisent le taux nominal (on n'a pas leurs conditions), la journée en
    # cours utilise les conditions RÉELLES et sa fraction écoulée : c'est elle qui fait monter
    # la valeur au fil des heures.
    # Les jours RÉVOLUS comptent au taux nominal (leurs conditions ne sont plus connues) ; la
    # journée EN COURS est la seule modulée, au prorata de sa fenêtre de pousse écoulée.
    # En fin de journée (20 h, conditions idéales) on retrouve exactement l'ancienne valeur :
    # le changement fait MONTER la courbe pendant la journée, il ne la déplace pas.
    # Le JOUR MÊME de la tonte : aucune pousse comptée. On ignore l'heure de la coupe, et
    # afficher « déjà 2 mm repoussés » quelques heures après être passé serait faux.
    if jours_pleins <= 0:
        # Le JOUR MÊME de la tonte : aucune pousse comptée, et le compteur repart de zéro.
        return {
            "hauteur_cm": round(cutting_height_cm, 1),
            "pousse_acquise_cm": 0.0,
            "pousse_jour_cm": 0.0,
            "etat": _etat_pousse_neuf(context, last_mowing, frein),
        }

    acquise, etat = _pousse_acquise_avant_aujourdhui(
        context, last_mowing=last_mowing, taux=taux, frein=frein, jours_pleins=jours_pleins
    )
    fraction = _growth_day_fraction(context.hour_of_day)
    # ⚠️ LA POUSSE DÉJÀ ACQUISE NE SE RECALCULE PAS. `taux × frein × fraction` appliquait le
    # frein du MOMENT à toute la journée : quand la chaleur montait, la pousse du matin était
    # effacée et la hauteur REDESCENDAIT. Mesuré sur l'installation le 01/08/2026 —
    # 09 h 10 : frein 0,87 × fraction 0,55 = 0,165 cm ; 11 h 40 : frein 0,50 × fraction 0,63 =
    # 0,109 cm. Un tiers de la matinée effacé, la hauteur passe de 6,0 à 5,9 cm. Le frein
    # thermique étant un escalier, il suffisait de franchir 24,0 °C pour perdre 35 % d'un coup.
    # On ACCUMULE donc : le frein ne pilote plus que l'incrément à venir. À conditions stables
    # le total de fin de journée est identique — c'est le chemin qui cesse de reculer.
    # Même famille que la falaise de minuit (0.31.1) : le passé qu'on recalcule.
    jour_precedent = etat.get("jour_cm")
    if jour_precedent is None:
        # Premier cycle de la journée (ou amorçage) : rien à prolonger, on estime la fenêtre
        # déjà écoulée avec les conditions du moment, faute de mieux.
        pousse_jour = taux * frein * fraction
    else:
        fraction_precedente = etat.get("fraction")
        reference = (
            float(fraction_precedente) if fraction_precedente is not None else fraction
        )
        pousse_jour = float(jour_precedent) + taux * frein * max(0.0, fraction - reference)
    pousse = acquise + pousse_jour
    # Mémorisé ICI, une fois la pousse du jour connue : c'est cette valeur que le report du
    # lendemain créditera, telle quelle.
    etat["jour_cm"] = round(pousse_jour, 4)
    etat["fraction"] = round(fraction, 6)
    return {
        "hauteur_cm": round(cutting_height_cm + max(0.0, pousse), 1),
        "pousse_acquise_cm": round(acquise, 2),
        "pousse_jour_cm": round(pousse_jour, 2),
        "etat": etat,
    }


_GROWTH_STATE_KEY = "pousse_gazon"


def _etat_pousse_neuf(context: DecisionContext, tonte: date, frein: float) -> dict[str, Any]:
    return {
        "date": context.today.isoformat(),
        "tonte": tonte.isoformat(),
        "acquis_cm": 0.0,
        "jour_cm": 0.0,
        "frein": round(float(frein), 3),
    }


def _pousse_acquise_avant_aujourdhui(
    context: DecisionContext,
    *,
    last_mowing: date,
    taux: float,
    frein: float,
    jours_pleins: int,
) -> tuple[float, dict[str, Any]]:
    """Pousse réellement acquise AVANT aujourd'hui, et l'état à persister.

    ⚠️ SANS cette mémoire, les journées révolues étaient recomptées au taux NOMINAL alors
    que la journée en cours était freinée par les conditions. À minuit, tout ce que la
    chaleur avait retiré était donc rendu d'un coup — mesuré le 30/07/2026 : +0,30 cm par
    30-35 °C, +0,40 cm au-delà de 35 °C. Le frein, qui est toute la raison d'être du modèle,
    était annulé chaque nuit. Repéré par Kévin : « la hauteur ne bouge pas ».

    La journée qui vient de s'achever est créditée avec SON propre frein, le dernier observé.
    Une journée entièrement manquée (intégration arrêtée > 24 h) retombe sur le taux nominal :
    on ne sait rien de ses conditions, et surestimer un peu vaut mieux que perdre la journée.
    """
    memoire = context.memory if isinstance(context.memory, dict) else {}
    precedent = memoire.get(_GROWTH_STATE_KEY)
    tonte_iso = last_mowing.isoformat()

    if not isinstance(precedent, dict) or str(precedent.get("tonte") or "") != tonte_iso:
        # AMORÇAGE — aucune mémoire pour cette tonte : premier calcul, montée de version, ou
        # nouvelle tonte. On repart de l'estimation nominale des journées révolues, exactement
        # comme avant la mémoire. Repartir de zéro ferait CHUTER la hauteur affichée d'un coup
        # (mesuré : 6,2 → 4,7 cm), ce qui serait pire que le défaut corrigé.
        amorce = taux * max(0, jours_pleins - 1)
        return amorce, {
            "date": context.today.isoformat(),
            "tonte": tonte_iso,
            "acquis_cm": round(amorce, 4),
            "frein": round(float(frein), 3),
        }

    acquis = float(precedent.get("acquis_cm") or 0.0)
    date_etat = str(precedent.get("date") or "")
    if date_etat == context.today.isoformat():
        return acquis, {**precedent, "frein": round(float(frein), 3)}

    try:
        jours_ecoules = (context.today - date.fromisoformat(date_etat)).days
    except ValueError:
        jours_ecoules = 1
    if jours_ecoules > 0:
        # ⚠️ On crédite la pousse RÉELLEMENT constatée la veille (`jour_cm`), pas une
        # reconstitution `taux × frein`. Reconstituer créditait une journée pleine au JOUR DE LA
        # TONTE, où la pousse est nulle par conception : la hauteur bondissait de 5,5 à 5,8 cm
        # à minuit — le saut qu'on venait justement de supprimer, revenu par une autre porte.
        # Repli sur l'ancienne reconstitution si l'état vient d'une version antérieure.
        veille = precedent.get("jour_cm")
        if veille is None:
            acquis += taux * float(precedent.get("frein") or 1.0)
        else:
            acquis += float(veille or 0.0)
        acquis += taux * max(0, jours_ecoules - 1)              # journées entièrement manquées
    return acquis, {
        "date": context.today.isoformat(),
        "tonte": tonte_iso,
        "acquis_cm": round(acquis, 4),
        "frein": round(float(frein), 3),
    }


def _mowing_spacing_min_days(
    phase_bundle: dict[str, Any],
) -> int:
    """Espacement minimal entre deux tontes selon la phase métier."""
    phase_dominante = str(phase_bundle.get("phase_dominante") or "")
    sous_phase = str(phase_bundle.get("sous_phase") or "")
    if phase_dominante == "Sursemis":
        if sous_phase == "Reprise":
            return 6
        if sous_phase == "Stabilisation":
            return 3
    return 2


def _project_next_mowing_date(
    context: DecisionContext,
    phase_bundle: dict[str, Any],
    water_bundle: dict[str, Any],
    tonte_ok: bool,
    reason_code: str | None,
) -> tuple[str | None, str | None, str | None]:
    """Projette la prochaine date de tonte autorisable."""
    if tonte_ok:
        today_iso = context.today.isoformat()
        return today_iso, context.today.strftime("%d/%m/%Y"), None

    anchor: datetime | None = None

    if reason_code in {"phase_sursemis", "phase_traitement", "phase_hivernage"}:
        phase_dominante = str(phase_bundle.get("phase_dominante") or "")
        sous_phase = str(phase_bundle.get("sous_phase") or "")
        phase_start = phase_bundle.get("date_action")
        if phase_dominante == "Sursemis" and sous_phase in {"Germination", "Enracinement"} and phase_start:
            try:
                reprise_start_date = date.fromisoformat(str(phase_start)) + timedelta(days=25)
                return (
                    reprise_start_date.isoformat(),
                    reprise_start_date.strftime("%d/%m/%Y"),
                    f"sous_phase={sous_phase.lower()}",
                )
            except ValueError:
                anchor = None
        else:
            phase_end = phase_bundle.get("date_fin")
            if phase_end:
                try:
                    phase_end_dt = datetime.combine(
                        date.fromisoformat(str(phase_end)),
                        time(6, 0),
                        tzinfo=timezone.utc,
                    )
                    anchor = phase_end_dt
                except ValueError:
                    anchor = None
    elif reason_code == "mowing_night":
        projected_date = context.today
        if context.hour_of_day is not None and context.hour_of_day >= 22:
            projected_date = context.today + timedelta(days=1)
        return projected_date.isoformat(), projected_date.strftime("%d/%m/%Y"), "nuit"
    elif reason_code == "mowing_spacing":
        last_mowing = _last_mowing_date(context)
        spacing_days = _mowing_spacing_min_days(phase_bundle)
        if last_mowing is not None:
            projected_date = max(context.today, last_mowing + timedelta(days=spacing_days))
            return (
                projected_date.isoformat(),
                projected_date.strftime("%d/%m/%Y"),
                f"espacement={spacing_days}j",
            )
        anchor = _default_projection_anchor(context)
    elif reason_code in {
        "watering_in_progress",
        "watering_cooldown",
        "post_application_active",
        "pluie_en_cours",
        "pluie_annoncee",
        "pluie_proche",
        "pluie_recente",
        "sol_humide_post_arrosage",
        "humidite_elevee",
    }:
        anchor = _latest_watering_timestamp(context)
    elif reason_code in {"rosee_persistante", "wet_grass"}:
        # Ressuyage : ancrage par défaut, identique au repli final. Les deux codes restent
        # nommés pour dire qu'ils ont été CONSIDÉRÉS — deux `elif` séparés laissaient croire à
        # un traitement spécifique, d'autant que le voisin `stress_thermique` en a un (+24 h).
        anchor = _default_projection_anchor(context)
    elif reason_code in {"stress_thermique", "temp_extreme"}:
        # `temp_extreme` n'avait AUCUNE branche : il tombait dans le repli, ancré sur maintenant,
        # et la projection annonçait donc « aujourd'hui » pendant que la tonte était bloquée
        # aujourd'hui pour cause de chaleur. Constaté sur l'install le 30/07/2026 : « Trop chaud
        # pour tondre (30 °C, seuil 30 °C) » et « Prochaine tonte estimée le 30/07/2026 » dans la
        # MÊME phrase. Il rejoint son voisin `stress_thermique` : la fenêtre suivante est le
        # lendemain, quand la température sera redescendue. Vaut aussi pour le trop-froid, que ce
        # code couvre également — dans les deux cas, c'est le jour suivant qu'on retente.
        anchor = _default_projection_anchor(context) + timedelta(hours=24)
    elif reason_code in {"hauteur_trop_faible", "regle_tiers", "regle_tiers_impossible"}:
        return None, None, "croissance"
    else:
        anchor = _default_projection_anchor(context)

    ressuyage_hours = _estimate_mowing_ressuyage_hours(context, phase_bundle, water_bundle)
    application_offset_hours, _ = _mowing_projection_application_offset_hours(context)
    projected = (anchor or _default_projection_anchor(context)) + timedelta(
        hours=ressuyage_hours + application_offset_hours
    )
    # Bascule en heure murale AVANT de tester les bornes horaires : « 18 h » et « 6 h » sont des
    # heures de la vie courante, pas des heures UTC. Et la date renvoyée plus bas doit être la
    # date LOCALE, puisqu'elle est comparée à `context.today` qui l'est.
    projected = _as_wall_clock(projected)

    if projected.hour >= 18:
        projected += timedelta(days=1)
        projected = projected.replace(hour=6, minute=0, second=0, microsecond=0)

    # `wet_grass` means "wait for the grass to dry", not "weather is bad for several days".
    # Keep the public projection short and let future refreshes re-evaluate if humidity persists.
    if reason_code == "wet_grass":
        projected_date = projected.date()
        if projected_date < context.today:
            projected_date = context.today
        max_short_projection = context.today + timedelta(days=1)
        if projected_date > max_short_projection:
            projected_date = max_short_projection
        return projected_date.isoformat(), projected_date.strftime("%d/%m/%Y"), None

    forecast_offset_days, _ = _mowing_projection_forecast_offset_days(context, phase_bundle)
    if forecast_offset_days > 0:
        projected += timedelta(days=forecast_offset_days)
        projected = projected.replace(hour=6, minute=0, second=0, microsecond=0)

    projected_date = projected.date()
    if projected_date < context.today:
        projected_date = context.today

    return projected_date.isoformat(), projected_date.strftime("%d/%m/%Y"), None


def _post_sursemis_bonus(age_days: int | None) -> float:
    """Donne un léger bonus de hauteur pendant la reprise post-sursemis."""
    if age_days is None:
        return 0.0
    if age_days <= 7:
        return 1.0
    if age_days <= 14:
        return 0.8
    if age_days <= 21:
        return 0.5
    if age_days <= 28:
        return 0.3
    if age_days <= 35:
        return 0.1
    if age_days <= 45:
        return 0.3
    if age_days <= 52:
        return 0.2
    if age_days <= 59:
        return 0.1
    return 0.0


def _theoretical_mowing_height(
    context: DecisionContext,
    phase_bundle: dict[str, Any],
    water_bundle: dict[str, Any],
    risk_bundle: dict[str, Any],
) -> float:
    """Estime une hauteur de coupe prudente selon la saison et le stress."""
    temperature = context.temperature or 0.0
    humidite = context.humidite or 0.0
    pluie_24h = context.pluie_24h or 0.0
    pluie_demain = context.pluie_demain or 0.0
    pluie_j2 = context.pluie_j2 or 0.0
    pluie_3j = context.pluie_3j or 0.0
    pluie_probabilite_max_3j = context.pluie_probabilite_max_3j or 0.0
    rosee = water_bundle["advanced_context"].get("rosee")
    etp = water_bundle["etp"] or 0.0
    water_balance = water_bundle["water_balance"]
    score_hydrique = int(risk_bundle["scores"]["score_hydrique"])
    score_stress = int(risk_bundle["scores"]["score_stress"])
    stress_level = classify_stress_level(
        score_hydrique=score_hydrique,
        score_stress=score_stress,
        water_balance=water_balance,
        temperature=temperature,
        etp=etp,
    )

    month = context.today.month
    target = _seasonal_base_height(month)

    if phase_bundle["phase_dominante"] == "Normal":
        if month in {4, 5, 6, 9} and stress_level == "leger":
            if 15 <= temperature <= 24 and humidite >= 50 and pluie_24h < 1 and pluie_demain < 1 and not rosee:
                target -= 0.5
        elif month == 3 and temperature <= 16 and stress_level == "leger":
            target += 0.2
    else:
        target += 0.3

    if month in {1, 2, 11, 12} or temperature <= 8:
        target += 0.5
    if temperature >= 32 or stress_level == "fort":
        target += 1.0
    elif temperature >= 28 or stress_level == "modere":
        target += 0.5
    elif temperature >= 24:
        target += 0.2

    if humidite <= 40:
        target += 0.3
    if rosee is not None and rosee > 0:
        target += 0.4
    if pluie_24h >= 2:
        target += 0.2
    if pluie_demain >= 2:
        target += 0.2
    if pluie_j2 >= 2:
        target += 0.1
    if pluie_3j >= 4:
        target += 0.1
    if pluie_probabilite_max_3j >= 80:
        target += 0.1

    if phase_bundle["phase_dominante"] == "Sursemis":
        if phase_bundle["sous_phase"] == "Germination":
            target = max(target, 7.6)
        elif phase_bundle["sous_phase"] == "Enracinement":
            target = max(target, 7.0)
        else:
            target = max(target, 6.6)
    else:
        post_sursemis_age = _last_sursemis_age_days(context)
        if post_sursemis_age is not None and post_sursemis_age <= 35:
            target += _post_sursemis_bonus(post_sursemis_age)

    return target


def _select_mowing_block_reason(
    *,
    context: DecisionContext,
    phase_bundle: dict[str, Any],
    water_bundle: dict[str, Any],
    weather_profile: dict[str, Any],
    rosee: Any,
    temperature: float,
    etp: float,
    score_tonte: int,
    score_stress: int,
    current_height: float | None,
    target_height: float,
    effective_max: float,
) -> tuple[str | None, str | None, bool]:
    """Résout une cause de blocage unique selon une priorité métier explicite."""
    phase_dominante = str(phase_bundle["phase_dominante"])
    min_height_after_cut = None if current_height is None else current_height * (2.0 / 3.0)
    last_mowing = _last_mowing_date(context)
    spacing_days = _mowing_spacing_min_days(phase_bundle)

    if phase_dominante == "Sursemis":
        if phase_bundle["sous_phase"] in _SURSEMIS_MOWING_BLOCKED_SUBPHASES:
            return (
                f"Sursemis / {phase_bundle['sous_phase']}: tonte interdite pendant l'installation du gazon.",
                "phase_sursemis",
                False,
            )
    if phase_dominante in {"Traitement", "Hivernage"}:
        return f"Phase {phase_dominante}: mieux vaut différer la tonte.", f"phase_{phase_dominante.lower()}", False

    candidates: list[tuple[int, str, str, bool]] = []

    sun_context = context.sun_context if isinstance(context.sun_context, dict) else {}
    sun_state = str(sun_context.get("sun_state") or "").strip().lower()
    sun_above_horizon = sun_context.get("sun_above_horizon")
    sun_below_horizon = sun_context.get("sun_below_horizon")
    if sun_below_horizon is True or sun_state == "below_horizon":
        candidates.append(
            (
                _MOWING_BLOCK_PRIORITIES["mowing_night"],
                "mowing_night",
                "Nuit: attendre le lever du soleil.",
                False,
            )
        )
    elif sun_above_horizon is None and context.hour_of_day is not None and (
        context.hour_of_day < 7 or context.hour_of_day >= 22
    ):
        candidates.append(
            (
                _MOWING_BLOCK_PRIORITIES["mowing_night"],
                "mowing_night",
                "Nuit: attendre le lever du soleil.",
                False,
            )
        )

    if last_mowing is not None:
        days_since_last_mowing = max((context.today - last_mowing).days, 0)
        if days_since_last_mowing < spacing_days:
            next_allowed = last_mowing + timedelta(days=spacing_days)
            candidates.append(
                (
                    _MOWING_BLOCK_PRIORITIES["mowing_spacing"],
                    "mowing_spacing",
                    f"Dernière tonte récente: laisse un jour de repos au gazon avant le {next_allowed.strftime('%d/%m/%Y')}.",
                    False,
                )
            )

    if is_active_rain_weather(weather_profile):
        candidates.append(
            (
                _MOWING_BLOCK_PRIORITIES["pluie_active"],
                "pluie_en_cours",
                "Pluie en cours ou imminente: attendre le ressuyage du gazon.",
                False,
            )
        )

    if float(context.vent or 0.0) > _MOWING_WINDOW_BLOCK_WIND:
        candidates.append(
            (
                _MOWING_BLOCK_PRIORITIES["vent_fort"],
                "vent_fort",
                "Vent fort: tonte interdite.",
                False,
            )
        )

    if current_height is not None:
        if current_height <= target_height:
            candidates.append(
                (
                    _MOWING_BLOCK_PRIORITIES["hauteur_trop_faible"],
                    "hauteur_trop_faible",
                    f"Hauteur actuelle trop faible: vise au moins {target_height:.1f} cm avant de tondre.",
                    True,
                )
            )
        elif min_height_after_cut is not None and target_height < min_height_after_cut:
            if effective_max < min_height_after_cut:
                candidates.append(
                    (
                        _MOWING_BLOCK_PRIORITIES["regle_tiers_impossible"],
                        "regle_tiers_impossible",
                        (
                            f"Règle du tiers impossible avec cette tondeuse: il faudrait au moins {min_height_after_cut:.1f} cm, "
                            f"mais la machine plafonne à {effective_max:.1f} cm."
                        ),
                        True,
                    )
                )
            else:
                candidates.append(
                    (
                        _MOWING_BLOCK_PRIORITIES["regle_tiers"],
                        "regle_tiers",
                        (
                            f"Règle du tiers: conserve au moins {min_height_after_cut:.1f} cm sur une hauteur actuelle de {current_height:.1f} cm."
                        ),
                        True,
                    )
                )

    if rosee is not None and float(rosee) > 0:
        candidates.append(
            (
                _MOWING_BLOCK_PRIORITIES["rosee"],
                "rosee_persistante",
                "Rosée présente: attendre le ressuyage du feuillage.",
                False,
            )
        )

    advanced_context = water_bundle.get("advanced_context")
    if not isinstance(advanced_context, dict):
        advanced_context = {}
    if _soil_is_wet(advanced_context, context):
        candidates.append(
            (
                _MOWING_BLOCK_PRIORITIES["humidite_elevee"],
                "soil_wet",
                "Sol humide: attendre le ressuyage.",
                False,
            )
        )

    if score_stress >= 70 or (temperature >= 30 and etp >= 4):
        candidates.append(
            (
                _MOWING_BLOCK_PRIORITIES["stress_thermique"],
                "stress_thermique",
                "Stress thermique élevé: limiter la tonte.",
                False,
            )
        )
    elif score_tonte >= 65:
        candidates.append(
            (
                _MOWING_BLOCK_PRIORITIES["conditions_defavorables"],
                "conditions_defavorables",
                "Conditions défavorables à la tonte.",
                False,
            )
        )

    if not candidates:
        return None, None, False

    _priority, reason_code, reason, height_rule_blocked = min(candidates, key=lambda item: item[0])
    return reason, reason_code, height_rule_blocked


def _compute_mowing_status(
    *,
    phase_bundle: dict[str, Any],
    risk_bundle: dict[str, Any],
    tonte_ok: bool,
    height_rule_blocked: bool,
    score_tonte: int,
) -> str:
    tonte_statut = compute_tonte_statut(
        phase_dominante=phase_bundle["phase_dominante"],
        tonte_autorisee=tonte_ok,
        score_tonte=score_tonte,
        risque_gazon=risk_bundle["risque_gazon"],
    )
    if height_rule_blocked and tonte_statut != "interdite":
        return "deconseillee"
    return tonte_statut


def _mowing_daily_session_policy(
    phase_bundle: dict[str, Any],
) -> tuple[int, str]:
    """Retourne la politique métier de sessions de tonte par jour."""
    phase_dominante = str(phase_bundle.get("phase_dominante") or "").strip()
    if phase_dominante in {"Sursemis", "Traitement", "Scarification", "Hivernage"}:
        return 1, "phase_sensitive"
    return 2, "standard"


def _build_mowing_bundle_payload(
    *,
    tonte_ok: bool,
    tonte_statut: str,
    reason: str,
    reason_code: str | None,
    next_mowing_date: str | None,
    next_mowing_display: str | None,
    score_tonte: int,
    score_stress: int,
    height_recommendation: dict[str, float | str | None],
    mowing_frequency_target_per_week: float,
    mowing_frequency_label: str,
    mowing_window_state: str,
    mowing_window_label: str,
    mowing_window_reason: str | None,
    mowing_daily_session_limit: int,
    mowing_daily_session_policy: str,
) -> dict[str, Any]:
    bundle = {
        "tonte_autorisee": tonte_ok,
        "tonte_statut": tonte_statut,
        "tonte_reason": reason,
        "raison_blocage_code": reason_code,
        "next_mowing_date": next_mowing_date,
        "next_mowing_display": next_mowing_display,
        "score_tonte": score_tonte,
        "score_stress": score_stress,
        "mowing_frequency_target_per_week": mowing_frequency_target_per_week,
        "mowing_frequency_label": mowing_frequency_label,
        "mowing_window_state": mowing_window_state,
        "mowing_window_label": mowing_window_label,
        "mowing_window_reason": mowing_window_reason,
        "mowing_daily_session_limit": mowing_daily_session_limit,
        "mowing_daily_session_policy": mowing_daily_session_policy,
        "mowing_blocked_by_watering": False,
        "mowing_blocked": False,
        "mowing_block_reason_code": None,
        "mowing_block_reason_label": None,
        "mowing_block_reason": None,
        "mowing_cooldown_remaining_minutes": 0,
        "mowing_post_application_active": False,
        **height_recommendation,
    }
    return bundle


def _recommended_mowing_height(
    context: DecisionContext,
    phase_bundle: dict[str, Any],
    water_bundle: dict[str, Any],
    risk_bundle: dict[str, Any],
) -> dict[str, float | str | None]:
    """Calcule une hauteur de coupe prudente et compatible avec la machine.

    Les bornes retournées (`hauteur_tonte_min_cm` / `_max_cm`) sont celles RÉELLEMENT appliquées,
    garde-fous agronomiques compris — pas la config brute. `hauteur_tonte_garde_fou_label` dit en
    clair quand un garde-fou a resserré la config, et vaut None sinon.
    """
    min_height, max_height, step = _mowing_height_settings(context)
    theoretical_height = _theoretical_mowing_height(context, phase_bundle, water_bundle, risk_bundle)
    current_height = water_bundle["advanced_context"].get("hauteur_gazon")
    if current_height is None:
        current_height = _estimated_grass_height_cm(context, phase_bundle, water_bundle)
    third_floor = None
    # PLANCHER/PLAFOND FIXES RETIRÉS le 29/07/2026 (arbitrage de Kévin : « pour la tondeuse il
    # devrait se fier au min max »). Ils valaient 4,0 et 6,5 cm, portaient un nom trompeur
    # (`robot_*`, comme des limites machine) et rognaient EN SILENCE la configuration : un
    # réglage 3,0-6,0 devenait 4,0-6,0.
    #
    # Ce qui protège du scalp, c'est la RÈGLE DU TIERS appliquée plus haut
    # (`third_floor = hauteur_actuelle × 2/3`) : elle interdit d'ôter plus d'un tiers du limbe.
    # Elle est meilleure qu'un plancher fixe parce qu'elle SUIT l'herbe — mesuré le 29/07/2026 :
    # gazon à 5,9 cm → plancher dynamique à 3,93 cm, soit le même ordre que l'ancien 4,0, mais
    # qui descend quand l'herbe est courte et monte quand elle est haute.
    #
    # La config décrit la MACHINE : c'est elle qui borne désormais, sans rognage caché. Le
    # commentaire de `number.py` (« aucune valeur codée en dur ») redevient vrai de bout en bout.
    # ⚠️ Seul trou connu : si `hauteur_gazon` est absente, `third_floor` vaut None et il ne reste
    # que la hauteur théorique (phase + saison) pour tenir le plancher. En saison chaude elle
    # pousse déjà vers le haut, donc le risque est hors saison de végétation.

    theoretical_before_third = theoretical_height
    if current_height is not None:
        try:
            current_height = float(current_height)
            third_floor = current_height * (2.0 / 3.0)
            theoretical_height = max(theoretical_height, third_floor)
        except (TypeError, ValueError):
            current_height = None
            third_floor = None

    effective_max = _round_down_to_step(max_height, min_height, step)
    recommended_height = _round_up_to_step(theoretical_height, min_height, step)
    allowed_min = min_height
    allowed_max = effective_max
    recommended_height = max(allowed_min, min(recommended_height, allowed_max))

    previous_height = _previous_recommended_height(context)
    if previous_height is not None:
        previous_height = max(allowed_min, min(previous_height, allowed_max))
        previous_height = _round_to_step(previous_height)
        diff = recommended_height - previous_height
        if abs(diff) < step:
            recommended_height = previous_height
        else:
            direction = step if diff > 0 else -step
            recommended_height = _round_to_step(previous_height + direction)
            recommended_height = max(allowed_min, min(recommended_height, allowed_max))

    # Les bornes PUBLIÉES sont désormais celles réellement appliquées (`allowed_*`), pas la config
    # brute. Avant, l'attribut annonçait le min configuré — 3,0 cm chez Kévin — alors que le
    # plancher agronomique de 4,0 cm interdit d'y descendre : l'attribut mentait sans le dire.
    # Le garde-fou n'est PAS retiré (voir sa note plus haut) ; il devient simplement visible.
    # Les valeurs configurées restent exposées sous des clés privées pour le diagnostic.
    # Le libellé n'annonce plus un rognage de la config — il n'y en a plus. Il explique la seule
    # contrainte qui peut encore relever la consigne au-dessus de ce que la saison demanderait :
    # la RÈGLE DU TIERS. Sans ce mot, une consigne à 4 cm sur une tondeuse réglable à 3 reste
    # incompréhensible. Vaut None quand c'est la saison qui pilote — cas courant.
    if (
        third_floor is not None
        and third_floor > theoretical_before_third + 1e-9
        and recommended_height > min_height + 1e-9
    ):
        garde_fou_label = (
            f"Règle du tiers : on n'ôte pas plus d'un tiers du limbe. Gazon à "
            f"{float(current_height):g} cm → ne pas descendre sous {third_floor:.1f} cm "
            f"(la saison seule aurait proposé {theoretical_before_third:.1f} cm)."
        )
    else:
        garde_fou_label = None

    return {
        "hauteur_tonte_recommandee_cm": round(recommended_height, 2),
        "hauteur_tonte_min_cm": round(allowed_min, 2),
        "hauteur_tonte_max_cm": round(allowed_max, 2),
        "hauteur_tonte_garde_fou_label": garde_fou_label,
        "_hauteur_tonte_min_config_cm": round(min_height, 2),
        "_hauteur_tonte_max_config_cm": round(max_height, 2),
        "_hauteur_tonte_effective_max_cm": round(effective_max, 2),
        "_hauteur_tonte_3e_cm": round(third_floor, 2) if third_floor is not None else None,
        "_hauteur_tonte_theorique_cm": round(theoretical_height, 2),
        "_hauteur_tonte_actuelle_cm": round(float(current_height), 2) if current_height is not None else None,
    }


def build_mowing_bundle(
    context: DecisionContext,
    phase_bundle: dict[str, Any],
    water_bundle: dict[str, Any],
    risk_bundle: dict[str, Any],
) -> dict[str, Any]:
    score_tonte = int(risk_bundle["scores"]["score_tonte"])
    score_stress = int(risk_bundle["scores"]["score_stress"])
    phase_dominante = str(phase_bundle.get("phase_dominante") or "")
    sous_phase = str(phase_bundle.get("sous_phase") or "")
    if phase_dominante == "Sursemis" and sous_phase in {"Reprise", "Stabilisation"}:
        baseline_tonte_ok = score_tonte < 65 and score_stress < 75
    else:
        baseline_tonte_ok = score_tonte < 55 and score_stress < 70

    mowing_frequency_target_per_week, mowing_frequency_label = _phase_adjusted_mowing_frequency(
        phase_bundle,
        context.today.month,
    )
    height_recommendation = _recommended_mowing_height(context, phase_bundle, water_bundle, risk_bundle)
    target_height = float(height_recommendation["hauteur_tonte_recommandee_cm"] or 0.0)
    # RÈGLE DU TIERS — ne jamais couper plus d'un tiers du brin d'un coup : au-delà, on retire
    # trop de surface foliaire et le gazon jaunit puis met des jours à repartir.
    # Elle ne lisait QUE `capteur_hauteur_gazon` (un capteur physique que peu d'installations
    # possèdent). Sans lui, `current_height` restait None et la règle — comme le garde-fou
    # « hauteur trop faible » — était purement INACTIVE : aucune protection de hauteur.
    # On retombe donc sur la hauteur ESTIMÉE par l'intégration, exactement comme le fait déjà
    # `_recommended_mowing_height` pour calculer la hauteur conseillée. Le capteur physique
    # garde la priorité quand il existe (mesure > estimation).
    current_height = water_bundle["advanced_context"].get("hauteur_gazon")
    if current_height is None:
        current_height = _estimated_grass_height_cm(context, phase_bundle, water_bundle)
    height_rule_blocked = False
    try:
        current_height_float = float(current_height) if current_height is not None else None
    except (TypeError, ValueError):
        current_height_float = None
    effective_max = float(height_recommendation["_hauteur_tonte_effective_max_cm"] or 0.0)

    post_application_active, post_application_code, post_application_label = _post_application_mowing_block(context)
    active_session = _active_irrigation_session(context)
    watering_in_progress = active_session is not None
    cooldown_active, cooldown_remaining_minutes = _mowing_cooldown_state(context)
    mowing_window_state, mowing_window_reason = _resolve_mowing_window(
        context,
        weather_profile=context.weather_profile,
    )
    mowing_blocked, mowing_block_reason_code, mowing_block_reason_label, mowing_machine_unavailable_detail, mowing_machine_unavailable_label = _resolve_mowing_block(
        context,
        phase_bundle,
        water_bundle,
    )
    # ⚠️ LE LIBELLÉ PRÉCIS EST DÉJÀ CALCULÉ, deux lignes plus haut. La décision publiait quand
    # même le générique « Robot indisponible: attendre qu'elle soit prête. », et chaque
    # plateforme d'entité le rafistolait de son côté — sauf qu'elles ne le faisaient pas toutes.
    # Résultat sur l'écran de Kévin le 03/08/2026 à 14 h 31, robot EN TONTE depuis 14 h 19 :
    #   binary_sensor  → « Robot déjà en tonte : attendre la fin du cycle. »   (juste)
    #   sensor hauteur → « Robot indisponible : attendre qu'elle soit prête. » (faux)
    # Même attribut, deux valeurs, même instant — et le bandeau de la carte affichait la fausse.
    # On corrige ICI : une seule fois, pour tous les consommateurs.
    if mowing_block_reason_code == "machine_unavailable" and mowing_machine_unavailable_label:
        mowing_block_reason_label = mowing_machine_unavailable_label
    if mowing_blocked:
        mowing_window_state = "blocked"
        mowing_window_reason = mowing_block_reason_label
    mowing_window_label = _mowing_window_label(mowing_window_state)
    mowing_window_blocked_by_schedule = mowing_window_state == "blocked" and not mowing_blocked

    reason, reason_code, height_rule_blocked = _select_mowing_block_reason(
        context=context,
        phase_bundle=phase_bundle,
        water_bundle=water_bundle,
        weather_profile=context.weather_profile,
        rosee=water_bundle["advanced_context"].get("rosee"),
        temperature=float(context.temperature or 0.0),
        etp=float(water_bundle.get("etp") or 0.0),
        score_tonte=score_tonte,
        score_stress=score_stress,
        current_height=current_height_float,
        target_height=target_height,
        effective_max=effective_max,
    )
    selected_reason = reason
    selected_reason_code = reason_code

    mowing_blocked_by_watering = False
    # UNE PANNE PASSE AVANT UN DÉLAI. Les branches « arrosage » ci-dessous écrasaient le motif
    # machine : un robot avec un moteur de lame bloqué affichait « Arrosage récent : attends
    # encore 180 min », et la panne restait cachée jusqu'à 3 h dans un attribut secondaire.
    # Un délai se résout tout seul, pas une panne — c'est elle qu'il faut montrer.
    machine_failure_first = bool(mowing_blocked) and mowing_block_reason_code == "machine_unavailable"
    if machine_failure_first:
        mowing_blocked_by_watering = False
        mowing_block_reason = mowing_block_reason_code
        if reason_code not in {"phase_sursemis", "phase_traitement", "phase_hivernage"}:
            reason = mowing_block_reason_label or reason
            reason_code = mowing_block_reason_code
        height_rule_blocked = False
    elif post_application_active:
        reason = post_application_label
        reason_code = post_application_code
        mowing_blocked = True
        mowing_blocked_by_watering = True
        mowing_block_reason_code = post_application_code
        mowing_block_reason_label = post_application_label
        mowing_block_reason = "recent_watering"
        height_rule_blocked = False
    elif watering_in_progress:
        reason = "Arrosage en cours: attends la fin du cycle avant de tondre."
        reason_code = "watering_in_progress"
        mowing_blocked = True
        mowing_blocked_by_watering = True
        mowing_block_reason_code = reason_code
        mowing_block_reason_label = reason
        mowing_block_reason = "recent_watering"
        height_rule_blocked = False
    elif cooldown_active:
        reason = (
            f"Arrosage récent: attends encore {cooldown_remaining_minutes} min avant de reprendre la tonte."
        )
        reason_code = "watering_cooldown"
        mowing_blocked = True
        mowing_blocked_by_watering = True
        mowing_block_reason_code = reason_code
        mowing_block_reason_label = reason
        mowing_block_reason = "recent_watering"
        height_rule_blocked = False
    elif mowing_blocked and mowing_block_reason_code:
        mowing_blocked_by_watering = mowing_block_reason_code in {"recent_watering", "soil_wet", "wet_grass"}
        mowing_block_reason = mowing_block_reason_code
        if reason_code not in {"phase_sursemis", "phase_traitement", "phase_hivernage"}:
            reason = mowing_block_reason_label or reason
            reason_code = mowing_block_reason_code
        height_rule_blocked = False
    else:
        mowing_block_reason = None

    if selected_reason_code in {"phase_sursemis", "phase_traitement", "phase_hivernage"}:
        reason = selected_reason
        reason_code = selected_reason_code
        mowing_blocked = True
        mowing_blocked_by_watering = False
        mowing_block_reason_code = selected_reason_code
        mowing_block_reason_label = selected_reason
        mowing_block_reason = selected_reason_code
        height_rule_blocked = False

    if reason_code and mowing_block_reason_code is None and not mowing_blocked:
        mowing_block_reason_code = reason_code
        mowing_block_reason_label = reason

    if mowing_window_blocked_by_schedule:
        window_msg = mowing_window_reason or "Fenêtre de tonte bloquée."
        if reason_code is None:
            reason_code = "mowing_window_blocked"
            reason = window_msg
            if mowing_block_reason_code is None:
                mowing_block_reason_code = reason_code
                mowing_block_reason_label = reason
        else:
            reason = f"{reason} Fenêtre horaire: {window_msg}"

    agronomic_block_codes = {
        "mowing_night",
        "mowing_spacing",
        "phase_sursemis",
        "phase_traitement",
        "phase_hivernage",
        "hauteur_trop_faible",
        "regle_tiers",
        "regle_tiers_impossible",
        "stress_thermique",
        "conditions_defavorables",
        "wet_grass",
        "rosee_persistante",
        "soil_wet",
        "pluie_en_cours",
        "recent_watering",
        "post_application_active",
        "watering_in_progress",
        "watering_cooldown",
        # Manquait : `tonte_autorisee` restait à ON à 35 °C (et à 5 °C) alors que l'intégration
        # affichait « bloqué » — une automatisation branchée sur le binary_sensor lançait donc le
        # robot en pleine canicule. La température, elle, EST un motif agronomique : c'est le gazon
        # qui souffre. On n'ajoute PAS ici `machine_unavailable` ni `upcoming_watering` : ce sont
        # des motifs MACHINE/coordination, portés par `machine_permet_tonte` et `action_possible`
        # (`tonte_autorisee` reste le verdict du GAZON — cf.
        # test_build_mowing_bundle_blocks_when_machine_unavailable).
        "temp_extreme",
    }
    soil_wet_is_permissive = reason_code == "soil_wet" and _has_recent_watering_history(context)

    mowing_is_overdue, overdue_factor, overdue_days = _mowing_overdue_state(context, phase_bundle)
    overdue_relaxed_baseline = False
    # `reason_code is None` couvre le blocage par SCORE SEUL : entre le seuil baseline (55) et le
    # seuil « conditions défavorables » (65), la tonte est refusée sans qu'aucun code agronomique
    # ne soit posé. L'override de retard étant indexé sur `reason_code`, cette bande était
    # impossible à débloquer — une tonte pouvait rester refusée avec 37 jours de retard, sans
    # motif affiché. C'est exactement le cas que l'override existe pour traiter.
    if mowing_is_overdue and (reason_code is None or reason_code in _OVERDUE_SOFT_OVERRIDE_CODES):
        extended_threshold = 65 if overdue_factor < 2.0 else 70
        overdue_relaxed_baseline = score_tonte < extended_threshold and score_stress < 70

    tonte_ok = (baseline_tonte_ok or overdue_relaxed_baseline) and not mowing_window_blocked_by_schedule and (
        reason_code not in agronomic_block_codes or soil_wet_is_permissive or overdue_relaxed_baseline
    )
    if reason is None:
        if mowing_window_state == "discouraged" and mowing_window_reason:
            reason = f"Tonte possible. Créneau déconseillé: {mowing_window_reason}"
        else:
            reason = "Fenêtre tonte acceptable."

    next_mowing_date, next_mowing_display, next_mowing_reason_hint = _project_next_mowing_date(
        context,
        phase_bundle,
        water_bundle,
        tonte_ok,
        reason_code,
    )

    if mowing_is_overdue and mowing_frequency_target_per_week > 0:
        interval_days_display = round(7.0 / mowing_frequency_target_per_week, 1)
        overdue_prefix = (
            f"Retard de tonte: {overdue_days} j depuis la dernière"
            f" (intervalle cible: {interval_days_display:.1f} j). "
        )
        if tonte_ok:
            reason = overdue_prefix + "Tonte recommandée."
        else:
            base = reason or ""
            if next_mowing_display:
                base = f"{base} Prochaine tonte estimée le {next_mowing_display}."
            reason = overdue_prefix + base.lstrip()
    else:
        if not tonte_ok and next_mowing_display:
            reason = f"{reason} Prochaine tonte estimée le {next_mowing_display}."

    watering_coord_level, watering_coord_msg = _upcoming_watering_coordination(context, water_bundle)
    if watering_coord_level == "block" and not mowing_blocked and not post_application_active and not watering_in_progress and not cooldown_active:
        tonte_ok = False
        reason = watering_coord_msg or reason
        reason_code = "upcoming_watering"
        mowing_block_reason_code = reason_code
        mowing_block_reason_label = watering_coord_msg
        mowing_block_reason = "recent_watering"
    elif watering_coord_msg and tonte_ok:
        reason = f"{reason} {watering_coord_msg}"

    tonte_statut = _compute_mowing_status(
        phase_bundle=phase_bundle,
        risk_bundle=risk_bundle,
        tonte_ok=tonte_ok,
        height_rule_blocked=height_rule_blocked,
        score_tonte=score_tonte,
    )
    if reason_code == "mowing_night":
        tonte_statut = "interdite"

    mowing_daily_session_limit, mowing_daily_session_policy = _mowing_daily_session_policy(
        phase_bundle
    )

    bundle = _build_mowing_bundle_payload(
        tonte_ok=tonte_ok,
        tonte_statut=tonte_statut,
        reason=reason,
        reason_code=reason_code,
        next_mowing_date=next_mowing_date,
        next_mowing_display=next_mowing_display,
        score_tonte=score_tonte,
        score_stress=score_stress,
        height_recommendation=height_recommendation,
        mowing_frequency_target_per_week=mowing_frequency_target_per_week,
        mowing_frequency_label=mowing_frequency_label,
        mowing_window_state=mowing_window_state,
        mowing_window_label=mowing_window_label,
        mowing_window_reason=mowing_window_reason,
        mowing_daily_session_limit=mowing_daily_session_limit,
        mowing_daily_session_policy=mowing_daily_session_policy,
    )
    # `mowing_blocked` = « quelque chose empêche de tondre », MACHINE OU GAZON. Il manquait le
    # second : la tonte pouvait être interdite (`tonte_autorisee` False pour cause de nuit,
    # d'espacement, de règle du tiers…) alors que `mowing_blocked` restait à False. Or c'est
    # l'attribut le plus « évident » pour une carte ou un flow Node-RED, et il ne pouvait donc
    # pas servir à décider de laisser sortir le robot.
    # On garde bien le OU : un robot en panne bloque sans que le GAZON s'y oppose — `tonte_autorisee`
    # reste le verdict agronomique seul (cf. test_build_mowing_bundle_blocks_when_machine_unavailable).
    # NB : la variable interne `mowing_blocked` reste utilisée en amont (calcul de la fenêtre) ;
    # seule la valeur PUBLIÉE est complétée ici, après le calcul de `tonte_ok`.
    bundle["mowing_blocked"] = bool(mowing_blocked) or not bool(tonte_ok)
    bundle["mowing_blocked_by_watering"] = mowing_blocked_by_watering
    bundle["mowing_block_reason_code"] = mowing_block_reason_code
    bundle["mowing_block_reason_label"] = mowing_block_reason_label
    bundle["mowing_block_reason"] = mowing_block_reason
    bundle["mowing_machine_unavailable_detail"] = mowing_machine_unavailable_detail
    bundle["mowing_machine_unavailable_label"] = mowing_machine_unavailable_label
    bundle["mowing_cooldown_remaining_minutes"] = cooldown_remaining_minutes
    bundle["mowing_post_application_active"] = post_application_active
    bundle["mowing_is_overdue"] = mowing_is_overdue
    bundle["mowing_overdue_days"] = overdue_days
    bundle["mowing_overdue_factor"] = overdue_factor
    _pousse = _grass_growth_details(context, phase_bundle, water_bundle)
    bundle["gazon_hauteur_estimee_cm"] = _pousse["hauteur_cm"] if _pousse else None
    bundle["gazon_pousse_jour_cm"] = _pousse["pousse_jour_cm"] if _pousse else None
    bundle["gazon_pousse_state"] = _pousse["etat"] if _pousse else None
    bundle["pluie_state"] = _etat_pluie(context, is_active_rain_weather(context.weather_profile))
    bundle["mowing_watering_coordination"] = watering_coord_level
    bundle["mowing_watering_coordination_msg"] = watering_coord_msg
    mower_context = context.mower_context if isinstance(context.mower_context, dict) else {}
    if mower_context:
        bundle.update(
            {
                key: value
                for key, value in mower_context.items()
                if key.startswith(("tondeuse_", "mower_")) and value is not None
            }
        )
    mower_coordination_ready = bundle.get("mower_coordination_ready", True)
    machine_permet_tonte = bool(bundle.get("tondeuse_prete", False)) and mower_coordination_ready is not False
    bundle["gazon_permet_tonte"] = bool(bundle.get("tonte_autorisee", False))
    bundle["machine_permet_tonte"] = machine_permet_tonte
    bundle["action_possible"] = bool(bundle["gazon_permet_tonte"] and machine_permet_tonte and not bundle.get("mowing_blocked", False))
    return bundle
