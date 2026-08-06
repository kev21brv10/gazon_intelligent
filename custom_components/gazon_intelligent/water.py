from __future__ import annotations

import math
from collections.abc import Callable
from datetime import date, datetime, time, timezone
from typing import Any
import logging

_LOGGER = logging.getLogger(__name__)

try:
    from homeassistant.util import dt as dt_util
except Exception:  # pragma: no cover - standalone fallback
    dt_util = None


# ─────────────────────────────────────────────────────────────────────────────────────────
# Horodatage d'une entrée d'historique — SOURCE UNIQUE, partagée arrosage ↔ tonte.
#
# Avant le 29/07/2026, les deux sous-systèmes dataient le MÊME arrosage différemment : la tonte
# retombait sur 06:00, l'arrosage sur 00:00, et seul le premier lisait `declared_at`. Un arrosage
# déclaré à la main (date seule) se retrouvait à 6 h d'écart selon qui le regardait.
#
# Arbitrage de Kévin : « le déclarer à l'heure où l'arrosage a été déclaré ». `declared_at` porte
# justement cet instant (écrit par gazon_brain lors de l'appel au service). On l'utilise donc —
# MAIS uniquement s'il tombe le jour déclaré : sur une déclaration rétroactive (« j'ai arrosé
# avant-hier »), l'instant de déclaration désigne aujourd'hui et daterait l'arrosage du mauvais
# jour. C'était le défaut du côté tonte, qui plaçait `declared_at` avant la date.
# ─────────────────────────────────────────────────────────────────────────────────────────

# Horodatages POSÉS PAR LA MACHINE : exacts, prioritaires, jamais réinterprétés.
_HISTORY_EXACT_MOMENT_FIELDS: tuple[str, ...] = (
    "ended_at",
    "started_at",
    "recorded_at",
    "detected_at_utc",
    "detected_at",
    "triggered_at",
    "last_watering_when",
)

# Heure retenue pour une entrée qui n'a QUE sa date, sans instant de déclaration exploitable.
# 06:00 et non minuit : la règle de Kévin est d'arroser à l'aube, un arrosage déclaré sans heure
# a donc eu lieu le matin. Repli plus proche du réel — et plus prudent sur le cooldown 24 h.
HISTORY_DATE_ONLY_FALLBACK_HOUR = 6


def _parse_history_moment_value(value: Any) -> datetime | None:
    """Parse un horodatage d'historique en UTC. Naïf → supposé UTC."""
    if value in (None, "", [], {}):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _history_declared_date(item: dict[str, Any]) -> date | None:
    """Date déclarée d'une entrée (`date_action` prioritaire sur `date`)."""
    for key in ("date_action", "date"):
        raw = item.get(key)
        if not raw:
            continue
        text = str(raw).strip()
        if not text:
            continue
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            continue
    return None


def resolve_history_moment(
    item: dict[str, Any],
    *,
    fallback_hour: int = HISTORY_DATE_ONLY_FALLBACK_HOUR,
) -> datetime | None:
    """Meilleur instant UTC pour une entrée d'historique, ou None si elle n'est pas datable.

    Ordre : horodatage machine exact → heure de déclaration si elle tombe le jour déclaré →
    date déclarée à `fallback_hour`.
    """
    if not isinstance(item, dict):
        return None

    for field in _HISTORY_EXACT_MOMENT_FIELDS:
        parsed = _parse_history_moment_value(item.get(field))
        if parsed is not None:
            return parsed

    declared_date = _history_declared_date(item)
    declared_at = _parse_history_moment_value(item.get("declared_at"))

    if declared_at is not None:
        # Déclaration du jour même → son heure est la meilleure approximation disponible.
        if declared_date is None or declared_at.date() == declared_date:
            return declared_at
        # Déclaration rétroactive → on garde la DATE déclarée, pas l'instant de saisie.

    if declared_date is None:
        return None
    return datetime.combine(
        declared_date, time(fallback_hour % 24, 0), tzinfo=timezone.utc
    )


# JUMEAU : soil_balance.SOIL_RESERVE_BASE_MM — même réserve utile du sol par type de sol.
# Les deux modules sont volontairement découplés (pas d'import croisé), on garde donc les deux
# tables identiques à la main (cf. tests/test_soil_balance.py::TestSoilReserveTwins).
_SOIL_RESERVE_UTILE_MM: dict[str, float] = {
    "sableux": 8.0,
    "limoneux": 12.0,
    "argileux": 16.0,
}

