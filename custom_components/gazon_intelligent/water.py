from __future__ import annotations

import math
from collections.abc import Callable
from datetime import date, datetime, timezone
from typing import Any
import logging

_LOGGER = logging.getLogger(__name__)

try:
    from homeassistant.util import dt as dt_util
except Exception:  # pragma: no cover - standalone fallback
    dt_util = None


# JUMEAU : soil_balance.SOIL_RESERVE_BASE_MM — même réserve utile du sol par type de sol.
# Les deux modules sont volontairement découplés (pas d'import croisé), on garde donc les deux
# tables identiques à la main (cf. tests/test_soil_balance.py::TestSoilReserveTwins).
_SOIL_RESERVE_UTILE_MM: dict[str, float] = {
    "sableux": 8.0,
    "limoneux": 12.0,
    "argileux": 16.0,
}

_PHASE_MAD_RATIO: dict[str, float] = {
    "Sursemis": 0.35,
    "Hivernage": 0.6,
}

_RAIN_HORIZON_WEIGHTS: dict[str, float] = {
    "today": 1.0,
    "tomorrow": 0.55,
    "day_after_tomorrow": 0.25,
}

_BALANCE_HORIZON_WEIGHTS: dict[int, dict[str, float]] = {
    1: {"etp": 1.0, "rain": 1.0},
    3: {"etp": 3.0, "rain": 1.4},
    7: {"etp": 7.0, "rain": 2.4},
}


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_half_up_1(value: float) -> float:
    # int(x * 10 + 0.5) arrondit vers +inf pour les positifs mais TRONQUE vers zéro pour les
    # négatifs (-0.99 → -0.9 au lieu de -1.0), soit une erreur de 0,1 mm systématiquement
    # optimiste sur les bilans déficitaires. On applique donc la règle sur la valeur absolue
    # puis on restaure le signe.
    # JUMEAU : soil_balance._round_half_up_1 — garder les deux identiques
    # (cf. tests/test_soil_balance.py::TestRoundHalfUpTwins).
    if value < 0:
        return -float(int(abs(value) * 10.0 + 0.5)) / 10.0
    return float(int(value * 10.0 + 0.5)) / 10.0


def _current_date() -> date:
    if dt_util is not None:
        now_getter = getattr(dt_util, "now", None)
        if callable(now_getter):
            current = now_getter()
            if isinstance(current, datetime):
                return current.date()
    return datetime.now(timezone.utc).date()


def _bound(value: float, lower: float, upper: float) -> float:
    return max(lower, min(value, upper))


def _zone_mm_value(zone: dict[str, Any] | None) -> float | None:
    if not isinstance(zone, dict):
        return None
    amount = _to_float(zone.get("mm"))
    if amount is None:
        rate_mm_h = _to_float(zone.get("rate_mm_h"))
        duration_min = _to_float(zone.get("duration_min"))
        if rate_mm_h is not None and duration_min is not None:
            amount = (rate_mm_h * duration_min) / 60.0
    if amount is None:
        amount = _to_float(zone.get("objectif_mm"))
    if amount is None:
        return None
    return max(0.0, amount)


def _zone_session_mm_values(zones: list[dict[str, Any]] | None) -> list[float]:
    if not isinstance(zones, list):
        return []
    values: list[float] = []
    for zone in zones:
        amount = _zone_mm_value(zone)
        if amount is None:
            continue
        values.append(amount)
    return values


def _zone_session_surface_mm(
    zones: list[dict[str, Any]] | None,
    *,
    objective_mm: float | None = None,
) -> float | None:
    if objective_mm is not None and objective_mm > 0:
        return _round_half_up_1(objective_mm)
    values = _zone_session_mm_values(zones)
    if not values:
        return None
    return _round_half_up_1(sum(values) / len(values))


def _zone_session_total_mm(zones: list[dict[str, Any]] | None) -> float | None:
    values = _zone_session_mm_values(zones)
    if not values:
        return None
    return _round_half_up_1(sum(values))


def compute_live_session_water(
    session: dict[str, Any] | None,
    *,
    now: datetime,
    rate_fn: Callable[[str], float],
) -> dict[str, Any]:
    """mm appliqués EN TEMPS RÉEL pendant une session d'arrosage en cours.

    Additionne, par zone, les segments déjà terminés et le segment en cours
    (zone active : ``durée_écoulée × débit``). Renvoie :
    - ``zone_mm`` : détail des mm par zone (arrondi),
    - ``surface_mm`` : dose surface (moyenne des zones, cohérente avec le modèle
      « lame surfacique » utilisé à la finalisation),
    - ``total_mm`` : cumul brut toutes zones.

    Fonction pure (aucun accès HA) pour rester testable hors Home Assistant.
    """
    zone_mm: dict[str, float] = {}
    if not isinstance(session, dict):
        return {"zone_mm": {}, "surface_mm": 0.0, "total_mm": 0.0}

    def _add(zone_id: Any, amount: float | None) -> None:
        if not zone_id or amount is None or amount <= 0:
            return
        key = str(zone_id)
        zone_mm[key] = zone_mm.get(key, 0.0) + float(amount)

    # Segments déjà terminés : `zones_done` (cycle piloté) ou `zones` (moniteur passif).
    zones_done = session.get("zones_done")
    if isinstance(zones_done, list) and zones_done:
        for segment in zones_done:
            if isinstance(segment, dict):
                _add(segment.get("zone") or segment.get("entity_id"), _to_float(segment.get("mm")))
    else:
        zones = session.get("zones")
        if isinstance(zones, dict):
            for zone_id, record in zones.items():
                if isinstance(record, dict):
                    _add(zone_id, _to_float(record.get("mm")))

    # Segment EN COURS : zone active × débit × temps écoulé (sauf en pause).
    if session.get("status") in (None, "running"):
        active = session.get("active_zones")
        pairs: list[tuple[Any, Any]] = []
        if isinstance(active, dict):
            pairs = list(active.items())
        elif isinstance(active, list):
            started = session.get("last_activity_at") or session.get("last_update")
            pairs = [(zone_id, started) for zone_id in active]
        for zone_id, started_at in pairs:
            if not isinstance(started_at, datetime):
                continue
            elapsed = (now - started_at).total_seconds()
            if elapsed <= 0:
                continue
            rate = max(0.0, float(rate_fn(str(zone_id))))
            if rate <= 0:
                continue
            _add(zone_id, (rate * elapsed) / 3600.0)

    zone_list = [{"zone": zone_id, "mm": amount} for zone_id, amount in zone_mm.items()]
    surface_mm = _zone_session_surface_mm(zone_list) or 0.0
    total_mm = _zone_session_total_mm(zone_list) or 0.0
    return {
        "zone_mm": {zone_id: _round_half_up_1(amount) for zone_id, amount in zone_mm.items()},
        "surface_mm": surface_mm,
        "total_mm": total_mm,
    }


