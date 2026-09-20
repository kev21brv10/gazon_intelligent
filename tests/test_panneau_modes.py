"""L'onglet Réglages → Modes, exécuté pour de vrai (0.96.0).

Une rangée de neuf modes, puis la fiche du mode regardé (ses règles, ses réglages) et une carte
d'action : passer dans ce mode, déclarer un produit, ou revenir au mode Normal. Ce test charge la
page dans Node, rend l'onglet avec le vrai registre et compare le HTML produit à ce que le serveur
connaît (`const.INTERVENTIONS_ACTIONS`, `const.APPLICATION_INTERVENTIONS`, durées de
`phases.py`). Seuls le rendu d'une ligne de réglage et le dessin sont remplacés par un repère :
ils sont vérifiés ailleurs. Sans Node, il est sauté.
"""

from __future__ import annotations

import html
import importlib
import json
import re
import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from tests.test_panneau import reglages

ROOT = Path(__file__).resolve().parents[1]
PANNEAU = ROOT / "custom_components" / "gazon_intelligent" / "frontend" / "gazon-intelligent-panel.js"
NODE = shutil.which("node")
const = importlib.import_module("custom_components.gazon_intelligent.const")
phases = importlib.import_module("custom_components.gazon_intelligent.phases")

MODES = ("Normal", *const.INTERVENTIONS_ACTIONS)
PRODUITS = [
    {"id": "fongicide", "nom": "Fongicide", "type": "Traitement"},
    {"id": "engrais", "nom": "Engrais", "type": "fertilisation"},
    {"id": "engrais_2", "nom": "Engrais d'automne", "type": "Fertilisation"},
    {"id": "algues", "nom": "Algues", "type": "Biostimulant"},
    {"id": "mouillant", "nom": "Mouillant", "type": "Agent Mouillant"},
    {"id": "scarif", "nom": "Après scarification", "type": " Scarification "},
]

SCRIPT = r"""
const fs = require("fs");
const vm = require("vm");
const { chemin, registre, cas } = JSON.parse(fs.readFileSync(0, "utf8"));
const ctx = {
  HTMLElement: class {},
  customElements: { get: () => undefined, define: (nom, classe) => { ctx.Classe = classe; } },
  console, structuredClone,
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(chemin, "utf8"), ctx);
const constantes = vm.runInContext("({ MODES, MODES_PRODUIT, REGLES_MODES, ICONES_MODES, LIENS_MODES, DISPOSITION })", ctx);
const groupe = registre.groupes.find((g) => g.cle === "modes");
const sorties = cas.map((c) => {
  const p = Object.create(ctx.Classe.prototype);
  const etats = {};
  if (c.actuel !== null) etats["select.gazon_mode"] = { state: c.actuel, attributes: { options: c.options } };
  etats["sensor.gazon_catalogue"] = { state: "ok", attributes: { products_summary: c.produits } };
  etats["sensor.gazon_blocage"] = { state: c.verrou ? "Bloqué (sécurité)" : "Aucun besoin", attributes: { safety_lock_actif: c.verrou } };
  p._hass = { states: etats, user: { is_admin: c.admin }, config: { time_zone: "Europe/Paris" } };
  p._donnees = {
    registre,
    entites: { mode: "select.gazon_mode", catalogue_produits: "sensor.gazon_catalogue", blocage_arrosage: "sensor.gazon_blocage" },
    valeurs: c.valeurs,
    produits: c.admin ? c.produits : undefined,
  };
  p._brouillon = {};
  p._modeReglage = c.choisi;
  p._ligneHtml = (r) => `<div class="repere-ligne" data-cle="${r.cle}"></div>`;
  p._dessinHtml = (d) => `<div class="repere-dessin" data-quoi="${d}"></div>`;
  p._contexte = () => ({ semis: c.semis });
  return { visible: p._modeVisible(), html: p._groupeHtml(groupe) };
});
process.stdout.write(JSON.stringify({ constantes, groupes: registre.groupes.map((g) => g.cle), sorties }));
"""


