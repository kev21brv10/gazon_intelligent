"""La page « Gazon » côté serveur : ce qu'elle lit, ce qu'elle écrit, et son panneau.

Les composants Home Assistant (websocket_api, frontend, panel_custom, http) sont remplacés par
de faux modules le temps de chaque test : `panneau.py` ne les importe qu'au moment d'enregistrer.
"""

from __future__ import annotations

import asyncio
import importlib
import re
import sys
import types
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

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


def _install_voluptuous_stub() -> None:
    if "voluptuous" in sys.modules:
        return
    vol_mod = types.ModuleType("voluptuous")
    vol_mod.Required = lambda value, default=None: value  # type: ignore[attr-defined]
    vol_mod.Optional = lambda value, default=None: value  # type: ignore[attr-defined]
    sys.modules["voluptuous"] = vol_mod


def _install_homeassistant_dt_stub() -> None:
    """Même stub que `test_watering_session_monitoring.py` : heure réelle, en UTC."""
    from datetime import datetime, timezone

    racine = sys.modules.setdefault("homeassistant", types.ModuleType("homeassistant"))
    if not hasattr(racine, "__path__"):
        racine.__path__ = []  # type: ignore[attr-defined]
    util = sys.modules.setdefault("homeassistant.util", types.ModuleType("homeassistant.util"))
    if not hasattr(util, "__path__"):
        util.__path__ = []  # type: ignore[attr-defined]
    dt_module = sys.modules.setdefault("homeassistant.util.dt", types.ModuleType("homeassistant.util.dt"))
    if not hasattr(dt_module, "now"):
        dt_module.now = lambda: datetime.now(timezone.utc)  # type: ignore[attr-defined]
    if not hasattr(dt_module, "utcnow"):
        dt_module.utcnow = lambda: datetime.now(timezone.utc)  # type: ignore[attr-defined]
    if not hasattr(util, "dt"):
        util.dt = dt_module  # type: ignore[attr-defined]


_ensure_package("custom_components", PACKAGE_DIR.parent)
_ensure_package("custom_components.gazon_intelligent", PACKAGE_DIR)
_install_voluptuous_stub()
_install_homeassistant_dt_stub()

panneau = importlib.import_module("custom_components.gazon_intelligent.panneau")
reglages = importlib.import_module("custom_components.gazon_intelligent.reglages")

DOMAIN = "gazon_intelligent"


@dataclass
class _Entree:
    entry_id: str
    title: str = "Gazon Intelligent"
    data: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class _EntreeRegistre:
    name: str | None = None
    original_name: str | None = None
    entity_id: str = ""
    device_id: str | None = None
    disabled_by: Any = None
    platform: str | None = None


@dataclass
class _Appareil:
    name: str | None = None
    name_by_user: str | None = None
    manufacturer: str | None = None
    model: str | None = None


class _Registre:
    def __init__(
        self,
        renommes: dict[tuple[str, str], str] | None = None,
        noms: dict[str, _EntreeRegistre] | None = None,
        appareils: dict[str, _Appareil] | None = None,
    ):
        self._renommes = renommes or {}
        self._noms = noms or {}
        self.appareils = appareils or {}

    def async_get_entity_id(self, domaine: str, plateforme: str, unique_id: str) -> str | None:
        assert plateforme == DOMAIN
        return self._renommes.get((domaine, unique_id))

    def async_get(self, entity_id: str) -> _EntreeRegistre | None:
        return self._noms.get(entity_id)

    def entites_de(self, device_id: str) -> list[_EntreeRegistre]:
        return [
            _EntreeRegistre(**{**vars(e), "entity_id": e.entity_id or eid})
            for eid, e in self._noms.items()
            if e.device_id == device_id
        ]


@dataclass
class _Etat:
    state: str
    attributes: dict[str, Any] = field(default_factory=dict)


class _Etats:
    def __init__(self, etats: dict[str, _Etat] | None = None):
        self._etats = etats or {}

    def get(self, entity_id: str) -> _Etat | None:
        return self._etats.get(entity_id)

    def async_entity_ids(self, domaine: str | None = None) -> list[str]:
        return [e for e in self._etats if e.startswith(f"{domaine}.")]


class _Coordinateur:
    def __init__(self, entree: _Entree, conf: dict[str, Any] | None = None, produits: dict | None = None):
        self.entry = entree
        self._conf = conf or {}
        self.brain = types.SimpleNamespace(products=produits or {})
        self.mises_a_jour: list[dict[str, Any]] = []
        self.entrees_changees: list[dict[str, Any]] = []
        self.arrose = False

    def _get_conf(self, cle: str) -> Any:
        if cle in self.entry.options:
            return self.entry.options[cle]
        return self._conf.get(cle)

    async def async_update_config(self, mises_a_jour: dict[str, Any]) -> None:
        self.mises_a_jour.append(dict(mises_a_jour))
        self.entry.options = {**self.entry.options, **mises_a_jour}

    def arrosage_en_cours(self) -> bool:
        return self.arrose

    async def async_changer_entrees(self, changements: dict[str, Any]) -> bool:
        self.entrees_changees.append(dict(changements))
        self.entry.options = {**self.entry.options, **changements}
        return True


def _hass(*coordinateurs: _Coordinateur, registre: _Registre | None = None, etats: _Etats | None = None):
    hass = types.SimpleNamespace(
        data={DOMAIN: {c.entry.entry_id: c for c in coordinateurs}},
        states=etats or _Etats(),
    )
    return hass, registre


def _avec_registre(registre: _Registre | None):
    """Remplace les registres des entités et des appareils le temps d'un test."""
    helpers = types.ModuleType("homeassistant.helpers")
    helpers.__path__ = []  # type: ignore[attr-defined]
    er = types.ModuleType("homeassistant.helpers.entity_registry")
    er.async_get = lambda hass: registre  # type: ignore[attr-defined]
    er.async_entries_for_device = lambda reg, device_id: reg.entites_de(device_id)  # type: ignore[attr-defined]
    dr = types.ModuleType("homeassistant.helpers.device_registry")
    appareils = registre.appareils if registre is not None else {}
    dr.async_get = lambda hass: types.SimpleNamespace(async_get=appareils.get)  # type: ignore[attr-defined]
    helpers.entity_registry = er  # type: ignore[attr-defined]
    helpers.device_registry = dr  # type: ignore[attr-defined]
    racine = sys.modules.get("homeassistant") or types.ModuleType("homeassistant")
    if not hasattr(racine, "__path__"):
        racine.__path__ = []  # type: ignore[attr-defined]
    return patch.dict(sys.modules, {
        "homeassistant": racine,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.entity_registry": er,
        "homeassistant.helpers.device_registry": dr,
    })


PRODUITS = {
    "kick_pro": {"id": "kick_pro", "nom": "Kick Pro", "type": "Agent Mouillant", "note": "n", "application_months": [4, 5]},
    "engrais": {"id": "engrais", "nom": "Engrais racinaire", "type": "Fertilisation", "temperature_min": 8.0},
}


class AvertissementsDesReglagesTests(unittest.TestCase):
    def test_la_page_affiche_les_avertissements_exportes_par_le_registre(self) -> None:
        source = (PACKAGE_DIR / "frontend" / "gazon-intelligent-panel.js").read_text(encoding="utf-8")
        self.assertIn("r.avertissement", source)
        self.assertIn("avertissement-reglage", source)
        self.assertIn('icon="mdi:alert-outline"', source)


class CeQueLaPageLitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.entree = _Entree("e1", options={"reglages": {"tonte_vent_bloque": 45, "tonte_vent_a_eviter": 20}})
        self.coordinateur = _Coordinateur(
            self.entree,
            conf={
                "zone_1": "switch.vanne_1", "zone_2": "switch.vanne_2", "zone_3": None,
                "entite_meteo": "weather.maison", "entite_pompe": "switch.pompe", "type_sol": "argileux",
            },
            produits=PRODUITS,
        )
        self.registre = _Registre(
            renommes={("sensor", "e1_assistant"): "sensor.mon_assistant"},
            noms={"switch.vanne_1": _EntreeRegistre(name="Pelouse côté A", original_name="Zone 1 Arrosage")},
        )
        self.etats = _Etats({"switch.vanne_2": _Etat("off", {"friendly_name": "Sonoff Zone 2"})})

    def _donnees(self) -> dict[str, Any]:
        hass, _ = _hass(self.coordinateur, etats=self.etats)
        with _avec_registre(self.registre):
            return panneau.donnees_de_la_page(hass, self.coordinateur)

    def test_la_forme_attendue_par_la_page(self) -> None:
        donnees = self._donnees()
        self.assertEqual(
            set(donnees),
            {"instances", "entry_id", "titre", "sous_titre", "registre", "valeurs", "choix", "produits",
             "entites", "zones", "pompe", "meteo", "notifications", "sources", "appareils", "pompe_choix",
             "garage_tondeuse"},
        )
        self.assertEqual(donnees["entry_id"], "e1")
        self.assertEqual(donnees["instances"], [{"entry_id": "e1", "titre": "Gazon Intelligent"}])
        self.assertIsNone(donnees["sous_titre"])
        self.assertEqual((donnees["pompe"], donnees["meteo"]), ("switch.pompe", "weather.maison"))
        self.assertEqual(donnees["registre"], reglages.exporter())

    def test_les_valeurs_sont_le_conseil_remplace_par_les_reglages(self) -> None:
        valeurs = self._donnees()["valeurs"]
        self.assertEqual(valeurs["tonte_vent_bloque"], 45)
        self.assertEqual(valeurs["tonte_vent_a_eviter"], 20)
        self.assertEqual(set(valeurs), {r.cle for r in reglages.REGLAGES})

    def test_le_type_de_sol_vient_des_options(self) -> None:
        self.assertEqual(self._donnees()["choix"], {
            "type_sol": "argileux",
            "pilotage_tondeuse": "desactive",
            "tondeuse_creneaux_depart": "ideal_seulement",
        })
        self.coordinateur._conf["type_sol"] = None
        self.assertEqual(self._donnees()["choix"], {
            "type_sol": "limoneux",
            "pilotage_tondeuse": "desactive",
            "tondeuse_creneaux_depart": "ideal_seulement",
        })

    def test_le_garage_de_tondeuse_reste_facultatif_et_liste_les_volets(self) -> None:
        self.etats._etats["cover.garage_tondeuse"] = _Etat("closed", {"friendly_name": "Garage tondeuse"})
        garage = self._donnees()["garage_tondeuse"]
        self.assertIsNone(garage["choisie"])
        self.assertEqual(garage["volets"], [{"entity_id": "cover.garage_tondeuse", "nom": "Garage tondeuse"}])

    def test_les_entites_suivent_le_registre_puis_le_nom_public(self) -> None:
        entites = self._donnees()["entites"]
        self.assertEqual(set(entites), set(panneau.ENTITES_DE_LA_PAGE))
        self.assertEqual(entites["assistant"], "sensor.mon_assistant")  # renommée par l'utilisateur
        self.assertEqual(entites["phase"], "sensor.gazon_intelligent_phase_dominante")
        self.assertEqual(entites["arrosage_automatique"], "switch.gazon_intelligent_arrosage_automatique_autorise")
        self.assertEqual(entites["hauteur_min_tondeuse_cm"], "number.gazon_intelligent_hauteur_min_tondeuse")

    def test_une_instance_nommee_a_ses_propres_entites(self) -> None:
        self.entree.title = "Gazon Intelligent - Gazon Potager"
        self.entree.data["instance_slug"] = "gazon_potager"
        donnees = self._donnees()
        self.assertEqual(donnees["sous_titre"], "Gazon Potager")
        self.assertEqual(donnees["entites"]["phase"], "sensor.gazon_intelligent_gazon_potager_phase_dominante")

    def test_les_zones_portent_le_nom_de_leur_entite(self) -> None:
        zones = self._donnees()["zones"]
        self.assertEqual(zones, [
            {"numero": 1, "nom": "Pelouse côté A", "switch": "switch.vanne_1", "etat": None},
            {"numero": 2, "nom": "Sonoff Zone 2", "switch": "switch.vanne_2", "etat": None},
        ])
        self.etats = _Etats()
        self.assertEqual(self._donnees()["zones"][1]["nom"], "Zone 2")

    def test_la_page_sait_ou_partent_les_alertes_et_si_l_ia_repond(self) -> None:
        self.entree.options.update({
            "notification_cibles": ["notify.telephone_a", "notify.telephone_b"],
            "entite_ia": "ai_task.openai",
        })
        self.etats = _Etats({
            "notify.telephone_a": _Etat("unknown", {"friendly_name": "Téléphone A"}),
            "ai_task.openai": _Etat("unknown", {"friendly_name": "OpenAI"}),
        })
        hass, _ = _hass(self.coordinateur, etats=self.etats)
        hass.services = types.SimpleNamespace(has_service=lambda domaine, service: (domaine, service) == ("ai_task", "generate_data"))
        with _avec_registre(self.registre):
            notifications = panneau.donnees_de_la_page(hass, self.coordinateur)["notifications"]
        self.assertEqual(notifications, {
            "cibles": [
                {"entity_id": "notify.telephone_a", "nom": "Téléphone A"},
                # Sans nom connu, l'identifiant : la page n'affiche jamais une case vide.
                {"entity_id": "notify.telephone_b", "nom": "notify.telephone_b"},
            ],
            "alertes": True,
            "mode": "manuel",
            "source": "integration",
            "niveau_minimal": "information",
            "heures_calmes": {"active": False, "debut": 1320, "fin": 420},
            "categories": {
                "arrosage_graines": True,
                "securite_arrosage": True,
                "capteurs_meteo": True,
                "tondeuse": True,
                "activite_arrosage": False,
                "activite_tondeuse": False,
                "garage_tondeuse": False,
            },
            "ia_choisie": "ai_task.openai",
            "ia": "ai_task.openai",
            "ia_nom": "OpenAI",
            "ia_disponible": True,
            # Ce qu'on peut choisir : ce qui existe dans Home Assistant, trié par nom.
            "telephones": [{"entity_id": "notify.telephone_a", "nom": "Téléphone A"}],
            "ias": [{"entity_id": "ai_task.openai", "nom": "OpenAI"}],
        })

    def test_sans_ia_ni_telephone(self) -> None:
        self.entree.options["alertes_actives"] = False
        notifications = self._donnees()["notifications"]
        self.assertEqual(notifications, {
            "cibles": [], "alertes": False, "mode": "manuel", "source": "integration",
            "niveau_minimal": "information",
            "heures_calmes": {"active": False, "debut": 1320, "fin": 420},
            "ia_choisie": None, "ia": None, "ia_nom": None,
            "ia_disponible": False, "telephones": [], "ias": [],
            "categories": {
                "arrosage_graines": True,
                "securite_arrosage": True,
                "capteurs_meteo": True,
                "tondeuse": True,
                "activite_arrosage": False,
                "activite_tondeuse": False,
                "garage_tondeuse": False,
            },
        })

    def test_automatique_nomme_la_seule_ia(self) -> None:
        self.etats = _Etats({
            "ai_task.openai": _Etat("unknown", {"friendly_name": "OpenAI"}),
            "notify.b": _Etat("unknown", {"friendly_name": "Tablette"}),
            "notify.a": _Etat("unknown", {"friendly_name": "iPhone"}),
        })
        notifications = self._donnees()["notifications"]
        self.assertIsNone(notifications["ia_choisie"], "rien n'est choisi dans les options")
        self.assertEqual((notifications["ia"], notifications["ia_nom"]), ("ai_task.openai", "OpenAI"))
        self.assertEqual([t["nom"] for t in notifications["telephones"]], ["iPhone", "Tablette"])

    def test_les_fiches_produits_sont_entieres_et_triees(self) -> None:
        produits = self._donnees()["produits"]
        self.assertEqual([p["id"] for p in produits], ["engrais", "kick_pro"])
        self.assertEqual(produits[1], PRODUITS["kick_pro"])
        produits[1]["application_months"].append(12)
        self.assertEqual(PRODUITS["kick_pro"]["application_months"], [4, 5], "une copie, pas la fiche du moteur")

    def test_seules_les_instances_qui_veulent_la_page_sont_proposees(self) -> None:
        autre = _Coordinateur(_Entree("e2", title="Gazon Intelligent - Potager", options={"page_gazon": False}))
        hass, _ = _hass(self.coordinateur, autre)
        self.assertEqual([c.entry.entry_id for c in panneau.instances_avec_page(hass)], ["e1"])
        self.assertIs(panneau.coordinateur_demande(hass, None), self.coordinateur)
        # Demandée explicitement, une instance reste joignable (écriture d'une instance masquée).
        self.assertIs(panneau.coordinateur_demande(hass, "e2"), autre)
        self.assertIsNone(panneau.coordinateur_demande(hass, "inconnue"))
        self.assertTrue(panneau.page_voulue(_Entree("e3")))
        self.assertFalse(panneau.page_voulue(_Entree("e4", data={"page_gazon": False})))

    def test_la_page_connait_chaque_entite_que_le_serveur_fournit(self) -> None:
        # Contrat : les clés de l'aperçu local (maison d'exemple) sont celles que le serveur envoie.
        source = (ROOT / "dev" / "panel" / "maison.exemple.js").read_text(encoding="utf-8")
        bloc = re.search(r"entites: \{(.*?)\n  \},", source, re.S)
        assert bloc is not None
        cles_apercu = set(re.findall(r"^\s+(\w+):", bloc.group(1), re.M))
        self.assertEqual(cles_apercu, set(panneau.ENTITES_DE_LA_PAGE))

    def test_le_fichier_de_la_page_existe(self) -> None:
        self.assertTrue((panneau.DOSSIER_FRONTEND / panneau.FICHIER_PANNEAU).is_file())
        page = (panneau.DOSSIER_FRONTEND / panneau.FICHIER_PANNEAU).read_text(encoding="utf-8")
        self.assertIn(f'customElements.define("{panneau.COMPOSANT}"', page)
        self.assertIn(f'const WS_LIRE = "{panneau.WS_LIRE}"', page)
        self.assertIn(f'const WS_ECRIRE = "{panneau.WS_ECRIRE}"', page)

    def test_les_fenetres_suivent_la_largeur_reelle_du_panneau(self) -> None:
        page = (panneau.DOSSIER_FRONTEND / panneau.FICHIER_PANNEAU).read_text(encoding="utf-8")
        self.assertIn("var(--gz-page-width, 100vw)", page)
        self.assertIn('this.style.setProperty("--gz-page-width", `${largeur}px`)', page)

    def test_l_apercu_telephone_represente_l_app_home_assistant(self) -> None:
        apercu = (ROOT / "dev" / "panel" / "index.html").read_text(encoding="utf-8")
        self.assertIn("width: min(390px, calc(100vw - 24px)); height: 844px", apercu)
        self.assertIn("gazon-intelligent-panel.js?dev=${Date.now()}", apercu)

    def test_le_bandeau_en_ce_moment_est_range_sur_mobile(self) -> None:
        page = (panneau.DOSSIER_FRONTEND / panneau.FICHIER_PANNEAU).read_text(encoding="utf-8")
        self.assertIn(".en-ce-moment .puces {\n    display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));", page)
        self.assertIn(".meteo-ligne {\n    display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));", page)
        self.assertIn(".meteo-ligne span:nth-child(n + 5) { display: none; }", page)
        self.assertIn("border-top: 1px solid rgba(255, 255, 255, .28)", page)
        self.assertIn(".en-ce-moment .puce { max-width: 100%; min-height: 28px;", page)

    def test_le_verrou_de_securite_a_sa_propre_action_dans_la_page(self) -> None:
        page = (panneau.DOSSIER_FRONTEND / panneau.FICHIER_PANNEAU).read_text(encoding="utf-8")
        self.assertIn('dialogue: "deverrouiller"', page)
        self.assertIn('["gazon_intelligent", "clear_irrigation_safety_lock"', page)
        self.assertIn("Le mode du gazon et le suivi Semis ou Sursemis sont conservés.", page)
        self.assertIn("Le verrou de sécurité restera posé", page)

    def test_la_fenetre_de_changement_de_mode_part_du_mode_choisi(self) -> None:
        # L'onglet Modes lui-même est exécuté dans `test_panneau_modes.py`.
        page = (panneau.DOSSIER_FRONTEND / panneau.FICHIER_PANNEAU).read_text(encoding="utf-8")
        self.assertIn('data-dialogue="mode" data-mode="${esc(mode)}"', page)
        self.assertIn("mode && options.includes(mode) ? mode", page)
        self.assertIn("etat.direct = Boolean(mode && options.includes(mode))", page)
        self.assertIn("if (d.direct) {", page)
        self.assertIn("Confirmer le mode ${d.choix}", page)

    def test_les_notifications_sont_choisies_par_categorie_dans_le_meme_panneau(self) -> None:
        page = (panneau.DOSSIER_FRONTEND / panneau.FICHIER_PANNEAU).read_text(encoding="utf-8")
        self.assertIn("Que veux-tu recevoir ?", page)
        self.assertIn('data-action="alerte-categorie"', page)
        for categorie in (
            "arrosage_graines", "securite_arrosage", "capteurs_meteo", "tondeuse",
            "activite_arrosage", "activite_tondeuse", "garage_tondeuse",
        ):
            self.assertIn(f'["{categorie}",', page)
        self.assertIn("Une même panne n'est envoyée qu'une fois.", page)
        self.assertIn("Qui rédige les notifications ?", page)
        self.assertIn('puce("alerte-source"', page)
        self.assertIn("Gazon Intelligent", page)
        self.assertIn("Conseiller Gazon", page)

    def test_les_animations_respectent_la_reduction_des_mouvements(self) -> None:
        page = (panneau.DOSSIER_FRONTEND / panneau.FICHIER_PANNEAU).read_text(encoding="utf-8")
        self.assertIn("@media (prefers-reduced-motion: reduce)", page)
        self.assertIn("animation: none !important; scroll-behavior: auto !important", page)