def _normalize_allowed_zone_ids(allowed_zone_ids: Any) -> set[str]:
    if not isinstance(allowed_zone_ids, (list, tuple, set)):
        return set()
    normalized: set[str] = set()
    for raw in allowed_zone_ids:
        text = str(raw or "").strip()
        if text:
            normalized.add(text)
    return normalized


def _zone_ids_for_item(item: dict[str, Any] | None) -> set[str]:
    if not isinstance(item, dict):
        return set()
    zones = item.get("zones")
    if not isinstance(zones, list):
        return set()
    zone_ids: set[str] = set()
    for zone in zones:
        if not isinstance(zone, dict):
            continue
        zone_id = str(zone.get("entity_id") or zone.get("zone") or "").strip()
        if zone_id:
            zone_ids.add(zone_id)
    return zone_ids


def _watering_item_matches_zones(
    item: dict[str, Any] | None,
    allowed_zone_ids: Any = None,
) -> bool:
    allowed = _normalize_allowed_zone_ids(allowed_zone_ids)
    if not allowed:
        return True
    zone_ids = _zone_ids_for_item(item)
    if not zone_ids:
        return False
    return bool(zone_ids & allowed)


_SOIL_MODEL_BASES: dict[str, dict[str, float]] = {
    "sableux": {
        "retention_factor": 0.84,
        "drainage_factor": 1.16,
        "infiltration_factor": 1.08,
    },
    "limoneux": {
        "retention_factor": 1.0,
        "drainage_factor": 1.0,
        "infiltration_factor": 1.0,
    },
    "argileux": {
        "retention_factor": 1.14,
        "drainage_factor": 0.88,
        "infiltration_factor": 0.92,
    },
}


def _compute_soil_profile(
    type_sol: str,
    humidite_sol: float | None = None,
    vent: float | None = None,
    rosee: float | None = None,
) -> dict[str, float | str]:
    soil_type = (type_sol or "limoneux").strip().lower()
    base = _SOIL_MODEL_BASES.get(soil_type, _SOIL_MODEL_BASES["limoneux"])
    retention_factor = float(base["retention_factor"])
    drainage_factor = float(base["drainage_factor"])
    infiltration_factor = float(base["infiltration_factor"])

    if humidite_sol is not None:
        if humidite_sol <= 25:
            retention_factor += 0.04
            drainage_factor += 0.05
            infiltration_factor += 0.03
        elif humidite_sol <= 40:
            retention_factor += 0.02
        elif humidite_sol >= 80:
            retention_factor -= 0.05
            drainage_factor -= 0.04
            infiltration_factor -= 0.04
        elif humidite_sol >= 65:
            retention_factor -= 0.03
            drainage_factor -= 0.02

    if vent is not None:
        if vent >= 25:
            drainage_factor += 0.08
            infiltration_factor += 0.04
        elif vent >= 15:
            drainage_factor += 0.05
        elif vent >= 8:
            drainage_factor += 0.02

    if rosee is not None and rosee > 0:
        retention_factor += 0.01

    retention_factor = max(0.75, min(retention_factor, 1.25))
    drainage_factor = max(0.75, min(drainage_factor, 1.25))
    infiltration_factor = max(0.75, min(infiltration_factor, 1.25))
    need_factor = 1.0
    need_factor += max(0.0, 1.0 - retention_factor) * 0.6
    need_factor += max(0.0, drainage_factor - 1.0) * 0.4
    need_factor += max(0.0, 1.0 - infiltration_factor) * 0.25
    need_factor = max(0.8, min(need_factor, 1.35))

    return {
        "soil_type": soil_type,
        "retention_factor": _round_half_up_1(retention_factor),
        "drainage_factor": _round_half_up_1(drainage_factor),
        "infiltration_factor": _round_half_up_1(infiltration_factor),
        "need_factor": _round_half_up_1(need_factor),
    }


def _watering_item_mm(item: dict[str, Any] | None) -> float | None:
    if not isinstance(item, dict):
        return None
    # Priorité au total surface CANONIQUE enregistré au moment de l'arrosage
    # (`total_mm` / `session_total_mm` = dose surface du cycle complet, déjà calculée).
    # Re-dériver depuis la liste `zones` via _zone_session_surface_mm() est FAUX pour un
    # cycle multi-passages : chaque passage y est une entrée distincte, et la moyenne
    # renvoie alors la dose d'UN passage, pas le cumul → sous-comptage ≈ ×nombre de
    # passages (réserve et budget hebdo gravement sous-crédités).
    for key in ("total_mm", "session_total_mm"):
        amount = _to_float(item.get(key))
        if amount is not None:
            return amount
    # Repli : pas de total stocké → on dérive depuis les zones (eau réellement appliquée),
    # puis l'objectif, puis mm. (Cas des records légers / historiques sans total.)
    zones = item.get("zones")
    if isinstance(zones, list):
        surface_mm = _zone_session_surface_mm(zones)
        if surface_mm is not None:
            return surface_mm
    for key in ("objectif_mm", "objective_mm", "mm"):
        amount = _to_float(item.get(key))
        if amount is not None:
            return amount
    return None


