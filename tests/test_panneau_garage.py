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

// Le volet que PORTE le bouton cliqué (`data-volet`) : par défaut le volet enregistré.
function boutonDe(c) {
  return { dataset: c.bouton_volet === null ? {} : { volet: c.bouton_volet || "cover.garage" } };
}

function fabriquer(c) {
  const p = Object.create(ctx.Classe.prototype);
  const etat = c.attributs || {};
  p._hass = {
    config: { time_zone: "Europe/Paris" },
    user: { is_admin: c.admin !== false },
    states: {
      "cover.garage": { state: c.volet, attributes: { friendly_name: "Garage - Tondeuse", ...(c.fonctions === null ? {} : { supported_features: c.fonctions ?? 15 }), current_position: c.position ?? 0 } },
      "sensor.etat": { state: "a_surveiller", attributes: etat },
    },
  };
  p._donnees = { entites: { tonte_etat: "sensor.etat" }, garage_tondeuse: { choisie: c.enregistre === undefined ? "cover.garage" : c.enregistre, volets: [] } };
  if (c.brouillon !== undefined) p._brouillonGarageTondeuse = c.brouillon;
  p._commandesEnCours = new Set();
  p._garageConfirmation = c.confirmation;
  p._fenetre = { contains: () => false };
  p.appels = [];
  p.toasts = [];
  p._afficherToast = (texte, erreur) => p.toasts.push([texte, Boolean(erreur)]);
  p._service = async (domaine, service, donnees, message) => { p.appels.push([domaine, service, donnees, message]); return true; };
  p._rendre = () => {};
  p._rendreQuandLibre = () => {};
  return p;
}

// La carte COMPLÈTE : registre réel, valeurs par défaut, volet enregistré (et brouillon éventuel).
function carte(p, c) {
  p._donnees.registre = c.registre;
  p._donnees.valeurs = c.valeurs;
  p._donnees.garage_tondeuse = {
    choisie: c.enregistre === undefined ? "cover.garage" : c.enregistre,
    volets: [{ entity_id: "cover.garage", nom: "Garage - Tondeuse" }, { entity_id: "cover.autre", nom: "Autre volet" }],
  };
  p._brouillon = {};
  p._brouillonChoix = {};
  return p._garageTondeuseHtml();
}

function clic(p, selecteurs) {
  const cible = { closest: (sel) => selecteurs[sel] || null };
  p._surClicAccueil({ target: cible });
}

