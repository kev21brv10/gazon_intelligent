from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from math import isfinite
from typing import Any

try:
    from homeassistant.util import dt as dt_util
except Exception:  # pragma: no cover - standalone fallback
    dt_util = None

_LOGGER = logging.getLogger(__name__)

# JUMEAU : water._SOIL_RESERVE_UTILE_MM — même réserve utile du sol par type de sol, gardée
# identique à la main (cf. tests/test_soil_balance.py::TestSoilReserveTwins).
SOIL_RESERVE_BASE_MM = {
    "sableux": 8.0,
    "limoneux": 12.0,
    "argileux": 16.0,
}

SOIL_RESERVE_MAX_MM = {
    "sableux": 16.0,
    "limoneux": 24.0,
    "argileux": 32.0,
}

SOIL_RESERVE_DEFAULT_BASE_MM = 12.0
SOIL_RESERVE_DEFAULT_MAX_MM = 24.0
SOIL_BALANCE_LEDGER_LIMIT = 120
# Plafond physique de l'ET0 journalière (mm) pour le bilan sol : borne le « pic du jour » retenu
# par le lissage, afin qu'un faux pic météo ponctuel ne draine pas la réserve de façon absurde.
# L'ET0 d'un gazon de référence ne dépasse quasi jamais ~12 mm/j, même en canicule → 14 = marge.
ETP_DAILY_CAP_MM = 14.0
# ACCUMULATION HORAIRE — pas maximal intégré en une fois (heures). Le coordinateur tourne toutes
# les ~2 min : un écart plus grand signale une coupure (Home Assistant arrêté, veille machine).
# Appliquer le taux courant sur tout le trou sur-débiterait massivement la réserve (ex. reprise à
# midi après une nuit d'arrêt : taux de midi × 12 h). On borne donc chaque pas.
_ACCUMULATION_MAX_STEP_HOURS = 2.0

# FRAÎCHEUR DU CUMUL (heures). En dessous, un taux horaire manquant est un simple blip de capteur
# ou un redémarrage de Home Assistant : le temps réellement écoulé est négligeable et la mesure
# acquise vaut mieux que l'estimation prorata. Au-delà, du temps a vraiment été perdu et le
# prorata redevient la seule source qui connaisse la fraction de journée écoulée.
# 15 min : le coordinateur tourne toutes les ~2 min, un redémarrage complet prend ~1 à 2 min.
# Volontairement bien PLUS COURT que `_ACCUMULATION_MAX_STEP_HOURS` — il ne s'agit pas de tolérer
# une coupure, seulement de ne pas jeter la mesure pour trois minutes d'absence.
_ACCUMULATION_FRESH_HOURS = 0.25


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_half_up_1(value: float) -> float:
    # int(x * 10 + 0.5) rounds toward +inf for positives but toward zero for
    # negatives, producing an asymmetric result (e.g. -1.2 → -1.1).
    # We apply the same logic on the absolute value and restore the sign so that
    # previous_reserve + delta_mm == reserve_mm holds after rounding.
    # JUMEAU : water._round_half_up_1 — garder les deux identiques
    # (cf. tests/test_soil_balance.py::TestRoundHalfUpTwins).
    if value < 0:
        return -float(int(abs(value) * 10.0 + 0.5)) / 10.0
    return float(int(value * 10.0 + 0.5)) / 10.0


def appliquer_cliquet_pluie(
    lecture: float,
    pic_precedent: float | None,
) -> tuple[float, float, bool]:
    """Cliquet intra-journée du pluviomètre. Rend (valeur retenue, pic du jour, remise à zéro).

    ⚠️ SOURCE UNIQUE DE LA RÈGLE — arbitrée par Kévin le 06/08/2026. Le pluviomètre journalier
    BAISSE en cours de journée : mesuré 10 fois le 04/08/2026 (00:48 1,0 → 03:11 2,6 → 04:08
    2,5 → 04:20 3,5 → 04:44 2,7 → 17:17 4,2 → 19:08 3,4 → 20:11 4,0 → 21:50 2,9 → 23:52 3,1).
    Un compteur du jour ne peut pas décroître : ces baisses sont du bruit, et la lecture brute
    ne dit donc ni ce qu'il est tombé, ni s'il pleut.

    ⚠️ PAS un `max()` nu : le capteur se remet à zéro plusieurs dizaines de minutes APRÈS
    minuit local, donc un maximum figerait le cumul de la veille pour toute la journée. On
    détecte la REMISE À ZÉRO — une chute vers ~0 — au lieu de se fier à l'heure.

    Extrait de `update_soil_balance` le 16/08/2026 pour servir aussi la garde « il pleut »
    (coordinateur) : sans ça, deux implémentations de la même règle — et la seconde a
    effectivement menti, en prenant quatre remontées de bruit pour des averses le 16/08.
    """
    if pic_precedent is None or pic_precedent <= lecture:
        return lecture, lecture, False
    if _est_une_remise_a_zero(lecture, pic_precedent):
        return lecture, lecture, True   # le compteur a rebouclé : on repart de la nouvelle base
    return pic_precedent, pic_precedent, False  # simple décrochage : on garde le maximum


