from .phases import PHASE_DURATIONS_DAYS

DOMAIN = "gazon_intelligent"
CONF_INSTANCE_SLUG = "instance_slug"

CONF_ZONE_1 = "zone_1"
CONF_ZONE_2 = "zone_2"
CONF_ZONE_3 = "zone_3"
CONF_ZONE_4 = "zone_4"
CONF_ZONE_5 = "zone_5"
CONF_DEBIT_ZONE_1 = "debit_zone_1"
CONF_DEBIT_ZONE_2 = "debit_zone_2"
CONF_DEBIT_ZONE_3 = "debit_zone_3"
CONF_DEBIT_ZONE_4 = "debit_zone_4"
CONF_DEBIT_ZONE_5 = "debit_zone_5"
CONF_ENTITE_METEO = "entite_meteo"
CONF_CAPTEUR_PLUIE_24H = "capteur_pluie_24h"
# Pluie INSTANTANÉE (mm sur le dernier relevé, ou mm/h). Non nulle seulement PENDANT l'averse.
# ⚠️ Rien à voir avec `capteur_pluie_24h`, qui est un CUMUL : 3,6 mm y restent affichés toute la
# journée après la pluie. C'est de cette confusion que viennent le détecteur de hausse, le
# cliquet et leurs défauts — on approximait « pleut-il ? » à partir d'un total.
# Netatmo : `sensor.<station>_precipitation`. Ecowitt/Shelly WS90 : `rain_rate`.
CONF_CAPTEUR_PLUIE_ACTUELLE = "capteur_pluie_actuelle"
CONF_CAPTEUR_PLUIE_DEMAIN = "capteur_pluie_demain"
CONF_CAPTEUR_HUMIDITE = "capteur_humidite"
CONF_CAPTEUR_HUMIDITE_SOL = "capteur_humidite_sol"
CONF_CAPTEUR_VENT = "capteur_vent"
CONF_CAPTEUR_ROSEE = "capteur_rosee"
CONF_CAPTEUR_HAUTEUR_GAZON = "capteur_hauteur_gazon"
CONF_CAPTEUR_RETOUR_ARROSAGE = "capteur_retour_arrosage"
CONF_CAPTEUR_TEMPERATURE = "capteur_temperature"
CONF_CAPTEUR_ETP = "capteur_etp"
# ET0 HORAIRE FAO-56 Eq. 53 (`water.compute_eto_hourly`, appelée par coordinator) : rayonnement
# global mesuré (W/m², ex. Open-Meteo) et pression atmosphérique mesurée (hPa, ex. station perso).
# Sans eux → replis (rayonnement déduit de la couverture nuageuse, pression standard 1013 hPa),
# nettement moins précis. Ces deux entrées ne concernent PAS `water.compute_etp` (ET0 journalière,
# qui ne les lit pas) : elles pilotent l'ET horaire intégrée par le bilan sol depuis la 0.19.0.
CONF_CAPTEUR_RAYONNEMENT = "capteur_rayonnement"
CONF_CAPTEUR_PRESSION = "capteur_pression"
CONF_ENTITE_TONDEUSE = "entite_tondeuse"
CONF_CAPTEUR_TONDEUSE_ERREUR = "capteur_tondeuse_erreur"
CONF_CAPTEUR_TONDEUSE_BATTERIE = "capteur_tondeuse_batterie"
CONF_CAPTEUR_TONDEUSE_PLUIE = "capteur_tondeuse_pluie"
CONF_CAPTEUR_TONDEUSE_EN_CHARGE = "capteur_tondeuse_en_charge"
CONF_CAPTEUR_TONDEUSE_PROCHAIN_DEPART = "capteur_tondeuse_prochain_depart"
CONF_CAPTEUR_TONDEUSE_HAUTEUR_COUPE = "capteur_tondeuse_hauteur_coupe"
CONF_HAUTEUR_COUPE_TONDEUSE_MM = "hauteur_coupe_tondeuse_mm"
CONF_HAUTEUR_MIN_TONDEUSE_CM = "hauteur_min_tondeuse_cm"
CONF_HAUTEUR_MAX_TONDEUSE_CM = "hauteur_max_tondeuse_cm"
CONF_TYPE_SOL = "type_sol"

SHARED_WEATHER_CONFIG_KEYS = frozenset(
    {
        CONF_ENTITE_METEO,
        CONF_CAPTEUR_PLUIE_24H,
        CONF_CAPTEUR_PLUIE_ACTUELLE,
        CONF_CAPTEUR_PLUIE_DEMAIN,
        CONF_CAPTEUR_TEMPERATURE,
        CONF_CAPTEUR_ETP,
        CONF_CAPTEUR_HUMIDITE,
        CONF_CAPTEUR_VENT,
        CONF_CAPTEUR_ROSEE,
        CONF_CAPTEUR_RAYONNEMENT,
        CONF_CAPTEUR_PRESSION,
    }
)

