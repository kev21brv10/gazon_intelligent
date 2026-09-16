from __future__ import annotations

from logging import Logger
from typing import Any


def _passe_a_retenir(passe: dict[str, Any]) -> bool:
    """Une passe mérite-t-elle d'entrer au carnet ?

    Retenue si elle a tondu, OU si elle a été bloquée — un blocage sans tonte est un fait utile.
    Écartée seulement quand elle n'a rien fait du tout : le rebond d'état au démarrage, qui
    ouvre et referme une passe en quelques secondes.

    ⚠️ `None` n'est pas zéro : une durée absente signifie qu'on ne sait pas, et on garde.

    ⚠️ ARBITRAGE RÉEXAMINÉ LE 04/09/2026, ET MAINTENU. Un audit proposait d'écarter aussi les
    passes « bloquee » à ZÉRO minute bloquée, en supposant que le fantôme du 02/09 passait par
    là. Vérifié : ce fantôme portait **0,8 minute de blocage mesuré** (`mower_blocked_minutes_
    today` 74,0 → 74,8) — il entrait par la clause précédente, pas par celle-ci.
    Et surtout, `minutes_bloquees` se crédite depuis l'échantillon PRÉCÉDENT : un blocage réel
    plus court qu'un cycle crédite légitimement 0,0. Durcir ici perdrait de vrais blocages
    courts sans rien empêcher. La vraie cause du fantôme était la fausse rentrée sur `idle`,
    corrigée en 0.70.0.
    """
    tondues = passe.get("minutes_tondues")
    bloquees = passe.get("minutes_bloquees")
    if not isinstance(tondues, (int, float)) or isinstance(tondues, bool):
        return True
    if float(tondues) > 0.0:
        return True
    if (
        isinstance(bloquees, (int, float))
        and not isinstance(bloquees, bool)
        and float(bloquees) > 0.0
    ):
        return True
    return str(passe.get("fin_motif") or "") == "bloquee"


def _clean_empty_attrs(attrs: dict[str, Any]) -> dict[str, Any] | None:
    """Retire les valeurs vides (None, '', {}, []) d'un dict d'attributs."""
    clean = {key: value for key, value in attrs.items() if value not in (None, "", {}, [])}
    return clean or None


def _to_float_or_none(value: Any) -> float | None:
    """Nombre lisible, ou `None`. ⚠️ `None` reste `None` : une absence n'est pas un zéro."""
    if value is None or isinstance(value, bool):
        return None
    try:
        nombre = float(value)
    except (TypeError, ValueError):
        return None
    return nombre if nombre == nombre else None  # NaN != NaN


def _float_conf_value(
    value: Any,
    *,
    key: str,
    default: float | None,
    logger: Logger,
) -> float | None:
    """Valeur de configuration numerique normalisee."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        logger.debug("Impossible de convertir la configuration %s en float: %s", key, value)
        return default


def _mediane(valeurs: list[float]) -> float:
    """Médiane, et non moyenne : une seule journée à trois blocages fausserait la moyenne."""
    ordonnees = sorted(valeurs)
    milieu = len(ordonnees) // 2
    if len(ordonnees) % 2:
        return ordonnees[milieu]
    return (ordonnees[milieu - 1] + ordonnees[milieu]) / 2.0