class LOngletMeteoTests(unittest.TestCase):
    """0.94.0 : chaque entrée branchée, son appareil, et toutes les mesures de cet appareil."""

    def setUp(self) -> None:
        self.entree = _Entree("e1", options={
            "entite_meteo": "weather.maison",
            "capteur_temperature": "sensor.station_temperature",
            "capteur_vent": "sensor.station_vent",
            "capteur_pluie_24h": "sensor.voisin_pluie",
        })
        self.coordinateur = _Coordinateur(self.entree, conf={"capteur_humidite": "sensor.inconnue"})
        self.registre = _Registre(
            noms={
                "sensor.station_temperature": _EntreeRegistre(name="Température du jardin", device_id="station"),
                "sensor.station_vent": _EntreeRegistre(device_id="station"),
                "sensor.station_point_de_rosee": _EntreeRegistre(original_name="Station Point de rosée", device_id="station"),
                "sensor.station_humidite_foliaire": _EntreeRegistre(original_name="Station Humidité foliaire", device_id="station"),
                "sensor.station_etp": _EntreeRegistre(device_id="station"),
                "sensor.station_etp_hors_service": _EntreeRegistre(device_id="station"),
                "sensor.station_uv": _EntreeRegistre(device_id="station"),
                "sensor.station_ancienne": _EntreeRegistre(device_id="station", disabled_by="user"),
                "button.station_identifier": _EntreeRegistre(device_id="station"),
                "sensor.station_latitude": _EntreeRegistre(device_id="station"),
                "sensor.voisin_pluie": _EntreeRegistre(device_id="voisin"),
            },
            appareils={
                "station": _Appareil(name="Station", name_by_user="Station du jardin", manufacturer="Shelly", model="WS"),
                "voisin": _Appareil(name="Voisin"),
            },
        )
        self.etats = _Etats({
            "sensor.station_vent": _Etat("3.2", {"friendly_name": "Station Vent"}),
            "sensor.station_uv": _Etat("4", {"friendly_name": "Station UV"}),
            "sensor.station_etp": _Etat("1.6", {"unit_of_measurement": "mm"}),
            # Le nom annonce une évaporation, mais la valeur n'est pas un nombre : pas une idée.
            "sensor.station_etp_hors_service": _Etat("erreur", {"unit_of_measurement": "mm"}),
        })

    def _donnees(self) -> dict[str, Any]:
        hass, _ = _hass(self.coordinateur, etats=self.etats)
        with _avec_registre(self.registre):
            return panneau.donnees_de_la_page(hass, self.coordinateur)

    def test_une_ligne_par_entree_dans_l_ordre_du_registre(self) -> None:
        sources = self._donnees()["sources"]
        self.assertEqual([s["cle"] for s in sources], [s.cle for s in panneau.sources_meteo.SOURCES])
        par_cle = {s["cle"]: s for s in sources}
        self.assertEqual(par_cle["capteur_temperature"], {
            "cle": "capteur_temperature", "titre": "Température", "groupe": "air",
            "apporte": "La mesure du jardin, prioritaire sur la prévision.",
            "sans_elle": "La température de l'entité météo.", "mesure": True, "numerique": True,
            "entity_id": "sensor.station_temperature", "nom": "Température du jardin",
            "partagee": False, "appareil": "station",
            # 0.95.0 : ce qui peut la remplacer, pour la liste de la page.
            "domaine": "sensor", "obligatoire": False, "unites": ["°C"], "sans_unite": False,
            "unites_refusees": [], "classes_refusees": [], "indices": [],
            "classes": ["temperature"], "classes_etat_refusees": [], "exige_indice": False,
            "indice_sans_classe": False,
            "noms_refuses": list(panneau.sources_meteo.PAR_CLE["capteur_temperature"].noms_refuses),
        })
        self.assertEqual(
            (par_cle["entite_meteo"]["domaine"], par_cle["entite_meteo"]["obligatoire"]), ("weather", True)
        )
        self.assertEqual(par_cle["capteur_rosee"]["classes_refusees"], ["temperature"])
        self.assertTrue(par_cle["capteur_rosee"]["exige_indice"])
        self.assertEqual(par_cle["capteur_pluie_actuelle"]["classes_etat_refusees"], ["total", "total_increasing"])
        # Branchée sans nom connu : l'identifiant. Sans appareil connu : rien à regrouper.
        self.assertEqual(par_cle["capteur_humidite"]["nom"], "sensor.inconnue")
        self.assertIsNone(par_cle["capteur_humidite"]["appareil"])
        # Non branchée : ni entité, ni nom.
        self.assertEqual((par_cle["capteur_rosee"]["entity_id"], par_cle["capteur_rosee"]["nom"]), (None, None))
        self.assertFalse(par_cle["entite_meteo"]["numerique"])
        self.assertFalse(par_cle["capteur_pluie_demain"]["mesure"])

    def test_une_entree_partagee_le_dit(self) -> None:
        self.coordinateur.shared_state = types.SimpleNamespace(get_conf=lambda cle: "sensor.commune" if cle == "capteur_pression" else None)
        self.coordinateur._conf["capteur_pression"] = "sensor.commune"
        par_cle = {s["cle"]: s for s in self._donnees()["sources"]}
        self.assertTrue(par_cle["capteur_pression"]["partagee"])
        self.assertFalse(par_cle["capteur_temperature"]["partagee"], "une option locale n'est pas partagée")

    def test_toutes_les_mesures_des_appareils_branches(self) -> None:
        appareils = self._donnees()["appareils"]
        self.assertEqual([a["id"] for a in appareils], ["station", "voisin"])
        station = appareils[0]
        self.assertEqual((station["nom"], station["fabricant"], station["modele"]), ("Station du jardin", "Shelly", "WS"))
        self.assertEqual(
            [(e["entity_id"], e["branchee"], e["pourrait"]) for e in station["entites"]],
            [
                # Les branchées d'abord, puis par nom.
                ("sensor.station_vent", "capteur_vent", []),
                ("sensor.station_temperature", "capteur_temperature", []),
                ("sensor.station_etp", None, ["capteur_etp"]),
                ("sensor.station_etp_hors_service", None, []),
                ("sensor.station_humidite_foliaire", None, ["capteur_rosee"]),
                # 0.94.1 : un point de rosée est une TEMPÉRATURE ; « Rosée sur l'herbe » attend une
                # humidité du feuillage (au-dessus de 0 = mouillée). Proposé, il bloquait la tonte.
                ("sensor.station_point_de_rosee", None, []),
                ("sensor.station_uv", None, []),
            ],
        )
        entites = {e["entity_id"] for a in appareils for e in a["entites"]}
        self.assertNotIn("sensor.station_ancienne", entites, "une entité désactivée n'est pas une mesure")
        self.assertNotIn("button.station_identifier", entites, "un bouton n'est pas une mesure")
        self.assertNotIn("sensor.station_latitude", entites, "rien de ce qui situe la maison")

    def test_sans_registre_aucun_appareil(self) -> None:
        hass, _ = _hass(self.coordinateur, etats=self.etats)
        with _avec_registre(None):
            donnees = panneau.donnees_de_la_page(hass, self.coordinateur)
        self.assertEqual(donnees["appareils"], [])
        self.assertTrue(all(s["appareil"] is None for s in donnees["sources"]))


