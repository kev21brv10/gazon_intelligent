"""Les entrées météo et jardin de l'intégration : leur rôle, ce qu'elles apportent, leur repli (0.94.0).

Une seule définition pour trois lecteurs :
    · la page « Gazon » (onglet Météo), qui montre chaque entrée, sa valeur et son état ;
    · l'alerte « des mesures manquent » (`notifications.py`), qui surveille celles qui mesurent ;
    · le changement d'entrée depuis la page (0.95.0), qui refuse une entité que le moteur lirait
      de travers (`refus`).

Les textes reprennent le tableau des entrées de la référence d'architecture, vérifié sur le code.
Module PUR : aucune dépendance à Home Assistant.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any

from .const import (
    CONF_CAPTEUR_ETP,
    CONF_CAPTEUR_HAUTEUR_GAZON,
    CONF_CAPTEUR_HUMIDITE,
    CONF_CAPTEUR_HUMIDITE_SOL,
    CONF_CAPTEUR_PLUIE_24H,
    CONF_CAPTEUR_PLUIE_ACTUELLE,
    CONF_CAPTEUR_PLUIE_CUMUL,
    CONF_CAPTEUR_PLUIE_DEMAIN,
    CONF_CAPTEUR_POINT_DE_ROSEE,
    CONF_CAPTEUR_PRESSION,
    CONF_CAPTEUR_RAYONNEMENT,
    CONF_CAPTEUR_RETOUR_ARROSAGE,
    CONF_CAPTEUR_ROSEE,
    CONF_CAPTEUR_TEMPERATURE,
    CONF_CAPTEUR_VENT,
    CONF_ENTITE_METEO,
)

# Groupes de l'onglet Météo, dans l'ordre d'affichage.
GROUPES_SOURCES: tuple[tuple[str, str], ...] = (
    ("meteo", "Prévisions"),
    ("air", "L'air du jardin"),
    ("pluie", "La pluie"),
    ("sol", "Le sol et l'arrosage"),
)


@dataclass(frozen=True)
class Source:
    """Une entrée que l'utilisateur peut donner à l'intégration.

    `mesure` : une panne compte pour l'alerte « des mesures manquent » (une prévision ou une
    mesure faite à la main n'en fait pas partie). `numerique` : une valeur qui n'est pas un nombre
    est inutilisable. `indices` : des morceaux de nom qui trahissent, chez un appareil déjà
    branché, une entité capable de tenir ce rôle.

    Ce que la page accepte en changeant l'entrée (0.95.0), dans l'ordre de `refus` :
      · le `domaine` ;
      · jamais une unité de `unites_refusees` ni une classe de `classes_refusees` (`refus_explique`
        dit le danger) ;
      · une classe d'appareil de `classes` quand l'entité en déclare une (une batterie en % n'est
        pas une humidité) ;
      · jamais une classe d'état de `classes_etat_refusees` (`refus_classe_etat`) : un cumul ne dit
        pas « il pleut », une mesure de l'instant n'est pas la pluie du jour ;
      · une unité de `unites` (celles que le moteur lit ou convertit — vide : toutes), ou aucune
        unité si `sans_unite` ;
      · un nombre, quand l'entité donne déjà une valeur ;
      · si `exige_indice`, un nom qui dit le rôle (`refus_indice`) ; si `indice_sans_classe`,
        seulement quand l'entité ne déclare pas de classe ;
      · aucun mot de `noms_refuses` dans son nom (un point de rosée est une température, pas
        celle de l'air).
    """

    cle: str
    titre: str
    dans_une_phrase: str
    groupe: str
    apporte: str
    sans_elle: str
    mesure: bool = True
    numerique: bool = True
    indices: tuple[str, ...] = ()
    domaine: str = "sensor"
    obligatoire: bool = False
    unites: tuple[str, ...] = ()
    sans_unite: bool = False
    unites_refusees: tuple[str, ...] = ()
    classes_refusees: tuple[str, ...] = ()
    refus_explique: str = ""
    classes: tuple[str, ...] = ()
    classes_etat_refusees: tuple[str, ...] = ()
    refus_classe_etat: str = ""
    exige_indice: bool = False
    refus_indice: str = ""
    indice_sans_classe: bool = False
    noms_refuses: tuple[str, ...] = ()


# Le moteur ne convertit que ces unités (`water.pression_vers_hpa`, `water.wind_speed_to_kmh`) ;
# une autre y serait lue comme des hPa ou des km/h, sans un mot.
UNITES_VENT = ("km/h", "m/s", "mph", "kn", "kt")
UNITES_PRESSION = ("hPa", "mbar", "kPa", "Pa", "bar", "inHg", "mmHg")
UNITES_TEMPERATURE = ("°C", "°F", "K")
# La pluie du jour et le compteur ne sont ni une prévision, ni la dernière heure, ni une intensité.
MOTS_PAS_LA_PLUIE_DU_JOUR = ("demain", "tomorrow", "prevision", "forecast", "heure", "hour", "intensite", "intensity", "rate")

SOURCES: tuple[Source, ...] = (
    Source(
        CONF_ENTITE_METEO, "Entité météo", "l'entité météo", "meteo",
        "Température, humidité, vent, nuages et prévisions : la base de tout, et le repli de chaque mesure.",
        "Obligatoire : sans elle, l'intégration ne décide rien.",
        numerique=False,
        domaine="weather",
        obligatoire=True,
        sans_unite=True,
    ),
    Source(
        CONF_CAPTEUR_TEMPERATURE, "Température", "la température", "air",
        "La mesure du jardin, prioritaire sur la prévision.",
        "La température de l'entité météo.",
        # Lue telle quelle : des °F seraient pris pour des °C.
        unites=("°C",),
        classes=("temperature",),
        noms_refuses=(
            "rosee", "dew", "ressenti", "ressentie", "feels", "apparent", "apparente", "humidex",
            "refroidissement", "chill", "windchill", "heat", "sol", "soil",
        ),
    ),
    Source(
        CONF_CAPTEUR_HUMIDITE, "Humidité de l'air", "l'humidité de l'air", "air",
        "L'assèchement de l'air, qui pèse sur l'évaporation.",
        "L'humidité de l'entité météo.",
        unites=("%",),
        classes=("humidity",),
        indices=("humidite", "humidity", "hygrometrie"),
        indice_sans_classe=True,
        noms_refuses=("sol", "soil", "foliaire", "feuillage", "leaf"),
    ),
    Source(
        CONF_CAPTEUR_VENT, "Vent", "le vent", "air",
        "Prioritaire sur la prévision ; décide aussi si les graines peuvent être arrosées.",
        "Le vent prévu, souvent plus fort : une évaporation de 9 mm par jour au lieu de 6, mesuré.",
        unites=UNITES_VENT,
        classes=("wind_speed", "speed"),
        # Les rafales dépassent le vent moyen : les graines attendraient plus souvent, et
        # l'évaporation serait gonflée.
        noms_refuses=("rafale", "rafales", "gust", "gusts", "max", "maximum"),
    ),
    Source(
        CONF_CAPTEUR_RAYONNEMENT, "Rayonnement solaire", "le rayonnement solaire", "air",
        "Le plus déterminant pour l'évaporation heure par heure.",
        "Le soleil déduit des nuages, nettement moins fidèle.",
        # Des kW/m² diviseraient l'évaporation par cinq ; des lux ne sont pas un rayonnement.
        unites=("W/m²", "W/m2"),
        classes=("irradiance",),
    ),
    Source(
        CONF_CAPTEUR_PRESSION, "Pression", "la pression", "air",
        "Rend exact le calcul de l'évaporation.",
        "Une pression standard de 1013 hPa.",
        unites=UNITES_PRESSION,
        classes=("atmospheric_pressure", "pressure"),
    ),
    Source(
        # Point de ROSÉE DE L'AIR (0.97.24) — pas la même chose que « Rosée sur l'herbe » juste
        # au-dessous : ici une température (°C), là une humidité du feuillage (%). Sert de repli
        # à `estimate_rosee` (l'herbe est jugée mouillée si l'air est à 2 °C ou moins de ce point)
        # UNIQUEMENT quand « Rosée sur l'herbe » n'est pas branché ; sans lui, repli sur le point
        # de rosée de l'entité météo, moins fidèle au jardin.
        CONF_CAPTEUR_POINT_DE_ROSEE, "Point de rosée (air)", "le point de rosée", "air",
        "Affine la détection de l'herbe mouillée quand aucune « Rosée sur l'herbe » n'est branchée.",
        "Le point de rosée de l'entité météo.",
        unites=UNITES_TEMPERATURE,
        classes=("temperature",),
        indices=("rosee", "dew"),
        exige_indice=True,
        refus_indice=(
            "« Point de rosée (air) » attend un point de rosée, avec « rosée » ou « dew » dans "
            "son nom : une température de l'air ordinaire fausserait la détection de l'herbe "
            "mouillée."
        ),
    ),
    Source(
        # ⚠️ PAS UN POINT DE ROSÉE (0.94.1). Le moteur lit « au-dessus de 0 = l'herbe est mouillée »
        # (`decision_mowing`, `scores`) ; sans capteur, `estimate_rosee` rend 1 ou 0,8 quand
        # l'herbe est mouillée. Un point de rosée à 11 °C bloquerait la tonte en permanence : la
        # 0.94.0 le proposait pourtant, sur la foi du nom. La page le refuse (0.95.0).
        CONF_CAPTEUR_ROSEE, "Rosée sur l'herbe", "la rosée sur l'herbe", "air",
        "Un capteur d'humidité du feuillage. Ce n'est pas le point de rosée : au-dessus de 0, "
        "l'herbe est mouillée et la tonte attend.",
        "Une rosée estimée : air à moins de 2 °C de son point de rosée, humidité d'au moins 88 %, brouillard ou pluie.",
        indices=("foliaire", "feuillage", "leaf_wetness", "leaf_moisture"),
        unites_refusees=UNITES_TEMPERATURE,
        classes_refusees=("temperature",),
        sans_unite=True,
        refus_explique=(
            "« Rosée sur l'herbe » attend une humidité du feuillage, et ce capteur donne une "
            "température (un point de rosée). Branché ici, il ferait croire que l'herbe est "
            "toujours mouillée : la tonte ne partirait plus."
        ),
        classes=("moisture", "humidity"),
        # ⚠️ TOUTE mesure au-dessus de 0 dit « mouillée » : une humidité de l'air (63 %), une
        # batterie ou une pression bloqueraient la tonte pour toujours. Seul le nom le dit.
        exige_indice=True,
        refus_indice=(
            "« Rosée sur l'herbe » attend un capteur d'humidité du feuillage, avec « foliaire », "
            "« feuillage » ou « leaf wetness » dans son nom. Au-dessus de 0, l'herbe est tenue pour "
            "mouillée : une autre mesure la ferait croire toujours mouillée, et la tonte ne "
            "partirait plus."
        ),
    ),
    Source(
        CONF_CAPTEUR_PLUIE_CUMUL, "Compteur de pluie", "le compteur de pluie", "pluie",
        "La pluie du jour, recomptée sur l'horloge de l'intégration depuis un compteur qui ne repart jamais à zéro.",
        "La pluie du jour lue telle quelle sur le capteur de pluie du jour.",
        unites=("mm",),
        classes=("precipitation",),
        classes_etat_refusees=("measurement",),
        refus_classe_etat="« Compteur de pluie » attend un compteur, et ce capteur mesure l'instant.",
        noms_refuses=MOTS_PAS_LA_PLUIE_DU_JOUR,
    ),
    Source(
        CONF_CAPTEUR_PLUIE_24H, "Pluie du jour", "la pluie du jour", "pluie",
        "La pluie tombée, créditée à la réserve du sol.",
        "La prévision, jamais créditée au sol.",
        unites=("mm",),
        classes=("precipitation",),
        classes_etat_refusees=("measurement",),
        refus_classe_etat=(
            "« Pluie du jour » attend la pluie tombée depuis minuit, et ce capteur mesure l'instant."
        ),
        noms_refuses=MOTS_PAS_LA_PLUIE_DU_JOUR,
    ),
    Source(
        CONF_CAPTEUR_PLUIE_ACTUELLE, "Pluie en ce moment", "la pluie en ce moment", "pluie",
        "Répond directement à « pleut-il ? » : pas d'arrosage sous la pluie.",
        "Une pluie déduite des hausses du compteur.",
        # Seul compte « au-dessus de 0 ». Une unité est exigée : l'indice UV de la station n'en a
        # pas, et vaut 2 en plein jour — branché ici, il dirait « il pleut » jusqu'au soir.
        unites=("mm", "mm/h"),
        classes=("precipitation", "precipitation_intensity"),
        # ⚠️ Un CUMUL reste au-dessus de 0 toute la journée après une averse.
        classes_etat_refusees=("total", "total_increasing"),
        noms_refuses=("demain", "tomorrow"),
        refus_classe_etat=(
            "« Pluie en ce moment » attend une mesure de l'instant, et ce capteur est un cumul : "
            "après une averse, il dirait « il pleut » toute la journée, et l'arrosage attendrait."
        ),
    ),
    Source(
        CONF_CAPTEUR_PLUIE_DEMAIN, "Pluie de demain", "la pluie de demain", "pluie",
        "Reporte un arrosage si la pluie annoncée suffit.",
        "La prévision de l'entité météo.",
        mesure=False,
        unites=("mm",),
        classes=("precipitation",),
        # Un pluviomètre est aussi en mm : la pluie d'aujourd'hui reporterait les arrosages à tort.
        indices=("demain", "tomorrow", "prevision", "forecast"),
        exige_indice=True,
        refus_indice=(
            "« Pluie de demain » attend une prévision, avec « demain », « tomorrow » ou « prévision » "
            "dans son nom : la pluie d'aujourd'hui reporterait les arrosages à tort."
        ),
    ),
    Source(
        CONF_CAPTEUR_ETP, "Évaporation du jour (ETP)", "l'évaporation du jour", "sol",
        "Remplace le calcul d'évaporation de l'intégration.",
        "L'évaporation calculée par l'intégration.",
        indices=("etp", "evapotranspiration", "evaporation"),
        unites=("mm", "mm/d", "mm/j", "mm/day", "mm/jour"),
        classes=("precipitation", "distance"),
        exige_indice=True,
        refus_indice=(
            "« Évaporation du jour (ETP) » attend une évaporation, avec « ETP » ou « évapotranspiration » "
            "dans son nom : un pluviomètre, lui aussi en mm, remplacerait le calcul par la pluie."
        ),
    ),
    Source(
        CONF_CAPTEUR_HUMIDITE_SOL, "Humidité du sol", "l'humidité du sol", "sol",
        "Recoupe le bilan du sol.",
        "Le bilan du sol fait foi seul.",
        # ⚠️ À 70 % ou plus, la tonte attend : une humidité de l'air (souvent plus) la bloquerait.
        indices=("humidite_sol", "humidite_du_sol", "soil_moisture", "sol_humidite", "soil"),
        unites=("%",),
        classes=("moisture",),
        indice_sans_classe=True,
        noms_refuses=("foliaire", "feuillage", "leaf"),
    ),
    Source(
        CONF_CAPTEUR_HAUTEUR_GAZON, "Hauteur du gazon", "la hauteur du gazon", "sol",
        "La règle du tiers sur une mesure réelle.",
        "La hauteur estimée depuis la dernière tonte.",
        mesure=False,
        unites=("cm",),
        classes=("distance",),
        # Un niveau de cuve ou une épaisseur de neige sont aussi des distances en cm.
        indices=("hauteur", "herbe", "gazon", "pelouse", "grass", "lawn", "height"),
        exige_indice=True,
        refus_indice=(
            "« Hauteur du gazon » attend la hauteur de l'herbe, avec « hauteur », « herbe » ou « gazon » "
            "dans son nom : une autre distance en cm fausserait la règle du tiers."
        ),
    ),
    Source(
        CONF_CAPTEUR_RETOUR_ARROSAGE, "Retour d'arrosage", "le retour d'arrosage", "sol",
        "Confirme l'eau réellement versée.",
        "L'eau déduite de l'historique des vannes.",
        mesure=False,
        unites=("mm",),
        classes=("precipitation",),
        # Un pluviomètre ferait croire que l'arrosage a eu lieu.
        indices=("arrosage", "irrigation", "watering", "sprinkler"),
        exige_indice=True,
        refus_indice=(
            "« Retour d'arrosage » attend l'eau versée par l'arrosage, avec « arrosage » ou « irrigation » "
            "dans son nom : un pluviomètre ferait croire que l'arrosage a eu lieu."
        ),
    ),
)

PAR_CLE: dict[str, Source] = {s.cle: s for s in SOURCES}

ETATS_SANS_VALEUR = frozenset({"", "unavailable", "unknown", "none"})

_ATTENDUS = {"weather": "une entité météo (weather)", "sensor": "un capteur (sensor)"}


def valeur_utilisable(etat: Any, *, numerique: bool) -> bool:
    """Une valeur que l'intégration peut lire : présente, et un nombre quand il en faut un."""
    texte = str(etat if etat is not None else "").strip()
    if texte.lower() in ETATS_SANS_VALEUR:
        return False
    if not numerique:
        return True
    try:
        nombre = float(texte)
    except ValueError:
        return False
    return nombre == nombre  # NaN écarté


def _liste(unites: tuple[str, ...]) -> str:
    # « W/m2 » n'est qu'une autre écriture de « W/m² » : on ne la montre pas.
    vues = [u for u in unites if u != "W/m2"]
    return vues[0] if len(vues) == 1 else f"{', '.join(vues[:-1])} ou {vues[-1]}"


def _nom_normalise(texte: Any) -> str:
    """« Humidité foliaire » → « humidite_foliaire » : un nom d'entité ou d'affichage, comparable."""
    sans_accents = "".join(
        c for c in unicodedata.normalize("NFD", str(texte or "")) if unicodedata.category(c) != "Mn"
    )
    return "_".join(sans_accents.casefold().replace("-", " ").split())


def interdit(source: Source, *, unite: Any = None, classe: Any = None) -> bool:
    """Une entité que le moteur lirait forcément de travers, quel que soit son nom (0.96.0) :
    une unité de `unites_refusees` ou une classe de `classes_refusees` (un point de rosée pour la
    rosée sur l'herbe). Le moteur l'ignore, et « Configurer » la refuse aussi."""
    norme = str(unite or "").strip().casefold()
    genre = str(classe or "").strip().casefold()
    return norme in {u.casefold() for u in source.unites_refusees} or genre in source.classes_refusees


def refus(
    source: Source,
    *,
    entity_id: str,
    unite: Any = None,
    classe: Any = None,
    classe_etat: Any = None,
    nom: Any = None,
    etat: Any = None,
) -> str | None:
    """Pourquoi `entity_id` ne peut pas tenir le rôle de `source` ; `None` s'il le peut.

    `unite`, `classe`, `classe_etat`, `nom` : `unit_of_measurement`, `device_class`,
    `state_class` et `friendly_name` de son état ; `etat`, sa valeur du moment.
    """
    domaine = str(entity_id).split(".", 1)[0]
    if domaine != source.domaine:
        return f"« {source.titre} » attend {_ATTENDUS.get(source.domaine, source.domaine)}."
    texte = str(unite or "").strip()
    norme = texte.casefold()
    genre = str(classe or "").strip().casefold()
    if interdit(source, unite=unite, classe=classe):
        return source.refus_explique or f"« {source.titre} » ne peut pas lire ce capteur."
    if genre and source.classes and genre not in source.classes:
        return f"« {source.titre} » attend {source.dans_une_phrase}, et ce capteur mesure autre chose ({classe})."
    if str(classe_etat or "").strip().casefold() in source.classes_etat_refusees:
        return source.refus_classe_etat or f"« {source.titre} » ne peut pas lire ce capteur."
    if not norme:
        if not (source.sans_unite or not source.unites):
            return f"« {source.titre} » attend une mesure en {_liste(source.unites)}, et ce capteur n'a pas d'unité."
    elif source.unites and norme not in {u.casefold() for u in source.unites}:
        return f"« {source.titre} » attend une mesure en {_liste(source.unites)}, et ce capteur est en {texte}."
    valeur = str(etat if etat is not None else "").strip()
    if source.numerique and valeur.casefold() not in ETATS_SANS_VALEUR and not valeur_utilisable(valeur, numerique=True):
        return f"« {source.titre} » attend un nombre, et ce capteur donne « {valeur} »."
    nom_entite, nom_affiche = _nom_normalise(entity_id), _nom_normalise(nom)
    annonce = any(indice in nom_entite or indice in nom_affiche for indice in source.indices)
    if source.exige_indice and not annonce:
        return source.refus_indice or f"« {source.titre} » ne peut pas lire ce capteur."
    if source.indice_sans_classe and not genre and not annonce:
        return (
            f"« {source.titre} » attend {source.dans_une_phrase}, et ce capteur ne dit pas ce qu'il "
            "mesure : ni classe d'appareil, ni nom qui l'annonce."
        )
    mots = set(re.split(r"[._]", nom_entite)) | set(nom_affiche.split("_"))
    if any(mot in mots for mot in source.noms_refuses):
        return f"« {source.titre} » attend {source.dans_une_phrase}, et « {nom or entity_id} » mesure autre chose."
    return None


def exporter() -> list[dict[str, Any]]:
    """Pour la page et l'aperçu local : des listes plutôt que des tuples, comme après JSON."""
    return [
        {cle: list(valeur) if isinstance(valeur, tuple) else valeur for cle, valeur in asdict(s).items()}
        for s in SOURCES
    ]