# Une remise à zéro est une chute VERS ZÉRO. La résolution du pluviomètre est de 0,1 mm.
_PLUIE_REMISE_A_ZERO_MAX_MM = 0.1
# En dessous de ce cumul, « 0,5 mm » n'est pas « ~0 » : c'est la moitié de la journée.
_PLUIE_PIC_MIN_POUR_CHUTE_RELATIVE_MM = 1.0


def _est_une_remise_a_zero(lecture: float, pic_precedent: float) -> bool:
    """Le compteur a-t-il rebouclé, ou est-ce un simple décrochage ?

    ⚠️ DEUX BRAS, ET LE PREMIER EST LE PLUS SÛR.

    · Une chute **vers zéro** est une remise à zéro, quel que soit le cumul de la veille.
      C'est la forme observée à chaque minuit : 0.0 le 17/08 à 01:39, le 25/08 à 00:04.

    · Une chute **très large depuis un cumul significatif** en est une aussi : après une
      journée à 29 mm, un compteur qui repart à 0,3 mm a bien rebouclé. Le garde
      `pic ≥ 1 mm` est indispensable — sans lui, le 29/08/2026 une simple oscillation
      0,4 → 0,2 mm passait pour une remise à zéro (0,2 ≤ 0,5 et 0,2 ≤ max(0,5 ; 0,2)),
      le cliquet se recalait sur 0,2, et la remontée à 0,4 était comptée comme une NOUVELLE
      averse. Une pluie inventée un jour de bruine, exactement le défaut que ce cliquet
      existe pour empêcher.
    """
    if lecture <= _PLUIE_REMISE_A_ZERO_MAX_MM:
        return True
    if pic_precedent < _PLUIE_PIC_MIN_POUR_CHUTE_RELATIVE_MM:
        return False
    return lecture <= pic_precedent * 0.5 and lecture <= 0.5


def base_reserve_mm(type_sol: str | None) -> float:
    return float(SOIL_RESERVE_BASE_MM.get(type_sol or "", SOIL_RESERVE_DEFAULT_BASE_MM))


def max_reserve_mm(type_sol: str | None) -> float:
    return float(SOIL_RESERVE_MAX_MM.get(type_sol or "", SOIL_RESERVE_DEFAULT_MAX_MM))


def _normalize_ledger_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    raw_date = entry.get("date")
    if not raw_date:
        return None
    try:
        date.fromisoformat(str(raw_date))
    except ValueError:
        return None
    normalized = {
        "date": str(raw_date),
        "reserve_mm": _to_float(entry.get("reserve_mm")),
        "previous_reserve_mm": _to_float(entry.get("previous_reserve_mm")),
        "pluie_mm": _to_float(entry.get("pluie_mm")),
        # ⚠️ LISTE BLANCHE : une clé absente d'ici est perdue à chaque passage et à chaque
        # rechargement du state. Sans elle, le cliquet intra-journée n'aurait aucune mémoire.
        "pluie_pic_mm": _to_float(entry.get("pluie_pic_mm")),
        "arrosage_mm": _to_float(entry.get("arrosage_mm")),
        "etp_mm": _to_float(entry.get("etp_mm")),
        # ET RÉELLEMENT écoulée (accumulation du taux horaire) + horodatage du dernier cumul.
        # Cette normalisation est une LISTE BLANCHE : toute clé absente d'ici est perdue à chaque
        # passage ET à chaque rechargement du state persisté — l'accumulation ne survivrait pas
        # d'un cycle à l'autre (donc jamais aucun débit horaire). Ne pas les retirer.
        "etp_elapsed_mm": _to_float(entry.get("etp_elapsed_mm")),
        "etp_last_ts": str(entry.get("etp_last_ts")) if entry.get("etp_last_ts") else None,
        "etp_hourly": True if entry.get("etp_hourly") else None,
        "delta_mm": _to_float(entry.get("delta_mm")),
        "type_sol": str(entry.get("type_sol")) if entry.get("type_sol") else None,
        # Marque une réserve recalée manuellement (service recalibrate_reserve) : la
        # journée correspondante ne doit pas être recalculée depuis l'historique.
        "manual_anchor": True if entry.get("manual_anchor") else None,
        # Relevés aberrants écrêtés (pluie > 100 mm, arrosage > 50 mm). Absents de cette liste,
        # ils étaient effacés dès le CYCLE SUIVANT — la normalisation tourne à chaque passage,
        # pas seulement au rechargement — donc ~2 minutes de survie. Le marqueur censé signaler
        # une journée douteuse était en pratique introuvable.
        "pluie_suspect": True if entry.get("pluie_suspect") else None,
        "arrosage_suspect": True if entry.get("arrosage_suspect") else None,
    }
    clean = {key: value for key, value in normalized.items() if value not in (None, "", {}, [])}
    return clean or None