const sorties = cas.map((c) => {
  const p = fabriquer(c);
  if (c.type === "commandes") return { html: p._commandesGarageHtml("cover.garage") };
  if (c.type === "carte") return { html: carte(p, c) };
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
    await p._commande(c.nom, boutonDe(c));
    sorties[i] = { appels: p.appels, toasts: p.toasts, confirmation: p._garageConfirmation === undefined ? "aucune" : p._garageConfirmation };
  }
  for (let i = 0; i < cas.length; i++) {
    const c = cas[i];
    if (c.type !== "course") continue;
    // Deux clics : « demander », puis (l'état de Home Assistant ayant changé) « confirmer ».
    const p = fabriquer(c);
    clic(p, { "[data-garage-demander]": { dataset: { garageDemander: c.verbe }, disabled: false } });
    const demande = p._garageConfirmation;
    Object.assign(p._hass.states["sensor.etat"].attributes, c.changement_attributs || {});
    if (c.changement_volet) p._hass.states["cover.garage"].state = c.changement_volet;
    const html = p._commandesGarageHtml("cover.garage");
    await p._commande(c.nom, boutonDe(c));
    sorties[i] = { demande, html, appels: p.appels, toasts: p.toasts, confirmation: p._garageConfirmation === undefined ? "aucune" : p._garageConfirmation };
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


def _carte(volet: str = "open", attributs: dict | None = None, **extra) -> str:
    (sortie,) = _rendre([{
        "type": "carte", "volet": volet, "position": 100, "attributs": attributs or {},
        "registre": reglages.exporter(), "valeurs": reglages.valeurs_par_defaut(), **extra,
    }])
    return sortie["html"]


def _bouton(html: str, repere: str) -> str:
    """La balise ouvrante du bouton qui porte `repere`."""
    debut = html.index(repere)
    debut = html.rfind("<button", 0, debut)
    return html[debut:html.index(">", debut) + 1]


DOCKEE = {"mower_is_docked": True, "mower_is_outside": False}
DEHORS = {"mower_is_docked": False, "mower_is_outside": True}


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
        html = self._commandes("open", position=100, attributs=DOCKEE)
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
        html = self._commandes("open", confirmation="fermer", position=100, attributs=DOCKEE)
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
        html = self._commandes("open", position=100, attributs={**DOCKEE, "mower_control_mode": "actif"})
        self.assertIn("Pilotage actif", html)
        html = self._commandes("open", position=100, attributs={**DOCKEE, "mower_control_mode": "observation"})
        self.assertNotIn("Pilotage actif", html)


@unittest.skipUnless(NODE, "Node n'est pas installé")
class EnvoiDesCommandesTests(unittest.TestCase):
    def _envoyer(self, nom: str, volet: str = "open", **extra) -> dict:
        (sortie,) = _rendre([{"type": "commande", "nom": nom, "volet": volet, "confirmation": "fermer",
                              "attributs": DOCKEE, **extra}])
        return sortie

    def test_la_confirmation_envoie_le_bon_service_au_bon_volet(self) -> None:
        for nom, service, volet in (
            ("garage-ouvrir", "open_cover", "closed"),
            ("garage-fermer", "close_cover", "open"),
            ("garage-arreter", "stop_cover", "opening"),
        ):
            with self.subTest(commande=nom):
                sortie = self._envoyer(nom, volet)
                self.assertEqual(len(sortie["appels"]), 1)
                domaine, appele, donnees, _ = sortie["appels"][0]
                self.assertEqual((domaine, appele, donnees), ("cover", service, {"entity_id": "cover.garage"}))
                self.assertEqual(sortie["confirmation"], "aucune", "la confirmation retombe après l'envoi")

    def test_les_clics_demander_puis_annuler_ne_commandent_rien(self) -> None:
        (sortie,) = _rendre([{"type": "clics", "volet": "open"}])
        self.assertEqual(sortie["trace"], ["fermer", "aucune", "ouvrir"])
        self.assertEqual(sortie["appels"], [], "demander ou annuler ne doit jamais envoyer de commande")


@unittest.skipUnless(NODE, "Node n'est pas installé")
class GardeDeLaFermetureTests(unittest.TestCase):
    """Fermer le volet sur une tondeuse dehors l'enfermerait dehors.

    ⚠️ Jugé à l'affichage du bouton ET juste avant l'envoi : la confirmation demandée par un
    premier clic survit aux mises à jour de Home Assistant, et la tondeuse peut sortir entre les
    deux clics (signalé en revue de la PR #81). Le texte « vérifier que la tondeuse n'est pas
    dehors » n'est pas une garde.
    """

    def _commandes(self, volet: str, attributs: dict, **extra) -> str:
        (sortie,) = _rendre([{"type": "commandes", "volet": volet, "attributs": attributs, **extra}])
        return sortie["html"]

    def _course(self, **cas) -> dict:
        (sortie,) = _rendre([{"type": "course", "verbe": "fermer", "nom": "garage-fermer", **cas}])
        return sortie

    # ---- au rendu ----
    def test_fermer_est_grise_quand_la_tondeuse_est_dehors(self) -> None:
        html = self._commandes("open", DEHORS, position=100)
        self.assertIn("disabled", _bouton(html, 'data-garage-demander="fermer"'))
        self.assertIn("La tondeuse est dehors : le volet reste ouvert pour son retour.", html)

    def test_fermer_est_grise_quand_la_position_de_la_tondeuse_n_est_pas_confirmee(self) -> None:
        html = self._commandes("open", {"mower_is_docked": False}, position=100)
        self.assertIn("disabled", _bouton(html, 'data-garage-demander="fermer"'))
        self.assertIn("n&#39;est pas confirmée à sa base", html)

    def test_fermer_est_possible_quand_la_tondeuse_est_rentree(self) -> None:
        html = self._commandes("open", DOCKEE, position=100)
        self.assertNotIn("disabled", _bouton(html, 'data-garage-demander="fermer"'))

    def test_sans_information_sur_la_tondeuse_fermer_est_refuse(self) -> None:
        """STRICT (choix du propriétaire) : aucune position publiée — redémarrage de Home Assistant,
        intégration muette — donc aucune preuve que la tondeuse est rentrée : pas de fermeture à
        l'aveugle. Le volet reste commandable depuis son entité dans Home Assistant."""
        for attributs in ({}, {"mower_is_outside": False}, {"mower_presence_state": "inconnue"}):
            with self.subTest(attributs=attributs):
                html = self._commandes("open", attributs, position=100)
                self.assertIn("disabled", _bouton(html, 'data-garage-demander="fermer"'))
                self.assertIn("n&#39;est pas confirmée à sa base", html)

    def test_sans_information_sur_la_tondeuse_l_ordre_n_est_jamais_envoye(self) -> None:
        for attributs in ({}, {"mower_is_outside": False}):
            with self.subTest(attributs=attributs):
                sortie = self._course(volet="open", position=100, attributs=attributs)
                self.assertEqual(sortie["appels"], [])
                self.assertIn("Commande annulée", sortie["toasts"][0][0])

    def test_ouvrir_reste_possible_sans_information_sur_la_tondeuse(self) -> None:
        html = self._commandes("closed", {})
        self.assertNotIn("disabled", _bouton(html, 'data-garage-demander="ouvrir"'))

    def test_ouvrir_reste_possible_tondeuse_dehors(self) -> None:
        """Ouvrir ne piège personne : c'est même ce qu'il faut pour son retour."""
        html = self._commandes("closed", DEHORS)
        self.assertNotIn("disabled", _bouton(html, 'data-garage-demander="ouvrir"'))

    # ---- entre les deux clics ----
    def test_la_tondeuse_sort_entre_la_demande_et_la_confirmation_pas_de_bouton_final(self) -> None:
        sortie = self._course(volet="open", position=100, attributs=DOCKEE, changement_attributs=DEHORS)
        self.assertEqual(sortie["demande"], "fermer", "la demande a bien été prise quand la tondeuse était rentrée")
        self.assertNotIn('data-commande="garage-fermer"', sortie["html"])
        self.assertIn("La confirmation est annulée", sortie["html"])
        self.assertIn("La tondeuse est dehors", sortie["html"])

    def test_la_tondeuse_sort_entre_les_deux_clics_l_ordre_n_est_jamais_envoye(self) -> None:
        sortie = self._course(volet="open", position=100, attributs=DOCKEE, changement_attributs=DEHORS)
        self.assertEqual(sortie["appels"], [], "aucune fermeture ne doit partir sur une tondeuse dehors")
        self.assertEqual(len(sortie["toasts"]), 1)
        self.assertTrue(sortie["toasts"][0][1], "l'annulation est signalée comme une erreur")
        self.assertIn("Commande annulée : La tondeuse est dehors", sortie["toasts"][0][0])
        self.assertEqual(sortie["confirmation"], "aucune")

    def test_le_volet_s_est_deja_ferme_entre_les_deux_clics(self) -> None:
        sortie = self._course(volet="open", position=100, attributs=DOCKEE, changement_volet="closed")
        self.assertEqual(sortie["appels"], [])
        self.assertIn("Le volet est déjà fermé", sortie["toasts"][0][0])

    def test_le_volet_est_devenu_indisponible_entre_les_deux_clics(self) -> None:
        sortie = self._course(volet="open", position=100, attributs=DOCKEE, changement_volet="unavailable")
        self.assertEqual(sortie["appels"], [])
        self.assertIn("Le volet ne répond pas", sortie["toasts"][0][0])

    def test_rien_ne_change_entre_les_deux_clics_la_fermeture_part(self) -> None:
        sortie = self._course(volet="open", position=100, attributs=DOCKEE)
        self.assertEqual(sortie["appels"][0][:3], ["cover", "close_cover", {"entity_id": "cover.garage"}])
        self.assertEqual(sortie["toasts"], [])

    def test_l_ouverture_deja_faite_entre_les_deux_clics_n_est_pas_renvoyee(self) -> None:
        sortie = self._course(verbe="ouvrir", nom="garage-ouvrir", volet="closed", attributs=DEHORS, changement_volet="open")
        self.assertEqual(sortie["appels"], [])
        self.assertIn("Le volet est déjà ouvert", sortie["toasts"][0][0])

    def test_ouvrir_part_meme_tondeuse_dehors(self) -> None:
        sortie = self._course(verbe="ouvrir", nom="garage-ouvrir", volet="closed", attributs=DEHORS)
        self.assertEqual(sortie["appels"][0][1], "open_cover")

    def test_l_arret_n_est_jamais_refuse_meme_tondeuse_dehors(self) -> None:
        (sortie,) = _rendre([{"type": "commande", "nom": "garage-arreter", "volet": "closing", "attributs": DEHORS}])
        self.assertEqual(sortie["appels"][0][1], "stop_cover")
        self.assertEqual(sortie["toasts"], [])


@unittest.skipUnless(NODE, "Node n'est pas installé")
class VoletEnregistreSeulementTests(unittest.TestCase):
    """⚠️ Les commandes visent le volet ENREGISTRÉ, jamais celui d'un choix pas encore enregistré.

    La carte dessinait les boutons du volet du brouillon, tandis que l'envoi lisait le volet
    enregistré : on pouvait confirmer un ordre sur un volet affiché et commander l'autre (ou rien,
    au premier branchement) — signalé en revue de la PR #81.
    """

    def test_un_autre_volet_choisi_sans_enregistrer_n_a_aucun_bouton(self) -> None:
        html = _carte(brouillon="cover.autre", attributs=DOCKEE)
        self.assertNotIn("data-garage-demander", html)
        self.assertNotIn('data-commande="garage-', html)
        self.assertIn("pas enregistré", html)

    def test_le_choix_enregistre_a_ses_boutons(self) -> None:
        html = _carte(attributs=DOCKEE)
        self.assertIn('data-garage-demander="fermer"', html)
        self.assertNotIn("pas enregistré", html)

    def test_revenir_au_volet_enregistre_remet_les_boutons(self) -> None:
        html = _carte(brouillon="cover.garage", attributs=DOCKEE)
        self.assertIn('data-garage-demander="ouvrir"', html)

    def test_au_premier_branchement_rien_n_est_commandable_avant_l_enregistrement(self) -> None:
        html = _carte(enregistre="", brouillon="cover.garage", attributs=DOCKEE)
        self.assertNotIn("data-garage-demander", html)
        self.assertIn("pas enregistré", html)

    def test_les_boutons_portent_l_identite_du_volet_enregistre(self) -> None:
        (sortie,) = _rendre([{"type": "commandes", "volet": "open", "position": 100, "confirmation": "fermer", "attributs": DOCKEE}])
        self.assertIn('data-commande="garage-fermer" data-volet="cover.garage"', sortie["html"])
        (sortie,) = _rendre([{"type": "commandes", "volet": "opening", "position": 40, "attributs": DOCKEE}])
        self.assertIn('data-commande="garage-arreter" data-volet="cover.garage"', sortie["html"])

    def _envoyer(self, nom: str, **extra) -> dict:
        (sortie,) = _rendre([{"type": "commande", "nom": nom, "volet": "open", "attributs": DOCKEE, **extra}])
        return sortie

    def test_un_bouton_d_un_autre_volet_n_envoie_rien(self) -> None:
        """Le brouillon a changé entre le rendu du bouton et le clic final."""
        for nom in ("garage-fermer", "garage-ouvrir", "garage-arreter"):
            with self.subTest(commande=nom):
                sortie = self._envoyer(nom, bouton_volet="cover.autre")
                self.assertEqual(sortie["appels"], [])
                self.assertIn("n'est plus celui qui est enregistré", sortie["toasts"][0][0])
                self.assertTrue(sortie["toasts"][0][1])

    def test_un_bouton_sans_identite_n_envoie_rien(self) -> None:
        sortie = self._envoyer("garage-fermer", bouton_volet=None)
        self.assertEqual(sortie["appels"], [])
        self.assertEqual(len(sortie["toasts"]), 1)

    def test_aucun_volet_enregistre_aucun_ordre(self) -> None:
        sortie = self._envoyer("garage-fermer", enregistre="", bouton_volet="cover.garage")
        self.assertEqual(sortie["appels"], [])

    def test_l_identite_correspondante_envoie_au_bon_volet(self) -> None:
        sortie = self._envoyer("garage-fermer", bouton_volet="cover.garage")
        self.assertEqual(sortie["appels"][0][:3], ["cover", "close_cover", {"entity_id": "cover.garage"}])
        self.assertEqual(sortie["toasts"], [])

    def test_le_volet_enregistre_a_change_entre_les_deux_clics(self) -> None:
        """Le bouton portait cover.garage ; l'utilisateur a enregistré cover.autre entre-temps."""
        sortie = self._envoyer("garage-fermer", bouton_volet="cover.garage", enregistre="cover.autre")
        self.assertEqual(sortie["appels"], [])


@unittest.skipUnless(NODE, "Node n'est pas installé")
class VoletEnMouvementTests(unittest.TestCase):
    """⚠️ Une confirmation ouverte AVANT un mouvement survit à ce mouvement : l'ordre inverse enverrait
    le volet repartir dans l'autre sens (signalé en revue de la PR #81). Seul l'arrêt passe."""

    def _course(self, verbe: str, nom: str, volet: str, mouvement: str) -> dict:
        (sortie,) = _rendre([{
            "type": "course", "verbe": verbe, "nom": nom, "volet": volet, "position": 100 if volet == "open" else 0,
            "attributs": DOCKEE, "changement_volet": mouvement,
        }])
        return sortie

    def test_fermer_confirme_puis_le_volet_se_met_a_s_ouvrir(self) -> None:
        sortie = self._course("fermer", "garage-fermer", "open", "opening")
        self.assertEqual(sortie["appels"], [])
        self.assertIn("en mouvement", sortie["toasts"][0][0])
        self.assertNotIn('data-commande="garage-fermer"', sortie["html"])
        self.assertIn("La confirmation est annulée", sortie["html"])

    def test_ouvrir_confirme_puis_le_volet_se_met_a_se_fermer(self) -> None:
        sortie = self._course("ouvrir", "garage-ouvrir", "closed", "closing")
        self.assertEqual(sortie["appels"], [])
        self.assertIn("en mouvement", sortie["toasts"][0][0])

    def test_fermer_confirme_puis_le_volet_se_ferme_deja_pas_de_double_ordre(self) -> None:
        sortie = self._course("fermer", "garage-fermer", "open", "closing")
        self.assertEqual(sortie["appels"], [])

    def test_l_arret_part_pendant_un_mouvement(self) -> None:
        for mouvement in ("opening", "closing"):
            with self.subTest(mouvement=mouvement):
                (sortie,) = _rendre([{"type": "commande", "nom": "garage-arreter", "volet": mouvement, "position": 50, "attributs": DEHORS}])
                self.assertEqual(sortie["appels"][0][1], "stop_cover")

    def test_sans_mouvement_l_ordre_confirme_part_toujours(self) -> None:
        (sortie,) = _rendre([{
            "type": "course", "verbe": "fermer", "nom": "garage-fermer", "volet": "open", "position": 100, "attributs": DOCKEE,
        }])
        self.assertEqual(sortie["appels"][0][1], "close_cover")


@unittest.skipUnless(NODE, "Node n'est pas installé")
class CapacitesDuVoletTests(unittest.TestCase):
    """Ouvrir et Fermer testent les capacités publiées par le volet, comme Arrêter teste son bit
    (signalé en revue de la PR #81) : un volet qui ne sait pas faire l'ordre ne le reçoit pas.
    OPEN = 1, CLOSE = 2, STOP = 8."""

    def _commandes(self, fonctions, volet: str = "open", **extra) -> str:
        (sortie,) = _rendre([{"type": "commandes", "volet": volet, "position": 100, "fonctions": fonctions,
                              "attributs": DOCKEE, **extra}])
        return sortie["html"]

    def test_un_volet_qui_ne_sait_que_s_ouvrir_n_a_pas_de_bouton_fermer(self) -> None:
        html = self._commandes(1, volet="closed")
        self.assertNotIn("disabled", _bouton(html, 'data-garage-demander="ouvrir"'))
        self.assertIn("disabled", _bouton(html, 'data-garage-demander="fermer"'))

    def test_un_volet_qui_ne_sait_que_se_fermer_n_a_pas_de_bouton_ouvrir(self) -> None:
        html = self._commandes(2, volet="open")
        self.assertIn("disabled", _bouton(html, 'data-garage-demander="ouvrir"'))
        self.assertNotIn("disabled", _bouton(html, 'data-garage-demander="fermer"'))

    def test_un_volet_complet_garde_les_deux_boutons(self) -> None:
        html = self._commandes(15, volet="closed")
        self.assertNotIn("disabled", _bouton(html, 'data-garage-demander="ouvrir"'))

    def test_un_volet_sans_aucune_capacite_n_a_aucun_ordre_mais_l_arret_suit_son_bit(self) -> None:
        html = self._commandes(0, volet="closed")
        self.assertIn("disabled", _bouton(html, 'data-garage-demander="ouvrir"'))
        self.assertIn("disabled", _bouton(html, 'data-garage-demander="fermer"'))
        self.assertNotIn('data-commande="garage-arreter"', html, "pas de bit STOP : pas de bouton Arrêter")

    def test_le_motif_du_refus_est_dit_au_survol(self) -> None:
        html = self._commandes(1, volet="closed")
        self.assertIn("Ce volet ne sait pas se fermer.", _bouton(html, 'data-garage-demander="fermer"'))

    def test_un_attribut_absent_ne_bloque_pas(self) -> None:
        """On ne bloque pas sur ce qu'on ne sait pas : sans `supported_features`, les ordres restent possibles."""
        html = self._commandes(None, volet="open")
        self.assertNotIn("disabled", _bouton(html, 'data-garage-demander="fermer"'))

    def test_la_confirmation_est_annulee_si_la_capacite_manque(self) -> None:
        html = self._commandes(1, volet="open", confirmation="fermer")
        self.assertNotIn('data-commande="garage-fermer"', html)
        self.assertIn("ne sait pas se fermer", html)

    def test_l_envoi_est_refuse_pour_un_ordre_non_pris_en_charge(self) -> None:
        for nom, fonctions, volet in (("garage-fermer", 1, "open"), ("garage-ouvrir", 2, "closed")):
            with self.subTest(commande=nom):
                (sortie,) = _rendre([{"type": "commande", "nom": nom, "volet": volet, "fonctions": fonctions, "attributs": DOCKEE}])
                self.assertEqual(sortie["appels"], [])
                self.assertIn("ne sait pas", sortie["toasts"][0][0])

    def test_l_envoi_part_quand_la_capacite_est_la(self) -> None:
        (sortie,) = _rendre([{"type": "commande", "nom": "garage-fermer", "volet": "open", "fonctions": 2, "attributs": DOCKEE}])
        self.assertEqual(sortie["appels"][0][1], "close_cover")


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
