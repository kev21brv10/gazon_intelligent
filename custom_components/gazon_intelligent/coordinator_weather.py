from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any


def sun_event_minute_from_context(sun_context: dict[str, Any], key: str, dt_util: Any) -> int | None:
    """Minute locale d'un evenement solaire Home Assistant."""
    if not isinstance(sun_context, dict):
        return None
    raw = sun_context.get(key)
    if not raw:
        return None
    try:
        parsed = dt_util.parse_datetime(str(raw))
        if parsed is None:
            return None
        local = dt_util.as_local(parsed)
        return local.hour * 60 + local.minute
    except (TypeError, ValueError):
        return None


def sunset_today_minute_from_context(sun_context: dict[str, Any], dt_util: Any, today: date) -> int | None:
    """Minute locale du coucher du soleil DU JOUR, y compris une fois le soleil couché.

    `next_setting` est le PROCHAIN coucher : le soir venu, c'est celui du lendemain, lu à l'heure
    locale du lendemain. La veille d'un changement d'heure, cette lecture saute d'une heure. Veille
    de l'heure d'été : la nuit de la tonte (coucher + 30 min) tombait une heure trop tard, dans le
    noir. Veille de l'heure d'hiver : une minute après le coucher. On recule donc de 24 h EN UTC
    avant de convertir : le coucher du jour à une ou deux minutes près, sans saut (revue du 15/09).
    """
    if not isinstance(sun_context, dict):
        return None
    raw = sun_context.get("sun_next_setting")
    if not raw:
        return None
    try:
        parsed = dt_util.parse_datetime(str(raw))
        if parsed is None:
            return None
        local = dt_util.as_local(parsed)
        if local.date() > today:
            local = dt_util.as_local(parsed - timedelta(days=1))
        return local.hour * 60 + local.minute
    except (TypeError, ValueError):
        return None


def et_elapsed_fraction(
    *,
    now: datetime,
    sunrise_minute: int | None,
    sunset_minute: int | None,
    fallback_day_start_minute: int,
    fallback_day_end_minute: int,
) -> float:
    """Fraction lineaire de jour ecoulee entre lever et coucher."""
    sunrise = sunrise_minute
    sunset = sunset_minute
    if sunrise is None or sunset is None or sunset <= sunrise:
        sunrise, sunset = fallback_day_start_minute, fallback_day_end_minute
    now_minute = now.hour * 60 + now.minute
    if now_minute <= sunrise:
        return 0.0
    if now_minute >= sunset:
        return 1.0
    return max(0.0, min(1.0, (now_minute - sunrise) / (sunset - sunrise)))


# Seuils de la garde « rosée ». L'ENTRÉE est l'ancienne règle, inchangée ; la SORTIE est plus large
# (hystérésis). La station mesure au dixième de degré et au pour cent : à 2,0 °C d'écart et
# 88 % d'humidité, UN tic de capteur suffisait à faire basculer l'autorisation de tondre. Le 27/10/2026
# elle a basculé 5 fois en 1 h 25 (écart 2,0 ↔ 2,2 °C, humidité 87 ↔ 88 %), et le pilote automatique a
# rappelé puis relancé la tondeuse à chaque bascule.
# ⚠️ MARGE CHOISIE SUR DES MESURES, pas à l'œil : rejouée sur 11 jours de la station (moyennes de 5 min),
# une sortie à 3,0 °C / 85 % supprimait aussi l'oscillation mais gardait le gazon « mouillé » toute la
# journée du 27/10 (35 min sèches contre 335), soit 17 % de minutes sèches perdues sur la période. 2,5 °C /
# 86 % supprime la même oscillation du matin et en perd 8 % ; le tic de capteur est de ±0,2 °C et ±1 %.
ROSEE_ENTREE_ECART_C = 2.0
ROSEE_ENTREE_HUMIDITE_PCT = 88.0
ROSEE_SORTIE_ECART_C = 2.5
ROSEE_SORTIE_HUMIDITE_PCT = 86.0
# Une mémoire plus vieille que cela n'est plus un état mais un souvenir : après une longue coupure
# de Home Assistant, elle ne doit pas prolonger la rosée de la veille.
ROSEE_MEMOIRE_MAX_MINUTES = 30.0


def _nombre_fini(valeur: Any) -> float | None:
    """Un nombre fini, ou None (booléen, texte non numérique, NaN et infini refusés)."""
    if isinstance(valeur, bool):
        return None
    try:
        nombre = float(valeur)
    except (TypeError, ValueError):
        return None
    if nombre != nombre or nombre in (float("inf"), float("-inf")):
        return None
    return nombre