def build_watering_session_summary(
    zones: list[dict[str, Any]],
    source: str | None = None,
    objective_mm: float | None = None,
) -> dict[str, Any]:
    normalized_zones: list[dict[str, Any]] = []
    zones_total_mm = 0.0
    for order, zone in enumerate(zones, start=1):
        if not isinstance(zone, dict):
            continue
        zone_name = str(zone.get("zone") or zone.get("entity_id") or "").strip()
        if not zone_name:
            continue
        rate_mm_h = _to_float(zone.get("rate_mm_h"))
        duration_min = _to_float(zone.get("duration_min"))
        mm = _zone_mm_value(zone)
        if mm is None:
            continue
        normalized_zone = {
            "order": order,
            "zone": zone_name,
            "entity_id": zone.get("entity_id") or zone_name,
            "mm": _round_half_up_1(mm),
        }
        if rate_mm_h is not None:
            normalized_zone["rate_mm_h"] = _round_half_up_1(rate_mm_h)
        if duration_min is not None:
            normalized_zone["duration_min"] = _round_half_up_1(duration_min)
        if zone.get("duration_seconds") is not None:
            duration_seconds = _to_float(zone.get("duration_seconds"))
            if duration_seconds is not None:
                normalized_zone["duration_seconds"] = int(max(0.0, duration_seconds))
        normalized_zones.append(normalized_zone)
        zones_total_mm += mm

    objective_value = _zone_session_surface_mm(normalized_zones, objective_mm=objective_mm)
    if objective_value is None:
        objective_value = 0.0
    zones_total_mm = _round_half_up_1(zones_total_mm)
    session: dict[str, Any] = {
        "mm_scope": "global_surface",
        "mm_interpretation": "surface_uniform",
        "objective_mm": objective_value,
        "objectif_mm": objective_value,
        "total_mm": objective_value,
        "session_total_mm": objective_value,
        "zones_total_mm": zones_total_mm,
        "zone_count": len(normalized_zones),
        "zones": normalized_zones,
    }
    if source:
        session["source"] = source
    return session


# Arrosages TECHNIQUES (rafraîchissement du soir en canicule, incorporation post-application) :
# ils rafraîchissent / incorporent un produit mais NE rechargent PAS la réserve hydrique. Ils
# sont donc exclus du total d'eau récente → ni comptés dans la recharge de réserve, ni dans le
# garde-fou hebdomadaire (sinon ce petit arrosage de cooling grignote le budget destiné à la
# vraie recharge, et la réserve paraît plus pleine qu'en réalité — cause d'un gazon qui sèche en
# canicule). Même principe que l'exclusion déjà appliquée au cooldown 24 h (cf. guidance.py).
_TECHNICAL_WATERING_CAUSES = ("rafraichissement_soir", "post_application")


def _is_technical_watering(item: dict[str, Any]) -> bool:
    return str(item.get("watering_cause") or "").strip().lower() in _TECHNICAL_WATERING_CAUSES


# Sources d'arrosage NON pilotées par l'intégration : sessions détectées en passif quand des
# vannes s'ouvrent HORS cycle intégré (Assist/voix, raccourci, toggle manuel dashboard, Node-RED…).
# Le moniteur passif est gelé pendant les cycles de l'intégration, donc `zone_session` ne double
# jamais un cycle piloté : c'est bien de l'arrosage externe.
#
# Choix explicite (Kévin, 25/06/2026) : ces sessions externes sont TOTALEMENT ignorées par la
# DÉCISION — ni budget hebdomadaire, ni cooldown 24 h (cf. guidance._latest_watering_datetime),
# ni crédit de la réserve sol (cf. gazon_brain). L'intégration pilote son auto-arrosage
# indépendamment de ce qu'on fait à la main. Contrepartie ASSUMÉE (pas de capteur de sol) : le
# robot croit le sol sec après un arrosage manuel et peut arroser PAR-DESSUS (double arrosage).
# Seul l'AFFICHAGE « dernière session détectée » garde une trace de ces arrosages (informatif).
_EXTERNAL_WATERING_SOURCES = ("zone_session",)


def _is_external_watering(item: dict[str, Any]) -> bool:
    return str(item.get("source") or "").strip().lower() in _EXTERNAL_WATERING_SOURCES


# Arrosages MANUELS lancés via l'intégration (bouton/carte/service start_manual_irrigation).
# Contrairement à l'externe, ils créditent bien la réserve sol (l'intégration sait exactement
# combien d'eau elle a délivrée). Mais ils NE doivent PAS compter dans le garde-fou hebdomadaire :
# celui-ci plafonne l'arrosage AUTO. Les compter créait un cercle vicieux (constaté 25/07/2026) :
# réserve à sec + budget déjà haut → auto bloqué → l'utilisateur arrose à la main → le manuel
# gonfle le budget → auto bloqué plus longtemps → … l'auto ne repartait jamais. Le manuel remplit
# la réserve, donc l'auto n'a de toute façon plus soif juste après : aucun sur-arrosage possible.
_MANUAL_WATERING_SOURCES = ("manual_irrigation", "manual_force", "manual_application")


def _is_manual_watering(item: dict[str, Any]) -> bool:
    return str(item.get("source") or "").strip().lower() in _MANUAL_WATERING_SOURCES


def compute_recent_watering_mm(
    history: list[dict[str, Any]],
    today: date | None = None,
    days: int = 2,
    include_external: bool = True,
    include_technical: bool = False,
    include_manual: bool = True,
) -> float:
    """Somme des mm arrosés sur la fenêtre.

    `include_technical=False` (défaut) = base du GARDE-FOU hebdomadaire : les arrosages
    techniques (rafraîchissement du soir, incorporation post-produit) en sont exclus.
    `include_technical=True` donne l'eau RÉELLEMENT reçue par le gazon — l'écart entre les deux
    est invisible autrement, ce qui a longtemps masqué un sur-arrosage.
    `include_manual=False` exclut les arrosages manuels : ils créditent la réserve mais ne
    plafonnent PAS l'auto (cf. `_is_manual_watering`). Défaut True = eau réellement reçue.
    """
    today = today or _current_date()
    total = 0.0
    for item in _iter_recent_watering_items(
        history,
        today=today,
        days=days,
        include_technical=include_technical,
        include_external=include_external,
        include_manual=include_manual,
    ):
        mm = _watering_item_mm(item)
        if mm is not None:
            total += float(mm)
    return total