# Kc gazon de référence en phase Normal (FAO-56). Sert de REPLI quand le Kc réel du cycle n'est
# pas disponible (bilan sol au démarrage) et de valeur TYPIQUE pour dimensionner le garde-fou
# hebdomadaire. Partagé pour éviter deux 0,8 indépendants qui divergeraient en silence.
# ⚠️ Le Kc RÉEL peut dépasser cette valeur : `compute_kc_gazon` ajoute un bonus post-tonte
# (+15 % pendant 8 jours), soit 0,92 en permanence avec une tondeuse robot.
KC_GAZON_NORMAL_DEFAUT = 0.8

DEFAULT_MODE = "Normal"
DEFAULT_TYPE_SOL = "limoneux"
DEFAULT_HAUTEUR_MIN_TONDEUSE_CM = 3.0
DEFAULT_HAUTEUR_MAX_TONDEUSE_CM = 8.0
DEFAULT_APPLICATION_POST_WATERING_MM = 1.0
DEFAULT_APPLICATION_IRRIGATION_BLOCK_HOURS = 24.0
DEFAULT_APPLICATION_IRRIGATION_DELAY_MINUTES = 0.0
DEFAULT_APPLICATION_IRRIGATION_MODE = "auto"
DEFAULT_AUTO_IRRIGATION_ENABLED = False
DEFAULT_MOWER_COORDINATION_ENABLED = False
DEFAULT_EVENING_COOLING_ENABLED = True
DEFAULT_MOWING_COOLDOWN_AFTER_WATERING_MINUTES = 180

# ⚠️ AUTO-DÉCLARATION DE LA TONTE — désactivée par défaut, comme les deux autres automatismes
# ci-dessus. Une déclaration est une ÉCRITURE dans l'historique : sur une installation neuve
# dont la tondeuse n'est pas encore correctement câblée, mieux vaut ne rien inscrire du tout.
#
# Le seuil de 90 min reprend celui que le flow Node-RED appliquait à 23:50. Il ne s'agit PAS
# d'une durée de tonte « normale » mais d'un plancher de crédibilité : en dessous, le robot est
# sorti sans faire le tour du jardin (sortie avortée, demi-tour immédiat), et compter ça comme
# une tonte ferait repartir le compteur de retard à tort.
DEFAULT_AUTO_MOWING_DECLARATION_ENABLED = False
DEFAULT_AUTO_MOWING_DECLARATION_MINUTES = 90

WATERING_STRATEGY_ADULT_DEEP = "adult_deep"
WATERING_STRATEGY_SEMIS_FREQUENT = "semis_frequent"

OBJECTIVE_SCOPE_GLOBAL_SURFACE = "global_surface"
OBJECTIVE_SCOPE_SURFACE_CYCLE = "surface_cycle"

WATERING_STAGE_NORMAL = "normal"
WATERING_STAGE_GERMINATION = "germination"
WATERING_STAGE_LEVEE = "levee"
WATERING_STAGE_ENRACINEMENT = "enracinement"

APPLICATION_TYPE_SOL = "sol"
APPLICATION_TYPE_FOLIAIRE = "foliaire"
APPLICATION_IRRIGATION_MODE_AUTO = "auto"
APPLICATION_IRRIGATION_MODE_MANUAL = "manuel"
APPLICATION_IRRIGATION_MODE_SUGGESTION = "suggestion"

WATERING_SESSION_MIN_DURATION_SECONDS = 30
WATERING_SESSION_END_GRACE_SECONDS = 15
WATERING_SESSION_MIN_SEGMENT_SECONDS = 5

TYPES_SOL = (
    "sableux",
    "limoneux",
    "argileux",
)

INTERVENTIONS_ACTIONS = (
    "Sursemis",
    "Traitement",
    "Fertilisation",
    "Biostimulant",
    "Agent Mouillant",
    "Scarification",
    "Hivernage",
)

APPLICATION_INTERVENTIONS = (
    "Traitement",
    "Fertilisation",
    "Biostimulant",
    "Agent Mouillant",
    "Scarification",
)

APPLICATION_IRRIGATION_MODES = (
    APPLICATION_IRRIGATION_MODE_AUTO,
    APPLICATION_IRRIGATION_MODE_MANUAL,
    APPLICATION_IRRIGATION_MODE_SUGGESTION,
)

APPLICATION_IRRIGATION_MODE_ALIASES = {
    "auto": APPLICATION_IRRIGATION_MODE_AUTO,
    "manual": APPLICATION_IRRIGATION_MODE_MANUAL,
    "manuel": APPLICATION_IRRIGATION_MODE_MANUAL,
    "suggestion": APPLICATION_IRRIGATION_MODE_SUGGESTION,
}

POST_APPLICATION_STATUS_INDISPONIBLE = "indisponible"
POST_APPLICATION_STATUS_NON_REQUIS = "non_requis"
POST_APPLICATION_STATUS_EN_ATTENTE = "en_attente"
POST_APPLICATION_STATUS_AUTORISE = "autorise"
POST_APPLICATION_STATUS_TERMINE = "termine"
POST_APPLICATION_STATUS_BLOQUE = "bloque"