def estimate_rosee(
    weather_profile: dict[str, Any],
    temperature: float | None,
    humidite: float | None,
    point_de_rosee: float | None = None,
) -> float | None:
    """Estime la presence de rosee/humidite foliaire depuis la meteo disponible.

    `point_de_rosee` : le capteur dedie (CONF_CAPTEUR_POINT_DE_ROSEE), prioritaire sur le point
    de rosee de l'entite meteo — plus fidele au jardin qu'une prevision generique.

    ⚠️ SANS MÉMOIRE : c'est la règle d'ENTRÉE, une photographie de l'instant. Pour décider de
    tondre, passer par `estimate_rosee_avec_memoire` : cette règle seule bascule à chaque tic de
    capteur quand l'écart reste autour de 2,0 °C.
    """
    dew_point = point_de_rosee if point_de_rosee is not None else weather_profile.get("weather_dew_point")
    if dew_point is not None and temperature is not None:
        try:
            if float(temperature) - float(dew_point) <= ROSEE_ENTREE_ECART_C:
                return 1.0
        except (TypeError, ValueError):
            pass
    try:
        if humidite is not None and float(humidite) >= ROSEE_ENTREE_HUMIDITE_PCT:
            return 0.8
    except (TypeError, ValueError):
        pass
    if weather_profile.get("weather_condition") in {"fog", "rainy", "pouring"}:
        return 1.0
    return None


def _memoire_rosee_valide(memoire: Any, maintenant: datetime) -> dict[str, Any] | None:
    """La mémoire précédente si elle est lisible et assez récente, sinon None."""
    if not isinstance(memoire, dict):
        return None
    valeur = _nombre_fini(memoire.get("valeur"))
    if valeur is None or valeur <= 0:
        return None
    try:
        mise_a_jour = datetime.fromisoformat(str(memoire.get("maj_a")))
    except (TypeError, ValueError):
        return None
    if mise_a_jour.tzinfo is None or maintenant.tzinfo is None:
        return None
    age_minutes = (maintenant - mise_a_jour).total_seconds() / 60.0
    if age_minutes < 0 or age_minutes > ROSEE_MEMOIRE_MAX_MINUTES:
        return None
    return {"valeur": valeur, "maj_a": mise_a_jour}


def estimate_rosee_avec_memoire(
    weather_profile: dict[str, Any],
    temperature: float | None,
    humidite: float | None,
    point_de_rosee: float | None,
    memoire: Any,
    maintenant: datetime,
) -> tuple[float | None, dict[str, Any] | None]:
    """`estimate_rosee` avec HYSTÉRÉSIS : rend `(valeur, nouvelle mémoire)`.

    Entrée : la règle de `estimate_rosee`, inchangée. Sortie : tant que la rosée était présente, elle
    le reste jusqu'à ce que l'écart température − point de rosée dépasse 2,5 °C ET que l'humidité
    repasse sous 86 %. La valeur maintenue est celle d'avant (1,0 ou 0,8), jamais renforcée.

    ⚠️ Une lecture absente ne maintient rien : « pas de lecture ≠ rosée ». Si ni l'écart ni l'humidité
    ne sont lisibles, la rosée est levée, comme avant. La mémoire rendue est `None` dès qu'il n'y a
    plus de rosée, et porte `maintenue: True` quand la valeur vient de l'hystérésis.
    """
    brut = estimate_rosee(weather_profile, temperature, humidite, point_de_rosee)
    horodatage = maintenant.isoformat()
    if brut is not None:
        return brut, {"valeur": brut, "maj_a": horodatage, "maintenue": False}
    precedent = _memoire_rosee_valide(memoire, maintenant)
    if precedent is None:
        return None, None
    dew_point = point_de_rosee if point_de_rosee is not None else weather_profile.get("weather_dew_point")
    temperature_c = _nombre_fini(temperature)
    dew_point_c = _nombre_fini(dew_point)
    humidite_pct = _nombre_fini(humidite)
    # `round` : 17,2 - 14,6 vaut 2,5999999999999996 en virgule flottante ; la frontière ne doit pas dépendre
    # du bruit de l'arithmétique.
    ecart = (
        round(temperature_c - dew_point_c, 2)
        if temperature_c is not None and dew_point_c is not None
        else None
    )
    encore_humide = (ecart is not None and ecart <= ROSEE_SORTIE_ECART_C) or (
        humidite_pct is not None and humidite_pct >= ROSEE_SORTIE_HUMIDITE_PCT
    )
    if not encore_humide:
        return None, None
    return precedent["valeur"], {"valeur": precedent["valeur"], "maj_a": horodatage, "maintenue": True}