# FRACTION D'ÉPUISEMENT FAO-56 (p) POUR LA PHASE NORMAL.
# `p` est la part du STOCK TOTAL (TAW) qu'on laisse partir avant d'arroser. La FAO-56 donne
# p = 0,40 pour un gazon de saison fraîche, ET fournit un ajustement à la demande du jour :
#
#     p = p_table + 0,04 × (5 − ETc)
#
# Plus il fait chaud, plus `p` DESCEND : sous forte évapotranspiration, la plante souffre avant
# d'avoir épuisé la même fraction. C'est ce que ne peut pas faire un seuil figé.
# Adopté le 29/07/2026 (arbitrage de Kévin) : l'ancien calcul empilait deux réductions —
# `stock × 0,5 → réserve utile × MAD 0,5` — soit 0,25 du stock, nettement en deçà de la
# référence, et sans lien avec les conditions du jour. Mesuré à ce moment-là : 6 mm autorisés
# contre 9 mm selon la FAO à l'ETc réelle, et 12,6 mm tolérés par le régime manuel éprouvé.
# ⚠️ PAS ENCORE BRANCHÉE — et voici pourquoi. La FAO mesure la déplétion depuis la CAPACITÉ AU
# CHAMP. Ce modèle-ci mesure la sienne depuis la réserve utile : tout stock au-dessus de 12 mm
# compte comme déplétion NULLE (vérifié : stock 24, 18, 15 et 12 donnent tous 0). Le sol travaille
# donc entre 6 et 12 mm sur un stock de 24, soit 25 à 50 % de la capacité — là où la FAO
# déclencherait à un stock de 15 mm. Les deux « déplétions » ne désignent pas la même grandeur, et
# poser `p × stock` comme seuil revenait à comparer des choux et des carottes.
# Brancher la FAO proprement suppose de changer AUSSI la cible de recharge (remplir vers la
# capacité au champ, pas vers 12) — donc la dose, qui passerait de ~6 à ~9-12 mm par apport.
# C'est cohérent avec le régime manuel éprouvé de Kévin (9-10 mm), mais ça demande de savoir si le
# sol tient et restitue réellement ses 24 mm aux racines : c'est la mesure au tournevis.
# Bornes FAO : p reste dans [0,1 ; 0,8].
# JUMEAU : const.KC_GAZON_NORMAL_DEFAUT — ce module est volontairement découplé (aucun import
# croisé, cf. l'en-tête), la valeur est donc recopiée et doit rester identique à la main.
_KC_GAZON_NORMAL = 0.8

FAO_P_TABLE_GAZON = 0.40
FAO_P_MIN, FAO_P_MAX = 0.1, 0.8

# Les AUTRES phases gardent leur ratio explicite, appliqué à la réserve utile : ce sont des
# consignes agronomiques délibérées (semis arrosé plus souvent, hivernage plus tolérant), pas
# des approximations de la FAO. Ne pas les basculer sans raison propre.
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


# RAFRAÎCHISSEMENT DU SOIR : ~3 mm pulvérisés pour faire baisser la température du gazon en
# canicule. Cette eau s'évapore pour l'essentiel — c'est son but — et ne recharge donc PAS la
# réserve. L'inclure ferait paraître le sol plus plein qu'il ne l'est, cause connue d'un gazon
# qui sèche en pleine canicule.
_COOLING_WATERING_CAUSES = ("rafraichissement_soir",)

# INCORPORATION POST-PRODUIT : 5 à 10 mm dont le BUT EST de faire pénétrer le produit dans le sol
# (fertigation). Cette eau atteint donc bien la zone racinaire.
# Décision de Kévin (29/07/2026) : elle CRÉDITE désormais la réserve. Ne pas la compter la
# sous-estimait de la dose d'incorporation, ce qui provoquait une recharge inutile le lendemain
# matin — en silence. Le motif historique (« les arrosages techniques ne rechargent pas ») reste
# vrai pour les 3 mm de rafraîchissement, il ne l'était pas pour 8 mm d'incorporation.
# Elle reste en revanche HORS du garde-fou hebdomadaire : celui-ci borne la recharge hydrique
# délibérée, et un produit ne doit pas grignoter le budget d'arrosage du gazon.
_INCORPORATION_WATERING_CAUSES = ("post_application",)

_TECHNICAL_WATERING_CAUSES = _COOLING_WATERING_CAUSES + _INCORPORATION_WATERING_CAUSES


