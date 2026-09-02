from __future__ import annotations

import unittest
from datetime import datetime
from pathlib import Path
import sys
import types
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "custom_components" / "gazon_intelligent"
TEST_TZ = ZoneInfo("Europe/Paris")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def _ensure_package(name: str, path: Path) -> None:
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    module.__path__ = [str(path)]  # type: ignore[attr-defined]
    sys.modules[name] = module


_ensure_package("custom_components", PACKAGE_DIR.parent)
_ensure_package("custom_components.gazon_intelligent", PACKAGE_DIR)

homeassistant = types.ModuleType("homeassistant")
homeassistant.__path__ = []  # type: ignore[attr-defined]
sys.modules.setdefault("homeassistant", homeassistant)
util = types.ModuleType("homeassistant.util")
util.__path__ = []  # type: ignore[attr-defined]
sys.modules.setdefault("homeassistant.util", util)
dt_module = types.ModuleType("homeassistant.util.dt")
dt_module.now = lambda: datetime(2026, 4, 4, 14, 15, tzinfo=TEST_TZ)  # type: ignore[attr-defined]
sys.modules.setdefault("homeassistant.util.dt", dt_module)

from custom_components.gazon_intelligent.mower_adapter import build_mower_context, derive_related_entity_id


class MowerAdapterTests(unittest.TestCase):
    def test_build_mower_context_maps_idle_mower_to_ready_rest_state(self) -> None:
        payload = build_mower_context(
            entity_id="lawn_mower.esperance_jr",
            entity_name="Esperance Jr",
            raw_state="docked",
            available=True,
            charging=False,
            rain=False,
            error_raw="no_error",
            battery_percent=44,
            next_schedule_raw="2026-04-16T13:00:00+02:00",
            cutting_height_mm=40,
        )

        self.assertEqual(payload["tondeuse_statut"], "au_repos")
        self.assertEqual(payload["tondeuse_statut_libelle"], "À la station")
        self.assertTrue(payload["tondeuse_prete"])
        self.assertEqual(payload["tondeuse_batterie"], 44)
        self.assertEqual(payload["tondeuse_hauteur_coupe_mm"], 40)
        self.assertEqual(payload["tondeuse_prochain_depart"], "2026-04-16T13:00:00+02:00")

    def test_un_etat_error_sans_code_n_invente_PAS_de_panne(self) -> None:
        """⚠️ MESURÉ SUR L'INSTALLATION LE 02/09/2026 À 01:26.

        Le robot est resté en `error` plusieurs minutes pour une MISE À JOUR de firmware
        (tête caméra 2.5.6+7 → 2.5.7+12 à 01:28:59, sortie de l'état quatre secondes plus
        tard), pendant que `sensor.…_erreur` affichait `no_error` DU DÉBUT À LA FIN.

        Le repli inventait « Erreur tondeuse. » — une panne que la machine avait explicitement
        démentie — et ce texte remontait jusqu'au libellé de blocage, donc aux notifications.
        """
        payload = build_mower_context(
            entity_id="lawn_mower.esperance_jr",
            entity_name="Esperance Jr",
            raw_state="error",
            available=True,
            charging=False,
            rain=False,
            error_raw="no_error",
            battery_percent=100,
            cutting_height_mm=55,
        )
        self.assertEqual(payload["tondeuse_statut"], "erreur",
                         "prémisse : l'état brut doit encore mener au statut bloquant")
        self.assertFalse(payload["tondeuse_prete"], "le blocage a disparu avec le libellé")
        self.assertNotIn(
            "Erreur tondeuse", payload["tondeuse_raison"],
            "une panne est affirmée alors que la machine dit `no_error`",
        )
        self.assertIn("aucun code d'erreur", payload["tondeuse_raison"])

    def test_un_VRAI_code_d_erreur_garde_son_libelle(self) -> None:
        """L'autre sens : sans ce test, le correctif rendrait toute panne réelle muette."""
        payload = build_mower_context(
            entity_id="lawn_mower.esperance_jr",
            entity_name="Esperance Jr",
            raw_state="error",
            available=True,
            error_raw="blade_blocked",
        )
        self.assertEqual(payload["tondeuse_statut"], "erreur")
        self.assertNotIn("aucun code d'erreur", payload["tondeuse_raison"],
                         "un code d'erreur réel est présenté comme une absence de code")
        self.assertTrue(payload["tondeuse_raison"].strip(), "la raison est vide")

    def test_build_mower_context_formats_departure_in_local_time(self) -> None:
        payload = build_mower_context(
            entity_id="lawn_mower.esperance_jr",
            entity_name="Esperance Jr",
            raw_state="docked",
            available=True,
            next_schedule_raw="2026-04-18T11:00:00+00:00",
        )

        self.assertEqual(payload["tondeuse_prochain_depart"], "2026-04-18T11:00:00+00:00")
        self.assertEqual(payload["tondeuse_prochain_depart_display"], "18/04/2026 à 13:00")

    def test_build_mower_context_prioritizes_error_and_rain_signals(self) -> None:
        payload = build_mower_context(
            entity_id="lawn_mower.robot",
            entity_name="Robot",
            raw_state="docked",
            available=True,
            charging=False,
            rain=True,
            error_raw="rain_delay",
        )
        self.assertEqual(payload["tondeuse_statut"], "pluie")
        self.assertFalse(payload["tondeuse_prete"])

        payload = build_mower_context(
            entity_id="lawn_mower.robot",
            entity_name="Robot",
            raw_state="mowing",
            available=True,
            charging=False,
            rain=False,
            error_raw="wire_missing",
        )
        self.assertEqual(payload["tondeuse_statut"], "erreur")
        self.assertEqual(payload["tondeuse_erreur"], "wire_missing")
        self.assertEqual(payload["tondeuse_erreur_libelle"], "Fil périmétrique manquant")
        self.assertFalse(payload["tondeuse_prete"])

    def test_build_mower_context_ignore_les_capteurs_indisponibles(self) -> None:
        # RÉGRESSION (28/07/2026) : `unavailable`/`unknown` sont des ABSENCES de mesure, pas des
        # valeurs. Le capteur d'erreur indisponible était lu comme un CODE d'erreur → la tonte
        # se bloquait sur « Robot en erreur : défaut signalé » alors que le robot allait bien.
        # Et l'heure du prochain départ s'affichait littéralement « unavailable » en attribut.
        # Cas quotidien : la plupart des intégrations de tondeuse republient leurs capteurs en
        # `unavailable` à chaque redémarrage de Home Assistant.
        for absent in ("unavailable", "unknown"):
            payload = build_mower_context(
                entity_id="lawn_mower.esperance_jr",
                entity_name="Esperance Jr",
                raw_state="docked",
                available=True,
                error_raw=absent,
                next_schedule_raw=absent,
            )
            # Aucun code d'erreur retenu (la clé est simplement absente du payload).
            self.assertIsNone(payload.get("tondeuse_erreur"), f"« {absent} » n'est pas une panne")
            self.assertNotEqual(payload.get("tondeuse_statut"), "erreur")
            self.assertTrue(payload.get("tondeuse_prete"))
            # Aucun libellé technique ne doit remonter tel quel jusqu'à l'affichage.
            self.assertNotEqual(payload.get("tondeuse_prochain_depart"), absent)
            self.assertNotEqual(payload.get("tondeuse_prochain_depart_display"), absent)

    def test_build_mower_context_keeps_landroid_activity_labels(self) -> None:
        payload = build_mower_context(
            entity_id="lawn_mower.robot",
            entity_name="Robot",
            raw_state="zoning",
            available=True,
        )

        self.assertEqual(payload["tondeuse_statut"], "inconnu")
        self.assertEqual(payload["tondeuse_statut_libelle"], "Changement de zone")

        payload = build_mower_context(
            entity_id="lawn_mower.robot",
            entity_name="Robot",
            raw_state="searching_zone",
            available=True,
        )

        self.assertEqual(payload["tondeuse_statut_libelle"], "Recherche de zone")

    def test_derive_related_entity_id_uses_mower_prefix(self) -> None:
        self.assertEqual(
            derive_related_entity_id("lawn_mower.esperance_jr", "sensor", "batterie"),
            "sensor.esperance_jr_batterie",
        )
        self.assertEqual(
            derive_related_entity_id("lawn_mower.esperance_jr", "binary_sensor", "en_charge"),
            "binary_sensor.esperance_jr_en_charge",
        )
        self.assertIsNone(derive_related_entity_id(None, "sensor", "batterie"))


if __name__ == "__main__":
    unittest.main()