class LaPompeTests(unittest.TestCase):
    """0.94.0 : la pompe se choisit sur la page, parmi les interrupteurs qui ne sont pas des vannes."""

    def setUp(self) -> None:
        self.entree = _Entree("e1", options={"reglages": {}})
        self.coordinateur = _Coordinateur(self.entree, conf={
            "zone_1": "switch.vanne_1", "zone_2": "switch.vanne_2", "entite_pompe": "switch.surpresseur",
        })
        self.hass = types.SimpleNamespace(
            data={DOMAIN: {"e1": self.coordinateur}},
            states=_Etats({
                "switch.vanne_1": _Etat("off"),
                "switch.vanne_2": _Etat("off"),
                "switch.gazon_intelligent_arrosage_automatique_autorise": _Etat("on"),
                "switch.salon": _Etat("off", {"friendly_name": "Lampe du salon"}),
                "switch.surpresseur": _Etat("off", {"friendly_name": "Surpresseur"}),
                "switch.relais_4": _Etat("off", {"friendly_name": "Pompe du puits"}),
                "light.salon": _Etat("off"),
            }),
        )

    def _ecrire(self, **kwargs: Any) -> dict[str, Any]:
        with _avec_registre(_Registre()):
            return asyncio.run(panneau.ecrire_reglages(self.coordinateur, {}, {}, hass=self.hass, **kwargs))

    def test_les_pompes_d_abord_jamais_une_vanne(self) -> None:
        with _avec_registre(_Registre()):
            choix = panneau.pompe_de_l_instance(self.hass, self.coordinateur)
        self.assertEqual(choix["choisie"], "switch.surpresseur")
        self.assertEqual(
            [(i["entity_id"], i["proposee"]) for i in choix["interrupteurs"]],
            [("switch.relais_4", True), ("switch.surpresseur", True), ("switch.salon", False)],
        )

    def test_choisir_puis_retirer(self) -> None:
        reponse = self._ecrire(pompe="switch.relais_4")
        self.assertTrue(reponse["ok"])
        self.assertEqual(self.entree.options["entite_pompe"], "switch.relais_4")
        self.assertEqual(reponse["pompe"], "switch.relais_4")
        self.assertEqual(reponse["pompe_choix"]["choisie"], "switch.relais_4")
        self.assertTrue(self._ecrire(pompe=None)["ok"])
        self.assertIsNone(self.entree.options["entite_pompe"])

    def test_sans_la_cle_la_pompe_ne_change_pas(self) -> None:
        self.assertTrue(self._ecrire()["ok"])
        self.assertNotIn("entite_pompe", self.entree.options)

    def test_un_refus_n_ecrit_rien(self) -> None:
        cas = {
            "vanne": ("switch.vanne_1", "Une vanne ne peut pas servir de pompe."),
            "inconnue": ("switch.disparue", "Cet interrupteur n'existe pas dans Home Assistant : switch.disparue."),
            "pas un interrupteur": ("light.salon", "Cet interrupteur n'existe pas dans Home Assistant : light.salon."),
            "mauvaise forme": (["switch.relais_4"], "Le choix de la pompe n'a pas la bonne forme."),
        }
        for nom, (envoi, message) in cas.items():
            with self.subTest(cas=nom):
                self.assertEqual(self._ecrire(pompe=envoi), {"ok": False, "erreurs": {"pompe": message}})
        self.assertEqual(self.coordinateur.mises_a_jour, [])

    def test_la_commande_ne_touche_la_pompe_que_si_on_l_envoie(self) -> None:
        connexion = _Connexion()
        message = {"id": 1, "type": panneau.WS_ECRIRE, "entry_id": "e1", "valeurs": {}, "choix": {}}
        with _avec_registre(_Registre()):
            asyncio.run(panneau._ws_ecrire(self.hass, connexion, dict(message)))
            self.assertNotIn("entite_pompe", self.entree.options)
            asyncio.run(panneau._ws_ecrire(self.hass, connexion, dict(message, id=2, pompe="switch.relais_4")))
        self.assertEqual(self.entree.options["entite_pompe"], "switch.relais_4")
        self.assertEqual([r[1]["ok"] for r in connexion.resultats], [True, True])


