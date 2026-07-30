from __future__ import annotations

import unittest
from pathlib import Path
import sys
import types


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "custom_components" / "gazon_intelligent"
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

from custom_components.gazon_intelligent.mower_adapter import build_mower_context
from custom_components.gazon_intelligent.mower_coordination import build_mower_coordination_context


class MowerCoordinationTests(unittest.TestCase):
    def test_charging_is_considered_safe_for_watering(self) -> None:
        payload = build_mower_coordination_context(
            {
                "tondeuse_source_entity": "lawn_mower.robot",
                "tondeuse_connectee": True,
                "tondeuse_etat_brut": "charging",
                "tondeuse_statut": "en_charge",
                "tondeuse_en_charge": True,
            },
            enabled=True,
        )

        self.assertTrue(payload["mower_coordination_ready"])
        self.assertEqual(payload["mower_operation_state"], "charging")
        self.assertEqual(payload["mower_presence_state"], "dockee")
        self.assertTrue(payload["mower_is_safe_for_watering"])

    def test_idle_counts_as_stowed_when_mower_is_resting(self) -> None:
        payload = build_mower_coordination_context(
            {
                "tondeuse_source_entity": "lawn_mower.robot",
                "tondeuse_connectee": True,
                "tondeuse_etat_brut": "idle",
                "tondeuse_statut": "au_repos",
            },
            enabled=True,
        )

        self.assertTrue(payload["mower_coordination_ready"])
        self.assertEqual(payload["mower_presence_state"], "dockee")
        self.assertTrue(payload["mower_is_safe_for_watering"])
        self.assertEqual(payload["mower_reason_code"], "none")

    def test_edgecut_counts_as_mowing_outside(self) -> None:
        payload = build_mower_coordination_context(
            {
                "tondeuse_source_entity": "lawn_mower.robot",
                "tondeuse_connectee": True,
                "tondeuse_etat_brut": "edgecut",
                "tondeuse_statut": "tonte_en_cours",
            },
            enabled=True,
        )

        self.assertTrue(payload["mower_coordination_ready"])
        self.assertEqual(payload["mower_operation_state"], "tonte")
        self.assertEqual(payload["mower_operation_label"], "Coupe des bordures")
        self.assertEqual(payload["mower_presence_state"], "dehors")
        self.assertFalse(payload["mower_is_safe_for_watering"])
        self.assertEqual(payload["mower_reason_code"], "mower_mowing")
        self.assertEqual(payload["mower_reason_label"], "Tondeuse en cours de tonte.")

    def test_zoning_and_rain_delay_are_exposed_with_specific_labels(self) -> None:
        payload = build_mower_coordination_context(
            {
                "tondeuse_source_entity": "lawn_mower.robot",
                "tondeuse_connectee": True,
                "tondeuse_etat_brut": "zoning",
                "tondeuse_statut": "inconnu",
            },
            enabled=True,
        )

        self.assertEqual(payload["mower_operation_state"], "zoning")
        self.assertEqual(payload["mower_operation_label"], "Changement de zone")
        self.assertEqual(payload["mower_reason_code"], "mower_zoning")

        payload = build_mower_coordination_context(
            {
                "tondeuse_source_entity": "lawn_mower.robot",
                "tondeuse_connectee": True,
                "tondeuse_etat_brut": "rain_delayed",
                "tondeuse_statut": "pluie",
            },
            enabled=True,
        )

        self.assertEqual(payload["mower_operation_state"], "rain_delayed")
        self.assertEqual(payload["mower_operation_label"], "Pause pluie")
        self.assertEqual(payload["mower_reason_code"], "mower_rain_delayed")

    def test_edgecut_keeps_specific_status_label(self) -> None:
        payload = build_mower_context(
            entity_id="lawn_mower.robot",
            entity_name="Robot",
            raw_state="edgecut",
            available=True,
        )

        self.assertEqual(payload["tondeuse_statut"], "tonte_en_cours")
        self.assertEqual(payload["tondeuse_statut_libelle"], "Coupe des bordures")

    def test_disabled_coordination_neutralizes_constraints(self) -> None:
        payload = build_mower_coordination_context({}, enabled=False)

        self.assertTrue(payload["mower_coordination_ready"])
        self.assertTrue(payload["mower_is_safe_for_watering"])
        self.assertEqual(payload["mower_reason_code"], "disabled")


