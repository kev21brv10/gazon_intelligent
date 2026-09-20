"""Recherche des réglages, tous onglets confondus (0.96.4).

Demande de Kévin (18/09/2026) : « dans les réglages, range tout correctement, j'ai du mal à
m'y retrouver et à savoir à quoi ça correspond, même si c'est déjà bien fait ». Le registre
range déjà chaque réglage dans un onglet et une section précise (`DISPOSITION`), mais avec 7
onglets et ~55 réglages, il fallait un moyen de retrouver directement l'un d'eux, où qu'il
vive. Ce test charge la page dans Node et exécute `_indexReglages`/`_rechercheResultatsHtml`
avec le VRAI registre de `reglages.py` (pas un registre inventé) : sans Node, il est sauté.
"""

from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import sys
import types
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "custom_components" / "gazon_intelligent"
PANNEAU = PACKAGE_DIR / "frontend" / "gazon-intelligent-panel.js"
NODE = shutil.which("node")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ensure_package(name: str, path: Path) -> None:
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module


# `reglages.py` est un module PUR (aucune dépendance à Home Assistant) : on l'importe par son
# chemin, sans passer par le vrai `__init__.py` du paquet (qui exige `voluptuous`/HA).
_ensure_package("custom_components", PACKAGE_DIR.parent)
_ensure_package("custom_components.gazon_intelligent", PACKAGE_DIR)
reglages = importlib.import_module("custom_components.gazon_intelligent.reglages")
REGISTRE = reglages.exporter()

SCRIPT = r"""
const fs = require("fs");
const vm = require("vm");
const { chemin, registre, requetes } = JSON.parse(fs.readFileSync(0, "utf8"));
const ctx = {
  HTMLElement: class {},
  customElements: { get: () => undefined, define: (nom, classe) => { ctx.Classe = classe; } },
  console,
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(chemin, "utf8"), ctx);
const sansBalises = (t) => String(t).replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
const p = Object.create(ctx.Classe.prototype);
p._donnees = { registre };

const index = p._indexReglages().map((it) => ({ cle: it.cle, ongletCle: it.ongletCle, section: it.section }));

const REGEX_RESULTAT = /data-cle="([^"]*)" data-cible-onglet="([^"]*)">\s*<span class="resultat-titre">([^<]*)<\/span>\s*<span class="resultat-chemin">([\s\S]*?)<\/span>/g;
const resultats = requetes.map((q) => {
  p._rechercheReglages = q;
  const html = p._rechercheResultatsHtml();
  const boutons = [...html.matchAll(REGEX_RESULTAT)].map((m) => ({
    cle: m[1], ongletCle: m[2], titre: m[3], chemin: sansBalises(m[4]),
  }));
  return { html, boutons, texte: sansBalises(html) };
});

// `_allerAuReglage` touche le DOM réel (shadowRoot, scrollIntoView) : hors de portée de ce
// bac à sable. On vérifie ici seulement la TRANSITION D'ÉTAT qu'il doit produire — l'onglet
// visé, la recherche vidée, le mois choisi remis à zéro — en stubant le reste sans y toucher.
let rendreAppelee = 0;
p._rendre = () => { rendreAppelee += 1; };
p.shadowRoot = { querySelector: () => null };
p._onglet = "arrosage";
p._rechercheReglages = "vent";
p._moisChoisi = { graines_duree: 3 };
p._allerAuReglage("tonte_vent_bloque", "tonte");
const apresAller = {
  onglet: p._onglet, recherche: p._rechercheReglages, rendreAppelee,
  moisChoisiVide: Object.keys(p._moisChoisi).length === 0,
};

process.stdout.write(JSON.stringify({ index, resultats, apresAller }));
"""


def _rendre(requetes: list[str]) -> dict[str, Any]:
    assert NODE
    sortie = subprocess.run(
        [NODE, "-e", SCRIPT],
        input=json.dumps({"chemin": str(PANNEAU), "registre": REGISTRE, "requetes": requetes}),
        capture_output=True, text=True, check=True, timeout=60,
    )
    return json.loads(sortie.stdout)


