"""Le bandeau d'intro des réglages ne doit pas bouger la page tout seul.

Signalé le 19/09/2026 (« pourquoi ma page bouge tout seul » puis « la page descend petit à
petit jusqu'au bas de la page », sur toutes les pages de réglages) : ce bandeau est nourri par
le moteur de décision, recalculé à chaque cycle du coordinateur (~2 min). Sans figeage, chaque
petit changement de contenu au-dessus de ce que l'utilisateur regarde plus bas décale toute la page,
cycle après cycle, sans qu'il ait touché à rien.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PANNEAU = ROOT / "custom_components" / "gazon_intelligent" / "frontend" / "gazon-intelligent-panel.js"
NODE = shutil.which("node")

SCRIPT = r"""
const fs = require("fs");
const vm = require("vm");
const chemin = JSON.parse(fs.readFileSync(0, "utf8")).chemin;
const ctx = {
  HTMLElement: class {},
  customElements: { get: () => undefined, define: (_nom, classe) => { ctx.Classe = classe; } },
  console,
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(chemin, "utf8"), ctx);

const panel = Object.create(ctx.Classe.prototype);
panel._hass = { user: { is_admin: true } };
panel._donnees = { titre: "", registre: { reglages: [] } };
panel._pucesProgrammeGraines = () => [];
panel._pucesProgrammeMode = () => [];

// Premier appel : le contexte dit « Sursemis ».
panel._contexte = () => ({ mode: "Sursemis", hauteurConseillee: null, soleil: null, semis: null });
const premier = panel._introReglagesHtml();

// Le moteur de décision change d'avis (cycle suivant du coordinateur), mais `_donnees` — donc
// la pelouse chargée — n'a pas changé : rien n'a été sauvegardé, rien n'a été rechargé.
panel._contexte = () => ({ mode: "TRAITEMENT", hauteurConseillee: null, soleil: null, semis: null });
const pendantLaLecture = panel._introReglagesHtml();

// Une vraie raison de rafraîchir : une sauvegarde crée une nouvelle référence `_donnees`
// (voir `_enregistrer`, `this._donnees = { ...this._donnees, ... }`).
panel._donnees = { ...panel._donnees };
const apresSauvegarde = panel._introReglagesHtml();

process.stdout.write(JSON.stringify({ premier, pendantLaLecture, apresSauvegarde }));
"""

SCRIPT_SETTER = r"""
const fs = require("fs");
const vm = require("vm");
const chemin = JSON.parse(fs.readFileSync(0, "utf8")).chemin;
const ctx = {
  HTMLElement: class {},
  customElements: { get: () => undefined, define: (_nom, classe) => { ctx.Classe = classe; } },
  console,
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(chemin, "utf8"), ctx);

function cas(themeChange) {
  const panel = Object.create(ctx.Classe.prototype);
  let partiel = 0;
  let complet = 0;
  panel._hass = { themes: { darkMode: false } };
  panel._etat = "pret";
  panel._vue = "reglages";
  panel._sombreConnu = false;
  panel.toggleAttribute = () => {};
  panel._oublierAttentesArrivees = () => {};
  panel._aChange = () => { panel._sombreConnu = themeChange; return true; };
  panel._rafraichirValeursReglages = () => { partiel += 1; };
  panel._rendreQuandLibre = () => { complet += 1; };
  Object.getOwnPropertyDescriptor(ctx.Classe.prototype, "hass").set.call(panel, { themes: { darkMode: themeChange } });
  return { partiel, complet };
}

process.stdout.write(JSON.stringify({ normal: cas(false), theme: cas(true) }));
"""

SCRIPT_GARAGE = r"""
const fs = require("fs");
const vm = require("vm");
const chemin = JSON.parse(fs.readFileSync(0, "utf8")).chemin;
const ctx = {
  HTMLElement: class {},
  customElements: { get: () => undefined, define: (_nom, classe) => { ctx.Classe = classe; } },
  console,
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(chemin, "utf8"), ctx);

function html(choisie) {
  const panel = Object.create(ctx.Classe.prototype);
  panel._hass = {
    user: { is_admin: true },
    states: {
      "cover.garage_tondeuse": { state: "closed", attributes: { friendly_name: "Garage tondeuse" } },
    },
  };
  panel._donnees = {
    garage_tondeuse: {
      choisie,
      volets: [{ entity_id: "cover.garage_tondeuse", nom: "Garage tondeuse" }],
    },
  };
  panel._brouillonGarageTondeuse = undefined;
  panel._brouillon = {};
  panel._reglage = (cle) => ({ cle, titre: cle });
  panel._ligneHtml = (reglage) => `<div data-reglage="${reglage.cle}"></div>`;
  panel._valeur = (cle) => ({
    tondeuse_garage_ouvrir_avant_depart: true,
    tondeuse_garage_ouverture_min: 95,
    tondeuse_garage_avance_ouverture: 2,
    tondeuse_garage_ouvrir_pour_retour: true,
    tondeuse_garage_fermer_apres_retour: true,
    tondeuse_garage_delai_fermeture: 2,
  })[cle];
  return panel._garageTondeuseHtml();
}

process.stdout.write(JSON.stringify({ avec: html("cover.garage_tondeuse"), sans: html(null) }));
"""

SCRIPT_BARRE = r"""
const fs = require("fs");
const vm = require("vm");
const chemin = JSON.parse(fs.readFileSync(0, "utf8")).chemin;
const ctx = {
  HTMLElement: class {},
  customElements: { get: () => undefined, define: (_nom, classe) => { ctx.Classe = classe; } },
  console,
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(chemin, "utf8"), ctx);

