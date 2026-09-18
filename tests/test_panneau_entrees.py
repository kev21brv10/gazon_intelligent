"""La page propose les mêmes entités que celles que le serveur accepte (0.95.0).

La page filtre la liste « Changer / Brancher » avec une copie JavaScript de `sources.refus`. Une
copie qui accepterait plus que le serveur proposerait des choix refusés à l'enregistrement ; une
copie qui accepterait moins cacherait des entités valables. Ce test exécute la copie avec Node sur
plus de 470 000 cas (15 entrées × 31 680 profils) et compare chaque verdict à celui du serveur.
Sans Node, il est sauté.
"""

from __future__ import annotations

import itertools
import json
import re
import shutil
import subprocess
import types
import unittest
from pathlib import Path
from typing import Any

from tests.test_panneau import _avec_registre, _Coordinateur, _Entree, _Etat, _Etats, _Registre, panneau

ROOT = Path(__file__).resolve().parents[1]
PANNEAU = ROOT / "custom_components" / "gazon_intelligent" / "frontend" / "gazon-intelligent-panel.js"
DEBUT_BLOC = "// ─── Changer une entrée (0.95.0)"
NODE = shutil.which("node")
sources = panneau.sources_meteo

PROFILS: list[dict[str, Any]] = [
    # (domaine, unité, classe d'appareil, classe d'état, valeur, nom d'affichage)
    {"id": f"{domaine}.capteur_{i}", "attributs": attributs, "etat": etat}
    for i, (domaine, attributs, etat) in enumerate(
        (domaine, {k: v for k, v in {
            "unit_of_measurement": unite, "device_class": classe, "state_class": classe_etat, "friendly_name": nom,
        }.items() if v is not None}, etat)
        for domaine, unite, classe, classe_etat, etat, nom in itertools.product(
            ("sensor", "weather", "switch"),
            (None, "°C", "°F", "%", "km/h", "ft/s", "hPa", "kPa", "psi", "W/m²", "lx", "mm", "mm/h", "in", "cm", "MM"),
            (None, "temperature", "humidity", "battery", "precipitation", "precipitation_intensity",
             "irradiance", "atmospheric_pressure", "wind_speed", "moisture", "distance"),
            (None, "measurement", "total_increasing"),
            ("12.5", "Pas de pluie", "unavailable", "3 mm"),
            (None, "Humidité foliaire", "Station Humidité", "Point de rosée", "Humidité du sol"),
        )
    )
]


def _bloc_des_entrees() -> str:
    texte = PANNEAU.read_text(encoding="utf-8")
    lignes = texte.splitlines()
    debut = next(i for i, ligne in enumerate(lignes) if ligne.startswith(DEBUT_BLOC))
    fin = next(i for i in range(debut + 1, len(lignes)) if lignes[i].startswith("// ───"))
    etats_sans_valeur = re.search(r"^const ETATS_SANS_VALEUR = .*;$", texte, re.M)
    assert etats_sans_valeur, "la page ne définit plus ETATS_SANS_VALEUR"
    return etats_sans_valeur.group(0) + "\n" + "\n".join(lignes[debut:fin])


def _lignes_servies() -> list[dict[str, Any]]:
    """Les lignes `sources` telles que la page les reçoit (c'est ce que la copie lit)."""
    coordinateur = _Coordinateur(_Entree("e1"))
    hass = types.SimpleNamespace(data={"gazon_intelligent": {"e1": coordinateur}}, states=_Etats())
    with _avec_registre(_Registre()):
        return panneau.sources_de_l_instance(hass, coordinateur)


def _node(script: str, donnees: Any) -> Any:
    sortie = subprocess.run(
        [NODE, "-e", script], input=json.dumps(donnees), capture_output=True, text=True, check=True, timeout=60,
    )
    return json.loads(sortie.stdout)


def _methode_page(nom: str) -> str:
    """Extrait une methode du composant pour verifier son rangement entre onglets."""
    texte = PANNEAU.read_text(encoding="utf-8")
    debut = texte.index(f"  {nom}(")
    fin = texte.index("\n  _", debut + 3)
    return texte[debut:fin]


class RangementDesEntreesTests(unittest.TestCase):
    def test_les_entrees_sont_dans_mon_installation_et_plus_dans_meteo(self) -> None:
        self.assertNotIn("this._meteoEntreesHtml()", _methode_page("_ongletMeteoHtml"))
        self.assertIn("this._meteoEntreesHtml()", _methode_page("_installationHtml"))