class _Balises(HTMLParser):
    """Chaque balise ouvrante (nom, attributs, texte jusqu'à sa fermeture), dans l'ordre."""

    def __init__(self) -> None:
        super().__init__()
        self.balises: list[dict[str, Any]] = []
        self._ouvertes: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        b = {"tag": tag, "attrs": dict(attrs), "texte": "", "classes": set((dict(attrs).get("class") or "").split())}
        self.balises.append(b)
        if tag not in ("br", "img", "input", "i"):
            self._ouvertes.append(b)

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self._ouvertes) - 1, -1, -1):
            if self._ouvertes[i]["tag"] == tag:
                del self._ouvertes[i:]
                break

    def handle_data(self, data: str) -> None:
        for b in self._ouvertes:
            b["texte"] += data


def _balises(fragment: str) -> list[dict[str, Any]]:
    lecteur = _Balises()
    lecteur.feed(fragment)
    return lecteur.balises


def _bloc(fragment: str, classe: str) -> str:
    """Le HTML de la première `<section>`/`<nav>` portant `classe` (sections non imbriquées)."""
    debut = re.search(rf'<(section|nav) class="[^"]*\b{classe}\b[^"]*"', fragment)
    if not debut:
        return ""
    fin = fragment.index(f"</{debut.group(1)}>", debut.start())
    return fragment[debut.start():fin]