if __name__ == "__main__":
    unittest.main()


from custom_components.gazon_intelligent import mower_coordination as _mc


class MowingBeatsChargingTests(unittest.TestCase):
    """Le test « en charge » passait AVANT le test de tonte. Au démarrage d'une session, le
    capteur binaire « en charge » reste à True quelques minutes (latence observée jusqu'à 8 min
    le 18/07) alors que l'état brut de l'appareil dit déjà `mowing` : la tondeuse était alors
    classée « à la station », la coordination anti-collision silencieusement neutralisée, et
    l'arrosage pouvait partir sur une tondeuse en pleine tonte."""

    def _state(self, **ctx):
        base = {"tondeuse_connectee": True}
        base.update(ctx)
        return _mc._operation_state(base)

    def test_letat_brut_mowing_prime_sur_le_capteur_de_charge(self) -> None:
        self.assertEqual(
            self._state(tondeuse_etat_brut="mowing", tondeuse_en_charge=True),
            "tonte",
        )

    def test_tonte_detectee_sans_capteur_de_charge(self) -> None:
        self.assertEqual(self._state(tondeuse_etat_brut="mowing"), "tonte")

    def test_a_la_station_reste_en_charge(self) -> None:
        self.assertEqual(
            self._state(tondeuse_etat_brut="docked", tondeuse_en_charge=True),
            "charging",
        )

    def test_charge_declaree_par_letat_brut(self) -> None:
        self.assertEqual(self._state(tondeuse_etat_brut="charging"), "charging")

    def test_statut_tonte_en_cours_reste_reconnu(self) -> None:
        self.assertEqual(self._state(tondeuse_statut="tonte_en_cours"), "tonte")

    def test_deconnectee_reste_inconnue(self) -> None:
        self.assertEqual(
            _mc._operation_state({"tondeuse_connectee": False, "tondeuse_etat_brut": "mowing"}),
            "unknown",
        )


class PauseAPluieTests(unittest.TestCase):
    """Un robot en pause pluie est RANGÉ : il ne doit pas bloquer l'arrosage."""

    BASE = {
        "tondeuse_connectee": True,
        "tondeuse_prete": False,
        "tondeuse_pluie": True,
        "tondeuse_statut": "pluie",
        "tondeuse_source_entity": "lawn_mower.esperance_jr",
        "tondeuse_resolution_state": "configured",
        "tondeuse_etat_brut": "rain_delayed",
    }

    def test_pause_pluie_compte_comme_rangee_et_liberer_larrosage(self) -> None:
        # RÉGRESSION (28/07/2026) : `rain_delayed` était classé « dehors » et jugé non fiable →
        # l'arrosage était bloqué (`mower_not_stowed`/`mower_unreliable`) pour une machine
        # pourtant à sa station. Or la pause pluie s'arme sur quelques dixièmes de mm et dure
        # 6 à 12 h : le lendemain d'une averse insignifiante, la fenêtre d'arrosage du matin
        # était perdue pour rien.
        ctx = build_mower_coordination_context(dict(self.BASE), enabled=True)

        self.assertEqual(ctx["mower_presence_state"], "dockee")
        self.assertTrue(ctx["mower_is_docked"])
        self.assertFalse(ctx["mower_is_outside"])
        self.assertTrue(ctx["mower_coordination_ready"])
        self.assertTrue(ctx["mower_is_safe_for_watering"], "l'arrosage doit être possible")
        self.assertEqual(ctx["mower_reason_code"], "mower_rain_delayed")

    def test_pause_pluie_reste_signalee_pour_la_tonte(self) -> None:
        # Contrepartie indispensable : libérer l'ARROSAGE ne doit pas effacer le motif que la
        # tonte utilise pour rester bloquée (gazon mouillé, robot en attente). Le code
        # `mower_rain_delayed` doit donc subsister, et la tondeuse ne pas être déclarée prête.
        ctx = build_mower_coordination_context(dict(self.BASE), enabled=True)

        self.assertEqual(ctx["mower_reason_code"], "mower_rain_delayed")
        self.assertFalse(ctx.get("tondeuse_prete", False))