@unittest.skipUnless(NODE, "Node n'est pas installé")
class LaPageProposeCeQueLeServeurAccepteTests(unittest.TestCase):
    def test_les_champs_lus_par_la_page_sont_servis(self) -> None:
        lus = set(re.findall(r"\bsource\.(\w+)", _bloc_des_entrees()))
        self.assertTrue(lus, "prémisse : la copie lit bien des champs de la ligne")
        for ligne in _lignes_servies():
            with self.subTest(cle=ligne["cle"]):
                self.assertLessEqual(lus, set(ligne), "un champ lu par la page n'est pas servi")

    def test_memes_verdicts_que_le_serveur(self) -> None:
        lignes = _lignes_servies()
        cas = [(ligne, profil) for ligne in lignes for profil in PROFILS]
        script = _bloc_des_entrees() + """
const cas = JSON.parse(require("fs").readFileSync(0, "utf8"));
console.log(JSON.stringify(cas.map(([ligne, p]) => entreeAcceptee(ligne, p.id, p.attributs, p.etat))));
"""
        verdicts_page = _node(script, cas)
        self.assertEqual(len(verdicts_page), len(cas))
        acceptes = refuses = 0
        for (ligne, profil), page in zip(cas, verdicts_page):
            a = profil["attributs"]
            serveur = sources.refus(
                sources.PAR_CLE[ligne["cle"]],
                entity_id=profil["id"],
                unite=a.get("unit_of_measurement"),
                classe=a.get("device_class"),
                classe_etat=a.get("state_class"),
                nom=a.get("friendly_name"),
                etat=profil["etat"],
            )
            if page != (serveur is None):
                self.fail(f"{ligne['cle']} × {profil} : page {page}, serveur {serveur!r}")
            acceptes += page
            refuses += not page
        # Le banc mord des deux côtés : assez de cas acceptés ET de cas refusés.
        self.assertGreater(acceptes, 500)
        self.assertGreater(refuses, 500)

    def test_la_page_ignore_ce_que_le_moteur_ignore(self) -> None:
        lignes = _lignes_servies()
        cas = [(ligne, profil["attributs"]) for ligne in lignes for profil in PROFILS[::7]]
        script = _bloc_des_entrees() + """
const cas = JSON.parse(require("fs").readFileSync(0, "utf8"));
console.log(JSON.stringify(cas.map(([ligne, a]) => lectureInterdite(ligne, a))));
"""
        verdicts = _node(script, cas)
        interdits = 0
        for (ligne, attributs), page in zip(cas, verdicts):
            serveur = sources.interdit(
                sources.PAR_CLE[ligne["cle"]],
                unite=attributs.get("unit_of_measurement"),
                classe=attributs.get("device_class"),
            )
            self.assertEqual(page, serveur, f"{ligne['cle']} × {attributs}")
            interdits += serveur
        self.assertGreater(interdits, 50, "prémisse : des cas interdits sont bien comparés")

    def test_la_liste_commence_par_ce_que_le_nom_annonce(self) -> None:
        rosee = next(ligne for ligne in _lignes_servies() if ligne["cle"] == "capteur_rosee")
        humidite = next(ligne for ligne in _lignes_servies() if ligne["cle"] == "capteur_humidite")
        etats = {
            "sensor.zz_humidite": _Etat("60", {"unit_of_measurement": "%", "device_class": "humidity", "friendly_name": "Zeta"}),
            "sensor.aa_humidite": _Etat("61", {"unit_of_measurement": "%", "device_class": "humidity", "friendly_name": "Alpha"}),
            "sensor.station_humidite": _Etat("63", {"unit_of_measurement": "%", "device_class": "humidity", "friendly_name": "Station"}),
            "sensor.gazon_intelligent_etat_hydrique": _Etat("40", {"unit_of_measurement": "%", "device_class": "humidity"}),
            "sensor.renomme": _Etat("40", {"unit_of_measurement": "%", "device_class": "humidity", "friendly_name": "Renommé"}),
            "sensor.jardin_humidite_foliaire": _Etat("0", {"unit_of_measurement": "%", "friendly_name": "Feuilles"}),
            "sensor.stress_thermique": _Etat("36", {"unit_of_measurement": "%", "friendly_name": "Stress thermique"}),
            "sensor.station_point_de_rosee": _Etat("11.8", {"unit_of_measurement": "°C", "device_class": "temperature"}),
        }
        script = _bloc_des_entrees() + """
const [ligne, etats, propres, appareils] = JSON.parse(require("fs").readFileSync(0, "utf8"));
console.log(JSON.stringify(candidatsEntree(ligne, etats, { propres: new Set(propres), appareils: new Map(appareils) })
  .map((c) => [c.id, c.indice, c.appareil])));
"""
        en_json = {k: {"state": v.state, "attributes": v.attributes} for k, v in etats.items()}
        appareils = [["sensor.station_humidite", "Station du jardin"]]
        self.assertEqual(
            _node(script, [humidite, en_json, ["sensor.renomme"], appareils]),
            [
                # Sur un appareil déjà branché d'abord, puis par nom ; jamais l'intégration elle-même,
                # ni une humidité du feuillage, ni un pourcentage sans classe ni nom (« Stress thermique »).
                ["sensor.station_humidite", True, "Station du jardin"],
                ["sensor.aa_humidite", True, None],
                ["sensor.zz_humidite", True, None],
            ],
        )
        self.assertEqual(
            _node(script, [rosee, en_json, [], appareils]),
            [["sensor.jardin_humidite_foliaire", True, None]],
            "ni l'humidité de l'air, ni un point de rosée",
        )


if __name__ == "__main__":
    unittest.main()