def _iter_recent_watering_items(
    history: list[dict[str, Any]],
    today: date,
    days: int,
    include_technical: bool = True,
    include_external: bool = True,
    include_manual: bool = True,
):
    for item in history:
        if not isinstance(item, dict) or item.get("type") != "arrosage":
            continue
        if not include_technical and _is_technical_watering(item):
            continue
        if not include_external and _is_external_watering(item):
            continue
        if not include_manual and _is_manual_watering(item):
            continue
        raw_date = item.get("date")
        if not raw_date:
            continue
        try:
            d = date.fromisoformat(str(raw_date))
        except ValueError:
            continue
        delta = (today - d).days
        if delta < 0 or delta > days:
            continue
        if _watering_item_mm(item) is None:
            continue
        yield item


def compute_recent_watering_count(
    history: list[dict[str, Any]],
    today: date | None = None,
    days: int = 7,
    include_external: bool = True,
) -> int:
    today = today or _current_date()
    return sum(
        1
        for _ in _iter_recent_watering_items(
            history, today=today, days=days, include_external=include_external
        )
    )


def _effective_rain_mm(
    pluie_j: float,
    pluie_j1: float,
    pluie_j2: float,
    pluie_factor: float,
) -> float:
    return _round_half_up_1(
        (pluie_j * pluie_factor * _RAIN_HORIZON_WEIGHTS["today"])
        + (pluie_j1 * _RAIN_HORIZON_WEIGHTS["tomorrow"])
        + (pluie_j2 * _RAIN_HORIZON_WEIGHTS["day_after_tomorrow"])
    )


def _recent_watering_windows(
    history: list[dict[str, Any]],
    today: date,
    recent_watering_mm_override: float | None,
    retour_arrosage: float | None,
) -> dict[str, float]:
    # Garde-fou hebdo & modèle déficit : ne compter QUE les arrosages AUTO de l'intégration.
    # On exclut l'externe (`zone_session`) ET le manuel (`start_manual_irrigation`) : le garde-fou
    # plafonne l'arrosage AUTO, or un arrosage manuel est une décision de l'utilisateur. Les
    # compter créait un cercle vicieux (25/07/2026) : réserve à sec + budget haut → auto bloqué →
    # arrosage manuel de secours → budget plus haut → auto bloqué plus longtemps → jamais de reprise
    # auto. Le crédit de la RÉSERVE sol passe par un autre chemin (gazon_brain, `arrosage_reel_jour`)
    # et reste, lui, alimenté par TOUT l'arrosage réel — manuel inclus (l'eau est bien tombée).
    arrosage_recent_7j = (
        recent_watering_mm_override
        if recent_watering_mm_override is not None
        else compute_recent_watering_mm(
            history, today=today, days=7, include_external=False, include_manual=False
        )
    )
    # `days=0` = AUJOURD'HUI SEUL. Le filtre retient `delta <= days`, donc `days=1` ramassait
    # aussi la veille : le bilan journalier créditait alors 2 jours d'arrosage contre 1 seul jour
    # d'ET0 (`_horizon_balance(horizon_days=1)`) → bilan surestimé d'un arrosage entier (vu en
    # réel : 24 mm affichés pour 12 mm réellement appliqués). Le ledger sol, lui, utilise déjà
    # `days=0` (`arrosage_reel_jour`, cf. gazon_brain) : on s'aligne dessus. Les fenêtres 3j/7j
    # gardent leur sémantique (budget hebdo) et ne sont pas touchées.
    arrosage_recent_jour = compute_recent_watering_mm(
        history, today=today, days=0, include_external=False, include_manual=False
    )
    arrosage_recent_3j = compute_recent_watering_mm(
        history, today=today, days=3, include_external=False, include_manual=False
    )
    if retour_arrosage is not None:
        retour = float(retour_arrosage)
        arrosage_recent_jour = max(arrosage_recent_jour, retour)
        arrosage_recent_3j = max(arrosage_recent_3j, retour)
        arrosage_recent_7j = max(arrosage_recent_7j, retour)
    arrosage_recent_3j = max(arrosage_recent_3j, arrosage_recent_jour)
    arrosage_recent_7j = max(arrosage_recent_7j, arrosage_recent_3j)
    # Eau RÉELLEMENT reçue sur 7 j (arrosages techniques INCLUS). Diagnostic : `arrosage_recent_7j`
    # sert au garde-fou et exclut le technique — sans ce total, l'écart reste invisible.
    arrosage_applique_7j = max(
        arrosage_recent_7j,
        compute_recent_watering_mm(
            history, today=today, days=7, include_external=False, include_technical=True
        ),
    )
    if arrosage_recent_7j > 100:
        _LOGGER.warning("arrosage_recent_7j aberrant (%.1f mm), valeur clampée à 100 mm", arrosage_recent_7j)
        arrosage_recent_7j = 100.0
    arrosage_applique_7j = min(max(arrosage_applique_7j, arrosage_recent_7j), 150.0)
    return {
        "jour": arrosage_recent_jour,
        "3j": arrosage_recent_3j,
        "7j": arrosage_recent_7j,
        "applique_7j": arrosage_applique_7j,
    }