def _is_technical_watering(item: dict[str, Any]) -> bool:
    return str(item.get("watering_cause") or "").strip().lower() in _TECHNICAL_WATERING_CAUSES


def _is_incorporation_watering(item: dict[str, Any]) -> bool:
    return str(item.get("watering_cause") or "").strip().lower() in _INCORPORATION_WATERING_CAUSES


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
    include_incorporation: bool = False,
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
        include_incorporation=include_incorporation,
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
    include_incorporation: bool = False,
):
    for item in history:
        if not isinstance(item, dict) or item.get("type") != "arrosage":
            continue
        if not include_technical and _is_technical_watering(item):
            # `include_incorporation` rouvre la seule incorporation post-produit : elle pénètre
            # le sol, contrairement au rafraîchissement du soir qui s'évapore.
            if not (include_incorporation and _is_incorporation_watering(item)):
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
    include_manual: bool = True,
) -> int:
    """Nombre d'arrosages sur la fenêtre demandée.

    ⚠️ `include_manual` a été ajouté pour que le garde-fou hebdomadaire puisse compter la MÊME
    chose que le budget en millimètres. Voir `_recent_watering_totals` : le manuel y est exclu
    depuis le 25/07/2026 parce que le compter créait un cercle vicieux — réserve à sec → auto
    bloqué → arrosage manuel de secours → budget plus haut → auto bloqué plus longtemps. Le
    compteur, lui, n'avait pas de quoi l'exclure : le cercle pouvait donc se refermer par cette
    porte-là, un arrosage manuel réarmant le blocage qu'il venait de contourner.
    """
    today = today or _current_date()
    return sum(
        1
        for _ in _iter_recent_watering_items(
            history,
            today=today,
            days=days,
            include_external=include_external,
            include_manual=include_manual,
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
    # Le garde-fou hebdo a besoin de la VRAIE somme 7 j de l'arrosage AUTO : on la calcule
    # TOUJOURS depuis l'historique. `recent_watering_mm_override` / `retour_arrosage` (l'arrosage
    # du JOUR, parfois pas encore dans l'historique) ne servent que de PLANCHER, jamais de
    # remplacement — sinon l'arrosage du jour ÉCRASE la somme des 6 jours précédents (budget hebdo
    # faux, garde-fou trop permissif ; constaté 28/07/2026 : 12 mm décomptés au lieu de 36).
    arrosage_recent_7j = compute_recent_watering_mm(
        history, today=today, days=6, include_external=False, include_manual=False
    )
    # `days=0` = AUJOURD'HUI SEUL. Le filtre retient `delta <= days`, donc `days=1` ramassait
    # aussi la veille : le bilan journalier créditait alors 2 jours d'arrosage contre 1 seul jour
    # d'ET0 (`_horizon_balance(horizon_days=1)`) → bilan surestimé d'un arrosage entier (vu en
    # réel : 24 mm affichés pour 12 mm réellement appliqués). Le ledger sol, lui, utilise déjà
    # `days=0` (`arrosage_reel_jour`, cf. gazon_brain) : on s'aligne dessus. Les fenêtres 3j/7j
    # suivent la MÊME règle : `days=N` retient `delta <= N`, soit N+1 jours calendaires. Pour une
    # vraie fenêtre de K jours il faut donc `days = K-1` → jour=0, 3j=2, 7j=6. (Auparavant 3j/7j
    # passaient days=3/7 = 4/8 jours : le garde-fou hebdo gardait un arrosage un jour de trop
    # dans le décompte — le budget mettait un jour de plus à retomber sous le plafond.)
    arrosage_recent_jour = compute_recent_watering_mm(
        history, today=today, days=0, include_external=False, include_manual=False
    )
    arrosage_recent_3j = compute_recent_watering_mm(
        history, today=today, days=2, include_external=False, include_manual=False
    )
    # PLANCHER (jamais un plafond) : l'arrosage du jour peut ne pas encore figurer dans
    # l'historique — on garantit qu'il est au moins compté. `recent_watering_mm_override` (capteur
    # « retour arrosage » externe) et `retour_arrosage` désignent la même eau du jour ; on prend le
    # max des deux, sans jamais RÉDUIRE la somme calculée depuis l'historique.
    retour_floor = max(
        (float(v) for v in (retour_arrosage, recent_watering_mm_override) if v is not None),
        default=0.0,
    )
    if retour_floor > 0.0:
        arrosage_recent_jour = max(arrosage_recent_jour, retour_floor)
        arrosage_recent_3j = max(arrosage_recent_3j, retour_floor)
        arrosage_recent_7j = max(arrosage_recent_7j, retour_floor)
    arrosage_recent_3j = max(arrosage_recent_3j, arrosage_recent_jour)
    arrosage_recent_7j = max(arrosage_recent_7j, arrosage_recent_3j)
    # Eau RÉELLEMENT reçue sur 7 j (arrosages techniques INCLUS). Diagnostic : `arrosage_recent_7j`
    # sert au garde-fou et exclut le technique — sans ce total, l'écart reste invisible.
    arrosage_applique_7j = max(
        arrosage_recent_7j,
        compute_recent_watering_mm(
            history, today=today, days=6, include_external=False, include_technical=True
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
    # Réserve issue du bilan sol interne de l'intégration (ledger soil_balance, mis à jour chaque
    # cycle : réserve += pluie + arrosage − ET consommée, borné par type de sol).
    # ⚠️ Ce commentaire affirmait le contraire jusqu'au 28/07/2026 (« c'est l'ET0 qui est
    # soustraite, pas l'ETc — choix conservateur »). C'est FAUX depuis la 0.17.3 : le ledger
    # débite bien l'**ETc** (= ET0 × Kc, cf. gazon_brain), et depuis la 0.19.0 il intègre même le
    # taux HORAIRE mesuré au fil du temps. Ne pas « re-corriger » en réappliquant un Kc ici : il
    # serait compté deux fois.
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



def fao_depletion_fraction(etc_mm: float | None, p_table: float = FAO_P_TABLE_GAZON) -> float:
    """Fraction d'épuisement FAO-56 ajustée à la demande du jour : p = p_table + 0,04 × (5 − ETc).

    Sans ETc connue, on rend la valeur de table — pas d'ajustement inventé sur une donnée absente.
    """
    if etc_mm is None:
        return p_table
    try:
        etc = float(etc_mm)
    except (TypeError, ValueError):
        return p_table
    return _bound(p_table + 0.04 * (5.0 - etc), FAO_P_MIN, FAO_P_MAX)


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


def estimate_days_until_watering(
    reserve_actuelle_mm: float | None,
    reserve_minimale_mm: float | None,
    etc_mm: float | None,
) -> int | None:
    """Estimation indicative du nombre de jours avant le prochain arrosage.

    Modèle simple et volontairement conservateur : la réserve du sol baisse d'~ETc par
    jour (le sol perd son eau au rythme de l'herbe — cf. ledger débité en ETc), et
    l'arrosage se déclenche quand elle atteint le seuil MAD (``reserve_minimale_mm``).
    Renvoie le nombre de jours estimé avant d'atteindre ce seuil :

      * ``0``    → réserve déjà au seuil (arrosage imminent) ;
      * ``n``    → il reste ``n`` jour(s) de séchage estimés ;
      * ``None`` → non calculable (séchage négligeable/inconnu ou données manquantes).

    Purement indicatif : la météo réelle des prochains jours (pluie, chaleur) n'est pas
    connue, donc la pluie prévue n'est PAS déduite ici — l'estimation se recale d'elle-même
    à chaque cycle. Cette valeur n'entre dans AUCUNE décision d'arrosage : affichage seul.

    Le déclenchement réel se fait à l'AUBE sur la déplétion PROJETÉE en fin de journée
    (``déplétion + ETc restant à s'écouler ≥ seuil MAD``, cf. ``guidance._profile_for_normal``) :
    l'arrosage part donc le matin du jour où la réserve VA franchir le seuil, pas le lendemain.
    Sans en tenir compte, l'estimation annonçait « demain » le matin même où l'arrosage partait.
    On retranche donc une journée de séchage à la marge disponible.
    """
    reserve = _to_float(reserve_actuelle_mm)
    mad = _to_float(reserve_minimale_mm)
    rate = _to_float(etc_mm)
    if reserve is None or mad is None or rate is None:
        return None
    if rate <= 0.1:
        return None  # séchage négligeable → pas d'échéance estimable
    # `- rate` = la journée qui déclenche : dès que la réserve passe sous « seuil + 1 jour d'ETc »,
    # la projection d'aube franchit le seuil MAD dès le lendemain matin.
    mm_avant_mad = reserve - mad - rate
    if mm_avant_mad <= 0.0:
        return 0  # la projection d'aube franchit déjà le seuil → arrosage imminent
    return int(math.ceil(mm_avant_mad / rate))


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


def wind_speed_to_ms(wind: float, unit: str | None) -> float:
    """Vitesse de vent → m/s (Penman-Monteith l'exige en m/s), plancher 0,5 m/s.

    Les entités météo Home Assistant fournissent le plus souvent des km/h, mais pas toujours :
    utiliser une valeur en m/s telle quelle (ou la diviser par 3,6 à tort) fausse fortement le
    terme aérodynamique. On lit donc l'unité déclarée, avec repli km/h (défaut HA) si elle est
    absente ou inconnue. Partagé par l'ET0 JOURNALIÈRE et l'ET0 HORAIRE : les deux doivent
    normaliser de la même façon, sans quoi le bilan sol et les seuils divergent.
    """
    unit_norm = str(unit or "").strip().lower()
    wind_ms = float(wind)
    if unit_norm in ("mph", "mi/h"):
        wind_ms *= 0.44704
    elif unit_norm in ("m/s", "ms", "mps"):
        pass
    else:  # km/h (défaut des entités météo HA) ou unité inconnue
        wind_ms /= 3.6
    return max(0.5, wind_ms)


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
        u2 = wind_speed_to_ms(wind, wind_unit_raw)
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


# ---------------------------------------------------------------------------
# ET0 HORAIRE — FAO-56 Penman-Monteith pas de temps horaire (Eq. 53)
# Port fidèle de la chaîne template `eto_fao56.yaml` (station Netatmo + rayonnement
# Open-Meteo). Contrairement à `compute_etp` (ET0 JOURNALIÈRE estimée depuis un
# instantané + radiation ciel-clair), ces fonctions calculent un TAUX horaire
# (mm/h) à partir de la radiation RÉELLE mesurée → destiné à être accumulé par le
# ledger sol (fin de l'extrapolation « pic d'après-midi » et de la falaise de minuit).
# Source de vérité : templates/eto_fao56.yaml (validé le 28/07/2026).
# ---------------------------------------------------------------------------
def _ra_hourly(
    latitude: float, longitude: float, day_of_year: int, hour_utc: float
) -> float:
    """Rayonnement extraterrestre horaire Ra (MJ/m²/h) — FAO-56 Eq. 28.

    100 % astronomique (aucune dépendance capteur). `hour_utc` = heure décimale UTC
    (le calcul en UTC évite le piège de l'heure d'été). Sert de plafond physique et
    de base au ciel clair Rso.
    """
    phi = math.radians(latitude)
    j = int(day_of_year)
    dr = 1.0 + 0.033 * math.cos(2 * math.pi * j / 365)
    dec = 0.409 * math.sin(2 * math.pi * j / 365 - 1.39)
    b = 2 * math.pi * (j - 81) / 364
    sc = 0.1645 * math.sin(2 * b) - 0.1255 * math.cos(b) - 0.025 * math.sin(b)
    w = (math.pi / 12) * ((hour_utc + 0.06667 * longitude + sc) - 12)
    ra = (
        (12 * 60 / math.pi)
        * 0.0820
        * dr
        * (
            (math.pi / 12) * math.sin(phi) * math.sin(dec)
            + math.cos(phi)
            * math.cos(dec)
            * (math.sin(w + math.pi / 24) - math.sin(w - math.pi / 24))
        )
    )
    return max(ra, 0.0)


def _rs_hourly(
    ra: float,
    radiation_wm2: float | None,
    cloud_pct: float | None,
    rso_factor: float = 0.7524,
) -> tuple[float, float]:
    """Rayonnement global horaire Rs (MJ/m²/h) + ratio Rs/Rso (pour Rnl).

    Priorité 1 : radiation mesurée `radiation_wm2` (W/m² → × 0.0036).
    Priorité 2 : Rso × facteur nuages (Kasten-Czeplak) si pas de radiation.
    Plafond d'absurdité 0.85·Ra (et NON Rso : transmissivité réelle d'un ciel sec
    ~0.80-0.82, cf. template). `rso_factor` dépend de l'altitude (0.7524 à 120 m).
    """
    rso = rso_factor * ra
    n = min(max(cloud_pct if cloud_pct is not None else 50.0, 0.0), 100.0) / 100.0
    r_nu = min(max(1.0 - 0.75 * (n**3.4), 0.15), 1.0)
    if radiation_wm2 is not None and radiation_wm2 >= 0:
        rs = radiation_wm2 * 0.0036
    else:
        rs = rso * r_nu
    rs = min(max(rs, 0.0), 0.85 * ra)
    if radiation_wm2 is not None and radiation_wm2 >= 0 and rso > 0.01:
        ratio = min(max(rs / rso, 0.15), 1.0)
    else:
        ratio = r_nu
    return rs, ratio


def compute_eto_hourly(
    temperature: float,
    humidity: float,
    pressure_hpa: float,
    wind_kmh: float,
    radiation_wm2: float | None,
    cloud_pct: float | None,
    latitude: float,
    longitude: float,
    day_of_year: int,
    hour_utc: float,
    rso_factor: float = 0.7524,
    wind_unit: str | None = None,
) -> float:
    """ET0 de référence HORAIRE (mm/h) — FAO-56 Penman-Monteith Eq. 53.

        ETo = [0.408·Δ·(Rn−G) + γ·37/(T+273)·u2·(es−ea)] / [Δ + γ·(1 + 0.34·u2)]

    γ = 0.000665·P (pression mesurée), Rns = 0.77·Rs, Rnl via σ horaire (2.04e-10),
    G = 0.1·Rn le jour / 0.5·Rn la nuit. Albédo 0.23 (gazon de référence).
    Port fidèle de `sensor.eto_horaire` (templates/eto_fao56.yaml).
    """
    ra = _ra_hourly(latitude, longitude, day_of_year, hour_utc)
    rs, ratio = _rs_hourly(ra, radiation_wm2, cloud_pct, rso_factor)
    t = float(temperature)
    rh = min(max(float(humidity), 1.0), 100.0)
    p_kpa = float(pressure_hpa) / 10.0
    # `wind_kmh` porte le nom de l'unité ATTENDUE (km/h, défaut HA), mais l'entité météo peut
    # publier des m/s ou des mph : on normalise comme l'ET0 journalière. Sans ça, un vent en m/s
    # était divisé par 3,6 en trop → ET0 horaire sous-estimée d'environ 12 %, donc un sol qui
    # paraît sécher trop lentement (ce taux pilote le ledger depuis la 0.19.0).
    u2 = wind_speed_to_ms(wind_kmh, wind_unit)
    es = 0.6108 * math.exp(17.27 * t / (t + 237.3))
    ea = es * rh / 100.0
    delta = 4098.0 * es / ((t + 237.3) ** 2)
    gamma = 0.000665 * p_kpa
    rns = 0.77 * rs
    rnl = (
        2.04e-10
        * ((t + 273.16) ** 4)
        * max(0.34 - 0.14 * math.sqrt(ea), 0.0)
        * max(1.35 * ratio - 0.35, 0.05)
    )
    rn = rns - rnl
    g_flux = 0.1 * rn if ra > 0 else 0.5 * rn
    numerator = 0.408 * delta * (rn - g_flux) + gamma * (37.0 / (t + 273.0)) * u2 * (es - ea)
    denominator = delta + gamma * (1.0 + 0.34 * u2)
    if denominator <= 0:
        return 0.0
    result = numerator / denominator
    # `max(nan, 0.0)` renvoie nan (Python garde le premier argument) : un capteur publiant `nan`
    # propagerait un taux NaN jusqu'au ledger, où il serait converti en 0 et GÈLERAIT le débit
    # de la réserve en silence. On renvoie 0.0, que l'appelant traite comme « pas de mesure ».
    if not math.isfinite(result):
        return 0.0
    return max(result, 0.0)


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
    # ⚠️ ET0 INCONNUE ≠ ET0 NULLE. `etp or 0.0` écrase l'absence en zéro, et TOUS les déficits
    # qui en découlent tombent alors à 0 — un « pas de besoin » indiscernable d'un vrai. C'est
    # ce qui se produit au premier cycle après un redémarrage (capteur de température pas encore
    # là) et à chaque coupure du capteur : mesuré le 01/08/2026, `bilan_hydrique_mm: 0`,
    # `deficit_3j: 0`, `deficit_7j: 0` alors que la déplétion du ledger valait 8,2 mm. On garde
    # le repli à 0 pour le calcul (il n'y a rien de mieux), mais on PUBLIE l'incertitude.
    etp_connue = etp is not None
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
        # Faux ⇒ les déficits ci-dessous valent 0 par DÉFAUT, pas par mesure.
        "etp_connue": etp_connue,
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
