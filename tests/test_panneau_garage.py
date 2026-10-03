"""La carte « Garage de la tondeuse » : commandes à la main, état et dernière commande du pilote.

Les commandes (ouvrir, fermer, arrêter) servent à tester et à dépanner le volet. Ouvrir et fermer
demandent une confirmation (« passage dégagé ») ; l'arrêt agit tout de suite. L'état « fermé » est
l'état normal au repos : il n'est signalé que si la tondeuse est dehors.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import types
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

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


def _install_homeassistant_dt_stub() -> None:
    if "homeassistant.util.dt" in sys.modules:
        return
    homeassistant_module = sys.modules.setdefault("homeassistant", types.ModuleType("homeassistant"))
    util_module = sys.modules.setdefault("homeassistant.util", types.ModuleType("homeassistant.util"))
    homeassistant_module.util = util_module  # type: ignore[attr-defined]
    dt_module = types.ModuleType("homeassistant.util.dt")
    dt_module.now = lambda: datetime(2026, 4, 4, 14, 15, tzinfo=ZoneInfo("Europe/Paris"))  # type: ignore[attr-defined]
    sys.modules["homeassistant.util.dt"] = dt_module
    util_module.dt = dt_module  # type: ignore[attr-defined]


_ensure_package("custom_components", PACKAGE_DIR.parent)
_ensure_package("custom_components.gazon_intelligent", PACKAGE_DIR)
_install_homeassistant_dt_stub()

reglages = __import__("custom_components.gazon_intelligent.reglages", fromlist=["_"])

PANNEAU = PACKAGE_DIR / "frontend" / "gazon-intelligent-panel.js"
NODE = shutil.which("node")
NBSP = " "

SCRIPT = r"""
const fs = require("fs");
const vm = require("vm");
const { chemin, cas } = JSON.parse(fs.readFileSync(0, "utf8"));
const ctx = {
  HTMLElement: class {},
  customElements: { get: () => undefined, define: (nom, classe) => { ctx.Classe = classe; } },
  console, structuredClone, setTimeout: () => 0,
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(chemin, "utf8"), ctx);

function fabriquer(c) {
  const p = Object.create(ctx.Classe.prototype);
  const etat = c.attributs || {};
  p._hass = {
    config: { time_zone: "Europe/Paris" },
    user: { is_admin: c.admin !== false },
    states: {
      "cover.garage": { state: c.volet, attributes: { friendly_name: "Garage - Tondeuse", supported_features: 15, current_position: c.position ?? 0 } },
      "sensor.etat": { state: "a_surveiller", attributes: etat },
    },
  };
  p._donnees = { entites: { tonte_etat: "sensor.etat" }, garage_tondeuse: { choisie: "cover.garage", volets: [] } };
  p._commandesEnCours = new Set();
  p._garageConfirmation = c.confirmation;
  p._fenetre = { contains: () => false };
  p.appels = [];
  p._service = async (domaine, service, donnees, message) => { p.appels.push([domaine, service, donnees, message]); return true; };
  p._rendre = () => {};
  p._rendreQuandLibre = () => {};
  return p;
}

function clic(p, selecteurs) {
  const cible = { closest: (sel) => selecteurs[sel] || null };
  p._surClicAccueil({ target: cible });
}

const sorties = cas.map((c) => {
  const p = fabriquer(c);
  if (c.type === "commandes") return { html: p._commandesGarageHtml("cover.garage") };
  if (c.type === "etat") return { html: p._etatGarageTondeuseHtml("cover.garage") };
  if (c.type === "pilote") return { html: p._garagePiloteHtml() };
  if (c.type === "bloc_pilote") return { html: p._pilotageTondeuseEtatHtml() };
  if (c.type === "instant") return { texte: ctx.instantFr(c.iso, "Europe/Paris", new Date(c.maintenant)) };
  if (c.type === "clics") {
    const trace = [];
    clic(p, { "[data-garage-demander]": { dataset: { garageDemander: "fermer" }, disabled: false } });
    trace.push(p._garageConfirmation);
    clic(p, { "[data-garage-annuler]": {} });
    trace.push(p._garageConfirmation === undefined ? "aucune" : p._garageConfirmation);
    clic(p, { "[data-garage-demander]": { dataset: { garageDemander: "ouvrir" }, disabled: false } });
    trace.push(p._garageConfirmation);
    return { trace, appels: p.appels };
  }
  return null;
});