function classeBarre(changements) {
  const classes = new Set();
  const attributs = {};
  const panel = Object.create(ctx.Classe.prototype);
  panel._etat = "pret";
  panel._enregistrement = false;
  panel._nombreChangements = () => changements;
  panel._barre = {
    classList: { toggle: (nom, actif) => actif ? classes.add(nom) : classes.delete(nom) },
    setAttribute: (nom, valeur) => { attributs[nom] = valeur; },
    innerHTML: "",
  };
  panel._donnees = { registre: { reglages: [], contraintes: [] } };
  panel._toutesLesValeurs = () => ({});
  panel._erreurEntite = () => "";
  panel._majBarre();
  return { visible: classes.has("visible"), ariaHidden: attributs["aria-hidden"], html: panel._barre.innerHTML };
}

process.stdout.write(JSON.stringify({ vide: classeBarre(0), brouillon: classeBarre(1) }));
"""


def _rendre() -> dict[str, str]:
    assert NODE
    resultat = subprocess.run(
        [NODE, "-e", SCRIPT],
        input=json.dumps({"chemin": str(PANNEAU)}),
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return json.loads(resultat.stdout)


def _rendre_setter() -> dict[str, dict[str, int]]:
    assert NODE
    resultat = subprocess.run(
        [NODE, "-e", SCRIPT_SETTER],
        input=json.dumps({"chemin": str(PANNEAU)}),
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return json.loads(resultat.stdout)


def _rendre_garage() -> dict[str, str]:
    assert NODE
    resultat = subprocess.run(
        [NODE, "-e", SCRIPT_GARAGE],
        input=json.dumps({"chemin": str(PANNEAU)}),
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return json.loads(resultat.stdout)


def _rendre_barre() -> dict[str, dict[str, Any]]:
    assert NODE
    resultat = subprocess.run(
        [NODE, "-e", SCRIPT_BARRE],
        input=json.dumps({"chemin": str(PANNEAU)}),
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return json.loads(resultat.stdout)


@unittest.skipUnless(NODE, "Node n'est pas installé")
class IntroReglagesFigeeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rendu = _rendre()

    def test_le_bandeau_reste_fige_tant_que_les_donnees_ne_changent_pas(self) -> None:
        self.assertIn("Sursemis", self.rendu["premier"])
        self.assertIn(
            "Sursemis",
            self.rendu["pendantLaLecture"],
            "le bandeau a été recalculé alors que rien n'a été sauvegardé ni rechargé : "
            "c'est exactement ce qui fait bouger la page toute seule",
        )
        self.assertNotIn("TRAITEMENT", self.rendu["pendantLaLecture"])
        self.assertEqual(self.rendu["premier"], self.rendu["pendantLaLecture"])

    def test_le_bandeau_se_met_a_jour_apres_un_vrai_changement_de_donnees(self) -> None:
        self.assertIn("TRAITEMENT", self.rendu["apresSauvegarde"])


@unittest.skipUnless(NODE, "Node n'est pas installé")
class ReglagesSansRenduCompletTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rendu = _rendre_setter()

    def test_une_mise_a_jour_ha_dans_reglages_ne_reconstruit_pas_la_page(self) -> None:
        self.assertEqual(self.rendu["normal"], {"partiel": 1, "complet": 0})

    def test_un_changement_de_theme_garde_un_rendu_complet(self) -> None:
        self.assertEqual(self.rendu["theme"], {"partiel": 0, "complet": 1})


@unittest.skipUnless(NODE, "Node n'est pas installé")
class GarageTondeuseAffichageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rendu = _rendre_garage()

    def test_un_volet_choisi_affiche_son_etat_et_ses_automatismes(self) -> None:
        self.assertIn("Garage tondeuse", self.rendu["avec"])
        self.assertIn("fermé", self.rendu["avec"])
        self.assertIn("Avant le départ", self.rendu["avec"])
        self.assertIn("Au retour", self.rendu["avec"])
        self.assertIn("passage à 95 %", self.rendu["avec"])
        self.assertIn('data-reglage="tondeuse_garage_ouvrir_avant_depart"', self.rendu["avec"])
        self.assertIn('data-reglage="tondeuse_garage_ouverture_min"', self.rendu["avec"])

    def test_sans_volet_les_automatismes_restent_masques(self) -> None:
        self.assertIn("Sélectionner un volet", self.rendu["sans"])
        self.assertNotIn("Avant le départ", self.rendu["sans"])
        self.assertNotIn("tondeuse_garage_ouvrir_avant_depart", self.rendu["sans"])


@unittest.skipUnless(NODE, "Node n'est pas installé")
class BarreEnregistrementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rendu = _rendre_barre()

    def test_la_barre_est_inerte_sans_changement(self) -> None:
        self.assertEqual(self.rendu["vide"], {"visible": False, "ariaHidden": "true", "html": ""})

    def test_la_barre_redevient_active_avec_un_brouillon(self) -> None:
        self.assertTrue(self.rendu["brouillon"]["visible"])
        self.assertEqual(self.rendu["brouillon"]["ariaHidden"], "false")
        self.assertIn("Enregistrer", self.rendu["brouillon"]["html"])


if __name__ == "__main__":
    unittest.main()