def _texte(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def _cas(**valeurs: Any) -> dict[str, Any]:
    cas: dict[str, Any] = {
        "actuel": "Normal", "options": list(MODES), "admin": True, "choisi": None,
        "valeurs": {}, "produits": PRODUITS, "semis": None,
        "verrou": False,
    }
    cas.update(valeurs)
    return cas


def _rendre(cas: list[dict[str, Any]]) -> dict[str, Any]:
    assert NODE
    donnees = {"chemin": str(PANNEAU), "registre": reglages.exporter(), "cas": cas}
    sortie = subprocess.run(
        [NODE, "-e", SCRIPT], input=json.dumps(donnees), capture_output=True, text=True, check=True, timeout=60,
    )
    return json.loads(sortie.stdout)


@unittest.skipUnless(NODE, "Node n'est pas installé")
class LOngletModesTests(unittest.TestCase):
    rendu: dict[str, Any]

    @classmethod
    def setUpClass(cls) -> None:
        cls.rendu = _rendre([_cas(choisi=mode) for mode in MODES])

    def _sortie(self, mode: str) -> str:
        return self.rendu["sorties"][MODES.index(mode)]["html"]

    def test_la_page_connait_les_memes_modes_que_le_moteur(self) -> None:
        c = self.rendu["constantes"]
        self.assertEqual(list(c["MODES"]), list(MODES))
        self.assertEqual(list(c["MODES_PRODUIT"]), list(const.APPLICATION_INTERVENTIONS))
        for mode in MODES:
            self.assertGreaterEqual(len(c["REGLES_MODES"].get(mode, [])), 2, mode)
            self.assertTrue(c["ICONES_MODES"].get(mode), mode)
        for mode, liens in c["LIENS_MODES"].items():
            self.assertIn(mode, MODES)
            for onglet, _titre in liens:
                self.assertIn(onglet, self.rendu["groupes"], f"{mode} renvoie vers un onglet absent : {onglet}")

    def test_la_rangee_montre_les_neuf_modes_et_celui_qu_on_regarde(self) -> None:
        for mode in MODES:
            nav = _bloc(self._sortie(mode), "modes-choix")
            puces = [b for b in _balises(nav) if b["tag"] == "button"]
            self.assertEqual([b["attrs"]["data-mode-reglage"] for b in puces], list(MODES))
            self.assertEqual([b["attrs"]["data-mode-reglage"] for b in puces if b["attrs"]["aria-pressed"] == "true"], [mode])
            self.assertEqual([b["attrs"]["data-mode-reglage"] for b in puces if "en ce moment" in b["texte"]], ["Normal"])

    def test_chaque_reglage_de_l_onglet_s_affiche_sous_son_mode(self) -> None:
        # Une section sans `mode` ne s'afficherait jamais : chaque réglage doit être rangé sous un mode.
        attendues = {r["cle"] for r in reglages.exporter()["reglages"] if r["groupe"] == "modes"}
        vues: dict[str, str] = {}
        for mode in MODES:
            for b in _balises(_bloc(self._sortie(mode), "mode-detail")):
                if "repere-ligne" in b["classes"]:
                    vues[b["attrs"]["data-cle"]] = mode
        self.assertEqual(set(vues), attendues)
        for mode, cle in phases._DUREES_REGLABLES.items():
            if mode in const.APPLICATION_INTERVENTIONS:
                self.assertEqual(vues.get(cle), mode)
        self.assertEqual(vues["mode_scarification_temperature_min"], "Scarification")

    def test_chaque_mode_montre_ses_regles(self) -> None:
        regles = self.rendu["constantes"]["REGLES_MODES"]
        for mode in MODES:
            detail = _bloc(self._sortie(mode), "mode-detail")
            lignes = [b["texte"].strip() for b in _balises(detail) if b["tag"] == "li"]
            self.assertEqual(lignes, [html.unescape(r) for r in regles[mode]], mode)

    def test_la_carte_d_action_propose_le_bon_geste(self) -> None:
        for mode in MODES:
            action = [b for b in _balises(_bloc(self._sortie(mode), "mode-action")) if b["tag"] == "button"]
            gestes = [(b["attrs"].get("data-dialogue"), b["attrs"].get("data-mode"), b["attrs"].get("data-produit")) for b in action]
            with self.subTest(mode=mode):
                self.assertTrue(all("disabled" not in b["attrs"] for b in action))
                if mode == "Normal":
                    self.assertEqual(gestes, [])
                elif mode in const.APPLICATION_INTERVENTIONS:
                    premier = next(p["id"] for p in PRODUITS if p["type"].strip().lower() == mode.lower())
                    self.assertEqual(gestes, [("produit", None, premier), ("mode", mode, None)])
                else:
                    self.assertEqual(gestes, [("mode", mode, None)])

    def test_les_produits_du_mode_seuls_sont_listes(self) -> None:
        for mode in MODES:
            catalogue = re.search(r'<ul class="catalogue catalogue-mode">(.*?)</ul>', self._sortie(mode), re.S)
            noms = re.findall(r"<b>(.*?)</b>", catalogue.group(1)) if catalogue else []
            attendus = [p["nom"] for p in PRODUITS if p["type"].strip().lower() == mode.lower()]
            if mode in const.APPLICATION_INTERVENTIONS:
                self.assertEqual([html.unescape(n) for n in noms], attendus, mode)
                fiches = re.findall(r'<dl class="parametres-produit">(.*?)</dl>', catalogue.group(1), re.S)
                self.assertEqual(len(fiches), len(attendus))
                for fiche in fiches:
                    self.assertEqual(
                        re.findall(r"<dt>(.*?)</dt>", fiche),
                        ["Application", "Arrosage", "Attente", "Température", "Tonte", "Période", "Fréquence", "Phases"],
                    )
            else:
                self.assertIsNone(catalogue, mode)
                self.assertNotIn('data-dialogue="fiche_produit"', self._sortie(mode))

    def test_remettre_comme_conseille_n_apparait_que_s_il_y_a_des_reglages(self) -> None:
        for mode in MODES:
            boutons = [b for b in _balises(self._sortie(mode)) if b["attrs"].get("data-action") == "mode-revenir"]
            if mode in const.APPLICATION_INTERVENTIONS:
                self.assertEqual(len(boutons), 1, mode)
                self.assertIn(f"Remettre {mode}", boutons[0]["texte"])
                self.assertIn("disabled", boutons[0]["attrs"], "tout est déjà sur les valeurs conseillées")
            else:
                self.assertEqual(boutons, [], mode)


@unittest.skipUnless(NODE, "Node n'est pas installé")
class LesSituationsDeLOngletModesTests(unittest.TestCase):
    def test_sans_choix_l_onglet_montre_le_mode_du_moment(self) -> None:
        rendu = _rendre([
            _cas(actuel="Sursemis", semis={"age": 3}),
            _cas(actuel="Sursemis", choisi="Nimporte"),
            _cas(actuel="Inconnu"),
            _cas(actuel=None),
        ])
        self.assertEqual([s["visible"] for s in rendu["sorties"]], ["Sursemis", "Sursemis", "Normal", "Normal"])
        sortie = rendu["sorties"][0]["html"]
        action = _bloc(sortie, "mode-action")
        boutons = [b for b in _balises(action) if b["tag"] == "button"]
        self.assertEqual([b["attrs"].get("data-dialogue") for b in boutons], ["normal"])
        self.assertNotIn("disabled", boutons[0]["attrs"])
        self.assertIn("Jour 3 depuis le semis", _texte(action))
        self.assertIn("C'est le mode du moment", _texte(action))
        for s in rendu["sorties"][2:]:
            self.assertNotIn("en ce moment", _texte(_bloc(s["html"], "modes-choix")))

    def test_un_utilisateur_simple_ne_peut_rien_changer(self) -> None:
        cle = phases._DUREES_REGLABLES["Traitement"]
        defaut = next(r["defaut"] for r in reglages.exporter()["reglages"] if r["cle"] == cle)
        rendu = _rendre([
            _cas(admin=False, choisi=mode, valeurs={cle: defaut + 1}) for mode in ("Semis", "Traitement")
        ] + [_cas(admin=False, actuel="Semis")])
        for s in rendu["sorties"]:
            boutons = [b for b in _balises(s["html"]) if b["tag"] == "button" and (
                b["attrs"].get("data-dialogue") in ("mode", "produit", "normal") or b["attrs"].get("data-action") == "mode-revenir")]
            self.assertTrue(boutons)
            self.assertTrue(all("disabled" in b["attrs"] for b in boutons), s["visible"])
            self.assertIn("Seul un administrateur", _texte(_bloc(s["html"], "mode-action")))
        self.assertNotIn('data-dialogue="fiche_produit"', rendu["sorties"][1]["html"])

    def test_remettre_s_allume_quand_un_reglage_a_bouge(self) -> None:
        cle = phases._DUREES_REGLABLES["Traitement"]
        defaut = next(r["defaut"] for r in reglages.exporter()["reglages"] if r["cle"] == cle)
        rendu = _rendre([_cas(choisi="Traitement", valeurs={cle: defaut + 1})])
        bouton = next(b for b in _balises(rendu["sorties"][0]["html"]) if b["attrs"].get("data-action") == "mode-revenir")
        self.assertNotIn("disabled", bouton["attrs"])

    def test_un_mode_que_l_entite_ne_propose_pas_n_a_pas_de_bouton(self) -> None:
        options = [m for m in MODES if m != "Hivernage"]
        rendu = _rendre([_cas(choisi="Hivernage", options=options), _cas(choisi="Traitement", produits=[])])
        action = _bloc(rendu["sorties"][0]["html"], "mode-action")
        self.assertNotIn("data-dialogue", action)
        self.assertIn("pas proposé", _texte(action))
        # Sans fiche de ce type, « J'ai mis un produit » ouvre la fenêtre sans produit choisi.
        boutons = [b for b in _balises(_bloc(rendu["sorties"][1]["html"], "mode-action")) if b["tag"] == "button"]
        self.assertEqual([(b["attrs"].get("data-dialogue"), b["attrs"].get("data-produit")) for b in boutons],
                         [("produit", None), ("mode", None)])

    def test_revenir_au_mode_normal_previent_qu_on_efface_le_suivi(self) -> None:
        rendu = _rendre([_cas(actuel="Fertilisation", choisi="Normal"), _cas(actuel="Normal", choisi="Normal")])
        self.assertIn("efface le suivi en cours (Fertilisation)", _texte(_bloc(rendu["sorties"][0]["html"], "mode-action")))
        self.assertNotIn("efface", _texte(_bloc(rendu["sorties"][1]["html"], "mode-action")))

    def test_revenir_au_mode_normal_conserve_le_verrou_de_securite(self) -> None:
        rendu = _rendre([_cas(actuel="Sursemis", choisi="Normal", verrou=True)])
        texte = _texte(_bloc(rendu["sorties"][0]["html"], "mode-action"))
        self.assertIn("efface le suivi en cours (Sursemis)", texte)
        self.assertIn("verrou de sécurité restera posé", texte)
        self.assertIn("se lève séparément", texte)


if __name__ == "__main__":
    unittest.main()
