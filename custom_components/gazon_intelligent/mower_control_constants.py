"""Constantes du pilote de tondeuse, sans dépendance Home Assistant."""

MOWER_CONTROL_MODES = ("desactive", "observation", "actif")
DEFAULT_MOWER_CONTROL_MODE = "desactive"
MOWER_START_WINDOW_POLICIES = ("ideal_seulement", "ideal_acceptable", "tout_non_bloque")
DEFAULT_MOWER_START_WINDOW_POLICY = "ideal_seulement"
DEFAULT_MOWER_CONTROL_MIN_BATTERY = 100
DEFAULT_MOWER_CONTROL_COMMAND_COOLDOWN_MINUTES = 10
# Départ envoyé sans signal frais après ce délai : libère l'attente et autorise
# une nouvelle tentative au cycle suivant, sous les mêmes gardes de sécurité.
MOWER_MANAGED_START_TIMEOUT_MINUTES = 15
DEFAULT_MOWER_GARAGE_OPEN_BEFORE_START = True
DEFAULT_MOWER_GARAGE_OPEN_FOR_RETURN = True
DEFAULT_MOWER_GARAGE_CLOSE_AFTER_DOCK = True
DEFAULT_MOWER_GARAGE_OPEN_LEAD_MINUTES = 2
DEFAULT_MOWER_GARAGE_MIN_OPEN_POSITION = 95
DEFAULT_MOWER_GARAGE_CLOSE_DELAY_MINUTES = 2