class ChangerLesEntreesTests(unittest.TestCase):
    """0.95.0 : les entrées météo et jardin se changent sur la page, avec les règles du moteur."""

    def setUp(self) -> None:
        self.entree = _Entree("e1", options={
            "reglages": {},
            "entite_meteo": "weather.maison",
            "capteur_vent": "sensor.station_vent",
            "capteur_pression": "sensor.voisin_pression",
        })
        self.coordinateur = _Coordinateur(self.entree)
        self.registre = _Registre(noms={
            "sensor.gazon_intelligent_et0": _EntreeRegistre(platform="gazon_intelligent"),
            "sensor.station_pression": _EntreeRegistre(platform="mqtt", device_id="station"),
            "sensor.renomme_par_moi": _EntreeRegistre(platform="gazon_intelligent"),
        })
        self.hass = types.SimpleNamespace(
            data={DOMAIN: {"e1": self.coordinateur}},
            states=_Etats({
                "weather.maison": _Etat("sunny"),
                "weather.autre": _Etat("cloudy"),
                "sensor.station_vent": _Etat("3.2", {"unit_of_measurement": "km/h"}),
                "sensor.voisin_pression": _Etat("1020.3", {"unit_of_measurement": "hPa"}),
                "sensor.station_pression": _Etat("100.8", {"unit_of_measurement": "kPa", "device_class": "atmospheric_pressure"}),
                "sensor.station_point_de_rosee": _Etat("11.8", {"unit_of_measurement": "°C", "device_class": "temperature"}),
                "sensor.jardin_feuilles": _Etat("0", {"unit_of_measurement": "%", "friendly_name": "Humidité foliaire"}),
                "sensor.station_humidite": _Etat("63", {"unit_of_measurement": "%", "device_class": "humidity"}),
                "sensor.station_batterie": _Etat("100", {"unit_of_measurement": "%", "device_class": "battery"}),
                "sensor.pluie_du_jour": _Etat("2.4", {"unit_of_measurement": "mm", "device_class": "precipitation", "state_class": "total_increasing"}),
                "sensor.detection_pluie": _Etat("Pas de pluie", {"unit_of_measurement": "mm"}),
                "sensor.luminosite": _Etat("64714", {"unit_of_measurement": "lx", "device_class": "illuminance"}),
                "sensor.gazon_intelligent_et0": _Etat("1.6", {"unit_of_measurement": "mm"}),
                "sensor.renomme_par_moi": _Etat("1.6", {"unit_of_measurement": "mm"}),
                "sensor.gazon_intelligent_hors_registre": _Etat("1.6", {"unit_of_measurement": "mm"}),
                "switch.station": _Etat("on"),
            }),
        )

    def _ecrire(self, entrees: Any, valeurs: Any = None) -> dict[str, Any]:
        with _avec_registre(self.registre):
            return asyncio.run(panneau.ecrire_reglages(
                self.coordinateur, valeurs or {}, {}, hass=self.hass, entrees=entrees,
            ))

    def test_brancher_une_mesure_compatible(self) -> None:
        reponse = self._ecrire({"capteur_pression": "sensor.station_pression"})
        self.assertTrue(reponse["ok"])
        self.assertTrue(reponse["recharge"])
        self.assertEqual(self.coordinateur.entrees_changees, [{"capteur_pression": "sensor.station_pression"}])
        self.assertEqual(self.coordinateur.mises_a_jour, [], "des entrées seules : les réglages ne sont pas réécrits")
        # La page repart des entrées telles qu'enregistrées.
        par_cle = {s["cle"]: s for s in reponse["sources"]}
        self.assertEqual(par_cle["capteur_pression"]["entity_id"], "sensor.station_pression")
        self.assertEqual(par_cle["capteur_pression"]["appareil"], "station")
        self.assertEqual([a["id"] for a in reponse["appareils"]], ["station"])
        self.assertEqual(reponse["meteo"], "weather.maison")

    def test_retirer_une_entree(self) -> None:
        self.assertTrue(self._ecrire({"capteur_vent": None})["ok"])
        self.assertTrue(self._ecrire({"capteur_pression": ""})["ok"])
        self.assertEqual(self.coordinateur.entrees_changees, [{"capteur_vent": None}, {"capteur_pression": None}])

    def test_changer_d_entite_meteo(self) -> None:
        self.assertTrue(self._ecrire({"entite_meteo": "weather.autre"})["ok"])
        self.assertEqual(self.coordinateur.entrees_changees, [{"entite_meteo": "weather.autre"}])

    def test_rien_n_est_ecrit_quand_rien_ne_change(self) -> None:
        reponse = self._ecrire({"capteur_vent": "sensor.station_vent", "capteur_rosee": None})
        self.assertTrue(reponse["ok"])
        self.assertNotIn("recharge", reponse)
        self.assertEqual((self.coordinateur.entrees_changees, self.coordinateur.mises_a_jour), ([], []))

    def test_avec_des_reglages_les_deux_sont_ecrits(self) -> None:
        reponse = self._ecrire({"capteur_pression": "sensor.station_pression"}, valeurs={"tonte_max_par_jour": 3})
        self.assertTrue(reponse["ok"])
        self.assertEqual(self.coordinateur.mises_a_jour[0]["reglages"], {"tonte_max_par_jour": 3})
        self.assertEqual(self.coordinateur.entrees_changees, [{"capteur_pression": "sensor.station_pression"}])

    def test_un_refus_n_ecrit_rien(self) -> None:
        cas = {
            "entrée inconnue": ({"capteur_lune": "sensor.feuillage"}, "Cette entrée n'existe pas : capteur_lune."),
            "météo retirée": (
                {"entite_meteo": None},
                "« Entité météo » est obligatoire : choisis-en une autre plutôt que de la retirer.",
            ),
            "absente": ({"capteur_vent": "sensor.disparu"}, "Cette entité n'existe pas dans Home Assistant : sensor.disparu."),
            "mauvaise forme": ({"capteur_vent": ["sensor.station_vent"]}, "Le choix des entrées n'a pas la bonne forme."),
            "pas un dictionnaire": (["capteur_vent"], "Le choix des entrées n'a pas la bonne forme."),
            "l'intégration elle-même": (
                {"capteur_etp": "sensor.gazon_intelligent_et0"},
                "« sensor.gazon_intelligent_et0 » vient de Gazon Intelligent : l'intégration ne peut pas se lire elle-même.",
            ),
            "renommée, mais toujours à elle": (
                {"capteur_etp": "sensor.renomme_par_moi"},
                "« sensor.renomme_par_moi » vient de Gazon Intelligent : l'intégration ne peut pas se lire elle-même.",
            ),
            "à elle, hors registre": (
                {"capteur_etp": "sensor.gazon_intelligent_hors_registre"},
                "« sensor.gazon_intelligent_hors_registre » vient de Gazon Intelligent : "
                "l'intégration ne peut pas se lire elle-même.",
            ),
            "point de rosée": ({"capteur_rosee": "sensor.station_point_de_rosee"}, panneau.sources_meteo.PAR_CLE["capteur_rosee"].refus_explique),
            "des lux pour le soleil": (
                {"capteur_rayonnement": "sensor.luminosite"},
                "« Rayonnement solaire » attend le rayonnement solaire, et ce capteur mesure autre chose (illuminance).",
            ),
            "un interrupteur": ({"capteur_vent": "switch.station"}, "« Vent » attend un capteur (sensor)."),
            "un capteur pour la météo": ({"entite_meteo": "sensor.jardin_feuilles"}, "« Entité météo » attend une entité météo (weather)."),
            "l'humidité de l'air pour la rosée": (
                {"capteur_rosee": "sensor.station_humidite"}, panneau.sources_meteo.PAR_CLE["capteur_rosee"].refus_indice,
            ),
            "une batterie pour l'humidité": (
                {"capteur_humidite": "sensor.station_batterie"},
                "« Humidité de l'air » attend l'humidité de l'air, et ce capteur mesure autre chose (battery).",
            ),
            "un cumul pour la pluie en ce moment": (
                {"capteur_pluie_actuelle": "sensor.pluie_du_jour"},
                panneau.sources_meteo.PAR_CLE["capteur_pluie_actuelle"].refus_classe_etat,
            ),
            "du texte pour la pluie en ce moment": (
                {"capteur_pluie_actuelle": "sensor.detection_pluie"},
                "« Pluie en ce moment » attend un nombre, et ce capteur donne « Pas de pluie ».",
            ),
        }
        for nom, (envoi, message) in cas.items():
            with self.subTest(cas=nom):
                reponse = self._ecrire(envoi, valeurs={"tonte_max_par_jour": 3})
                self.assertEqual(reponse, {"ok": False, "erreurs": {"entrees": message}})
        self.assertEqual((self.coordinateur.entrees_changees, self.coordinateur.mises_a_jour), ([], []))

    def test_une_humidite_du_feuillage_est_acceptee_pour_la_rosee(self) -> None:
        # Le nom d'affichage suffit à dire le rôle : « Humidité foliaire ».
        self.assertTrue(self._ecrire({"capteur_rosee": "sensor.jardin_feuilles"})["ok"])
        self.assertEqual(self.coordinateur.entrees_changees, [{"capteur_rosee": "sensor.jardin_feuilles"}])

    def test_jamais_pendant_un_arrosage(self) -> None:
        self.coordinateur.arrose = True
        reponse = self._ecrire({"capteur_pression": "sensor.station_pression"}, valeurs={"tonte_max_par_jour": 3})
        self.assertEqual(reponse, {"ok": False, "erreurs": {"entrees": (
            "Un arrosage est en cours : change les entrées quand il sera fini, le changement recharge l'intégration."
        )}})
        self.assertEqual((self.coordinateur.entrees_changees, self.coordinateur.mises_a_jour), ([], []))
        # Rien à changer : l'arrosage n'empêche pas d'enregistrer le reste.
        self.assertTrue(self._ecrire({"capteur_vent": "sensor.station_vent"}, valeurs={"tonte_max_par_jour": 3})["ok"])

    def test_la_commande_transmet_les_entrees(self) -> None:
        connexion = _Connexion()
        message = {"id": 1, "type": panneau.WS_ECRIRE, "entry_id": "e1", "valeurs": {}, "choix": {}}
        with _avec_registre(self.registre):
            asyncio.run(panneau._ws_ecrire(self.hass, connexion, dict(message)))
            asyncio.run(panneau._ws_ecrire(self.hass, connexion, dict(message, id=2, entrees={"capteur_vent": None})))
        self.assertEqual(self.coordinateur.entrees_changees, [{"capteur_vent": None}])
        premier, second = (r[1] for r in connexion.resultats)
        self.assertNotIn("sources", premier, "sans entrées envoyées, la réponse ne change pas")
        self.assertTrue(second["recharge"])
        self.assertIn("sources", second)