def _hydric_parameters(
    type_sol: str,
    advanced_context: dict[str, Any],
    phase_dominante: str | None,
) -> dict[str, float]:
    reserve_utile_mm = _SOIL_RESERVE_UTILE_MM.get(type_sol, _SOIL_RESERVE_UTILE_MM["limoneux"])
    soil_need_factor = float(advanced_context.get("soil_need_factor", advanced_context.get("soil_factor", 1.0)))
    soil_factor = (12.0 / reserve_utile_mm) * soil_need_factor
    soil_factor *= float(advanced_context.get("wind_factor", 1.0))
    soil_factor *= float(advanced_context.get("dew_factor", 1.0))
    mad_ratio = _PHASE_MAD_RATIO.get(str(phase_dominante or ""), 0.5)
    return {
        "reserve_utile_mm": reserve_utile_mm,
        "soil_factor": soil_factor,
        "mad_ratio": mad_ratio,
    }


def _soil_balance_priority(
    reserve_utile_mm: float,
    bilan_hydrique_mm: float,
    soil_balance: dict[str, Any] | None,
) -> dict[str, Any]:
    reserve_actuelle_source = None
    if isinstance(soil_balance, dict):
        reserve_actuelle_source = _to_float(soil_balance.get("reserve_mm"))
    # Réserve issue du bilan sol interne de l'intégration (ledger soil_balance, mis à jour
    # chaque cycle : réserve += pluie + arrosage − ET0, borné par type de sol). NB : c'est
    # l'ET0 de référence qui est soustraite, pas l'ETc (= ET0 × Kc gazon) — choix
    # conservateur (perte légèrement surestimée). Voir audit : appliquer le Kc recalibrerait
    # la déplétion.
    # Le pilotage par épuisement (MAD) n'est fiable que dans ce cas ; sinon la réserve
    # dérive du bilan court et n'atteint pas le seuil, d'où le repli sur le modèle déficit.
    reserve_from_soil_ledger = reserve_actuelle_source is not None
    if reserve_actuelle_source is None:
        reserve_actuelle_source = reserve_utile_mm + bilan_hydrique_mm
    reserve_stock_max_mm = _to_float(soil_balance.get("reserve_max_mm")) if isinstance(soil_balance, dict) else None
    if reserve_stock_max_mm is None:
        reserve_stock_max_mm = max(reserve_utile_mm, reserve_utile_mm * 2.0)
    reserve_stock_max_mm = max(reserve_utile_mm, float(reserve_stock_max_mm))
    return {
        "reserve_actuelle_source": float(reserve_actuelle_source),
        "reserve_stock_max_mm": reserve_stock_max_mm,
        "reserve_from_soil_ledger": reserve_from_soil_ledger,
    }


def _reserve_metrics(
    reserve_utile_mm: float,
    mad_ratio: float,
    reserve_actuelle_source: float,
    reserve_stock_max_mm: float,
) -> dict[str, float]:
    reserve_stock_mm = _bound(float(reserve_actuelle_source), 0.0, reserve_stock_max_mm)
    reserve_actuelle_mm = _bound(reserve_stock_mm, 0.0, reserve_utile_mm)
    depletion_allowed_mm = reserve_utile_mm * mad_ratio
    reserve_minimale_mm = reserve_utile_mm - depletion_allowed_mm
    depletion_mm = max(0.0, reserve_utile_mm - reserve_actuelle_mm)
    depletion_ratio = depletion_mm / reserve_utile_mm if reserve_utile_mm > 0 else 0.0
    reserve_surplus_mm = max(0.0, reserve_stock_mm - reserve_utile_mm)
    reserve_fill_ratio = reserve_stock_mm / reserve_stock_max_mm if reserve_stock_max_mm > 0 else 0.0
    reserve_available_ratio = reserve_actuelle_mm / reserve_utile_mm if reserve_utile_mm > 0 else 0.0
    return {
        "reserve_stock_mm": reserve_stock_mm,
        "reserve_actuelle_mm": reserve_actuelle_mm,
        "depletion_allowed_mm": depletion_allowed_mm,
        "reserve_minimale_mm": reserve_minimale_mm,
        "depletion_mm": depletion_mm,
        "depletion_ratio": depletion_ratio,
        "reserve_surplus_mm": reserve_surplus_mm,
        "reserve_fill_ratio": reserve_fill_ratio,
        "reserve_available_ratio": reserve_available_ratio,
    }


def _horizon_balance(
    etp_j: float,
    pluie_efficace: float,
    arrosage_mm: float,
    soil_factor: float,
    horizon_days: int,
) -> tuple[float, float]:
    weights = _BALANCE_HORIZON_WEIGHTS[horizon_days]
    deficit = max(0.0, ((etp_j * weights["etp"]) - (pluie_efficace * weights["rain"]) - arrosage_mm) * soil_factor)
    bilan = _round_half_up_1((pluie_efficace * weights["rain"] + arrosage_mm) - (etp_j * weights["etp"]))
    return deficit, bilan


