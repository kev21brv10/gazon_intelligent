DOMAIN = "gazon_intelligent"

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
CONF_CAPTEUR_PLUIE_DEMAIN = "capteur_pluie_demain"
CONF_CAPTEUR_HUMIDITE = "capteur_humidite"
CONF_CAPTEUR_HUMIDITE_SOL = "capteur_humidite_sol"
CONF_CAPTEUR_VENT = "capteur_vent"
CONF_CAPTEUR_ROSEE = "capteur_rosee"
CONF_CAPTEUR_HAUTEUR_GAZON = "capteur_hauteur_gazon"
CONF_CAPTEUR_RETOUR_ARROSAGE = "capteur_retour_arrosage"
CONF_CAPTEUR_TEMPERATURE = "capteur_temperature"
CONF_CAPTEUR_ETP = "capteur_etp"
CONF_HAUTEUR_MIN_TONDEUSE_CM = "hauteur_min_tondeuse_cm"
CONF_HAUTEUR_MAX_TONDEUSE_CM = "hauteur_max_tondeuse_cm"
CONF_TYPE_SOL = "type_sol"

DEFAULT_MODE = "Normal"
DEFAULT_TYPE_SOL = "limoneux"
DEFAULT_HAUTEUR_MIN_TONDEUSE_CM = 3.0
DEFAULT_HAUTEUR_MAX_TONDEUSE_CM = 8.0
DEFAULT_APPLICATION_POST_WATERING_MM = 1.0
DEFAULT_APPLICATION_IRRIGATION_BLOCK_HOURS = 24.0
DEFAULT_APPLICATION_IRRIGATION_DELAY_MINUTES = 0.0
DEFAULT_APPLICATION_IRRIGATION_MODE = "auto"
DEFAULT_AUTO_IRRIGATION_ENABLED = True

APPLICATION_TYPE_SOL = "sol"
APPLICATION_TYPE_FOLIAIRE = "foliaire"
APPLICATION_IRRIGATION_MODE_AUTO = "auto"
APPLICATION_IRRIGATION_MODE_MANUAL = "manuel"
APPLICATION_IRRIGATION_MODE_SUGGESTION = "suggestion"

WATERING_SESSION_MIN_DURATION_SECONDS = 30
WATERING_SESSION_END_GRACE_SECONDS = 15
WATERING_SESSION_MIN_SEGMENT_SECONDS = 5

TYPES_SOL = [
    "sableux",
    "limoneux",
    "argileux",
]

INTERVENTIONS_ACTIONS = [
    "Sursemis",
    "Traitement",
    "Fertilisation",
    "Biostimulant",
    "Agent Mouillant",
    "Scarification",
    "Hivernage",
]

APPLICATION_INTERVENTIONS = [
    "Traitement",
    "Fertilisation",
    "Biostimulant",
    "Agent Mouillant",
    "Scarification",
]

APPLICATION_IRRIGATION_MODES = [
    APPLICATION_IRRIGATION_MODE_AUTO,
    APPLICATION_IRRIGATION_MODE_MANUAL,
    APPLICATION_IRRIGATION_MODE_SUGGESTION,
]

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

PRODUCT_USAGE_MODES = [
    "preventif",
    "curatif",
    "entretien",
    "rattrapage",
]

MODES_GAZON = [
    "Normal",
    "Sursemis",
    "Traitement",
    "Fertilisation",
    "Biostimulant",
    "Agent Mouillant",
    "Scarification",
    "Hivernage",
]
