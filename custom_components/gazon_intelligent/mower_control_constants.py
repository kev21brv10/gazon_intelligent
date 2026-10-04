"""Constantes du pilote de tondeuse, sans dépendance Home Assistant."""

MOWER_CONTROL_MODES = ("desactive", "observation", "volet_seul", "actif")
# Mode « volet seul » : le volet suit l'état de la tondeuse, mais l'intégration ne la commande JAMAIS
# (ni départ, ni retour, ni reprise) : elle reste gérée par son appli et ses horaires.
MOWER_CONTROL_COVER_ONLY = "volet_seul"
DEFAULT_MOWER_CONTROL_MODE = "desactive"
MOWER_START_WINDOW_POLICIES = ("ideal_seulement", "ideal_acceptable", "tout_non_bloque")
DEFAULT_MOWER_START_WINDOW_POLICY = "ideal_seulement"
DEFAULT_MOWER_CONTROL_MIN_BATTERY = 100
DEFAULT_MOWER_CONTROL_COMMAND_COOLDOWN_MINUTES = 10
# Départ envoyé sans aucun signal frais après ce délai : purement diagnostique (le libellé
# affiché change), ne relance rien et n'annule rien — la commande reste due tant qu'aucun
# signal frais ne l'a confirmée.
MOWER_MANAGED_START_TIMEOUT_MINUTES = 15
# Un travail inachevé (recharge à mi-travail) garde le volet ouvert au plus ce temps après la rentrée :
# la recharge dure environ 70 min ; passé ce délai, un vieux travail abandonné ne doit pas bloquer
# la fermeture pour toujours.
MOWER_JOB_HOLD_MAX_MINUTES = 180
DEFAULT_MOWER_GARAGE_OPEN_BEFORE_START = True
DEFAULT_MOWER_GARAGE_OPEN_FOR_RETURN = True
DEFAULT_MOWER_GARAGE_CLOSE_AFTER_DOCK = True
DEFAULT_MOWER_GARAGE_OPEN_LEAD_MINUTES = 2
DEFAULT_MOWER_GARAGE_MIN_OPEN_POSITION = 95
DEFAULT_MOWER_GARAGE_CLOSE_DELAY_MINUTES = 2