class CeQueLaPageEcritTests(unittest.TestCase):
    def setUp(self) -> None:
        self.entree = _Entree("e1", options={"reglages": {"tonte_fenetre_ideale_fin": 15 * 60}, "debit_zone_1": 14.0})
        self.coordinateur = _Coordinateur(self.entree, conf={"type_sol": "limoneux"})

    def _ecrire(self, valeurs: Any, choix: Any = None) -> dict[str, Any]:
        return asyncio.run(panneau.ecrire_reglages(self.coordinateur, valeurs, {} if choix is None else choix))

    def test_une_valeur_valide_est_enregistree_avec_les_autres(self) -> None:
        reponse = self._ecrire({"tonte_vent_bloque": 45})
        self.assertTrue(reponse["ok"])
        self.assertEqual(
            self.entree.options["reglages"], {"tonte_fenetre_ideale_fin": 900, "tonte_vent_bloque": 45}
        )
        self.assertEqual(self.entree.options["debit_zone_1"], 14.0, "les autres options restent")
        self.assertEqual(reponse["valeurs"]["tonte_vent_bloque"], 45)
        self.assertEqual(reponse["valeurs"]["tonte_fenetre_ideale_fin"], 900)
        self.assertEqual(reponse["choix"], {
            "type_sol": "limoneux",
            "pilotage_tondeuse": "desactive",
            "tondeuse_creneaux_depart": "ideal_seulement",
        })

    def test_revenir_au_conseil_retire_la_valeur(self) -> None:
        self.assertTrue(self._ecrire({"tonte_fenetre_ideale_fin": 14 * 60})["ok"])
        self.assertEqual(self.entree.options["reglages"], {})

    def test_une_valeur_refusee_n_ecrit_rien(self) -> None:
        reponse = self._ecrire({"tonte_vent_bloque": 200, "tonte_max_par_jour": 3})
        self.assertEqual(reponse, {"ok": False, "erreurs": {"tonte_vent_bloque": "Choisis une valeur entre 20 et 60."}})
        self.assertEqual(self.coordinateur.mises_a_jour, [])

    def test_une_contrainte_est_jugee_contre_ce_qui_est_enregistre(self) -> None:
        # Fin enregistrée à 15:00 : un début à 14:30 est valable, alors qu'il serait refusé face
        # au conseil (14:00) ; un début à 15:00 est refusé.
        self.assertTrue(self._ecrire({"tonte_fenetre_ideale_debut": 14 * 60})["ok"])
        refus = self._ecrire({"tonte_fenetre_ideale_debut": 14 * 60, "tonte_fenetre_ideale_fin": 14 * 60})
        self.assertFalse(refus["ok"])
        self.assertIn("tonte_fenetre_ideale_debut", refus["erreurs"])

    def test_le_type_de_sol_est_ecrit_dans_les_options(self) -> None:
        reponse = self._ecrire({}, {"type_sol": "sableux"})
        self.assertTrue(reponse["ok"])
        self.assertEqual(self.entree.options["type_sol"], "sableux")
        self.assertEqual(reponse["choix"], {
            "type_sol": "sableux",
            "pilotage_tondeuse": "desactive",
            "tondeuse_creneaux_depart": "ideal_seulement",
        })
        refus = self._ecrire({}, {"type_sol": "tourbe"})
        self.assertEqual(refus["erreurs"], {"type_sol": "Choisis parmi : sableuse, limoneuse, argileuse."})

    def test_le_pilotage_tondeuse_est_un_choix_separe_des_autres_reglages(self) -> None:
        reponse = self._ecrire({}, {"pilotage_tondeuse": "observation"})
        self.assertTrue(reponse["ok"])
        self.assertEqual(self.entree.options["pilotage_tondeuse"], "observation")
        refus = self._ecrire({}, {"pilotage_tondeuse": "magique"})
        self.assertIn("pilotage_tondeuse", refus["erreurs"])

    def test_les_creneaux_de_depart_sont_un_choix_separe_du_mode_actif(self) -> None:
        reponse = self._ecrire({}, {"tondeuse_creneaux_depart": "ideal_acceptable"})
        self.assertTrue(reponse["ok"])
        self.assertEqual(self.entree.options["tondeuse_creneaux_depart"], "ideal_acceptable")
        self.assertNotIn("pilotage_tondeuse", self.entree.options)
        refus = self._ecrire({}, {"tondeuse_creneaux_depart": "nimporte_quand"})
        self.assertIn("tondeuse_creneaux_depart", refus["erreurs"])

    def test_le_volet_du_garage_est_valide_avant_ecriture(self) -> None:
        hass = types.SimpleNamespace(states=_Etats({"cover.garage_tondeuse": _Etat("closed")}))
        reponse = asyncio.run(panneau.ecrire_reglages(
            self.coordinateur, {}, {}, hass=hass, garage_tondeuse="cover.garage_tondeuse"
        ))
        self.assertTrue(reponse["ok"])
        self.assertEqual(self.entree.options["entite_volet_garage_tondeuse"], "cover.garage_tondeuse")
        refus = asyncio.run(panneau.ecrire_reglages(
            self.coordinateur, {}, {}, hass=hass, garage_tondeuse="cover.introuvable"
        ))
        self.assertFalse(refus["ok"])
        self.assertIn("garage_tondeuse", refus["erreurs"])

    def test_un_envoi_mal_forme_est_refuse(self) -> None:
        for valeurs, choix in (([], {}), ({}, "sableux")):
            with self.subTest(valeurs=valeurs, choix=choix):
                self.assertFalse(self._ecrire(valeurs, choix)["ok"])
        self.assertEqual(self.coordinateur.mises_a_jour, [])

    def test_une_valeur_inconnue_est_refusee(self) -> None:
        self.assertEqual(self._ecrire({"inconnu": 1})["erreurs"], {"inconnu": "Réglage inconnu."})