POST_APPLICATION_STATUSES = frozenset(
    {
        POST_APPLICATION_STATUS_INDISPONIBLE,
        POST_APPLICATION_STATUS_NON_REQUIS,
        POST_APPLICATION_STATUS_EN_ATTENTE,
        POST_APPLICATION_STATUS_AUTORISE,
        POST_APPLICATION_STATUS_TERMINE,
        POST_APPLICATION_STATUS_BLOQUE,
    }
)

POST_APPLICATION_STATUS_ALIASES = {
    "non_autorise": POST_APPLICATION_STATUS_TERMINE,
}

IRRIGATION_REASON_KIND_NO_NEED = "no_need"
IRRIGATION_REASON_KIND_WAITING = "waiting"
IRRIGATION_REASON_KIND_BLOCKED = "blocked"
IRRIGATION_REASON_KIND_BLOCKED_DUE_TO_CONDITIONS = "blocked_due_to_conditions"
IRRIGATION_REASON_KIND_POST_APPLICATION = "post_application"
IRRIGATION_REASON_KIND_HYDRIC_NEED = "hydric_need"
IRRIGATION_REASON_KIND_PHASE_SUPPORT = "phase_support"

IRRIGATION_ACTION_LABEL_NONE = "Aucune action"
IRRIGATION_ACTION_LABEL_WAIT = "Attendre"
IRRIGATION_ACTION_LABEL_POST_APPLICATION = "Arrosage post-application"
IRRIGATION_ACTION_LABEL_NOW = "Arroser maintenant"
IRRIGATION_ACTION_LABEL_AUTO = "Arrosage automatique"

PRODUCT_USAGE_MODES = (
    "preventif",
    "curatif",
    "entretien",
    "rattrapage",
)

MODES_GAZON = tuple(PHASE_DURATIONS_DAYS.keys())

# Valeur interne produite par le snapshot/brain (legacy)
PLUIE_SOURCE_INDISPONIBLE = "indisponible"
# Valeur publique exposée dans les attributs Home Assistant
PLUIE_SOURCE_NON_DISPONIBLE = "non disponible"

# Libellés lisibles des raisons de blocage (arrosage/tonte). Source UNIQUE partagée par
# sensor.py et binary_sensor.py — auparavant dupliquée et divergente (binary_sensor en avait
# une version incomplète → certains motifs s'affichaient en snake_case brut).
BLOCK_REASON_DISPLAY_LABELS: dict[str, str] = {
    "pluie_prevue_suffisante": "Pluie prévue suffisante",
    "temperature_trop_basse": "Température trop basse",
    "arrosage_recent": "Arrosage récent",
    "sol_deja_humide": "Sol déjà humide",
    "sol_non_adapte": "Sol non adapté",
    "pluie_probabilite_elevee": "Pluie probable élevée",
    "surface_non_seche": "Surface non sèche",
    "cooldown_24h": "Déjà arrosé aujourd'hui",
    "humidite_excessive": "Humidité excessive",
    "humidite_elevee": "Humidité élevée",
    "garde_fou_hebdomadaire": "Garde-fou hebdomadaire",
    "mode_bloque": "Mode bloqué",
    "pluie_active": "Pluie active",
    "bloque": "Bloqué",
    "mower_mowing": "Tondeuse en cours de tonte",
    "mower_returning": "Tondeuse en retour station",
    "mower_starting": "Tondeuse en démarrage",
    "mower_zoning": "Tondeuse en changement de zone",
    "mower_searching_zone": "Tondeuse en recherche de zone",
    "mower_rain_delayed": "Pause pluie active",
    "mower_escaped_digital_fence": "Tondeuse sortie du périmètre",
    "mower_not_stowed": "Tondeuse non rangée",
    "mower_unreliable": "Coordination tondeuse indisponible",
    "post_application_active": "Post-produit actif",
    "watering_in_progress": "Arrosage en cours",
    "watering_cooldown": "Cooldown tonte après arrosage",
    "application_foliaire": "Application foliaire en cours",
    "temperature_trop_basse_germination": "Température trop basse (germination)",
    "semis_cycle_daily_target_reached": "Objectif du jour atteint (semis)",
    "semis_cycle_pending": "Cycle de semis en attente",
    # ⚠️ Ces six codes étaient PUBLIÉS sans libellé : ils s'affichaient en snake_case brut sur
    # la carte et dans les attributs. Relevé à l'audit du 06/08/2026 en comparant les codes
    # réellement émis par decision_mowing / guidance / decision_watering à cette table.
    "machine_unavailable": "Robot indisponible",
    "mowing_window_blocked": "Hors fenêtre de tonte",
    "recent_watering": "Arrosage récent",
    "soil_wet": "Sol détrempé",
    "upcoming_watering": "Arrosage imminent",
    "wet_grass": "Herbe mouillée",
}
