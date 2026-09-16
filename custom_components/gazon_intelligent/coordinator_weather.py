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


def estimate_rosee(
    weather_profile: dict[str, Any],
    temperature: float | None,
    humidite: float | None,
) -> float | None:
    """Estime la presence de rosee/humidite foliaire depuis la meteo disponible."""
    dew_point = weather_profile.get("weather_dew_point")
    if dew_point is not None and temperature is not None:
        try:
            if float(temperature) - float(dew_point) <= 2.0:
                return 1.0
        except (TypeError, ValueError):
            pass
    try:
        if humidite is not None and float(humidite) >= 88:
            return 0.8
    except (TypeError, ValueError):
        pass
    if weather_profile.get("weather_condition") in {"fog", "rainy", "pouring"}:
        return 1.0
    return None