class LesAlertesSeReglentSurLaPageTests(unittest.TestCase):
    """0.93.0 : téléphones, alertes et IA, écrits dans les options de l'entrée par la page."""

    def setUp(self) -> None:
        self.entree = _Entree("e1", options={"reglages": {"tonte_vent_bloque": 45}, "debit_zone_1": 14.0})
        self.coordinateur = _Coordinateur(self.entree, conf={"type_sol": "limoneux"})
        self.hass = types.SimpleNamespace(
            data={DOMAIN: {"e1": self.coordinateur}},
            states=_Etats({
                "notify.iphone": _Etat("unknown", {"friendly_name": "iPhone"}),
                "notify.ipad": _Etat("unknown", {"friendly_name": "iPad"}),
                "ai_task.openai": _Etat("unknown", {"friendly_name": "OpenAI"}),
                "ai_task.ollama": _Etat("unknown", {"friendly_name": "Ollama"}),
            }),
            services=types.SimpleNamespace(has_service=lambda domaine, service: True),
        )

    def _ecrire(self, alertes: Any, valeurs: Any = None) -> dict[str, Any]:
        with _avec_registre(_Registre()):
            return asyncio.run(panneau.ecrire_reglages(
                self.coordinateur, valeurs or {}, {}, alertes, hass=self.hass,
            ))

    def test_les_trois_choix_sont_ecrits_avec_le_reste(self) -> None:
        reponse = self._ecrire(
            {"cibles": ["notify.iphone", "notify.iphone", "notify.ipad"], "alertes": False, "ia": "ai_task.ollama"},
            {"tonte_max_par_jour": 3},
        )
        self.assertTrue(reponse["ok"])
        self.assertEqual(len(self.coordinateur.mises_a_jour), 1, "une seule écriture pour tout")
        options = self.entree.options
        self.assertEqual(options["notification_cibles"], ["notify.iphone", "notify.ipad"])
        self.assertIs(options["alertes_actives"], False)
        self.assertEqual(options["entite_ia"], "ai_task.ollama")
        self.assertEqual(options["reglages"], {"tonte_vent_bloque": 45, "tonte_max_par_jour": 3})
        self.assertEqual(options["debit_zone_1"], 14.0, "les autres options restent")
        # La page repart de ce qui est enregistré.
        self.assertEqual([c["nom"] for c in reponse["notifications"]["cibles"]], ["iPhone", "iPad"])
        self.assertEqual(reponse["notifications"]["ia_choisie"], "ai_task.ollama")
        self.assertIs(reponse["notifications"]["alertes"], False)

    def test_seules_les_cles_envoyees_changent(self) -> None:
        self.entree.options.update({"notification_cibles": ["notify.ipad"], "entite_ia": "ai_task.openai"})
        self.assertTrue(self._ecrire({"alertes": True})["ok"])
        self.assertEqual(self.entree.options["notification_cibles"], ["notify.ipad"])
        self.assertEqual(self.entree.options["entite_ia"], "ai_task.openai")
        self.assertIs(self.entree.options["alertes_actives"], True)

    def test_les_categories_de_notification_sont_independantes(self) -> None:
        self.assertTrue(self._ecrire({
            "categories": {
                "arrosage_graines": False,
                "securite_arrosage": True,
                "capteurs_meteo": False,
                "tondeuse": True,
                "activite_arrosage": True,
                "activite_tondeuse": False,
                "garage_tondeuse": True,
            },
        })["ok"])
        self.assertIs(self.entree.options["notifier_arrosage_graines"], False)
        self.assertIs(self.entree.options["notifier_securite_arrosage"], True)
        self.assertIs(self.entree.options["notifier_capteurs_meteo"], False)
        self.assertIs(self.entree.options["notifier_tondeuse"], True)
        self.assertIs(self.entree.options["notifier_activite_arrosage"], True)
        self.assertIs(self.entree.options["notifier_activite_tondeuse"], False)
        self.assertIs(self.entree.options["notifier_garage_tondeuse"], True)

    def test_la_page_relit_chaque_famille(self) -> None:
        """Relevé par le banc de mutations (0.96.0) : chaque famille décochée doit se relire
        décochée, et elle seule."""
        familles = {
            "arrosage_graines": "notifier_arrosage_graines",
            "securite_arrosage": "notifier_securite_arrosage",
            "capteurs_meteo": "notifier_capteurs_meteo",
            "tondeuse": "notifier_tondeuse",
            "activite_arrosage": "notifier_activite_arrosage",
            "activite_tondeuse": "notifier_activite_tondeuse",
            "garage_tondeuse": "notifier_garage_tondeuse",
        }
        actifs_par_defaut = {"arrosage_graines", "securite_arrosage", "capteurs_meteo", "tondeuse"}
        for famille, option in familles.items():
            with self.subTest(famille=famille):
                entree = _Entree("e1", options={option: famille not in actifs_par_defaut})
                lues = panneau.notifications_de_l_instance(types.SimpleNamespace(states=_Etats()), entree)["categories"]
                attendu = {f: f in actifs_par_defaut for f in familles}
                attendu[famille] = famille not in actifs_par_defaut
                self.assertEqual(lues, attendu)

    def test_le_mode_de_notification_est_enregistre(self) -> None:
        reponse = self._ecrire({"mode": "veille_intelligente"})
        self.assertTrue(reponse["ok"])
        self.assertEqual(self.entree.options["mode_notifications"], "veille_intelligente")
        self.assertEqual(reponse["notifications"]["mode"], "veille_intelligente")

    def test_la_source_des_messages_est_enregistree(self) -> None:
        reponse = self._ecrire({"source": "conseiller_gazon"})
        self.assertTrue(reponse["ok"])
        self.assertEqual(self.entree.options["source_notifications"], "conseiller_gazon")
        self.assertEqual(reponse["notifications"]["source"], "conseiller_gazon")

    def test_niveau_et_heures_calmes_sont_enregistres_ensemble(self) -> None:
        reponse = self._ecrire({
            "niveau_minimal": "action",
            "heures_calmes": {"active": True, "debut": 21 * 60 + 30, "fin": 6 * 60 + 45},
        })
        self.assertTrue(reponse["ok"])
        self.assertEqual(self.entree.options["notification_niveau_minimal"], "action")
        self.assertIs(self.entree.options["notification_heures_calmes"], True)
        self.assertEqual(self.entree.options["notification_heures_calmes_debut"], 1290)
        self.assertEqual(self.entree.options["notification_heures_calmes_fin"], 405)
        self.assertEqual(reponse["notifications"]["niveau_minimal"], "action")
        self.assertEqual(
            reponse["notifications"]["heures_calmes"],
            {"active": True, "debut": 1290, "fin": 405},
        )

    def test_automatique_efface_le_choix_de_l_ia(self) -> None:
        self.entree.options["entite_ia"] = "ai_task.openai"
        self.assertTrue(self._ecrire({"ia": ""})["ok"])
        self.assertIsNone(self.entree.options["entite_ia"])
        self.assertTrue(self._ecrire({"cibles": []})["ok"])
        self.assertEqual(self.entree.options["notification_cibles"], [])

    def test_un_refus_n_ecrit_rien(self) -> None:
        cas = {
            "téléphone disparu": ({"cibles": ["notify.ancien"]}, "Ce téléphone n'existe plus dans Home Assistant : notify.ancien."),
            "ia inconnue": ({"ia": "ai_task.inconnue"}, "Cette IA n'existe pas dans Home Assistant : ai_task.inconnue."),
            "pas une entité notify": ({"cibles": ["light.salon"]}, "Ce téléphone n'existe plus dans Home Assistant : light.salon."),
            "liste mal formée": ({"cibles": "notify.iphone"}, "La liste des téléphones n'a pas la bonne forme."),
            "case mal formée": ({"alertes": "oui"}, "Le choix des alertes n'a pas la bonne forme."),
            "catégories mal formées": ({"categories": []}, "Les catégories de notification n'ont pas la bonne forme."),
            "catégorie inconnue": ({"categories": {"pluie": True}}, "Catégorie de notification inconnue : pluie."),
            "valeur de catégorie mal formée": ({"categories": {"tondeuse": "oui"}}, "Chaque catégorie de notification doit être cochée ou décochée."),
            "mode inconnu": ({"mode": "magique"}, "Choisis Veille intelligente ou Choix manuel."),
            "source inconnue": ({"source": "magique"}, "Choisis les messages de Gazon Intelligent ou du Conseiller Gazon."),
            "niveau inconnu": ({"niveau_minimal": "bruyant"}, "Choisis Tout recevoir, Important ou Urgences seulement."),
            "heures calmes mal formées": ({"heures_calmes": {"active": True}}, "Les heures calmes n'ont pas la bonne forme."),
            "heure hors journée": ({"heures_calmes": {"active": True, "debut": 1440, "fin": 420}}, "Choisis des heures calmes comprises dans la journée."),
            "ia mal formée": ({"ia": 3}, "Cette IA n'existe pas dans Home Assistant : 3."),
            "clé inconnue": ({"sirene": True}, "Réglage d'alerte inconnu : sirene."),
        }
        for nom, (envoi, message) in cas.items():
            with self.subTest(cas=nom):
                reponse = self._ecrire(envoi, {"tonte_max_par_jour": 3})
                self.assertEqual(reponse, {"ok": False, "erreurs": {"notifications": message}})
        self.assertEqual(self.coordinateur.mises_a_jour, [], "un refus ne doit rien écrire, réglages compris")

    def test_la_commande_transmet_les_alertes(self) -> None:
        connexion = _Connexion()
        message = {
            "id": 9, "type": panneau.WS_ECRIRE, "entry_id": "e1", "valeurs": {}, "choix": {},
            "notifications": {"cibles": ["notify.iphone"]},
        }
        with _avec_registre(_Registre()):
            asyncio.run(panneau._ws_ecrire(self.hass, connexion, message))
        self.assertTrue(connexion.resultats[0][1]["ok"])
        self.assertEqual(self.entree.options["notification_cibles"], ["notify.iphone"])
        self.assertIn("notifications", connexion.resultats[0][1])