def normalize_soil_balance_state(state: dict[str, Any] | None) -> dict[str, Any]:
    state = state or {}
    ledger = state.get("ledger")
    if isinstance(ledger, list):
        normalized_ledger = []
        for item in ledger:
            normalized = _normalize_ledger_entry(item)
            if normalized is not None:
                normalized_ledger.append(normalized)
        ledger = normalized_ledger[-SOIL_BALANCE_LEDGER_LIMIT:]
    else:
        ledger = []

    today = state.get("date")
    reserve_mm = _to_float(state.get("reserve_mm"))
    previous_reserve_mm = _to_float(state.get("previous_reserve_mm"))
    pluie_mm = _to_float(state.get("pluie_mm"))
    arrosage_mm = _to_float(state.get("arrosage_mm"))
    etp_mm = _to_float(state.get("etp_mm"))
    delta_mm = _to_float(state.get("delta_mm"))
    type_sol = str(state.get("type_sol")) if state.get("type_sol") else None
    reserve_min_mm = _to_float(state.get("reserve_min_mm"))
    reserve_max = _to_float(state.get("reserve_max_mm"))

    if reserve_min_mm is None:
        reserve_min_mm = 0.0
    if reserve_max is None:
        reserve_max = max_reserve_mm(type_sol)
    if reserve_mm is None and ledger:
        reserve_mm = _to_float(ledger[-1].get("reserve_mm"))
    if previous_reserve_mm is None and ledger:
        previous_reserve_mm = _to_float(ledger[-1].get("previous_reserve_mm"))

    clean = {
        "date": today if isinstance(today, str) else (str(today) if today else None),
        "reserve_mm": reserve_mm,
        "previous_reserve_mm": previous_reserve_mm,
        "pluie_mm": pluie_mm,
        "arrosage_mm": arrosage_mm,
        "etp_mm": etp_mm,
        "delta_mm": delta_mm,
        "type_sol": type_sol,
        "reserve_min_mm": reserve_min_mm,
        "reserve_max_mm": reserve_max,
        "ledger": ledger,
    }
    return clean