(async () => {
  // La confirmation envoie la commande : on la rejoue séparément (asynchrone).
  for (let i = 0; i < cas.length; i++) {
    const c = cas[i];
    if (c.type !== "commande") continue;
    const p = fabriquer(c);
    await p._commande(c.nom, { dataset: {} });
    sorties[i] = { appels: p.appels, confirmation: p._garageConfirmation === undefined ? "aucune" : p._garageConfirmation };
  }
  process.stdout.write(JSON.stringify(sorties));
  process.exit(0);
})();
"""


def _rendre(cas: list[dict]) -> list[dict]:
    assert NODE
    sortie = subprocess.run(
        [NODE, "-e", SCRIPT],
        input=json.dumps({"chemin": str(PANNEAU), "cas": cas}),
        capture_output=True, text=True, check=True, timeout=60,
    )
    return json.loads(sortie.stdout)


def _bouton(html: str, repere: str) -> str:
    """La balise ouvrante du bouton qui porte `repere`."""
    debut = html.index(repere)
    debut = html.rfind("<button", 0, debut)
    return html[debut:html.index(">", debut) + 1]


@unittest.skipUnless(NODE, "Node n'est pas installé")
class CommandesDuVoletTests(unittest.TestCase):
    def _commandes(self, volet: str, **extra) -> str:
        (sortie,) = _rendre([{"type": "commandes", "volet": volet, **extra}])
        return sortie["html"]

    def test_ferme_on_peut_ouvrir_pas_fermer(self) -> None:
        html = self._commandes("closed")
        self.assertNotIn("disabled", _bouton(html, 'data-garage-demander="ouvrir"'))
        self.assertIn("disabled", _bouton(html, 'data-garage-demander="fermer"'))
        self.assertIn("disabled", _bouton(html, 'data-commande="garage-arreter"'))

    def test_ouvert_on_peut_fermer_pas_ouvrir(self) -> None:
        html = self._commandes("open", position=100)
        self.assertIn("disabled", _bouton(html, 'data-garage-demander="ouvrir"'))
        self.assertNotIn("disabled", _bouton(html, 'data-garage-demander="fermer"'))

    def test_en_mouvement_seul_l_arret_est_possible(self) -> None:
        for volet in ("opening", "closing"):
            with self.subTest(volet=volet):
                html = self._commandes(volet, position=48)
                self.assertIn("disabled", _bouton(html, 'data-garage-demander="ouvrir"'))
                self.assertIn("disabled", _bouton(html, 'data-garage-demander="fermer"'))
                self.assertNotIn("disabled", _bouton(html, 'data-commande="garage-arreter"'))

    def test_un_volet_indisponible_ne_recoit_aucune_commande(self) -> None:
        for volet in ("unavailable", "unknown"):
            with self.subTest(volet=volet):
                html = self._commandes(volet)
                for repere in ('data-garage-demander="ouvrir"', 'data-garage-demander="fermer"', 'data-commande="garage-arreter"'):
                    self.assertIn("disabled", _bouton(html, repere))
                self.assertIn("ne répond pas", html)

    def test_un_lecteur_non_administrateur_ne_peut_rien_commander(self) -> None:
        html = self._commandes("open", admin=False, position=100)
        for repere in ('data-garage-demander="ouvrir"', 'data-garage-demander="fermer"'):
            self.assertIn("disabled", _bouton(html, repere))

    def test_fermer_demande_une_confirmation_avec_le_passage_degage(self) -> None:
        html = self._commandes("open", confirmation="fermer", position=100)
        self.assertIn("Fermer le volet ?", html)
        self.assertIn("sous le volet", html)
        self.assertIn("la tondeuse n&#39;est pas dehors", html)
        self.assertIn('data-commande="garage-fermer"', html)
        self.assertIn("data-garage-annuler", html)
        self.assertNotIn("data-garage-demander", html, "pas de nouvelle demande pendant la confirmation")

    def test_ouvrir_demande_aussi_une_confirmation(self) -> None:
        html = self._commandes("closed", confirmation="ouvrir")
        self.assertIn("Ouvrir le volet ?", html)
        self.assertIn('data-commande="garage-ouvrir"', html)

    def test_en_pilotage_actif_la_page_previent_que_le_pilote_peut_reprendre_la_main(self) -> None:
        html = self._commandes("open", position=100, attributs={"mower_control_mode": "actif"})
        self.assertIn("Pilotage actif", html)
        html = self._commandes("open", position=100, attributs={"mower_control_mode": "observation"})
        self.assertNotIn("Pilotage actif", html)


@unittest.skipUnless(NODE, "Node n'est pas installé")
class EnvoiDesCommandesTests(unittest.TestCase):
    def _envoyer(self, nom: str) -> dict:
        (sortie,) = _rendre([{"type": "commande", "nom": nom, "volet": "open", "confirmation": "fermer"}])
        return sortie

    def test_la_confirmation_envoie_le_bon_service_au_bon_volet(self) -> None:
        for nom, service in (("garage-ouvrir", "open_cover"), ("garage-fermer", "close_cover"), ("garage-arreter", "stop_cover")):
            with self.subTest(commande=nom):
                sortie = self._envoyer(nom)
                self.assertEqual(len(sortie["appels"]), 1)
                domaine, appele, donnees, _ = sortie["appels"][0]
                self.assertEqual((domaine, appele, donnees), ("cover", service, {"entity_id": "cover.garage"}))
                self.assertEqual(sortie["confirmation"], "aucune", "la confirmation retombe après l'envoi")

    def test_les_clics_demander_puis_annuler_ne_commandent_rien(self) -> None:
        (sortie,) = _rendre([{"type": "clics", "volet": "open"}])
        self.assertEqual(sortie["trace"], ["fermer", "aucune", "ouvrir"])
        self.assertEqual(sortie["appels"], [], "demander ou annuler ne doit jamais envoyer de commande")


@unittest.skipUnless(NODE, "Node n'est pas installé")
class EtatDuVoletTests(unittest.TestCase):
    def _etat(self, volet: str, **extra) -> str:
        (sortie,) = _rendre([{"type": "etat", "volet": volet, **extra}])
        return sortie["html"]

    def test_ferme_au_repos_n_est_pas_un_avertissement(self) -> None:
        html = self._etat("closed", attributs={"mower_is_outside": False})
        self.assertIn("statut neutre", html)
        self.assertNotIn("retient", html)

    def test_ferme_alors_que_la_tondeuse_est_dehors_est_signale(self) -> None:
        html = self._etat("closed", attributs={"mower_is_outside": True})
        self.assertIn("statut retient", html)
        self.assertIn("fermé alors que la tondeuse est dehors", html)

    def test_ouvert_reste_en_vert(self) -> None:
        self.assertIn("statut ok", self._etat("open", position=100))


@unittest.skipUnless(NODE, "Node n'est pas installé")
class DerniereCommandeDuPiloteTests(unittest.TestCase):
    ATTRS = {
        "mower_control_mode": "observation",
        "mower_control_last_action": "start_mowing",
        "mower_control_last_action_at": "2026-10-02T16:08:03+02:00",
        "mower_control_pending_action": "close_cover",
    }

    def test_la_carte_du_garage_dit_la_derniere_commande_et_la_prochaine_action(self) -> None:
        (sortie,) = _rendre([{"type": "pilote", "volet": "open", "attributs": self.ATTRS}])
        self.assertIn("Dernière commande du pilote : <b>départ</b>, le 02/10 à 16", sortie["html"])
        self.assertIn("Prochaine action prévue : <b>fermeture du garage</b>", sortie["html"])
        self.assertIn("affichée seulement, pilotage en observation", sortie["html"])

    def test_en_actif_la_prochaine_action_n_est_pas_dite_affichee_seulement(self) -> None:
        (sortie,) = _rendre([{"type": "pilote", "volet": "open", "attributs": {**self.ATTRS, "mower_control_mode": "actif"}}])
        self.assertIn("Prochaine action prévue", sortie["html"])
        self.assertNotIn("affichée seulement", sortie["html"])

    def test_une_prochaine_action_hors_volet_n_est_pas_affichee_dans_la_carte_du_garage(self) -> None:
        (sortie,) = _rendre([{"type": "pilote", "volet": "closed", "attributs": {**self.ATTRS, "mower_control_pending_action": "start_mowing"}}])
        self.assertNotIn("Prochaine action", sortie["html"])

    def test_rien_a_dire_quand_le_pilote_n_a_encore_rien_fait(self) -> None:
        (sortie,) = _rendre([{"type": "pilote", "volet": "closed", "attributs": {"mower_control_mode": "observation"}}])
        self.assertEqual(sortie["html"], "")

    def test_l_onglet_tonte_dit_aussi_la_derniere_commande(self) -> None:
        (sortie,) = _rendre([{"type": "bloc_pilote", "volet": "closed", "attributs": self.ATTRS}])
        self.assertIn("Dernière commande envoyée : <b>départ</b>", sortie["html"])


@unittest.skipUnless(NODE, "Node n'est pas installé")
class InstantEnFrancaisTests(unittest.TestCase):
    def _instant(self, iso: str, maintenant: str) -> str:
        (sortie,) = _rendre([{"type": "instant", "volet": "closed", "iso": iso, "maintenant": maintenant}])
        return sortie["texte"]

    def test_le_meme_jour_dit_aujourd_hui(self) -> None:
        self.assertEqual(
            self._instant("2026-10-03T18:02:04Z", "2026-10-03T18:30:00Z"),
            f"aujourd'hui à 20{NBSP}h{NBSP}02",
        )

    def test_un_autre_jour_dit_la_date(self) -> None:
        self.assertEqual(
            self._instant("2026-10-02T14:08:03Z", "2026-10-03T18:30:00Z"),
            f"le 02/10 à 16{NBSP}h{NBSP}08",
        )

    def test_le_jour_est_celui_du_fuseau_de_home_assistant(self) -> None:
        # 22:30 UTC le 02/10 = 00:30 le 03/10 à Paris : « aujourd'hui » pour un 03/10 local.
        self.assertEqual(
            self._instant("2026-10-02T22:30:00Z", "2026-10-03T08:00:00Z"),
            f"aujourd'hui à 0{NBSP}h{NBSP}30",
        )

    def test_un_instant_illisible_donne_une_chaine_vide(self) -> None:
        self.assertEqual(self._instant("pas une date", "2026-10-03T18:30:00Z"), "")
        self.assertEqual(self._instant("", "2026-10-03T18:30:00Z"), "")


class LibelleDuReglageDOuvertureTests(unittest.TestCase):
    def test_le_libelle_dit_que_le_volet_s_ouvre_des_que_la_tondeuse_est_dehors(self) -> None:
        r = reglages.reglage("tondeuse_garage_ouvrir_pour_retour")
        self.assertIn("dès que la tondeuse est dehors", r.titre)
        self.assertIn("départ lancé depuis l'appli", r.aide)


if __name__ == "__main__":
    unittest.main()