class _Connexion:
    def __init__(self) -> None:
        self.resultats: list[tuple[int, Any]] = []
        self.erreurs: list[tuple[int, str, str]] = []

    def send_result(self, id_: int, resultat: Any) -> None:
        self.resultats.append((id_, resultat))

    def send_error(self, id_: int, code: str, message: str) -> None:
        self.erreurs.append((id_, code, message))


class LesCommandesTests(unittest.TestCase):
    def test_lire_sans_instance_rend_une_erreur_claire(self) -> None:
        hass, _ = _hass()
        connexion = _Connexion()
        asyncio.run(panneau._ws_lire(hass, connexion, {"id": 3, "type": panneau.WS_LIRE}))
        self.assertEqual(connexion.erreurs[0][:2], (3, "not_found"))

    def test_lire_rend_les_donnees_de_l_instance(self) -> None:
        coordinateur = _Coordinateur(_Entree("e1"), conf={"zone_1": "switch.vanne_1"})
        hass, _ = _hass(coordinateur)
        connexion = _Connexion()
        with _avec_registre(_Registre()):
            asyncio.run(panneau._ws_lire(hass, connexion, {"id": 4, "type": panneau.WS_LIRE}))
        self.assertEqual(connexion.resultats[0][0], 4)
        self.assertEqual(connexion.resultats[0][1]["entry_id"], "e1")

    def test_ecrire_rend_le_resultat_ou_l_erreur(self) -> None:
        coordinateur = _Coordinateur(_Entree("e1"))
        hass, _ = _hass(coordinateur)
        connexion = _Connexion()
        message = {"id": 5, "type": panneau.WS_ECRIRE, "entry_id": "e1", "valeurs": {"tonte_max_par_jour": 3}, "choix": {}}
        asyncio.run(panneau._ws_ecrire(hass, connexion, message))
        self.assertTrue(connexion.resultats[0][1]["ok"])
        coordinateur.async_update_config = AsyncMock(side_effect=RuntimeError("disque plein"))
        asyncio.run(panneau._ws_ecrire(hass, connexion, dict(message, id=6)))
        self.assertEqual(connexion.erreurs[-1], (6, "unknown_error", "disque plein"))
        asyncio.run(panneau._ws_ecrire(hass, connexion, dict(message, id=7, entry_id="inconnue")))
        self.assertEqual(connexion.erreurs[-1][:2], (7, "not_found"))


def _faux_composants():
    """websocket_api, frontend, panel_custom, http et loader, qui notent ce qu'on leur demande."""
    journal: dict[str, list] = {"commandes": [], "panneaux": [], "retraits": [], "fichiers": []}

    ws = types.ModuleType("homeassistant.components.websocket_api")

    def websocket_command(schema):
        def decorer(fonction):
            fonction._ws_schema = schema
            # La clé est `vol.Required("type")` : selon le stub de voluptuous chargé par la suite,
            # ce n'est pas forcément la chaîne « type ». La commande est la valeur qui la nomme.
            fonction._ws_command = next(v for v in schema.values() if isinstance(v, str) and v.startswith(f"{DOMAIN}/"))
            return fonction
        return decorer

    def require_admin(fonction):
        fonction._admin = True
        return fonction

    ws.websocket_command = websocket_command  # type: ignore[attr-defined]
    ws.async_response = lambda fonction: fonction  # type: ignore[attr-defined]
    ws.require_admin = require_admin  # type: ignore[attr-defined]
    ws.async_register_command = lambda hass, gestionnaire: journal["commandes"].append(gestionnaire)  # type: ignore[attr-defined]

    frontend = types.ModuleType("homeassistant.components.frontend")
    frontend.async_remove_panel = lambda hass, url: journal["retraits"].append(url)  # type: ignore[attr-defined]

    panel_custom = types.ModuleType("homeassistant.components.panel_custom")

    async def async_register_panel(hass, **kwargs):
        journal["panneaux"].append(kwargs)

    panel_custom.async_register_panel = async_register_panel  # type: ignore[attr-defined]

    http = types.ModuleType("homeassistant.components.http")
    http.StaticPathConfig = lambda url, chemin, cache: (url, chemin, cache)  # type: ignore[attr-defined]

    loader = types.ModuleType("homeassistant.loader")

    async def async_get_integration(hass, domaine):
        return types.SimpleNamespace(version="0.92.0")

    loader.async_get_integration = async_get_integration  # type: ignore[attr-defined]

    components = types.ModuleType("homeassistant.components")
    components.__path__ = []  # type: ignore[attr-defined]
    components.websocket_api = ws  # type: ignore[attr-defined]
    components.frontend = frontend  # type: ignore[attr-defined]
    components.panel_custom = panel_custom  # type: ignore[attr-defined]
    components.http = http  # type: ignore[attr-defined]
    racine = sys.modules.get("homeassistant") or types.ModuleType("homeassistant")
    if not hasattr(racine, "__path__"):
        racine.__path__ = []  # type: ignore[attr-defined]
    modules = {
        "homeassistant": racine,
        "homeassistant.components": components,
        "homeassistant.components.websocket_api": ws,
        "homeassistant.components.frontend": frontend,
        "homeassistant.components.panel_custom": panel_custom,
        "homeassistant.components.http": http,
        "homeassistant.loader": loader,
    }
    return patch.dict(sys.modules, modules), journal


class LEnregistrementTests(unittest.TestCase):
    def _hass_http(self, *coordinateurs):
        hass, _ = _hass(*coordinateurs)
        fichiers: list = []

        async def async_register_static_paths(configs):
            fichiers.extend(configs)

        hass.http = types.SimpleNamespace(async_register_static_paths=async_register_static_paths)
        return hass, fichiers

    def test_les_commandes_une_seule_fois_et_l_ecriture_reservee_aux_admins(self) -> None:
        faux, journal = _faux_composants()
        hass, _ = self._hass_http()
        with faux:
            panneau.async_enregistrer_commandes(hass)
            panneau.async_enregistrer_commandes(hass)
        self.assertEqual([c._ws_command for c in journal["commandes"]], [panneau.WS_LIRE, panneau.WS_ECRIRE])
        lire, ecrire = journal["commandes"]
        self.assertFalse(getattr(lire, "_admin", False))
        self.assertTrue(getattr(ecrire, "_admin", False))
        # Le schéma accepte les alertes (0.93.0) : sans cette clé, Home Assistant refuserait l'envoi.
        # Selon le stub de voluptuous chargé avant, une clé est une chaîne ou un marqueur qui la porte.
        noms = {(cle.args[0] if getattr(cle, "args", None) else cle) for cle in ecrire._ws_schema}
        self.assertIn("notifications", noms)
        self.assertIn("pompe", noms)
        self.assertIn("entrees", noms)

    def test_le_panneau_suit_les_instances_qui_le_veulent(self) -> None:
        faux, journal = _faux_composants()
        coordinateur = _Coordinateur(_Entree("e1"))
        hass, fichiers = self._hass_http(coordinateur)
        with faux:
            asyncio.run(panneau.async_mettre_a_jour_panneau(hass))
            asyncio.run(panneau.async_mettre_a_jour_panneau(hass))  # rien ne change : rien de refait
            self.assertEqual(len(journal["panneaux"]), 1)
            appel = journal["panneaux"][0]
            self.assertEqual(appel["frontend_url_path"], "gazon")
            self.assertEqual(appel["webcomponent_name"], "gazon-intelligent-panel")
            self.assertEqual(appel["module_url"], "/gazon_intelligent_panneau/gazon-intelligent-panel.js?v=0.92.0")
            self.assertFalse(appel["require_admin"])
            self.assertEqual(fichiers, [("/gazon_intelligent_panneau", str(panneau.DOSSIER_FRONTEND), False)])

            coordinateur.entry.options = {"page_gazon": False}  # case décochée
            asyncio.run(panneau.async_mettre_a_jour_panneau(hass))
            self.assertEqual(journal["retraits"], ["gazon"])

            coordinateur.entry.options = {}  # recochée : le panneau revient, les fichiers ne sont pas réenregistrés
            asyncio.run(panneau.async_mettre_a_jour_panneau(hass))
            self.assertEqual(len(journal["panneaux"]), 2)
            self.assertEqual(len(fichiers), 1)

    def test_sans_instance_rien_n_est_affiche(self) -> None:
        faux, journal = _faux_composants()
        hass, fichiers = self._hass_http()
        with faux:
            asyncio.run(panneau.async_mettre_a_jour_panneau(hass))
        self.assertEqual((journal["panneaux"], journal["retraits"], fichiers), ([], [], []))


if __name__ == "__main__":
    unittest.main()