def _accumulate_elapsed_etp(
    *,
    ledger: list[dict[str, Any]],
    today_str: str,
    etc_hourly_mm_h: float | None,
    now: datetime | None,
    fallback_prorata: float,
) -> tuple[float, str | None, bool]:
    """ETc réellement écoulée aujourd'hui (mm), horodatage du dernier cumul, mode horaire.

    Le 3e élément indique si la journée est pilotée par l'intégration HORAIRE mesurée. Il
    commande le filet de clôture de la veille : sans lui, une journée en repli prorata serait
    clôturée sur sa fraction écoulée (Home Assistant arrêté à midi → veille sous-débitée,
    erreur qui se propage), alors que l'ET0 pleine journée doit alors faire foi.

    Intègre le taux horaire mesuré au fil des cycles (Riemann). Retombe sur le prorata de
    l'ET0 journalière estimée quand le taux horaire manque — ou pour AMORCER la journée si
    l'accumulation démarre en cours de route (Home Assistant lancé à midi : les heures
    précédentes n'ont pas été intégrées, le prorata les couvre).

    Le cumul déjà acquis n'est JAMAIS détruit : un seul cycle en repli (capteur momentanément
    `unavailable` — cas courant : TOUT redémarrage de Home Assistant rend les capteurs
    indisponibles le temps du démarrage, ce n'est pas une défaillance du matériel) doit laisser
    l'accumulation intacte, sans quoi l'intégration horaire est silencieusement remplacée par
    le prorata (sur-débit mesuré à +22 % quand un capteur clignote).
    """
    today_entry = ledger[-1] if ledger and ledger[-1].get("date") == today_str else None
    previous_elapsed = _to_float(today_entry.get("etp_elapsed_mm")) if today_entry else None
    previous_ts_raw = today_entry.get("etp_last_ts") if today_entry else None
    previous_ts_raw = previous_ts_raw if isinstance(previous_ts_raw, str) else None
    was_hourly = bool(today_entry.get("etp_hourly")) if today_entry else False

    # Un taux non fini (NaN/inf, possible dès qu'un capteur publie `nan`) doit être traité comme
    # ABSENT, jamais comme zéro : `max(0.0, nan)` renvoie 0.0 et gèlerait le débit en silence,
    # réserve figée, journée clôturée sur cette valeur bloquée.
    rate = _to_float(etc_hourly_mm_h)
    if rate is None or not isfinite(rate) or rate < 0.0 or now is None:
        # REPLI — le taux horaire manque. Deux situations très différentes, longtemps confondues.
        #
        # ⚠️ DÉFAUT CORRIGÉ le 30/07/2026 (signalé par Kévin : « à chaque fois que je redémarre
        # la réserve du sol descend »). Ce repli faisait `max(prorata, cumul)` dans TOUS les cas.
        # Or tout redémarrage de Home Assistant rend le capteur d'ET horaire indisponible le temps
        # du démarrage — c'est le redémarrage qui le prive de données, pas le capteur qui défaille :
        # chaque redémarrage remplaçait donc la mesure (fine, chaîne FAO-56 horaire) par
        # l'estimation prorata, plus grossière et systématiquement PLUS HAUTE. Mesuré sur
        # l'install : −0,2 / −0,4 / −0,8 et jusqu'à **−1,4 mm en un pas**, là où la dérive
        # normale est de 0,1 mm. Six redémarrages le 29/07 ont coûté 2 à 3 mm — un quart de la
        # réserve utile, effacé par de l'outillage, pas par le gazon.
        #
        # On distingue donc :
        # - le CUMUL EST FRAIS (dernier pas < `_ACCUMULATION_FRESH_HOURS`, soit 15 min) : blip de
        #   capteur ou redémarrage. On garde la mesure telle quelle, aucun rattrapage — le temps
        #   réellement écoulé est négligeable et la mesure vaut mieux que l'estimation ;
        # - le CUMUL EST VIEUX ou absent : on a vraiment perdu du temps (coupure, HA lancé en
        #   cours de journée). Le prorata est alors la seule source qui connaisse la fraction de
        #   journée écoulée — on s'y resynchronise, comme le fait déjà le chemin « coupure ».
        #
        # Le débit ne recule toujours jamais (l'eau évaporée ne revient pas) et le mode de la
        # journée est préservé : un blip ne bascule pas la clôture de la veille sur l'ET0 pleine.
        cumul_frais = False
        if previous_elapsed is not None and previous_ts_raw is not None and now is not None:
            try:
                _prev = datetime.fromisoformat(previous_ts_raw)
            except ValueError:
                _prev = None
            if _prev is not None and (_prev.tzinfo is None) == (now.tzinfo is None):
                _ecart_h = (now - _prev).total_seconds() / 3600.0
                cumul_frais = 0.0 <= _ecart_h <= _ACCUMULATION_FRESH_HOURS
        if cumul_frais:
            return (
                min(previous_elapsed or 0.0, ETP_DAILY_CAP_MM),
                previous_ts_raw,
                was_hourly,
            )
        return (
            min(max(fallback_prorata, previous_elapsed or 0.0), ETP_DAILY_CAP_MM),
            previous_ts_raw,
            was_hourly,
        )

    now_ts = now.isoformat()
    if previous_elapsed is None:
        # Premier cumul de la journée : on part du prorata pour ne pas ignorer les heures déjà
        # écoulées (ET0 estimée), l'accumulation prend le relais à partir de maintenant.
        return min(max(fallback_prorata, 0.0), ETP_DAILY_CAP_MM), now_ts, True

    previous_ts: datetime | None = None
    if previous_ts_raw is not None:
        try:
            previous_ts = datetime.fromisoformat(previous_ts_raw)
        except ValueError:
            previous_ts = None
    if previous_ts is not None and (previous_ts.tzinfo is None) != (now.tzinfo is None):
        # Un horodatage persisté naïf face à un `now` aware (ou l'inverse) ferait lever une
        # TypeError dans un chemin qui tourne toutes les 2 min : on le traite comme illisible.
        previous_ts = None
    if previous_ts is None:
        return min(max(previous_elapsed, fallback_prorata), ETP_DAILY_CAP_MM), now_ts, True

    elapsed_hours = (now - previous_ts).total_seconds() / 3600.0
    if elapsed_hours <= 0:
        # Horloge non monotone (changement d'heure, resynchronisation NTP) : on ne débite rien
        # plutôt que d'inventer un pas négatif ou géant.
        return min(previous_elapsed, ETP_DAILY_CAP_MM), previous_ts_raw, True
    if elapsed_hours > _ACCUMULATION_MAX_STEP_HOURS:
        # COUPURE. Appliquer le taux courant sur tout le trou sur-débiterait ; le perdre
        # sous-débiterait DÉFINITIVEMENT (l'erreur se fige dans la réserve d'ouverture du
        # lendemain, ~2,6 mm d'eau fantôme mesurés sur une coupure de 8 h). On borne le pas ET
        # on se resynchronise sur le prorata, seule estimation qui connaisse la fraction de
        # journée réellement écoulée pendant l'absence.
        _LOGGER.debug(
            "Bilan sol : écart de %.1f h depuis le dernier cumul d'ET (coupure ?) — pas borné à "
            "%.1f h et resynchronisation sur le prorata.",
            elapsed_hours,
            _ACCUMULATION_MAX_STEP_HOURS,
        )
        rattrapage = previous_elapsed + rate * _ACCUMULATION_MAX_STEP_HOURS
        return min(max(rattrapage, fallback_prorata), ETP_DAILY_CAP_MM), now_ts, True
    accumulated = previous_elapsed + rate * elapsed_hours
    return min(accumulated, ETP_DAILY_CAP_MM), now_ts, True