def compute_advanced_context(
    humidite_sol: float | None = None,
    vent: float | None = None,
    rosee: float | None = None,
    hauteur_gazon: float | None = None,
    retour_arrosage: float | None = None,
    pluie_source: str = "capteur_pluie_24h",
    type_sol: str = "limoneux",
    weather_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    weather_profile = weather_profile or {}
    humidite_sol = _to_float(humidite_sol)
    vent = _to_float(vent)
    rosee = _to_float(rosee)
    hauteur_gazon = _to_float(hauteur_gazon)
    retour_arrosage = max(0.0, _to_float(retour_arrosage) or 0.0)
    soil_profile = _compute_soil_profile(
        type_sol=type_sol,
        humidite_sol=humidite_sol,
        vent=vent,
        rosee=rosee,
    )
    weather_precipitation_probability = _to_float(
        weather_profile.get("weather_precipitation_probability")
    )

    soil_factor = 1.0
    if humidite_sol is not None:
        if humidite_sol <= 25:
            soil_factor = 1.18
        elif humidite_sol <= 40:
            soil_factor = 1.08
        elif humidite_sol >= 80:
            soil_factor = 0.82
        elif humidite_sol >= 65:
            soil_factor = 0.92

    wind_factor = 1.0
    if vent is not None:
        if vent >= 25:
            wind_factor = 1.18
        elif vent >= 15:
            wind_factor = 1.10
        elif vent >= 8:
            wind_factor = 1.04

    dew_factor = 0.96 if rosee is not None and rosee > 0 else 1.0
    rain_factor = 0.85
    if weather_precipitation_probability is not None:
        if weather_precipitation_probability >= 80:
            rain_factor = 0.95
        elif weather_precipitation_probability >= 50:
            rain_factor = 0.9
        elif weather_precipitation_probability >= 20:
            rain_factor = 0.86
        else:
            rain_factor = 0.82
    if weather_profile.get("weather_condition") in {"rainy", "pouring"}:
        rain_factor = max(rain_factor, 0.95)

    return {
        "humidite_sol": humidite_sol,
        "vent": vent,
        "rosee": rosee,
        "hauteur_gazon": hauteur_gazon,
        "retour_arrosage": retour_arrosage if retour_arrosage > 0 else None,
        "pluie_source": pluie_source,
        "soil_factor": soil_factor,
        "soil_profile": soil_profile,
        "soil_retention_factor": soil_profile["retention_factor"],
        "soil_drainage_factor": soil_profile["drainage_factor"],
        "soil_infiltration_factor": soil_profile["infiltration_factor"],
        "soil_need_factor": soil_profile["need_factor"],
        "wind_factor": wind_factor,
        "dew_factor": dew_factor,
        "rain_factor": rain_factor,
        "weather_precipitation_probability": weather_precipitation_probability,
        "weather_temperature": weather_profile.get("weather_temperature"),
        "weather_apparent_temperature": weather_profile.get("weather_apparent_temperature"),
        "weather_humidity": weather_profile.get("weather_humidity"),
        "weather_wind_speed": weather_profile.get("weather_wind_speed"),
        "weather_pressure": weather_profile.get("weather_pressure"),
        "weather_cloud_coverage": weather_profile.get("weather_cloud_coverage"),
        "weather_dew_point": weather_profile.get("weather_dew_point"),
        "weather_uv_index": weather_profile.get("weather_uv_index"),
        "weather_condition": weather_profile.get("weather_condition"),
    }


def _ra_extraterrestrial(latitude_deg: float, day_of_year: int) -> float:
    """Rayonnement extraterrestre Ra (MJ/m²/j) — FAO-56 équation 21.

    Varie de ~12 MJ/m²/j en hiver à ~40 MJ/m²/j en été à 45°N.
    """
    lat = math.radians(float(latitude_deg))
    doy = max(1, min(365, int(day_of_year)))
    dr = 1.0 + 0.033 * math.cos(2.0 * math.pi * doy / 365.0)
    delta = 0.409 * math.sin(2.0 * math.pi * doy / 365.0 - 1.39)
    cos_ws = -math.tan(lat) * math.tan(delta)
    cos_ws = max(-1.0, min(1.0, cos_ws))
    ws = math.acos(cos_ws)
    Ra = (24.0 * 60.0 / math.pi) * 0.0820 * dr * (
        ws * math.sin(lat) * math.sin(delta)
        + math.cos(lat) * math.cos(delta) * math.sin(ws)
    )
    return max(0.0, Ra)


def compute_etp(
    temperature: float | None,
    pluie_24h: float | None,
    etp_capteur: float | None,
    temperature_reference_hydrique: float | None = None,
    weather_profile: dict[str, Any] | None = None,
    humidite: float | None = None,
    vent: float | None = None,
) -> float | None:
    """Estimation ET0 par Penman-Monteith simplifié (FAO-56) sans capteur dédié.

    Utilise la température, l'humidité, le vent et la couverture nuageuse
    disponibles dans le profil météo HA. Nettement plus précis que la formule
    empirique linéaire précédente, notamment en conditions estivales où
    l'ancienne formule sous-estimait l'ET0 d'un facteur 2 à 3.

    Le capteur dédié (etp_capteur) reste prioritaire s'il est configuré.
    """
    if etp_capteur is not None:
        return etp_capteur

    weather_profile = weather_profile or {}

    # Résolution de la température de référence
    if temperature_reference_hydrique is not None:
        temperature = temperature_reference_hydrique
    if temperature is None:
        temperature = weather_profile.get("weather_temperature")
    if temperature is None:
        temperature = weather_profile.get("weather_apparent_temperature")
    if temperature is None:
        return None
    temperature = float(temperature)

    # Priorité aux capteurs mesurés configurés (ex. Netatmo) → repli sur l'entité météo
    # (weather_profile) → repli sur les valeurs par défaut plus bas. Demandé par Kévin.
    humidity = humidite if humidite is not None else weather_profile.get("weather_humidity")
    wind = vent if vent is not None else weather_profile.get("weather_wind_speed")
    cloud = weather_profile.get("weather_cloud_coverage")
    uv_index = weather_profile.get("weather_uv_index")
    dew_point = weather_profile.get("weather_dew_point")

    # Pression de vapeur saturante (kPa)
    es = 0.6108 * math.exp(17.27 * temperature / (temperature + 237.3))

    # Pression de vapeur réelle (kPa) — point de rosée prioritaire sur humidité relative
    if dew_point is not None:
        ea = 0.6108 * math.exp(17.27 * float(dew_point) / (float(dew_point) + 237.3))
    elif humidity is not None:
        ea = es * max(0.0, min(1.0, float(humidity) / 100.0))
    else:
        ea = es * 0.60  # hypothèse conservative : 60 % HR

    vpd = max(0.0, es - ea)  # déficit de pression de vapeur (kPa)

    # Pente de la courbe pression de vapeur saturante (kPa/°C)
    delta = 4098.0 * es / (temperature + 237.3) ** 2

    # Constante psychrométrique (kPa/°C) à pression standard
    gamma = 0.067

    # Fraction de ciel dégagé — couverture nuageuse prioritaire, sinon UV
    if cloud is not None:
        sky_clear = max(0.2, 1.0 - float(cloud) / 100.0 * 0.80)
    elif uv_index is not None:
        sky_clear = max(0.2, min(1.0, float(uv_index) / 9.0))
    else:
        sky_clear = 0.55  # valeur médiane par défaut

    # Rayonnement net estimé (MJ/m²/j)
    # Si la latitude et le jour de l'année sont disponibles (injectés par le coordinator
    # depuis hass.config.latitude), on calcule Ra exactement selon FAO-56.
    # Sinon on utilise un proxy température valable en zone tempérée.
    ha_latitude = weather_profile.get("ha_latitude")
    ha_day_of_year = weather_profile.get("ha_day_of_year")
    if ha_latitude is not None and ha_day_of_year is not None:
        Ra_ref = _ra_extraterrestrial(float(ha_latitude), int(ha_day_of_year))
    else:
        Ra_ref = max(2.0, 0.5 * temperature + 2.0)
    Rns = 0.77 * sky_clear * 0.75 * Ra_ref   # rayonnement net courtes longueurs d'onde
    # Rayonnement net grandes longueurs d'onde sortant (FAO-56 éq. 39, simplifié) :
    # loi de Stefan-Boltzmann pondérée par l'humidité (ea) et la couverture nuageuse.
    # L'ancienne approximation (0.5 + 0.01*T ≈ 0.7 MJ/m²/j) sous-estimait Rnl d'un
    # facteur ~7, gonflant Rn et surestimant l'ET0 (~8 mm à 20 °C au lieu de ~5).
    sigma_tk4 = 4.903e-9 * (temperature + 273.16) ** 4
    emissivity_net = max(0.05, 0.34 - 0.14 * math.sqrt(max(0.0, ea)))
    cloud_factor = max(0.05, min(1.0, 1.35 * sky_clear - 0.35))
    Rnl = sigma_tk4 * emissivity_net * cloud_factor
    Rn = max(0.0, Rns - Rnl)

    # Vitesse du vent à 2 m, convertie en m/s (Penman-Monteith l'exige en m/s).
    # Les entités météo HA fournissent le vent en km/h par défaut ; l'utiliser tel
    # quel comme des m/s surestimait fortement le terme aérodynamique de l'ET0.
    if wind is not None:
        # Vent issu d'un capteur mesuré → on suppose km/h (unité standard des capteurs de
        # vent HA, ex. Netatmo) ; sinon on lit l'unité fournie par l'entité météo.
        wind_unit_raw = "km/h" if vent is not None else weather_profile.get("weather_wind_speed_unit")
        wind_unit = str(wind_unit_raw or "").strip().lower()
        wind_ms = float(wind)
        if wind_unit in ("mph", "mi/h"):
            wind_ms *= 0.44704
        elif wind_unit in ("m/s", "ms", "mps"):
            pass
        else:  # km/h (défaut des entités météo HA) ou unité inconnue
            wind_ms /= 3.6
        u2 = max(0.5, wind_ms)
    else:
        u2 = 1.5  # légère brise par défaut

    # Formule Penman-Monteith FAO-56 (mm/j)
    numerator = 0.408 * delta * Rn + gamma * (900.0 / (temperature + 273.0)) * u2 * vpd
    denominator = delta + gamma * (1.0 + 0.34 * u2)
    et0 = max(0.0, numerator / denominator) if denominator > 0 else 0.0

    # Légère réduction si pluie récente (sol frais, évaporation réduite)
    if pluie_24h and pluie_24h > 0:
        et0 *= max(0.85, 1.0 - float(pluie_24h) * 0.015)

    return round(et0, 1)


def compute_water_balance(
    history: list[dict[str, Any]],
    today: date | None = None,
    etp: float | None = None,
    pluie_24h: float | None = None,
    pluie_demain: float | None = None,
    pluie_j2: float | None = None,
    type_sol: str = "limoneux",
    recent_watering_mm_override: float | None = None,
    advanced_context: dict[str, Any] | None = None,
    weather_profile: dict[str, Any] | None = None,
    soil_balance: dict[str, Any] | None = None,
    phase_dominante: str | None = None,
) -> dict[str, Any]:
    today = today or _current_date()
    advanced_context = advanced_context or {}
    weather_profile = weather_profile or {}
    etp_j = max(0.0, etp or 0.0)
    pluie_j = max(0.0, pluie_24h or 0.0)
    pluie_j1 = max(0.0, pluie_demain or 0.0)
    pluie_j2 = max(0.0, pluie_j2 or 0.0)
    pluie_source = advanced_context.get("pluie_source", "capteur_pluie_24h")
    hydric_params = _hydric_parameters(
        type_sol=type_sol,
        advanced_context=advanced_context,
        phase_dominante=phase_dominante,
    )
    reserve_utile_mm = hydric_params["reserve_utile_mm"]
    soil_factor = hydric_params["soil_factor"]
    mad_ratio = hydric_params["mad_ratio"]

    pluie_factor = float(advanced_context.get("rain_factor", 0.85))
    pluie_efficace = _effective_rain_mm(pluie_j=pluie_j, pluie_j1=pluie_j1, pluie_j2=pluie_j2, pluie_factor=pluie_factor)
    recent_watering = _recent_watering_windows(
        history=history,
        today=today,
        recent_watering_mm_override=recent_watering_mm_override,
        retour_arrosage=advanced_context.get("retour_arrosage"),
    )
    arrosage_recent_jour = recent_watering["jour"]
    arrosage_recent_3j = recent_watering["3j"]
    arrosage_recent_7j = recent_watering["7j"]

    deficit_jour, bilan_hydrique_mm = _horizon_balance(
        etp_j=etp_j,
        pluie_efficace=pluie_efficace,
        arrosage_mm=arrosage_recent_jour,
        soil_factor=soil_factor,
        horizon_days=1,
    )
    deficit_3j, bilan_hydrique_3j = _horizon_balance(
        etp_j=etp_j,
        pluie_efficace=pluie_efficace,
        arrosage_mm=arrosage_recent_3j,
        soil_factor=soil_factor,
        horizon_days=3,
    )
    deficit_7j, bilan_hydrique_7j = _horizon_balance(
        etp_j=etp_j,
        pluie_efficace=pluie_efficace,
        arrosage_mm=arrosage_recent_7j,
        soil_factor=soil_factor,
        horizon_days=7,
    )
    soil_balance_priority = _soil_balance_priority(
        reserve_utile_mm=reserve_utile_mm,
        bilan_hydrique_mm=bilan_hydrique_mm,
        soil_balance=soil_balance,
    )
    reserve_metrics = _reserve_metrics(
        reserve_utile_mm=reserve_utile_mm,
        mad_ratio=mad_ratio,
        reserve_actuelle_source=soil_balance_priority["reserve_actuelle_source"],
        reserve_stock_max_mm=soil_balance_priority["reserve_stock_max_mm"],
    )

    # --- Réserve AFFICHÉE = réserve de DÉCISION (anti-incohérence) ----------------------
    # Choix Kévin (25/06/2026) : la jauge de la carte affiche EXACTEMENT la réserve sur
    # laquelle l'intégration DÉCIDE d'arroser. L'ancien « lissage » (réserve de décision + ET
    # du jour, plafonné au plein utile) gonflait la jauge à « plein » le matin alors que la
    # décision pouvait être « a soif » → la carte contredisait le cerveau (cas vécu : décision
    # 2,2 mm « soif » mais affichage 10,4 mm « pas soif »). On affiche donc la vraie réserve de
    # décision : elle évolue déjà au fil de la journée → la jauge bouge sans jamais mentir. Le
    # cas « recalage manuel » donne le même résultat (la valeur ancrée EST la réserve de décision).
    _fraction_raw = _to_float(weather_profile.get("et_elapsed_fraction"))
    et_elapsed_fraction = _bound(_fraction_raw if _fraction_raw is not None else 1.0, 0.0, 1.0)  # exposé (diagnostic)
    reserve_actuelle_affichee = reserve_metrics["reserve_actuelle_mm"]
    reserve_stock_affichee = reserve_metrics["reserve_stock_mm"]
    depletion_affichee_mm = max(0.0, reserve_utile_mm - reserve_actuelle_affichee)
    depletion_ratio_affiche = _bound(depletion_affichee_mm / reserve_utile_mm, 0.0, 1.0) if reserve_utile_mm > 0 else 0.0

    return {
        "et0_mm": _round_half_up_1(max(0.0, etp_j)),
        "bilan_hydrique_mm": bilan_hydrique_mm,
        "bilan_hydrique_3j": bilan_hydrique_3j,
        "bilan_hydrique_7j": bilan_hydrique_7j,
        "deficit_jour": _round_half_up_1(deficit_jour),
        "deficit_3j": _round_half_up_1(deficit_3j),
        "deficit_7j": _round_half_up_1(deficit_7j),
        "pluie_efficace": pluie_efficace,
        "pluie_j2": pluie_j2,
        "arrosage_recent": _round_half_up_1(arrosage_recent_7j),
        "arrosage_applique_7j": _round_half_up_1(recent_watering["applique_7j"]),
        "arrosage_recent_jour": _round_half_up_1(arrosage_recent_jour),
        "arrosage_recent_3j": _round_half_up_1(arrosage_recent_3j),
        "arrosage_recent_7j": _round_half_up_1(arrosage_recent_7j),
        "pluie_source": pluie_source,
        "weather_precipitation_probability": weather_profile.get("weather_precipitation_probability"),
        "humidite_sol": advanced_context.get("humidite_sol"),
        "vent": advanced_context.get("vent"),
        "rosee": advanced_context.get("rosee"),
        "hauteur_gazon": advanced_context.get("hauteur_gazon"),
        "retour_arrosage": advanced_context.get("retour_arrosage"),
        "reserve_utile_mm": _round_half_up_1(reserve_utile_mm),
        "reserve_stock_mm": _round_half_up_1(reserve_metrics["reserve_stock_mm"]),
        "reserve_stock_max_mm": _round_half_up_1(soil_balance_priority["reserve_stock_max_mm"]),
        "reserve_from_soil_ledger": bool(soil_balance_priority["reserve_from_soil_ledger"]),
        "reserve_surplus_mm": _round_half_up_1(reserve_metrics["reserve_surplus_mm"]),
        "reserve_actuelle_mm": _round_half_up_1(reserve_metrics["reserve_actuelle_mm"]),
        "reserve_fill_ratio": round(_bound(reserve_metrics["reserve_fill_ratio"], 0.0, 1.0), 3),
        "reserve_available_ratio": round(_bound(reserve_metrics["reserve_available_ratio"], 0.0, 1.0), 3),
        "mad_ratio": round(_bound(mad_ratio, 0.0, 1.0), 2),
        "depletion_allowed_mm": _round_half_up_1(reserve_metrics["depletion_allowed_mm"]),
        "reserve_minimale_mm": _round_half_up_1(reserve_metrics["reserve_minimale_mm"]),
        "depletion_mm": _round_half_up_1(reserve_metrics["depletion_mm"]),
        "depletion_ratio": round(_bound(reserve_metrics["depletion_ratio"], 0.0, 1.0), 3),
        # Champs d'AFFICHAGE (réserve à descente progressive) — non utilisés par la décision.
        "et_elapsed_fraction": round(et_elapsed_fraction, 3),
        "reserve_actuelle_affichee_mm": _round_half_up_1(reserve_actuelle_affichee),
        "reserve_stock_affichee_mm": _round_half_up_1(reserve_stock_affichee),
        "depletion_affichee_mm": _round_half_up_1(depletion_affichee_mm),
        "depletion_ratio_affiche": round(depletion_ratio_affiche, 3),
        "soil_factor": _round_half_up_1(soil_factor),
        "soil_profile": advanced_context.get("soil_profile"),
        "soil_retention_factor": advanced_context.get("soil_retention_factor"),
        "soil_drainage_factor": advanced_context.get("soil_drainage_factor"),
        "soil_infiltration_factor": advanced_context.get("soil_infiltration_factor"),
        "soil_need_factor": advanced_context.get("soil_need_factor"),
    }