@unittest.skipUnless(NODE, "Node n'est pas installé")
class RechercheReglagesTests(unittest.TestCase):
    def test_chaque_reglage_reel_atteint_l_index_sans_perte(self) -> None:
        """⚠️ RECOPIE CLÉ PAR CLÉ, le piège documenté de ce projet : un réglage ajouté à
        `reglages.py` sans être relié à un groupe existant se perdrait en silence."""
        rendu = _rendre([""])
        cles_index = {it["cle"] for it in rendu["index"]}
        cles_registre = {r["cle"] for r in REGISTRE["reglages"]} | {c["cle"] for c in REGISTRE["choix"]}
        manquants = cles_registre - cles_index
        self.assertEqual(manquants, set(), "des réglages réels n'atteignent jamais la recherche")

    def test_les_reglages_places_par_DISPOSITION_portent_leur_section(self) -> None:
        rendu = _rendre([""])
        par_cle = {it["cle"]: it for it in rendu["index"]}
        # Choisi au hasard dans DISPOSITION : doit porter une section, pas juste un onglet.
        self.assertEqual(par_cle["tonte_vent_bloque"]["ongletCle"], "tonte")
        self.assertTrue(par_cle["tonte_vent_bloque"]["section"], "la section de DISPOSITION ne remonte pas")

    def test_type_sol_reste_cherchable_sans_section_dediee(self) -> None:
        """`type_sol` (Choix) n'est pas placé par `DISPOSITION` (propre à `_installationHtml`) :
        il doit rester trouvable, juste sans le fil « onglet › section »."""
        rendu = _rendre([""])
        par_cle = {it["cle"]: it for it in rendu["index"]}
        self.assertEqual(par_cle["type_sol"]["ongletCle"], "installation")
        self.assertEqual(par_cle["type_sol"]["section"], "")

    def test_une_recherche_par_cle_trouve_le_bon_reglage_et_son_chemin(self) -> None:
        [rendu] = _rendre(["tonte_vent_bloque"])["resultats"]
        self.assertEqual([b["cle"] for b in rendu["boutons"]], ["tonte_vent_bloque"])
        self.assertEqual(rendu["boutons"][0]["ongletCle"], "tonte")
        self.assertIn("Tonte", rendu["boutons"][0]["chemin"])
        self.assertIn("›", rendu["boutons"][0]["chemin"], "le chemin ne dit plus dans quelle section c'est")

    def test_le_chemin_de_type_sol_n_a_pas_de_chevron_fantome(self) -> None:
        [rendu] = _rendre(["type_sol"])["resultats"]
        self.assertEqual([b["cle"] for b in rendu["boutons"]], ["type_sol"])
        self.assertNotIn("›", rendu["boutons"][0]["chemin"])

    def test_la_recherche_ignore_accents_et_majuscules(self) -> None:
        minuscule, majuscule = _rendre(["tonte_vent_bloque", "TONTE_VENT_BLOQUE"])["resultats"]
        self.assertEqual(minuscule["boutons"], majuscule["boutons"])

    def test_aucune_correspondance_dit_pourquoi_la_liste_est_vide(self) -> None:
        [rendu] = _rendre(["zzz_reglage_qui_n_existe_pas"])["resultats"]
        self.assertEqual(rendu["boutons"], [])
        self.assertIn("Aucun réglage ne correspond", rendu["texte"])

    def test_une_recherche_vide_n_affiche_rien(self) -> None:
        [rendu] = _rendre([""])["resultats"]
        self.assertEqual(rendu["html"], "")

    def test_trop_de_resultats_se_limite_et_le_dit(self) -> None:
        # Une lettre courante dépasse largement la limite d'affichage (8).
        [rendu] = _rendre(["e"])["resultats"]
        self.assertEqual(len(rendu["boutons"]), 8)
        self.assertRegex(rendu["texte"], r"Et \d+ autres? ")

    def test_aller_au_reglage_change_bien_d_onglet_et_vide_la_recherche(self) -> None:
        """⚠️ CALCULER N'EST PAS APPLIQUER : un clic qui ne fait que RE-CALCULER les résultats
        sans jamais changer d'onglet ni relancer le rendu laisserait l'utilisateur sur place."""
        apres = _rendre([""])["apresAller"]
        self.assertEqual(apres["onglet"], "tonte", "le clic n'a pas changé d'onglet")
        self.assertEqual(apres["recherche"], "", "la recherche n'est pas vidée après un clic")
        self.assertEqual(apres["rendreAppelee"], 1, "le rendu n'a pas été relancé")
        self.assertTrue(apres["moisChoisiVide"], "le mois choisi d'un autre onglet n'est pas remis à zéro")

    def test_le_clic_est_cable_jusqu_a_allerAuReglage(self) -> None:
        """Le pendant JS de la vérification « câblage » déjà faite côté Python
        (`AmortissementDuRisqueTests`/`AjustementMeteoGrainesHysteresisTests`) : une fonction
        correcte mais jamais appelée depuis le clic n'existerait pas pour l'utilisateur."""
        source = PANNEAU.read_text(encoding="utf-8")
        self.assertIn('data-action="aller-reglage"', source, "le bouton de résultat ne porte plus l'action")
        self.assertIn('case "aller-reglage":', source, "le clic n'a plus de branche pour cette action")
        self.assertIn(
            "this._allerAuReglage(cle, bouton.dataset.cibleOnglet)", source,
            "la branche du clic n'appelle plus _allerAuReglage",
        )


if __name__ == "__main__":
    unittest.main()