def update_soil_balance(
    previous_state: dict[str, Any] | None,
    today: date | None = None,
    pluie_mm: float | None = None,
    arrosage_mm: float | None = None,
    etp_mm: float | None = None,
    type_sol: str | None = None,
    et_elapsed_fraction: float | None = None,
    etc_hourly_mm_h: float | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if today is None:
        if dt_util is not None:
            now_getter = getattr(dt_util, "now", None)
            if callable(now_getter):
                current = now_getter()
                if isinstance(current, datetime):
                    today = current.date()
        if today is None:
            today = datetime.now(timezone.utc).date()
    today_str = today.isoformat()
    state = normalize_soil_balance_state(previous_state)
    ledger = list(state.get("ledger") or [])

    if ledger and ledger[-1].get("date") == today_str and ledger[-1].get("manual_anchor"):
        # Réserve recalée manuellement aujourd'hui (service recalibrate_reserve) : on
        # conserve l'ancre pour le reste de la journée au lieu de la recalculer depuis
        # l'historique (qui peut contenir d'anciens doublons). L'évolution normale (ET,
        # pluie, arrosage) reprend dès le lendemain.
        return state

    reserve_min_mm = _to_float(state.get("reserve_min_mm"))
    if reserve_min_mm is None:
        reserve_min_mm = 0.0
    # Plafond de stock : il DOIT suivre le type de sol configuré. `normalize_soil_balance_state`
    # le résout depuis l'état PERSISTÉ, or au tout premier appel cet état est vide → type_sol None
    # → SOIL_RESERVE_DEFAULT_MAX_MM (24 mm) écrit dans le ledger. Comme la valeur n'était alors
    # plus None, elle n'était jamais recalculée : toute installation restait bloquée sur 24 mm et
    # la table SOIL_RESERVE_MAX_MM (sableux 16 / argileux 32) était inatteignable. On re-résout
    # donc dès que le type de sol reçu diffère de celui mémorisé (premier appel inclus, où le
    # mémorisé vaut None), ce qui couvre aussi un changement de sol en configuration.
    stored_type_sol = state.get("type_sol")
    reserve_max_mm = _to_float(state.get("reserve_max_mm"))
    if reserve_max_mm is None or (type_sol is not None and type_sol != stored_type_sol):
        reserve_max_mm = max_reserve_mm(type_sol or stored_type_sol)
    if reserve_max_mm < reserve_min_mm:
        reserve_max_mm = reserve_min_mm

    if ledger and ledger[-1].get("date") == today_str:
        previous_reserve = _to_float(ledger[-1].get("previous_reserve_mm"))
        if previous_reserve is None:
            previous_reserve = _to_float(state.get("previous_reserve_mm"))
        # REPLIS OBLIGATOIRES. Sans eux, une entrée du jour dépourvue de réserve d'ouverture
        # (entrée héritée d'une version antérieure à cette clé, ou `.storage` retouché) laissait
        # `previous_reserve` à None et le calcul de la réserve plus bas levait un TypeError :
        # le bilan sol s'arrêtait alors à chaque cycle, en silence côté utilisateur. La branche
        # « nouveau jour » possède déjà cette chaîne ; on s'aligne dessus.
        # On remonte à la CLÔTURE DE LA VEILLE, et non à `state["reserve_mm"]` qui est la réserve
        # de fin de journée d'aujourd'hui — déjà débitée, elle ferait perdre l'ET0 du jour.
        if previous_reserve is None and len(ledger) >= 2:
            previous_reserve = _to_float(ledger[-2].get("reserve_mm"))
        if previous_reserve is None:
            previous_reserve = base_reserve_mm(type_sol or state.get("type_sol"))
    else:
        # CLÔTURE DE LA VEILLE. L'ET0 est désormais débitée AU FIL de la journée (cf. plus bas) :
        # la dernière valeur écrite pour hier ne reflète donc que la fraction de journée écoulée au
        # moment du dernier passage. Si Home Assistant s'est arrêté avant le coucher du soleil,
        # hier resterait sous-débité et l'erreur se propagerait de jour en jour. On reconstruit
        # donc le solde de clôture de la veille avec son ET0 du jour ENTIER — les trois composantes
        # (réserve d'ouverture, pluie, arrosage) sont stockées dans l'entrée, et `etp_mm` y est
        # toujours l'ET0 pleine journée (pic du jour), jamais la fraction écoulée.
        previous_reserve = None
        if ledger:
            _last = ledger[-1]
            _last_open = _to_float(_last.get("previous_reserve_mm"))
            # ET de clôture : l'ETc RÉELLEMENT accumulée hier fait foi quand elle existe (mesurée
            # heure par heure), sinon l'estimation pleine journée.
            # GARDE ANTI-JOURNÉE-TRONQUÉE : si Home Assistant n'a tourné qu'une fraction de la
            # veille, le cumul est amputé et le figer laisserait de l'eau FANTÔME dans la réserve
            # d'ouverture — définitivement (cas mesuré : un seul cycle avant l'aube → cumul 0,0 mm
            # alors que la journée a bien évaporé ~5 mm). Une journée réellement couverte accumule
            # au moins la moitié de l'estimation journalière (celle-ci étant plutôt majorante) :
            # en dessous, on retient l'estimation pleine journée, plus sûre.
            _last_etp_estime = _to_float(_last.get("etp_mm"))
            _last_etp = _to_float(_last.get("etp_elapsed_mm"))
            if _last_etp is None:
                _last_etp = _last_etp_estime
            elif _last_etp_estime is not None and _last_etp < _last_etp_estime * 0.5:
                _LOGGER.debug(
                    "Bilan sol : clôture de %s sur l'ET0 estimée (%.2f mm) — cumul horaire "
                    "amputé (%.2f mm), journée probablement non couverte.",
                    _last.get("date"),
                    _last_etp_estime,
                    _last_etp,
                )
                _last_etp = _last_etp_estime
            if _last_open is not None and _last_etp is not None:
                _last_close = (
                    _last_open
                    + (_to_float(_last.get("pluie_mm")) or 0.0)
                    + (_to_float(_last.get("arrosage_mm")) or 0.0)
                    - _last_etp
                )
                previous_reserve = min(max(_last_close, reserve_min_mm), reserve_max_mm)
        if previous_reserve is None:
            previous_reserve = _to_float(state.get("reserve_mm"))
        if previous_reserve is None:
            previous_reserve = base_reserve_mm(type_sol or state.get("type_sol"))

    pluie_raw = max(0.0, _to_float(pluie_mm) or 0.0)
    arrosage_raw = max(0.0, _to_float(arrosage_mm) or 0.0)
    pluie_suspect = pluie_raw > 100.0
    arrosage_suspect = arrosage_raw > 50.0
    pluie = min(pluie_raw, 30.0) if pluie_suspect else pluie_raw
    arrosage = min(arrosage_raw, 25.0) if arrosage_suspect else arrosage_raw
    if pluie_suspect:
        _LOGGER.warning(
            "Pluie aberrante (%.1f mm) clampée à 30 mm dans le bilan sol — vérifie le capteur pluie.",
            pluie_raw,
        )
    if arrosage_suspect:
        _LOGGER.warning(
            "Arrosage aberrant (%.1f mm) clampé à 25 mm dans le bilan sol — vérifie la détection d'arrosage.",
            arrosage_raw,
        )
    etp = max(0.0, _to_float(etp_mm) or 0.0)
    # Lissage de l'ET0 du jour : on retient le PIC de la journée (la vraie demande max) au lieu de
    # laisser l'estimation redescendre le soir ou suivre les soubresauts météo (met.no qui passe de
    # soleil à pluie → ET0 qui chute à tort). Sans ça la réserve fait du yoyo (constaté 06/2026 :
    # ET0 4,9 ↔ 9,5 dans la même journée → réserve 7,5 ↔ 11,6, jauge instable). Le pic se
    # réinitialise chaque jour (au 1er passage d'une nouvelle date, l'entrée repart de l'ET0
    # courante). Plafonné (ETP_DAILY_CAP_MM) pour qu'un faux pic ponctuel ne casse pas le bilan.
    if ledger and ledger[-1].get("date") == today_str:
        _etp_pic_jour = _to_float(ledger[-1].get("etp_mm"))
        if _etp_pic_jour is not None:
            etp = max(etp, _etp_pic_jour)
    etp = min(etp, ETP_DAILY_CAP_MM)
    # Protection de bord de journée pour la PLUIE : conserver la valeur déjà comptabilisée
    # UNIQUEMENT quand la lecture du jour est ABSENTE (capteur indisponible, glitch, redémarrage).
    # Sans cela, `_to_float(None) or 0.0` transforme une absence de mesure en « 0 mm de pluie » et
    # efface rétroactivement la pluie du jour, faisant chuter la réserve.
    #
    # NE PAS utiliser max(pluie, pic_du_jour) ici : la remise à zéro du capteur ne coïncide PAS
    # avec le changement de date (le Netatmo bascule plusieurs dizaines de minutes après minuit
    # local). Le coordinateur tournant toutes les 2 min, l'entrée du jour est donc systématiquement
    # créée avec le cumul de la VEILLE — qu'un max() figerait pour toute la journée. Un simple
    # remplacement laisse au contraire l'erreur se corriger d'elle-même au reset suivant.
    # Comme pour les débits de zone : « absent » et « zéro » ne sont pas la même chose.
    if pluie_mm is None and ledger and ledger[-1].get("date") == today_str:
        _pluie_deja_comptee = _to_float(ledger[-1].get("pluie_mm"))
        if _pluie_deja_comptee is not None:
            pluie = _pluie_deja_comptee

    # ── CLIQUET INTRA-JOURNÉE ──────────────────────────────────────── voir appliquer_cliquet_pluie
    # Le pluviomètre journalier BAISSE en cours de journée : mesuré 10 fois le 04/08/2026
    # (00:48 1,0 → 03:11 2,6 → 04:08 2,5 → 04:20 3,5 → 04:44 2,7 → 17:17 4,2 → 19:08 3,4 →
    # 20:11 4,0 → 21:50 2,9 → 23:52 3,1), et la réserve suivait pas pour pas — 21:33→21:50,
    # réserve 9,8 → 8,9 pour un pluviomètre 3,8 → 2,9, pendant que l'ET0 horaire valait
    # 0,04 mm/h, soit 90 fois moins. Le ledger retenait la DERNIÈRE lecture (3,1) quand le
    # maximum du jour valait 4,2 : **1,1 mm réellement tombé n'entrait jamais au bilan**.
    #
    # L'objection du commentaire ci-dessus est juste et reste respectée : un `max()` nu figerait
    # le cumul de la VEILLE pour toute la journée, puisque le capteur se remet à zéro plusieurs
    # dizaines de minutes après minuit local. La différence ici, c'est qu'on détecte la REMISE À
    # ZÉRO — une chute vers ~0 — au lieu de se fier à l'heure. Le cliquet se relâche alors de
    # lui-même, et le pic du jour repart de la valeur remise à zéro. Ça corrige du même coup la
    # « marche de minuit » (31/07 : 8,6 à 23:36 → 11,2 à 00:00:32 → 8,6 à 00:44).
    _pic_precedent = None
    if ledger and ledger[-1].get("date") == today_str:
        _pic_precedent = _to_float(ledger[-1].get("pluie_pic_mm"))
    pluie, pluie_pic, _ = appliquer_cliquet_pluie(pluie, _pic_precedent)
    # DÉBIT PROGRESSIF DE L'ET0. Débiter toute l'ET0 du jour dès le premier passage après minuit
    # (comportement historique) rendait la réserve ANTICIPÉE : à 00h01 elle chutait d'un coup de
    # toute la demande à venir (« falaise de minuit ») et se trouvait ÉCRASÉE au plancher dès que
    # le résultat passait sous zéro — information perdue pour de bon. Au petit matin le pilotage
    # voyait donc un sol « vide » et commandait une recharge pleine sur un sol encore rempli : le
    # surplus drainait sous les racines (constaté 07/2026 : ~59 mm appliqués sur 7 jours pour un
    # besoin ETc de ~33 mm). On débite donc l'ET0 au prorata de la journée RÉELLEMENT écoulée
    # (`et_elapsed_fraction`, 0 au lever → 1 au coucher). Le total débité en fin de journée est
    # identique : seule la RÉPARTITION change. `etp_mm` reste l'ET0 pleine journée dans l'entrée —
    # le pic du jour et la clôture de la veille (ci-dessus) en dépendent.
    # Fraction absente (démarrage, position du soleil inconnue) → 1.0 = comportement historique.
    _fraction = 1.0 if et_elapsed_fraction is None else min(1.0, max(0.0, float(et_elapsed_fraction)))
    etp_prorata = etp * _fraction
    # ET RÉELLEMENT ÉCOULÉE. Le prorata ci-dessus répartit une ET0 *estimée pour la journée*, dont
    # la valeur est extrapolée d'un instantané (vent prévu, ciel supposé) et sujette au yo-yo
    # (constaté 28/07/2026 : 9 mm/j annoncés à 15 h, 6,9 à 17 h, contre ~6 mesurés). Quand un taux
    # HORAIRE mesuré est disponible (`etc_hourly_mm_h`, déjà en ETc), on intègre ce taux au fil du
    # temps — intégrale de Riemann — au lieu d'étaler une prévision. Le débit suit alors la demande
    # réelle heure par heure, et la « falaise de minuit » disparaît par construction.
    etp_elapsed, etp_last_ts, etp_hourly_mode = _accumulate_elapsed_etp(
        ledger=ledger,
        today_str=today_str,
        etc_hourly_mm_h=etc_hourly_mm_h,
        now=now,
        fallback_prorata=etp_prorata,
    )
    delta = pluie + arrosage - etp_elapsed
    reserve_mm = min(max(previous_reserve + delta, reserve_min_mm), reserve_max_mm)

    entry = {
        "date": today_str,
        "previous_reserve_mm": _round_half_up_1(previous_reserve),
        "pluie_mm": _round_half_up_1(pluie),
        # Maximum du jour retenu par le cliquet intra-journée. Sans cette clé, le cliquet
        # perdrait sa mémoire à chaque cycle ET à chaque rechargement du state persisté.
        "pluie_pic_mm": _round_half_up_1(pluie_pic),
        "arrosage_mm": _round_half_up_1(arrosage),
        "etp_mm": _round_half_up_1(etp),
        # ET effectivement débitée à cet instant, écrite UNIQUEMENT en mode horaire (mesuré) :
        # en repli prorata, l'absence de ces clés fait retomber la clôture de la veille sur
        # `etp_mm` (ET0 pleine journée), filet indispensable si Home Assistant s'arrête en cours
        # de journée. `etp_mm` reste l'estimation PLEINE JOURNÉE dans tous les cas (pic du jour).
        "etp_elapsed_mm": round(etp_elapsed, 3) if etp_hourly_mode else None,
        "etp_last_ts": etp_last_ts if etp_hourly_mode else None,
        # Drapeau EXPLICITE du mode horaire. Il était auparavant déduit de la présence des clés
        # ci-dessus — or `_round_half_up_1`/le filtre de nettoyage peuvent les faire disparaître,
        # et un cumul légitimement nul (avant le lever du soleil) est indiscernable d'une absence.
        "etp_hourly": True if etp_hourly_mode else None,
        "delta_mm": _round_half_up_1(delta),
        "reserve_mm": _round_half_up_1(reserve_mm),
        "type_sol": type_sol or state.get("type_sol"),
    }
    if pluie_suspect:
        entry["pluie_suspect"] = True
    if arrosage_suspect:
        entry["arrosage_suspect"] = True
    entry = {key: value for key, value in entry.items() if value not in (None, "", {}, [])}

    if ledger and ledger[-1].get("date") == today_str:
        ledger[-1] = entry
    else:
        ledger.append(entry)
    ledger = ledger[-SOIL_BALANCE_LEDGER_LIMIT:]

    return {
        "date": today_str,
        "reserve_mm": _round_half_up_1(reserve_mm),
        "previous_reserve_mm": _round_half_up_1(previous_reserve),
        "pluie_mm": _round_half_up_1(pluie),
        "arrosage_mm": _round_half_up_1(arrosage),
        "etp_mm": _round_half_up_1(etp),
        "delta_mm": _round_half_up_1(delta),
        "type_sol": type_sol or state.get("type_sol"),
        "reserve_min_mm": _round_half_up_1(reserve_min_mm),
        "reserve_max_mm": _round_half_up_1(reserve_max_mm),
        "ledger": ledger,
    }


def set_reserve_mm(
    previous_state: dict[str, Any] | None,
    reserve_mm: float,
    today: date | None = None,
    type_sol: str | None = None,
    freeze_day: bool = True,
) -> dict[str, Any]:
    """Recale la réserve sol à une valeur connue (calibration manuelle).

    `freeze_day=True` (défaut, comportement historique) pose une entrée « ancre » :
    `update_soil_balance` ne recalcule plus la journée, la valeur tient jusqu'à minuit.
    C'est ce qu'il faut pour l'usage prévu — « j'ai sondé mon sol ce soir, il est à 8 mm » :
    sans le gel, le recalcul du cycle suivant (ouverture + pluie + arrosage − ET) écraserait
    la mesure deux minutes plus tard.

    `freeze_day=False` répond au besoin INVERSE : corriger une comptabilité faussée en cours
    de journée, puis laisser la journée se dérouler normalement (ET débitée, pluie et arrosage
    crédités, jauge qui redescend). On ne pose alors pas d'ancre : on réécrit la RÉSERVE
    D'OUVERTURE de façon que la réserve courante vaille bien la valeur demandée compte tenu de
    ce qui s'est déjà passé aujourd'hui. Cas réel : le 29/07/2026, un défaut avait débité l'ETc
    pleine journée à 3 h du matin ; il fallait remettre 7,5 mm sans figer la journée entière.

    La valeur est bornée à [reserve_min, reserve_max] dans les deux cas.
    """
    if today is None:
        if dt_util is not None:
            now_getter = getattr(dt_util, "now", None)
            if callable(now_getter):
                current = now_getter()
                if isinstance(current, datetime):
                    today = current.date()
        if today is None:
            today = datetime.now(timezone.utc).date()
    today_str = today.isoformat()
    state = normalize_soil_balance_state(previous_state)
    ledger = list(state.get("ledger") or [])

    resolved_type = type_sol or state.get("type_sol")
    reserve_max = _to_float(state.get("reserve_max_mm"))
    if reserve_max is None:
        reserve_max = max_reserve_mm(resolved_type)
    reserve_min = _to_float(state.get("reserve_min_mm"))
    if reserve_min is None:
        reserve_min = 0.0
    if reserve_max < reserve_min:
        reserve_max = reserve_min
    raw = _to_float(reserve_mm)
    if raw is None or raw != raw:  # None ou NaN (NaN != NaN)
        raw = reserve_min
    value = _round_half_up_1(min(max(raw, reserve_min), reserve_max))

    if freeze_day:
        entry = {
            "date": today_str,
            "previous_reserve_mm": value,
            "pluie_mm": 0.0,
            "arrosage_mm": 0.0,
            "etp_mm": 0.0,
            "delta_mm": 0.0,
            "reserve_mm": value,
            "type_sol": resolved_type,
            "manual_anchor": True,
        }
        opening = value
    else:
        # SANS GEL — on ne réécrit pas la réserve COURANTE (elle serait recalculée au cycle
        # suivant et la correction disparaîtrait), mais la réserve d'OUVERTURE, seule valeur que
        # le recalcul relit. On la choisit telle que le recalcul retombe sur la valeur demandée :
        #   réserve = ouverture + pluie + arrosage − ET écoulée   ⟹   ouverture = valeur + ET − apports
        # Ce qui s'est déjà passé aujourd'hui est donc PRÉSERVÉ, au lieu d'être effacé comme le
        # fait l'ancre. Avant le lever du soleil ces trois termes sont nuls et l'ouverture vaut
        # simplement la valeur demandée.
        today_entry = ledger[-1] if ledger and ledger[-1].get("date") == today_str else {}
        elapsed_etp = _to_float(today_entry.get("etp_elapsed_mm"))
        if elapsed_etp is None:
            elapsed_etp = _to_float(today_entry.get("etp_mm")) or 0.0
        pluie_today = _to_float(today_entry.get("pluie_mm")) or 0.0
        arrosage_today = _to_float(today_entry.get("arrosage_mm")) or 0.0
        opening = _round_half_up_1(
            min(max(value + elapsed_etp - pluie_today - arrosage_today, reserve_min), reserve_max)
        )
        entry = dict(today_entry)
        entry.update(
            {
                "date": today_str,
                "previous_reserve_mm": opening,
                "reserve_mm": value,
                "type_sol": resolved_type,
            }
        )
        # Le drapeau d'ancre doit disparaître, sinon la journée reste figée — c'est exactement
        # ce que `freeze_day=False` sert à éviter.
        entry.pop("manual_anchor", None)
    entry = {key: val for key, val in entry.items() if val not in (None, "", {}, [])}
    if ledger and ledger[-1].get("date") == today_str:
        ledger[-1] = entry
    else:
        ledger.append(entry)
    ledger = ledger[-SOIL_BALANCE_LEDGER_LIMIT:]

    # L'état renvoyé reflète l'entrée écrite : sans gel, la journée garde ce qu'elle a déjà
    # accumulé (l'écraser à 0 ferait re-débiter l'ET du matin au cycle suivant).
    return {
        "date": today_str,
        "reserve_mm": value,
        "previous_reserve_mm": opening,
        "pluie_mm": float(entry.get("pluie_mm") or 0.0),
        "arrosage_mm": float(entry.get("arrosage_mm") or 0.0),
        "etp_mm": float(entry.get("etp_mm") or 0.0),
        "delta_mm": float(entry.get("delta_mm") or 0.0),
        "type_sol": resolved_type,
        "reserve_min_mm": _round_half_up_1(reserve_min),
        "reserve_max_mm": _round_half_up_1(reserve_max),
        "ledger": ledger,
    }
