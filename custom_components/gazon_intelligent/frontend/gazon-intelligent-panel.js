/**
 * Gazon Intelligent — la page « Gazon » : une base de contrôle et des réglages.
 *
 * Panneau Home Assistant écrit sans dépendance (web component + shadow DOM), en deux vues :
 *   · Accueil : tout ce que montre la carte Lovelace (état du moment, bulletin, arrosage, tonte,
 *     gazon, produits) et les actions (arroser, arrêter, déclarer, changer de mode…) ;
 *   · Réglages (chemin « /reglages ») : le registre `reglages.py`, servi par la commande WebSocket
 *     `gazon_intelligent/reglages/get` avec la liste des entités de l'instance (`entites`, `zones`,
 *     `pompe`, `meteo`). Ce fichier ne décide que de la MISE EN PAGE et ne contient aucune valeur
 *     du moteur. Côté serveur : `panneau.py` (commande et enregistrement du panneau, 0.92.0).
 *
 * ⚠️ Les dessins rejouent des règles du moteur ; toute évolution de ces règles doit s'y reporter :
 *   · frise de tonte      → decision_mowing._resolve_mowing_window (nuit jugée sur le soleil) ;
 *   · feux vent/chaleur   → mêmes comparaisons (« à éviter » ≥, « interdit » >, gel < 8 °C) ;
 *   · frise du matin      → guidance._morning_window_bounds + fin 15 min avant le lever (0.90.0) ;
 *   · frise des graines   → guidance._semis_window_bounds (plafond 16 h certains jours) ;
 *   · étapes des graines  → phases.compute_subphase (bornes INCLUSES : J0-10, J11-24…) ;
 *   · première coupe      → phases.jours_avant_premiere_coupe.
 *
 * Aperçu local : dev/panel/index.html (maison simulée, rien n'est envoyé à Home Assistant).
 */

const WS_LIRE = "gazon_intelligent/reglages/get";
const WS_ECRIRE = "gazon_intelligent/reglages/set";

const MOIS_LONGS = [
  "janvier", "février", "mars", "avril", "mai", "juin",
  "juillet", "août", "septembre", "octobre", "novembre", "décembre",
];
const INITIALES_MOIS = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];

// Les tableaux « un chiffre par mois » : ce que disent leurs boutons et leur note.
const TABLES_MOIS = {
  tonte_hauteur_par_mois: {
    groupe: "Hauteur par mois", moins: "Plus court", plus: "Plus haut",
    note: "Le point vert montre le mois en cours ; un trait pointillé, la hauteur personnalisée d'un mois. Ce n'est qu'un point de départ : la chaleur, un semis ou la règle du tiers peuvent faire monter la hauteur conseillée.",
  },
  tonte_frequence_par_mois: {
    groupe: "Tontes par semaine, mois par mois", moins: "Moins souvent", plus: "Plus souvent",
    note: "Le point vert montre le mois en cours ; un trait pointillé, le rythme personnalisé d'un mois. C'est un rythme visé, pas un ordre : la tondeuse ne sort que si le gazon et la météo le permettent.",
  },
};

// ─── La mosaïque ─────────────────────────────────────────────────────────────────────────
// Des couloirs sur 12 colonnes, écrits « début / largeur ». Une case en a deux : le premier vaut
// pour une grande page (1 280 px et plus), le second pour une page moyenne (901 à 1 279 px). Un
// téléphone empile tout, dans l'ordre du code.

// Questions proposées dans la fenêtre « Demander conseil à l'IA ».
const QUESTIONS_IA = [
  "Les graines ont-elles eu assez d'eau aujourd'hui ?",
  "Quels points surveiller cette semaine ?",
  "Quelle est la prochaine période favorable à la tonte ?",
];

const COULOIRS = {
  tout: "1 / -1",
  // Deux couloirs : large à gauche, étroit à droite… ou l'inverse.
  large: "1 / span 7", etroit: "8 / span 5",
  etroitG: "1 / span 5", largeD: "6 / span 7",
  // Trois couloirs de largeurs différentes.
  gauche: "1 / span 5", milieu: "6 / span 4", droite: "10 / span 3",
};

const RANGEE_MOSAIQUE_PX = 4;

// ─── Mise en page des onglets du registre ────────────────────────────────────────────────
// Un réglage du registre absent d'ici n'est pas perdu : il tombe dans « Autres réglages ».
// `place` : [couloir sur grande page, couloir sur page moyenne]. Une frise prend un couloir large,
// un feu tricolore tient dans un couloir étroit.

const DISPOSITION = {
  tonte: [
    {
      titre: "Quand la tondeuse peut-elle travailler ?",
      phrase: "Le dessin montre la journée en cours, avec le lever et le coucher du soleil réels.",
      dessin: "journee_tonte",
      cles: ["tonte_fenetre_ideale_debut", "tonte_fenetre_ideale_fin"],
      place: ["gauche", "large"],
    },
    {
      titre: "Le soir",
      phrase: "Quand le soleil baisse, la tondeuse peut ressortir. Ces heures suivent le coucher du soleil.",
      dessin: "soir_tonte",
      cles: ["tonte_soir_avant_coucher", "tonte_soir_apres_coucher"],
      place: ["gauche", "large"],
    },
    {
      titre: "Le vent",
      phrase: "Vert, on tond. Orange, mieux vaut attendre. Rouge, on ne tond pas.",
      dessin: "feu_vent",
      cles: ["tonte_vent_a_eviter", "tonte_vent_bloque"],
      place: ["droite", "etroit"],
    },
    {
      titre: "La chaleur",
      phrase: "Le gazon n'aime pas être coupé quand il a trop chaud… ni quand il gèle.",
      dessin: "feu_chaleur",
      cles: ["tonte_temperature_a_eviter", "tonte_temperature_bloquee"],
      place: ["droite", "large"],
    },
    {
      titre: "L'air humide",
      phrase: "Quand l'air est très humide, l'herbe reste mouillée.",
      dessin: "feu_humidite",
      cles: ["tonte_humidite_bloquee"],
      place: ["gauche", "etroit"],
    },
    {
      titre: "Le rythme",
      phrase: "Au plus souvent, voilà comment la tondeuse peut sortir sur deux semaines.",
      dessin: "rythme_tonte",
      cles: ["tonte_ecart_min_jours", "tonte_max_par_jour"],
      place: ["milieu", "etroit"],
    },
    {
      titre: "Le rythme de la saison",
      phrase: "Nombre de tontes visé chaque semaine, mois par mois. Sélectionner un mois pour le modifier.",
      cles: ["tonte_frequence_par_mois"],
      place: ["milieu", "etroit"],
    },
    {
      titre: "La hauteur de l'herbe",
      phrase: "Sélectionner un mois pour modifier sa hauteur.",
      cles: ["tonte_hauteur_par_mois"],
      place: ["milieu", "large"],
    },
  ],
  arrosage: [
    {
      titre: "L'arrosage du matin",
      phrase: "L'arrosage se termine juste avant le lever du soleil : l'herbe sèche vite, les maladies n'ont pas le temps de s'installer.",
      dessin: "matin_arrosage",
      cles: ["arrosage_ouverture", "arrosage_marge_avant_lever"],
      place: ["gauche", "large"],
    },
    {
      titre: "Jusqu'à quand arroser le matin ?",
      phrase: "Après le meilleur moment, l'arrosage reste possible jusqu'à l'heure limite. Ensuite, il attend le lendemain.",
      cles: ["arrosage_fin_optimale", "arrosage_fin_acceptable"],
      place: ["milieu", "etroit"],
    },
    {
      titre: "Les gros arrosages",
      phrase: "Une grosse dose se donne en deux fois, avec une pause pour que l'eau rentre dans la terre. En mode Normal.",
      dessin: "decoupage",
      cles: ["arrosage_decoupage_seuil", "arrosage_pause_dose_min", "arrosage_pause_duree"],
      place: ["droite", "large"],
    },
    {
      titre: "La sécurité",
      phrase: "Pour ne jamais arroser deux fois par erreur.",
      cles: ["arrosage_delai_relance"],
      place: ["gauche", "etroit"],
    },
    {
      titre: "La pluie annoncée",
      phrase: "Définit combien les prévisions peuvent faire reporter un arrosage. La pluie réellement mesurée garde toujours la priorité.",
      cles: ["arrosage_sensibilite_pluie"],
      place: ["gauche", "etroit"],
    },
    {
      titre: "Les zones ombragées",
      phrase: "Chaque zone peut recevoir moins d'eau que la dose générale. Une zone à 0 % garde la durée normale.",
      cles: [1, 2, 3, 4, 5].map((numero) => `arrosage_reduction_ombre_zone_${numero}`),
      place: ["milieu", "large"],
    },
    {
      titre: "Les soirs de forte chaleur",
      phrase: "Un petit coup de frais le soir, seulement quand il fait vraiment chaud.",
      dessin: "rafraichissement",
      cles: ["rafraichissement_temperature", "rafraichissement_dose"],
      place: ["milieu", "etroit"],
    },
  ],
  graines: [
    {
      titre: "Le voyage de la graine",
      phrase: "De la graine au vrai gazon, en quatre étapes. Chaque étape a son arrosage.",
      dessin: "voyage_graine",
      cles: ["graines_duree"],
      place: ["gauche", "large"],
    },
    {
      titre: "Les étapes",
      phrase: "Chaque étape dure jusqu'au jour sélectionné, ce jour compris.",
      cles: ["graines_fin_germination", "graines_fin_enracinement", "graines_fin_reprise"],
      place: ["droite", "etroit"],
    },
    {
      titre: "L'eau pendant la germination",
      phrase: "Au début, un peu d'eau, souvent : la surface ne doit jamais sécher.",
      dessin: "eau_germination",
      cles: ["graines_germination_dose", "graines_germination_cycles"],
      place: ["milieu", "large"],
    },
    {
      titre: "L'eau pendant l'enracinement",
      phrase: "Plus d'eau d'un coup, moins souvent : les racines descendent la chercher.",
      dessin: "eau_enracinement",
      cles: ["graines_enracinement_dose", "graines_enracinement_cycles"],
      place: ["milieu", "large"],
    },
    {
      titre: "L'eau pour la reprise et la stabilisation",
      phrase: "Jusqu'à la fin du suivi, le jeune gazon tient de mieux en mieux sans eau.",
      dessin: "eau_reprise",
      cles: ["graines_reprise_dose", "graines_reprise_cycles"],
      place: ["milieu", "large"],
    },
    {
      titre: "L'heure des graines",
      phrase: "Les graines s'arrosent en journée, jamais la nuit.",
      dessin: "journee_graines",
      cles: ["graines_fenetre_debut", "graines_fenetre_fin"],
      place: ["gauche", "etroit"],
    },
    {
      titre: "La météo",
      phrase: "Quand il fait trop froid ou trop venteux, on attend.",
      dessin: "feux_graines",
      cles: ["graines_vent_max", "graines_temperature_min"],
      place: ["droite", "etroit"],
    },
    {
      titre: "L'alerte",
      phrase: "Une notification est envoyée lorsqu'un arrosage des graines ne part pas. Les appareils destinataires se configurent dans Entités.",
      cles: ["graines_alerte_retard"],
      place: ["gauche", "etroit"],
    },
  ],
  sursemis: [
    {
      titre: "La tondeuse et les jeunes pousses",
      phrase: "Le sursemis concerne un gazon déjà en pousse : la tondeuse continue avec des précautions adaptées.",
      dessin: "voyage_sursemis",
      cles: ["sursemis_levee", "sursemis_ecart_tontes"],
      place: ["gauche", "large"],
    },
    {
      titre: "La première coupe des pousses",
      phrase: "Elle arrive quand les jeunes pousses sont assez hautes. C'est une estimation.",
      cles: ["sursemis_pousse_plantules", "sursemis_premiere_coupe"],
      place: ["droite", "etroit"],
    },
    {
      titre: "La hauteur de la lame",
      phrase: "Courte au début pour laisser passer la lumière, puis un peu plus haute.",
      dessin: "lame_sursemis",
      cles: ["sursemis_lame", "sursemis_lame_finale"],
      place: ["milieu", "etroit"],
    },
    {
      titre: "Quand remonter la lame ?",
      phrase: "Après quelques coupes des jeunes pousses, la lame remonte.",
      cles: ["sursemis_coupes_avant_remontee"],
      place: ["milieu", "large"],
    },
  ],
  semis: [
    {
      titre: "Quand la tondeuse peut-elle reprendre ?",
      phrase: "Ce délai protège le jeune gazon sans changer son programme d'arrosage.",
      cles: ["semis_reprise_tonte_jours"],
      place: ["gauche", "etroit"],
    },
    {
      titre: "La hauteur conseillée à chaque étape",
      phrase: "Sur un terrain nu, on ne tond pas tout de suite. Puis on descend doucement.",
      dessin: "escalier_semis",
      cles: ["semis_hauteur_germination", "semis_hauteur_enracinement"],
      place: ["large", "large"],
    },
    {
      titre: "Les premières coupes",
      phrase: "Quand le jeune gazon peut être coupé, la hauteur conseillée descend doucement.",
      cles: ["semis_hauteur_reprise", "semis_hauteur_stabilisation"],
      place: ["etroit", "etroit"],
    },
  ],
  modes: [
    {
      mode: "Traitement",
      titre: "Après un traitement",
      phrase: "La dose, le délai et les autres consignes viennent de la fiche du produit.",
      dessin: "jours:mode_traitement_duree",
      cles: ["mode_traitement_duree"],
      place: ["gauche", "large"],
    },
    {
      mode: "Fertilisation",
      titre: "Après un engrais",
      phrase: "La dose d'incorporation vient de la fiche de chaque engrais.",
      dessin: "jours:mode_fertilisation_duree",
      cles: ["mode_fertilisation_duree"],
      place: ["gauche", "large"],
    },
    {
      mode: "Biostimulant",
      titre: "Après un biostimulant",
      phrase: "La dose vient de la fiche du produit.",
      dessin: "jours:mode_biostimulant_duree",
      cles: ["mode_biostimulant_duree"],
      place: ["gauche", "large"],
    },
    {
      mode: "Agent Mouillant",
      titre: "Après un agent mouillant",
      phrase: "L'eau aide le produit à descendre dans le sol. Sa fiche précise la dose et le délai à respecter.",
      dessin: "jours:mode_agent_mouillant_duree",
      cles: ["mode_agent_mouillant_duree"],
      place: ["gauche", "large"],
    },
    {
      mode: "Scarification",
      titre: "Après une scarification",
      phrase: "Les consignes particulières restent dans la fiche du produit utilisé.",
      dessin: "jours:mode_scarification_duree",
      cles: ["mode_scarification_duree", "mode_scarification_temperature_min"],
      place: ["gauche", "large"],
    },
    {
      mode: "Hivernage",
      titre: "Pendant l'hivernage",
      phrase: "Ces protections ne sont pas réglables.",
      statique: true,
      cles: [],
      place: ["gauche", "large"],
    },
  ],
};

// ─── Les fiches produit ──────────────────────────────────────────────────────────────────
// ⚠️ `register_product` REMPLACE la fiche entière : un champ non renvoyé est perdu. La page
// renvoie donc TOUS ces champs, repris de la fiche complète. `tests/test_panneau_produits.py`
// vérifie que la liste couvre chaque champ du service et chaque champ que le moteur garde.
const CHAMPS_PRODUIT = [
  "nom", "type", "dose_conseillee", "usage_mode", "max_applications_per_year", "reapplication_after_days",
  "delai_avant_tonte_jours", "phase_compatible", "application_months", "application_type",
  "application_requires_watering_after", "application_post_watering_mm", "application_irrigation_block_hours",
  "application_irrigation_delay_minutes", "application_irrigation_mode", "application_label_notes", "note",
  "temperature_min", "temperature_max",
];
// Les listes proposées par le service (services.yaml).
const TYPES_PRODUIT = ["Fertilisation", "Biostimulant", "Agent Mouillant", "Traitement", "Scarification", "Hivernage"];
const USAGES_PRODUIT = { preventif: "Pour prévenir", curatif: "Pour soigner", entretien: "Pour entretenir", rattrapage: "Pour rattraper" };
const PHASES_PRODUIT = { Semis: "Semis", Sursemis: "Sursemis", Croissance: "Croissance", Entretien: "Entretien" };
const MODES_ARROSAGE_PRODUIT = { auto: "Automatique", manuel: "Manuel", suggestion: "Proposé seulement" };

// `memory.normalize_product_id`, sans les accents : un identifiant lisible et stable.
function idProduit(nom) {
  return String(nom ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").trim().toLowerCase()
    .replace(/ /g, "_").replace(/[^a-z0-9_-]/g, "").replace(/^[_-]+|[_-]+$/g, "");
}

// Les modes à durée réglable, et ce qu'ils changent (relu dans le moteur le 16/09/2026).
const MODES_DUREES = [
  { cle: "mode_traitement_duree", nom: "Traitement", effet: "tondeuse à l'arrêt" },
  { cle: "mode_fertilisation_duree", nom: "Fertilisation" },
  { cle: "mode_biostimulant_duree", nom: "Biostimulant" },
  { cle: "mode_agent_mouillant_duree", nom: "Agent mouillant" },
  { cle: "mode_scarification_duree", nom: "Scarification", effet: "une tonte par jour au plus" },
];

// Ce que chaque mode change, relu dans le moteur (`watering_policy.py`, `decision_mowing.py`) et
// dans le README pour les valeurs par défaut des graines.
const REGLES_MODES = {
  Normal: [
    "Un arrosage profond, à l'aube, quand la réserve du sol passe sous son seuil.",
    "Il se termine 15 minutes avant le lever du soleil.",
    "La tonte suit ses fenêtres et ses limites de vent et de chaleur.",
  ],
  Semis: [
    "Le chantier comprend un travail complet du sol avant la mise en place des graines.",
    "Les graines sont arrosées par petits cycles, ajustés à la météo.",
    "Par défaut, la tonte est interdite 25 jours.",
    "Puis la hauteur de coupe descend par étapes, de 7,5 à 5 cm.",
  ],
  Sursemis: [
    "Le chantier comprend la scarification du gazon existant avant l'épandage des graines.",
    "Les graines sont arrosées par petits cycles, ajustés à la météo.",
    "Par défaut, la tonte est suspendue pendant la levée (7 jours), puis reprend.",
    "Coupe à 4 cm, puis 4,5 cm après deux coupes des jeunes pousses.",
  ],
  Traitement: [
    "Un traitement foliaire reste au sec.",
    "Sans dose précise dans la fiche, un traitement racinaire vise 3 à 6 mm.",
    "La tondeuse reste à sa base pendant le traitement.",
  ],
  Fertilisation: [
    "La pluie prévue peut remplacer l'arrosage d'incorporation.",
    "Sans dose précise dans la fiche, le moteur vise 5 à 8 mm en un passage.",
  ],
  Biostimulant: [
    "La pluie prévue peut incorporer le produit à la place de l'arrosage.",
    "Sans dose précise dans la fiche, le soutien reste léger : 3 à 7 mm.",
  ],
  "Agent Mouillant": [
    "Sans dose précise dans la fiche, le moteur vise 5 à 12 mm.",
    "La quantité s'adapte à l'état hydrique du sol.",
  ],
  Scarification: [
    "Ce mode correspond à une scarification seule, sans semis ni sursemis.",
    "Sans dose précise dans la fiche, l'accompagnement vise 5 à 10 mm.",
    "Le sol doit être légèrement humide et sans forte pluie annoncée.",
    "La tonte est limitée à une session par jour pendant la récupération.",
  ],
  Hivernage: [
    "La tonte reste bloquée.",
    "L'arrosage automatique aussi, sauf en cas de sécheresse prolongée.",
    "Le mode reste actif jusqu'à un changement manuel.",
    "Un sursemis déclaré reste prioritaire sur le repos hivernal.",
  ],
};

// Les modes dont les réglages vivent dans d'autres onglets.
const LIENS_MODES = {
  Normal: [["tonte", "Tonte"], ["arrosage", "Arrosage"]],
  Semis: [["semis", "Semis"]],
  Sursemis: [["sursemis", "Sursemis"]],
};

// Un produit se déclare plutôt qu'un mode : il est noté, et sa fiche fixe la dose.
const MODES_PRODUIT = ["Traitement", "Fertilisation", "Biostimulant", "Agent Mouillant", "Scarification"];

// Phases où `guidance.py` ne cappe jamais la dose sur le plafond hebdomadaire du profil Normal
// (`_profile_for_sursemis`, `_profile_for_traitement`, `_profile_for_agro_phases`,
// `_profile_for_blocked` pour l'Hivernage) — seul `_profile_for_normal` l'applique réellement.
// Liste blanche explicite, pas un `!== "Normal"` : voir `_budgetEstInformatifSeul`.
const _PHASES_SANS_PLAFOND_HEBDO = new Set(["Semis", "Sursemis", "Hivernage", ...MODES_PRODUIT]);

// Le besoin propre à chaque mode produit et à l'hivernage, en une phrase courte pour une puce
// (0.96.2) — repris de `REGLES_MODES`, jamais réinventé. Sans dose précise dans une fiche, le
// moteur applique la sienne (cf. `REGLES_MODES`) ; la puce le dit en bref, la phrase complète
// reste dans l'onglet Modes.
const BESOIN_MODES = {
  Traitement: "Le foliaire reste au sec",
  Fertilisation: "La pluie prévue peut incorporer",
  Biostimulant: "La pluie prévue peut incorporer",
  "Agent Mouillant": "Vise 5 à 12 mm, selon le sol",
  Scarification: "Sol légèrement humide requis",
  Hivernage: "Arrosage bloqué sauf sécheresse prolongée",
};

// ─── Onglet « Installation » : des entités existantes, pas le registre ─────────────────
// Les identifiants d'entité arrivent du serveur (`entites`), jamais écrits en dur ici.

const INSTALLATION = [
  {
    groupe: "arrosage",
    titre: "Arroseurs",
    phrase: "Combien d'eau chaque zone reçoit en une heure. C'est ce qui donne la durée d'arrosage.",
    place: ["gauche", "large"],
    lignes: [
      {
        cle: "debit_zone_1", icone: "mdi:numeric-1-circle-outline",
        titre: "Zone 1 : combien de millimètres d'eau en une heure ?",
        aide: "Placer un verre à fond plat dans la zone, arroser une heure et mesurer la hauteur d'eau. 0 = zone non utilisée.",
      },
      { cle: "debit_zone_2", icone: "mdi:numeric-2-circle-outline", titre: "Zone 2 : combien en une heure ?", aide: "Même mesure, dans la zone 2." },
      { cle: "debit_zone_3", icone: "mdi:numeric-3-circle-outline", titre: "Zone 3 : combien en une heure ?", aide: "Même mesure, dans la zone 3." },
    ],
  },
  {
    groupe: "arrosage",
    titre: "Les zones en plus",
    phrase: "Laisser 0 lorsque les zones 4 ou 5 ne sont pas utilisées.",
    place: ["droite", "etroit"],
    lignes: [
      { cle: "debit_zone_4", icone: "mdi:numeric-4-circle-outline", titre: "Zone 4 : combien en une heure ?", aide: "0 = zone pas utilisée." },
      { cle: "debit_zone_5", icone: "mdi:numeric-5-circle-outline", titre: "Zone 5 : combien en une heure ?", aide: "0 = zone pas utilisée." },
    ],
  },
  {
    groupe: "arrosage",
    titre: "Les interrupteurs de l'arrosage",
    phrase: "Activation ou désactivation selon le fonctionnement souhaité.",
    place: ["gauche", "etroit"],
    lignes: [
      {
        cle: "arrosage_automatique", icone: "mdi:sprinkler", genre: "interrupteur",
        titre: "Arroser tout seul ?",
        aide: "Éteint : Gazon Intelligent indique quand arroser, mais n'ouvre jamais les vannes lui-même.",
      },
      {
        cle: "rafraichissement_soir", icone: "mdi:weather-sunset-down", genre: "interrupteur",
        titre: "Rafraîchir le gazon les soirs de forte chaleur ?",
        aide: "La chaleur de départ et la quantité d'eau se règlent dans l'onglet Arrosage.",
      },
    ],
  },
  {
    groupe: "tondeuse",
    titre: "Tondeuse",
    phrase: "Les capacités de la tondeuse et ses réglages actuels.",
    place: ["milieu", "large"],
    lignes: [
      {
        cle: "hauteur_coupe_tondeuse", icone: "mdi:content-cut",
        titre: "À quelle hauteur la lame est-elle réglée en ce moment ?",
        aide: "Régler d'abord la molette de la tondeuse, puis reporter la même valeur ici : Home Assistant ne peut pas lire la molette.",
      },
    ],
  },
  {
    groupe: "tondeuse",
    titre: "Les limites de la tondeuse",
    phrase: "Le plus petit et le plus grand cran de la molette.",
    place: ["milieu", "large"],
    lignes: [
      {
        cle: "hauteur_min_tondeuse_cm", icone: "mdi:arrow-collapse-down",
        titre: "Quelle est la hauteur la plus basse de la tondeuse ?",
        aide: "Le plus petit cran de la molette.",
      },
      {
        cle: "hauteur_max_tondeuse_cm", icone: "mdi:arrow-collapse-up",
        titre: "Et la plus haute ?",
        aide: "Le plus grand cran. C'est une limite de la machine, pas la hauteur souhaitée.",
      },
    ],
  },
  {
    groupe: "tondeuse",
    titre: "Les temps d'attente",
    phrase: "Pour que la tondeuse et l'arrosage ne se marchent pas dessus.",
    place: ["milieu", "large"],
    lignes: [
      {
        cle: "delai_reprise_tonte_apres_arrosage", icone: "mdi:timer-sand", genre: "duree",
        titre: "Après un arrosage, combien de temps la tondeuse attend-elle ?",
        aide: "Le temps que l'herbe sèche : une herbe mouillée se coupe mal.",
      },
      {
        cle: "seuil_declaration_tonte", icone: "mdi:timer-check-outline", genre: "duree",
        titre: "Combien de minutes de travail pour qu'une journée compte comme tondue ?",
        aide: "En dessous, la tondeuse est seulement sortie faire un tour : ce n'est pas une vraie tonte.",
      },
    ],
  },
  {
    groupe: "tondeuse",
    titre: "Les interrupteurs de la tondeuse",
    phrase: "Activation ou désactivation selon le fonctionnement souhaité.",
    place: ["gauche", "etroit"],
    lignes: [
      {
        cle: "coordination_tondeuse", icone: "mdi:robot-mower", genre: "interrupteur",
        titre: "Attendre la tondeuse avant d'arroser ?",
        aide: "Allumé : les vannes restent fermées tant que la tondeuse travaille ou rentre à sa base.",
      },
      {
        cle: "declaration_tonte_auto", icone: "mdi:clipboard-check-outline", genre: "interrupteur",
        titre: "Noter les tontes tout seul ?",
        aide: "Allumé : une journée où la tondeuse a assez travaillé est inscrite comme tondue.",
      },
    ],
  },
];

// Ordre d'affichage des groupes de l'onglet « Installation » : un titre visible avant
// chaque paquet de cartes, pour qu'on les reconnaisse d'un coup d'œil au lieu d'une suite de
// cartes individuelles sans repère commun.
const GROUPES_INSTALLATION = [
  { cle: "arrosage", titre: "Arrosage", icone: "mdi:sprinkler-variant" },
  { cle: "tondeuse", titre: "Tondeuse", icone: "mdi:robot-mower" },
  { cle: "notifications", titre: "Alertes et notifications", icone: "mdi:bell-outline" },
];

// Les bornes de la lame dépendent des hauteurs min et max : on les écrit d'abord.
const ORDRE_ECRITURE = ["hauteur_min_tondeuse_cm", "hauteur_max_tondeuse_cm"];

const ONGLET_INSTALLATION = {
  cle: "installation",
  titre: "Installation",
  phrase: "Les arroseurs, la tondeuse, les automatismes et les alertes.",
  icone: "mdi:tune-variant",
};

const ONGLET_ENTITES = {
  cle: "entites",
  titre: "Entités",
  phrase: "Tous les appareils et capteurs lus par l'intégration, réunis au même endroit.",
  icone: "mdi:connection",
};

// Valeurs communes aux trois profils : des repères de confort/sécurité de la tonte (vent,
// chaleur, humidité, fenêtre horaire) et de fractionnement de l'arrosage. Ce sont des limites
// physiques ou liées au sol (réglage « type de terre »), pas un style d'entretien — aucune
// source n'indique qu'elles devraient varier selon le type de gazon voulu.
const PROFIL_GAZON_COMMUN = {
  tonte_fenetre_ideale_debut: 600, tonte_fenetre_ideale_fin: 840,
  tonte_soir_avant_coucher: 300, tonte_soir_apres_coucher: 30,
  tonte_vent_a_eviter: 20, tonte_vent_bloque: 40,
  tonte_temperature_a_eviter: 25, tonte_temperature_bloquee: 30,
  tonte_humidite_bloquee: 90, tonte_max_par_jour: 2,
  arrosage_decoupage_seuil: 10.0, arrosage_pause_dose_min: 10.0, arrosage_pause_duree: 25,
};

// Trois profils, un seul levier agronomique à chaque fois : la hauteur et la fréquence de
// tonte, et la confiance dans la pluie annoncée (arrosage_sensibilite_pluie, déjà réglable
// séparément : Économe ×0,75 / Équilibrée ×1,0 / Prudente ×1,25). Sources : une coupe plus haute
// favorise des racines profondes, donc moins d'arrosage et plus de résistance à la sécheresse
// (gazon rustique) ; un gazon de jeu vise une pelouse dense toute l'année pour encaisser le
// piétinement, avec un arrosage qui ne se fie pas trop vite à une pluie annoncée qui n'arrive
// pas. Chaque valeur est dans les bornes du réglage correspondant (reglages.py).
const PROFILS_GAZON = [
  {
    cle: "ornement", titre: "Gazon d'ornement", titreCourt: "Ornement", resume: "Dense et régulier", icone: "mdi:grass",
    phrase: "Dense, court et régulier : tonte fréquente, arrosage suivi. Le profil déjà conseillé par défaut.",
    choix: { tondeuse_creneaux_depart: "ideal_seulement" },
    valeurs: {
      ...PROFIL_GAZON_COMMUN,
      tonte_ecart_min_jours: 2,
      tonte_frequence_par_mois: [0.0, 0.0, 2.5, 2.5, 5.0, 5.0, 3.0, 3.0, 5.0, 5.0, 1.5, 0.0],
      tonte_hauteur_par_mois: [4.0, 4.0, 4.5, 4.0, 4.0, 4.5, 5.0, 5.0, 4.0, 4.0, 4.0, 4.0],
      arrosage_sensibilite_pluie: 1.0,
      rafraichissement_temperature: 32, rafraichissement_dose: 3.0,
    },
  },
  {
    cle: "jeu", titre: "Gazon de jeu", titreCourt: "Jeu", resume: "Résiste au passage", icone: "mdi:soccer",
    phrase: "Un peu plus haut pour encaisser le piétinement, arrosage plus prudent pour rester dense et résistant.",
    choix: { tondeuse_creneaux_depart: "ideal_acceptable" },
    valeurs: {
      ...PROFIL_GAZON_COMMUN,
      tonte_ecart_min_jours: 2,
      tonte_frequence_par_mois: [0.0, 0.0, 2.5, 2.5, 5.0, 5.0, 3.0, 3.0, 5.0, 5.0, 1.5, 0.0],
      tonte_hauteur_par_mois: [4.5, 4.5, 5.0, 4.5, 4.5, 5.0, 5.5, 5.5, 4.5, 4.5, 4.5, 4.5],
      arrosage_sensibilite_pluie: 1.25,
      rafraichissement_temperature: 32, rafraichissement_dose: 3.0,
    },
  },
  {
    cle: "rustique", titre: "Gazon rustique, économe en eau", titreCourt: "Rustique", resume: "Économe en eau", icone: "mdi:cactus",
    phrase: "Tonte plus haute et plus espacée, arrosage réduit : un gazon robuste qui se contente de peu.",
    choix: { tondeuse_creneaux_depart: "ideal_acceptable" },
    valeurs: {
      ...PROFIL_GAZON_COMMUN,
      tonte_ecart_min_jours: 4,
      tonte_frequence_par_mois: [0.0, 0.0, 1.5, 1.5, 3.0, 3.0, 2.0, 2.0, 3.0, 3.0, 1.0, 0.0],
      tonte_hauteur_par_mois: [5.5, 5.5, 6.0, 6.0, 6.5, 6.5, 7.0, 7.0, 6.0, 6.0, 5.5, 5.5],
      arrosage_sensibilite_pluie: 0.75,
      rafraichissement_temperature: 35, rafraichissement_dose: 2.0,
    },
  },
];

const ICONES_UNITE = {
  "km/h": "mdi:weather-windy",
  "°C": "mdi:thermometer",
  "%": "mdi:water-percent",
  jours: "mdi:calendar-range",
  tontes: "mdi:robot-mower-outline",
  coupes: "mdi:content-cut",
  cm: "mdi:ruler",
  mm: "mdi:water",
  "par jour": "mdi:repeat",
  "par semaine": "mdi:calendar-sync",
  h: "mdi:timer-sand",
  "cm/jour": "mdi:sprout",
  "×": "mdi:arrow-expand-vertical",
};

function iconeDe(r) {
  if (r.genre === "heure") return "mdi:clock-outline";
  if (r.genre === "duree") return "mdi:timer-sand";
  if (r.genre === "jour") return "mdi:calendar-arrow-right";
  if (r.genre === "table_mois") return "mdi:calendar-month-outline";
  return ICONES_UNITE[r.unite] || "mdi:tune-variant";
}

// ─── Accueil : la base de contrôle ───────────────────────────────────────────────────────
// Reprend TOUT ce que montre la carte Lovelace (dépôt lovelace-gazon-intelligent-card,
// src/gazon-intelligent-card.js), dans le style de cette page. Ses règles d'affichage sont
// reprises avec leurs raisons : l'orange est une ALERTE rare, un arrosage bloqué se lit sur l'ÉTAT
// « Bloqué »/« Retenu » (le motif peut traîner), et la tonte a DEUX axes, gazon et machine, jamais
// fusionnés. Les identifiants d'entité arrivent du serveur (`entites`, `zones`, `pompe`, `meteo`).

const ONGLETS_ACCUEIL = [
  { cle: "apercu", titre: "Aperçu", icone: "mdi:view-dashboard-outline" },
  { cle: "arrosage", titre: "Arrosage", icone: "mdi:sprinkler-variant" },
  { cle: "tonte", titre: "Tonte", icone: "mdi:robot-mower" },
  { cle: "gazon", titre: "Gazon", icone: "mdi:grass" },
  { cle: "meteo", titre: "Météo", icone: "mdi:weather-partly-cloudy" },
  { cle: "produits", titre: "Produits", icone: "mdi:flask-outline" },
];

// ─── Onglet Météo (0.94.0) ──────────────────────────────────────────────────────────────
// Les entrées viennent du serveur (`sources`, `appareils`) : rôle, entité branchée, appareil.

const GROUPES_METEO = { meteo: "Prévisions", air: "L'air du jardin", pluie: "La pluie", sol: "Le sol et l'arrosage" };

const SOURCES_ET0 = {
  capteur: "lue sur le capteur d'évaporation",
  fallback_pm_location: "calculée par l'intégration (Penman-Monteith, position de la maison)",
  fallback_pm: "calculée par l'intégration (Penman-Monteith)",
};

const DIRECTIONS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSO", "SO", "OSO", "O", "ONO", "NO", "NNO"];
const directionFr = (deg) => {
  const n = nombreOuNul(deg);
  return n === null ? null : DIRECTIONS[Math.round((((n % 360) + 360) % 360) / 22.5) % 16];
};

const NIVEAUX_RISQUE = { low: "faible", faible: "faible", moderate: "modéré", medium: "modéré", modere: "modéré", high: "élevé", eleve: "élevé", critical: "critique", critique: "critique", severe: "sévère", vigilance: "vigilance", normal: "normal", aucun: "aucun", none: "aucun" };

// « 7 j 15 h », « 3 h », « 25 min » : le temps écoulé depuis un évènement.
function ageFr(minutes) {
  const m = Math.max(0, Math.round(minutes));
  if (m < 60) return `${m}\u00a0min`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h}\u00a0h`;
  const j = Math.floor(h / 24);
  return h % 24 ? `${j}\u00a0j ${h % 24}\u00a0h` : `${j}\u00a0j`;
}

// « Aujourd'hui », « Demain », puis « Vendredi 20 » : court, pour une liste de jours.
function jourCourt(brut, aujourdHui, fuseau) {
  const j = jourDe(brut, fuseau);
  if (!j) return "—";
  const n = ecartJours(aujourdHui, j);
  if (n >= -1 && n <= 1) return majuscule(dateHumaine(brut, aujourdHui, fuseau));
  return majuscule(jourPlus(j, 0, { weekday: "long", day: "numeric" }));
}

// « il y a 3 min », « il y a 2 h », « il y a 4 j » : l'âge d'une mesure, lisible d'un coup d'œil.
function ilYA(brut, maintenant = Date.now()) {
  const t = brut instanceof Date ? brut.getTime() : Date.parse(brut);
  if (!Number.isFinite(t)) return "";
  const minutes = Math.max(0, Math.round((maintenant - t) / 60000));
  if (minutes < 1) return "à l'instant";
  if (minutes < 60) return `il y a ${minutes}\u00a0min`;
  const heures = Math.round(minutes / 60);
  if (heures < 48) return `il y a ${heures}\u00a0h`;
  return `il y a ${Math.round(heures / 24)}\u00a0j`;
}

const ETATS_SANS_VALEUR = new Set(["", "unavailable", "unknown", "none"]);

// La valeur d'une entité, avec son unité, telle qu'on la lirait sur l'appareil.
function valeurEtat(etat) {
  if (!etat) return "—";
  const brut = String(etat.state ?? "");
  if (ETATS_SANS_VALEUR.has(brut.toLowerCase())) return brut.toLowerCase() === "unavailable" ? "indisponible" : "inconnue";
  const a = etat.attributes || {};
  const domaine = String(etat.entity_id || "").split(".")[0];
  if (domaine === "binary_sensor") return brut === "on" ? "oui" : brut === "off" ? "non" : brut;
  // Un état météo (« sunny »), celui de l'entité météo comme celui d'un capteur de station.
  if (METEOS[brut]) return METEOS[brut][1];
  if (domaine === "weather") return majuscule(brut.replace(/[-_]/g, " "));
  if (a.device_class === "timestamp") return ilYA(brut) || brut;
  const n = nombreOuNul(brut);
  if (n !== null && /^-?\d+([.,]\d+)?$/.test(brut.trim())) {
    const decimales = Math.abs(n) >= 10 ? 1 : 2;
    const unite = a.unit_of_measurement ? `\u00a0${a.unit_of_measurement}` : "";
    return `${nombreFr(n, decimales)}${unite}`;
  }
  return majuscule(brut.replace(/_/g, " "));
}

// « Station Météo - Jardin Température » → « Température » : le nom sans celui de l'appareil.
function nomCourt(nom, appareil) {
  const n = String(nom || "");
  const a = String(appareil || "");
  if (a && n.toLowerCase().startsWith(a.toLowerCase())) {
    const reste = n.slice(a.length).replace(/^[\s\-–:·]+/, "");
    if (reste) return majuscule(reste);
  }
  return n;
}

const COULEURS_ZONES = ["#10b981", "#3b82f6", "#8b5cf6", "#f59e0b", "#ec4899"];

// Une ouverture de vanne plus longue ne décrit pas un arrosage mais un trou dans l'historique
// (le plan borne chaque zone à 180 min) : la carte a dessiné une barre de 144 h le 29/07/2026.
const SESSION_PLAUSIBLE_MAX_MS = 6 * 3600 * 1000;

// Alignée sur `water._TECHNICAL_WATERING_CAUSES` : hors du budget de la semaine.
const CAUSES_TECHNIQUES = ["rafraichissement_soir", "post_application"];

// Le vocabulaire RÉEL de l'assistant (assistant.py, relu le 16/09/2026) : une action
// (arrosage, traitement, tonte), ou « aucune_action » / « attente_conditions », qui se lit AVEC
// son statut (« blocked » = elle attend). La carte attendait « arroser… », jamais publié.
const ACTIONS = {
  aucune_action: { titre: "Rien à faire pour l'instant", icone: "mdi:check-circle-outline" },
  attente_conditions: { titre: "On attend de meilleures conditions", icone: "mdi:timer-sand" },
  arrosage: { titre: "Il faut arroser", attente: "L'arrosage attend", icone: "mdi:water" },
  traitement: { titre: "Un traitement demande une attention", attente: "Le traitement attend", icone: "mdi:flask-outline" },
  tonte: { titre: "La tonte est possible", attente: "La tonte attend", icone: "mdi:robot-mower" },
};

// `ASSISTANT_MOMENT_VALUES` (assistant.py) ; « none » et « attendre » ne s'affichent pas.
const MOMENTS = {
  maintenant: "maintenant", ce_matin: "ce matin", demain_matin: "demain matin",
  apres_pluie: "après la pluie", soir: "ce soir",
};

// ⚠️ Les quatre états que l'intégration émet vraiment (sensor.py), pas un vocabulaire supposé.
const ETATS_HYDRIQUES = {
  plein: "Réserve pleine", confort: "Confortable", depletion: "Réserve entamée", critique: "Critique",
};

const RISQUES = { faible: "Faible", modere: "Modéré", eleve: "Élevé", critique: "Critique" };

// `POSSIBLE_TONTE_STATUT_VALUES` (decision_models.py) : cinq valeurs.
const STATUTS_TONTE = {
  autorisee: "Autorisée", autorisee_avec_precaution: "Autorisée avec précaution",
  a_surveiller: "À surveiller", deconseillee: "Déconseillée", interdite: "Interdite",
};
// Autorisée avec précaution EST une tonte autorisée : même couleur, sinon le point clignote.
const TONS_TONTE = {
  autorisee: "ok", autorisee_avec_precaution: "ok", a_surveiller: "attention", deconseillee: "attention", interdite: "arret",
};

const DECLARATIONS = {
  declaree: "Tonte inscrite", deja_declaree: "Déjà inscrite aujourd'hui",
  travail_en_cours: "Pas encore : travail pas fini", travail_au_repos: "Pas de travail à inscrire",
  travail_en_pause: "Travail en pause à la base",
  travail_trop_court: "Trop court pour compter", sans_mesure: "Pas de mesure",
  desactivee: "Inscription automatique coupée", erreur: "Erreur d'inscription",
};

const FINS_DE_PASSE = {
  batterie_vide: "batterie vide", rappelee: "rappelée", retour_autonome: "rentrée toute seule",
  terminee: "travail fini", hors_coordination: "hors coordination",
};

const ETATS_INTERVENTION = {
  recommande: "Conseillé", recommended: "Conseillé", preparation: "À préparer", possible: "À préparer",
  blocked: "Bloqué", bloque: "Bloqué", unavailable: "Indisponible",
};

const SOURCES_ARROSAGE = {
  auto_irrigation: "Automatique", manual_irrigation: "Lancé à la main", zone_session: "Vanne ouverte à la main",
  rafraichissement_soir: "Rafraîchissement du soir", application_technique_auto: "Après un produit",
  manual_force: "Forcé à la main", service: "Déclaré",
};

const CAUSES_ARROSAGE = {
  hydrique: "soif du sol", rafraichissement_soir: "fraîcheur du soir",
  post_application: "incorporation du produit", arret_manuel: "arrêté à la main",
};

// Conditions de `weather.*` (Home Assistant), avec un mot simple pour chacune.
const METEOS = {
  sunny: ["mdi:weather-sunny", "Ensoleillé"],
  "clear-night": ["mdi:weather-night", "Nuit claire"],
  partlycloudy: ["mdi:weather-partly-cloudy", "Éclaircies"],
  cloudy: ["mdi:weather-cloudy", "Nuageux"],
  fog: ["mdi:weather-fog", "Brouillard"],
  rainy: ["mdi:weather-rainy", "Pluie"],
  pouring: ["mdi:weather-pouring", "Averses"],
  "snowy-rainy": ["mdi:weather-snowy-rainy", "Pluie et neige"],
  snowy: ["mdi:weather-snowy", "Neige"],
  hail: ["mdi:weather-hail", "Grêle"],
  lightning: ["mdi:weather-lightning", "Orage"],
  "lightning-rainy": ["mdi:weather-lightning-rainy", "Orage et pluie"],
  windy: ["mdi:weather-windy", "Venteux"],
  "windy-variant": ["mdi:weather-windy-variant", "Venteux"],
  exceptional: ["mdi:alert-circle-outline", "Exceptionnel"],
};

// Les modes du sélecteur « Mode du gazon », expliqués simplement.
// Volontairement sobres : le détail de chaque mode vit dans le moteur, pas ici.
const MODES = {
  Normal: "L'entretien de tous les jours.",
  Semis: "Semis sur terrain nu après un travail complet du sol : les graines sont arrosées plusieurs fois par jour et la tondeuse attend.",
  Sursemis: "Sursemis dans un gazon en place, scarification incluse : les graines sont arrosées souvent, puis la tonte reprend progressivement après la levée.",
  Traitement: "Un traitement vient d'être appliqué au gazon.",
  Fertilisation: "Un engrais vient d'être appliqué.",
  Biostimulant: "Un biostimulant vient d'être appliqué.",
  "Agent Mouillant": "Un agent mouillant vient d'être appliqué.",
  Scarification: "Le gazon vient d'être scarifié sans semis ni sursemis.",
  Hivernage: "Le gazon se repose pour l'hiver.",
};

const ICONES_MODES = {
  Normal: "mdi:grass",
  Semis: "mdi:seed-outline",
  Sursemis: "mdi:sprout-outline",
  Traitement: "mdi:shield-outline",
  Fertilisation: "mdi:flask-outline",
  Biostimulant: "mdi:leaf-circle-outline",
  "Agent Mouillant": "mdi:water-plus-outline",
  Scarification: "mdi:rake",
  Hivernage: "mdi:snowflake",
};

// ─── Petits outils ───────────────────────────────────────────────────────────────────────

function esc(texte) {
  return String(texte ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function decimalesDe(x) {
  const s = String(x);
  const i = s.indexOf(".");
  return i < 0 ? 0 : s.length - i - 1;
}

function nombreFr(x, decimales = 2) {
  return Number(x).toLocaleString("fr-FR", { maximumFractionDigits: decimales });
}

const deuxChiffres = (n) => String(n).padStart(2, "0");

function heureFr(minutes) {
  const m = ((Math.round(minutes) % 1440) + 1440) % 1440;
  return `${Math.floor(m / 60)}\u00a0h\u00a0${deuxChiffres(m % 60)}`;
}

function heurePourChamp(minutes) {
  const m = ((Math.round(minutes) % 1440) + 1440) % 1440;
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

function minuteDepuisChamp(texte) {
  const morceaux = String(texte || "").match(/^(\d{2}):(\d{2})$/);
  if (!morceaux) return null;
  const heure = Number(morceaux[1]);
  const minute = Number(morceaux[2]);
  return heure < 24 && minute < 60 ? heure * 60 + minute : null;
}

function dureeFr(minutes) {
  // Certains d\u00e9lais (garage de la tondeuse) se r\u00e8glent au quart de minute : arrondir \u00e0 la
  // minute effacerait ces secondes plut\u00f4t que de les afficher.
  const secondesTotales = Math.round(minutes * 60);
  const m = Math.floor(secondesTotales / 60);
  const s = secondesTotales % 60;
  if (m < 60) {
    if (!s) return `${m}\u00a0min`;
    return m ? `${m}\u00a0min\u00a0${s}\u00a0s` : `${s}\u00a0s`;
  }
  const h = Math.floor(m / 60);
  const reste = m % 60;
  return reste ? `${h}\u00a0h\u00a0${deuxChiffres(reste)}` : `${h}\u00a0h`;
}

const UNITES_AU_PLURIEL = new Set(["jours", "tontes", "coupes"]);

function uniteAccordee(unite, valeur) {
  return UNITES_AU_PLURIEL.has(unite) && Math.abs(valeur) < 2 ? unite.slice(0, -1) : unite;
}

function valeurFr(r, v) {
  if (v === undefined || v === null || Number.isNaN(v)) return "—";
  if (r.genre === "heure") return heureFr(v);
  if (r.genre === "duree") return dureeFr(v);
  if (r.genre === "jour") return `jour ${Math.round(v)}`;
  const n = nombreFr(v, Math.max(decimalesDe(r.pas), 0));
  if (r.unite === "×") return `${n}\u00a0×`;
  return r.unite ? `${n}\u00a0${uniteAccordee(r.unite, v)}` : n;
}

// Espace INSÉCABLE avant l'unité : « 10 h 00 » ou « 5,3 mm » ne se coupent pas en fin de ligne.
const cmFr = (x) => `${nombreFr(x, 1)}\u00a0cm`;
const mmFr = (x) => `${nombreFr(x, 1)}\u00a0mm`;
const ordinal = (n) => (n === 1 ? "1ʳᵉ" : `${n}ᵉ`);
const ordinalM = (n) => (n === 1 ? "1ᵉʳ" : `${n}ᵉ`);

function caler(r, v) {
  const d = Math.max(decimalesDe(r.pas), decimalesDe(r.minimum));
  const crans = Math.round((v - r.minimum) / r.pas);
  const x = Number((r.minimum + crans * r.pas).toFixed(d));
  return Math.min(r.maximum, Math.max(r.minimum, x));
}

function egal(a, b) {
  if (Array.isArray(a) || Array.isArray(b)) {
    return Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((x, i) => egal(x, b[i]));
  }
  return typeof a === "number" && typeof b === "number" ? Math.abs(a - b) < 1e-9 : a === b;
}

const copie = (v) => (Array.isArray(v) ? [...v] : v);
const pourcent = (x, min, max) => Math.min(100, Math.max(0, ((x - min) / (max - min)) * 100));

function partiesLocales(date, fuseau) {
  const format = new Intl.DateTimeFormat("fr-FR", {
    timeZone: fuseau || undefined,
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  });
  const p = {};
  for (const part of format.formatToParts(date)) p[part.type] = part.value;
  return {
    annee: Number(p.year), mois: Number(p.month), jour: Number(p.day),
    minute: (Number(p.hour) % 24) * 60 + Number(p.minute),
  };
}

function jourPlus(base, jours, options = { weekday: "short", day: "numeric", month: "short" }) {
  const d = new Date(Date.UTC(base.annee, base.mois - 1, base.jour + jours));
  return d.toLocaleDateString("fr-FR", { timeZone: "UTC", ...options });
}

// Jour calendaire d'une valeur de l'intégration : « 2026-09-18 », « 18/09/2026 » ou un instant ISO
// (lu dans le fuseau de Home Assistant). Rend {annee, mois, jour} ou null.
function jourDe(brut, fuseau) {
  if (brut === undefined || brut === null || brut === "") return null;
  const s = String(brut).trim();
  let m = s.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (m) return { annee: Number(m[1]), mois: Number(m[2]), jour: Number(m[3]) };
  m = s.match(/^(\d{2})\/(\d{2})\/(\d{4})/);
  if (m) return { annee: Number(m[3]), mois: Number(m[2]), jour: Number(m[1]) };
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return null;
  const p = partiesLocales(d, fuseau);
  return { annee: p.annee, mois: p.mois, jour: p.jour };
}

// En JOURS CALENDAIRES : un jour de changement d'heure dure 23 ou 25 h (piège vu sur la carte).
function ecartJours(de, a) {
  return Math.round((Date.UTC(a.annee, a.mois - 1, a.jour) - Date.UTC(de.annee, de.mois - 1, de.jour)) / 86400000);
}

function dateHumaine(brut, aujourdHui, fuseau) {
  const j = jourDe(brut, fuseau);
  if (!j) return "—";
  const n = ecartJours(aujourdHui, j);
  if (n === 0) return "aujourd'hui";
  if (n === 1) return "demain";
  if (n === -1) return "hier";
  if (n === 2) return "après-demain";
  return jourPlus(j, 0, { weekday: "long", day: "numeric", month: "long" });
}

function isoDuJour(j) {
  return `${j.annee}-${deuxChiffres(j.mois)}-${deuxChiffres(j.jour)}`;
}

const majuscule = (t) => {
  const s = String(t ?? "").trim();
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : "";
};
const minuscule = (t) => {
  const s = String(t ?? "").trim();
  return s ? s.charAt(0).toLowerCase() + s.slice(1) : "";
};
// Première phrase d'un motif. Coupe sur un point SUIVI D'UNE ESPACE : « 32.0 °C » reste entier.
const premierePhrase = (t) => String(t ?? "").split(/\.\s/)[0].replace(/\.$/, "").trim();
const nombreOuNul = (v) => {
  const n = Number.parseFloat(v);
  return Number.isFinite(n) ? n : null;
};
const libelleDe = (table, cle) => table[cle] || majuscule(String(cle ?? "").replace(/_/g, " ")) || "—";

// Chronomètre « 12:05 » (minutes:secondes), ou « 1 h 12 » au-delà d'une heure.
function chronoFr(ms) {
  const total = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h ? `${h}\u00a0h\u00a0${deuxChiffres(m)}` : `${deuxChiffres(m)}:${deuxChiffres(s)}`;
}

// « 22 min 30 » : une durée d'arrosage à la seconde près, comme le moteur l'écrit.
function dureeSecondesFr(secondes) {
  const s = Math.max(0, Math.round(secondes));
  const reste = s % 60;
  if (!reste || s >= 3600) return dureeFr(s / 60);
  const m = Math.floor(s / 60);
  return m ? `${m} min ${deuxChiffres(reste)}` : `${reste} s`;
}

// Formes d'erreur de Home Assistant : refus `{ code, message }`, connexion perdue
// `{ error: { code, message } }`.
function erreurLisible(e) {
  if (!e) return "erreur inconnue";
  // Une connexion déjà fermée au moment du clic rejette avec le nombre 3, tout seul.
  if (e === 3) return "la connexion avec Home Assistant est perdue";
  return e.message || e.error?.message || e.code || String(e);
}

// ─── Le plan d'arrosage, construit comme le moteur ───────────────────────────────────────
// Copie de `build_watering_plan` et de `WateringPlan.zone_for_passage` (watering_plan.py) :
// chaque zone reçoit la dose entière, sa durée est arrondie à la demi-minute (entre 30 s et
// 3 h), puis partagée entre les passages. `tests/test_panneau_plan.py` la compare au moteur.

const DUREE_ZONE_MIN_MIN = 0.5;
const DUREE_ZONE_MAX_MIN = 180;
const PAS_DUREE_ZONE_MIN = 0.5;

// Le `round()` de Python : une moitié exacte va vers le nombre pair.
function arrondiPython(x) {
  const bas = Math.floor(x);
  const reste = x - bas;
  if (reste !== 0.5) return reste > 0.5 ? bas + 1 : bas;
  return bas % 2 === 0 ? bas : bas + 1;
}

// `zones` : [{ …, debit }] dans l'ordre du moteur. `null` sans dose ou sans zone utilisable.
function planArrosage(mm, zones, passages = 1, pauseS = 0) {
  if (!(mm > 0)) return null;
  const retenues = [];
  for (const z of zones) {
    if (!(z.debit > 0)) continue;
    const brute = (mm / z.debit) * 60.0;
    if (!(brute > 0)) continue;
    const arrondie = Math.min(DUREE_ZONE_MAX_MIN, Math.max(DUREE_ZONE_MIN_MIN, arrondiPython(brute / PAS_DUREE_ZONE_MIN) * PAS_DUREE_ZONE_MIN));
    const secondes = arrondiPython(arrondie * 60.0);
    if (secondes > 0) retenues.push({ ...z, secondes });
  }
  return retenues.length ? planDepuisZones(retenues, passages, pauseS) : null;
}

// Les étapes dans l'ordre : chaque passage fait toutes les zones, une pause sépare deux passages.
function planDepuisZones(zones, passages, pauseS) {
  const n = Math.max(1, Math.floor(Number(passages)) || 1);
  const pause = n > 1 ? Math.max(0, Math.floor(Number(pauseS)) || 0) : 0;
  const etapes = [];
  for (let p = 1; p <= n; p++) {
    for (const z of zones) {
      const secondes = Math.floor(z.secondes / n) + (p <= z.secondes % n ? 1 : 0);
      if (secondes > 0) etapes.push({ genre: "zone", passage: p, zone: z, secondes });
    }
    if (p < n && pause > 0) etapes.push({ genre: "pause", passage: p, secondes: pause });
  }
  const eauS = zones.reduce((s, z) => s + z.secondes, 0);
  return { zones, passages: n, pauseS: pause, etapes, eauS, totalS: eauS + pause * (n - 1) };
}

// ─── Le moteur en miniature (pour les dessins) ───────────────────────────────────────────

function classeTonte(min, v, soleil) {
  const nuit = soleil
    ? min < soleil.lever || min >= soleil.coucher + v.tonte_soir_apres_coucher
    : min < 7 * 60 || min >= 22 * 60;
  if (nuit) return "nuit";
  if (min < v.tonte_fenetre_ideale_debut) return "tot";
  if (min < v.tonte_fenetre_ideale_fin) return "ideal";
  const soirDebut = soleil ? soleil.coucher - v.tonte_soir_avant_coucher : 17 * 60;
  const soirFin = soleil ? soleil.coucher + v.tonte_soir_apres_coucher : 19 * 60;
  if (min >= soirDebut && min < soirFin) return "possible";
  if (min < 22 * 60) return "eviter";
  return "nuit";
}

function classeMatin(min, v) {
  if (min < v.arrosage_ouverture) return "tot";
  if (min < v.arrosage_fin_optimale) return "ideal";
  if (min < v.arrosage_fin_acceptable) return "possible";
  return "tard";
}

const PLAFOND_GRAINES_CERTAINS_JOURS = 16 * 60;

function classeGraines(min, v) {
  if (min < v.graines_fenetre_debut) return "tot";
  if (min >= v.graines_fenetre_fin) return "soir";
  if (min >= PLAFOND_GRAINES_CERTAINS_JOURS) return "parfois";
  return "ouvert";
}

function repartirCreneauxGraines(v, cycles, minimum = 120) {
  const nombre = Math.max(1, Math.floor(Number(cycles)) || 1);
  const debut = Math.floor(Number(v.graines_fenetre_debut));
  const fin = Math.floor(Number(v.graines_fenetre_fin));
  if (!Number.isFinite(debut) || !Number.isFinite(fin) || nombre === 1) return [debut];
  const dernier = Math.max(fin - 60, debut + Math.max(1, minimum) * (nombre - 1));
  if (dernier >= fin) {
    return Array.from({ length: nombre }, (_, i) => debut + i * Math.max(1, minimum))
      .filter((minute) => minute < fin);
  }
  return Array.from(
    { length: nombre },
    (_, i) => debut + Math.round(i * (dernier - debut) / (nombre - 1)),
  );
}

// Range les étiquettes d'une frise : une étiquette près d'un bord s'aligne sur son repère au lieu
// de déborder, et deux étiquettes qui se toucheraient passent sur deux rangées. La largeur d'une
// étiquette est ESTIMÉE (12 px, demi-gras ≈ 6,8 px par caractère) : sans mesure, rien ne bouge
// après l'affichage.
function rangerEtiquettes(items, largeurPx) {
  const finsDeRangee = [];
  for (const it of [...items].sort((a, b) => a.p - b.p)) {
    const largeur = 16 + (it.icone ? 19 : 0) + String(it.texte).length * 6.8;
    const x = (it.p / 100) * largeurPx;
    let gauche = x - largeur / 2;
    it.cote = "";
    if (gauche < 0) {
      it.cote = "gauche";
      gauche = x;
    } else if (x + largeur / 2 > largeurPx) {
      it.cote = "droite";
      gauche = x - largeur;
    }
    let rang = finsDeRangee.findIndex((fin) => gauche >= fin + 6);
    if (rang < 0) {
      rang = finsDeRangee.length;
      finsDeRangee.push(0);
    }
    finsDeRangee[rang] = gauche + largeur;
    it.rang = rang;
  }
  return finsDeRangee.length;
}

function segmenter(classer, debut, fin) {
  const segments = [];
  for (let m = debut; m < fin; m += 1) {
    const c = classer(m);
    const dernier = segments[segments.length - 1];
    if (dernier && dernier.classe === c) dernier.fin = m + 1;
    else segments.push({ classe: c, debut: m, fin: m + 1 });
  }
  return segments;
}

function joursAvantPremiereCoupe(v) {
  const hauteur = v.sursemis_premiere_coupe * v.sursemis_lame;
  return v.sursemis_levee + Math.ceil(Number((hauteur / v.sursemis_pousse_plantules).toFixed(6)));
}

function etapesGraines(v) {
  return [
    { nom: "Germination", de: 0, a: v.graines_fin_germination, teinte: "germe", icone: "mdi:seed-outline", phrase: "la graine se réveille" },
    { nom: "Enracinement", de: v.graines_fin_germination + 1, a: v.graines_fin_enracinement, teinte: "racine", icone: "mdi:sprout-outline", phrase: "les racines descendent" },
    { nom: "Reprise", de: v.graines_fin_enracinement + 1, a: v.graines_fin_reprise, teinte: "pousse", icone: "mdi:sprout", phrase: "le jeune gazon se renforce" },
    { nom: "Stabilisation", de: v.graines_fin_reprise + 1, a: v.graines_duree - 1, teinte: "gazon", icone: "mdi:grass", phrase: "il devient un vrai gazon" },
  ];
}

// ─── Changer une entrée (0.95.0) ─────────────────────────────────────────────────────────
// Les mêmes règles que `sources.refus` (un test les compare), sur la ligne `sources` du serveur :
// le domaine, une unité que le moteur lit ou convertit, jamais une température pour la rosée.
// Le serveur revérifie tout, et refuse en plus ce qui vient de Gazon Intelligent.

function entreeAcceptee(source, entityId, attributs = {}, etat = undefined) {
  if (String(entityId).split(".")[0] !== source.domaine) return false;
  const bas = (v) => String(v ?? "").trim().toLowerCase();
  const unite = bas(attributs.unit_of_measurement);
  const genre = bas(attributs.device_class);
  const unites = (source.unites || []).map(bas);
  if ((source.unites_refusees || []).map(bas).includes(unite)) return false;
  if ((source.classes_refusees || []).includes(genre)) return false;
  if (genre && (source.classes || []).length && !source.classes.includes(genre)) return false;
  if ((source.classes_etat_refusees || []).includes(bas(attributs.state_class))) return false;
  if (!unite ? !(source.sans_unite || !unites.length) : unites.length && !unites.includes(unite)) return false;
  // Conversion stricte, comme `float()` : « 3 mm » ou « Pas de pluie » ne sont pas des nombres.
  const valeur = String(etat ?? "").trim();
  if (source.numerique && !ETATS_SANS_VALEUR.has(valeur.toLowerCase()) && Number.isNaN(Number(valeur))) return false;
  const nom = (t) => sansAccents(t).replace(/-/g, " ").trim().split(/\s+/).join("_");
  const [nomEntite, nomAffiche] = [nom(entityId), nom(attributs.friendly_name)];
  const annonce = (source.indices || []).some((i) => nomEntite.includes(i) || nomAffiche.includes(i));
  if (source.exige_indice && !annonce) return false;
  if (source.indice_sans_classe && !genre && !annonce) return false;
  const mots = new Set([...nomEntite.split(/[._]/), ...nomAffiche.split("_")]);
  return !(source.noms_refuses || []).some((m) => mots.has(m));
}

// Ce que le moteur ignore quoi qu'il arrive (`sources.interdit`) : un point de rosée pour la rosée.
function lectureInterdite(source, attributs = {}) {
  const bas = (v) => String(v ?? "").trim().toLowerCase();
  return (source?.unites_refusees || []).map(bas).includes(bas(attributs.unit_of_measurement))
    || (source?.classes_refusees || []).includes(bas(attributs.device_class));
}

// Les entités qui peuvent tenir le rôle : celles des appareils déjà branchés d'abord, celles dont
// le nom annonce le rôle ensuite, puis les autres, par nom.
function candidatsEntree(source, etats, { propres = new Set(), appareils = new Map() } = {}) {
  const liste = [];
  for (const [id, etat] of Object.entries(etats || {})) {
    if (propres.has(id) || id.split(".")[1]?.startsWith("gazon_intelligent_")) continue;
    if (!entreeAcceptee(source, id, etat?.attributes || {}, etat?.state)) continue;
    const appareilBrut = appareils.get(id);
    const appareil = typeof appareilBrut === "string" ? appareilBrut : appareilBrut?.nom || null;
    liste.push({
      id,
      nom: String(etat?.attributes?.friendly_name || id),
      appareil,
      stationPersonnelle: Boolean(appareilBrut && typeof appareilBrut === "object" && appareilBrut.stationPersonnelle),
      indice: (source.indices || []).some((i) => `${id} ${etat?.attributes?.friendly_name || ""}`.toLowerCase().includes(i)),
    });
  }
  const rang = (c) => (c.stationPersonnelle ? 0 : c.appareil ? 2 : 4) + (c.indice ? 0 : 1);
  return liste.sort((a, b) => rang(a) - rang(b) || a.nom.localeCompare(b.nom, "fr"));
}

const sansAccents = (t) => String(t ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();

// Au-delà, la liste se parcourt mal : la recherche prend le relais.
const CANDIDATS_MONTRES = 60;

// ─── Validation (même règles que `reglages.valider`, le serveur revérifie) ─────────────

function surLePas(r, x) {
  const crans = (x - r.minimum) / r.pas;
  return Math.abs(crans - Math.round(crans)) < 1e-6;
}

function valider(registre, valeurs) {
  const erreurs = {};
  const fr = (x) => nombreFr(x, 3);
  for (const r of registre.reglages) {
    const v = valeurs[r.cle];
    if (r.genre === "interrupteur") {
      if (typeof v !== "boolean") erreurs[r.cle] = "Sélectionner activé ou désactivé.";
      continue;
    }
    const nombres = r.genre === "table_mois" ? (Array.isArray(v) && v.length === 12 ? v : null) : [v];
    if (!nombres || !nombres.every((x) => typeof x === "number" && Number.isFinite(x))) {
      erreurs[r.cle] = r.genre === "table_mois" ? "Il faut un nombre pour chaque mois." : "Il faut un nombre.";
    } else if (!nombres.every((x) => x >= r.minimum && x <= r.maximum)) {
      erreurs[r.cle] = `Sélectionner une valeur entre ${fr(r.minimum)} et ${fr(r.maximum)}.`;
    } else if (!nombres.every((x) => surLePas(r, x))) {
      erreurs[r.cle] = `La valeur avance de ${fr(r.pas)} en ${fr(r.pas)}.`;
    }
  }
  const affichees = { ...erreurs };
  for (const c of registre.contraintes) {
    if (erreurs[c.gauche] || erreurs[c.droite]) continue;
    const g = valeurs[c.gauche];
    const d = valeurs[c.droite];
    if (g > d || (c.stricte && egal(g, d))) {
      erreurs[c.gauche] = erreurs[c.gauche] || c.message;
      // Affichée des DEUX côtés : on a souvent bougé l'autre curseur.
      affichees[c.gauche] = affichees[c.gauche] || c.message;
      affichees[c.droite] = affichees[c.droite] || c.message;
    }
  }
  return { erreurs, affichees };
}

// ─── Styles ──────────────────────────────────────────────────────────────────────────────

const STYLES = `
:host {
  display: block;
  position: relative;
  height: 100%;
  --gz-accent: var(--gazon-accent, #10b981);
  --gz-accent-fort: #059669;
  --gz-accent-doux: color-mix(in srgb, var(--gz-accent) 14%, transparent);
  --gz-eau: #3b82f6;
  --gz-eau-doux: color-mix(in srgb, var(--gz-eau) 32%, var(--gz-carte));
  --gz-ambre: #f59e0b;
  --gz-rouge: #ef4444;
  --gz-froid: #60a5fa;
  --gz-nuit: #334155;
  --gz-germe: #eab308;
  --gz-racine: #a16207;
  --gz-pousse: #4ade80;
  --gz-produit: #8b5cf6;
  --gz-fond: var(--primary-background-color, #fafafa);
  --gz-carte: var(--ha-card-background, var(--card-background-color, #fff));
  --gz-surface: var(--secondary-background-color, #f3f4f6);
  --gz-texte: var(--primary-text-color, #111827);
  --gz-doux: var(--secondary-text-color, #6b7280);
  --gz-trait: var(--divider-color, rgba(0, 0, 0, 0.1));
  --gz-piste: color-mix(in srgb, var(--gz-texte) 12%, transparent);
  --gz-gris: color-mix(in srgb, var(--gz-texte) 16%, var(--gz-carte));
  --gz-rayon: var(--ha-card-border-radius, 20px);
  color: var(--gz-texte);
  background: var(--gz-fond);
  font-family: var(--ha-font-family-body, var(--mdc-typography-font-family, Roboto, -apple-system, "Segoe UI", sans-serif));
  -webkit-font-smoothing: antialiased;
}
:host([sombre]) {
  --gz-nuit: #475569;
  --gz-racine: #ca8a04;
}
* { box-sizing: border-box; }
[hidden] { display: none !important; }
button { font: inherit; color: inherit; }
ha-icon { --mdc-icon-size: 20px; display: inline-flex; width: var(--mdc-icon-size); height: var(--mdc-icon-size); flex: none; }

/* La mise en page suit la largeur de la PAGE, pas celle de la fenêtre : dans Home Assistant, la
   barre latérale en prend une partie. D'où les requêtes de conteneur plutôt que @media. */
.page { height: 100%; overflow-y: auto; overscroll-behavior: contain; container: page / inline-size; }

/* ── Barre du haut ── */
.barre {
  position: sticky; top: 0; z-index: 5;
  height: var(--header-height, 56px);
  display: flex; align-items: center; gap: 4px;
  padding: 0 8px 0 4px;
  background: var(--app-header-background-color, var(--gz-fond));
  color: var(--app-header-text-color, var(--gz-texte));
  border-bottom: var(--app-header-border-bottom, 1px solid var(--gz-trait));
}
.barre h1 { margin: 0 0 0 8px; font-size: 20px; font-weight: 500; flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bouton-rond {
  width: 44px; height: 44px; border-radius: 50%; border: none; background: none;
  display: inline-flex; align-items: center; justify-content: center; cursor: pointer;
  --mdc-icon-size: 24px;
}
.bouton-rond:hover { background: var(--gz-piste); }
.bouton-rond:active { background: color-mix(in srgb, var(--gz-texte) 22%, transparent); }
.choix-instance {
  font: inherit; font-size: 14px; color: inherit; background: var(--gz-surface);
  border: 1px solid var(--gz-trait); border-radius: 10px; padding: 6px 8px; max-width: 45vw;
}

/* ── Contenu ── */
/* PLEINE LARGEUR (16/09/2026) : sur un grand écran, la page prend toute la largeur et range
   ses blocs en colonnes plutôt que de s'étirer vers le bas. */
.contenu { padding: 16px 24px 120px; display: flex; flex-direction: column; gap: 16px; }
/* LA MOSAÏQUE (16/09/2026, sur demande : « adapte la taille de chaque cadre, ils sont tous à la même
   dimension »). Douze colonnes. Chaque cadre prend un COULOIR choisi pour son contenu : une jauge
   reste étroite, une frise s'étale. Sa hauteur est mesurée et convertie en rangées de 4 px, si bien
   que les cadres d'un même couloir s'empilent sans trou. Sur téléphone, tout s'empile dans l'ordre. */
.mosaique { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); grid-auto-rows: 4px; grid-auto-flow: row dense; column-gap: 16px; align-items: start; }
.mosaique > .tesselle { grid-column: 1 / -1; min-width: 0; display: flex; flex-direction: column; gap: 16px; }

.accueil {
  background: var(--gz-carte); border-radius: var(--gz-rayon);
  padding: 20px; display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 0 16px; align-items: start;
  border: 1px solid var(--gz-trait);
}
.accueil > .puces { grid-column: 2; }
.accueil-icone {
  width: 52px; height: 52px; border-radius: 16px; flex: none;
  background: var(--gz-accent-doux); color: var(--gz-accent-fort);
  display: flex; align-items: center; justify-content: center; --mdc-icon-size: 30px;
}
:host([sombre]) .accueil-icone { color: var(--gz-accent); }
.accueil h2 { margin: 0 0 4px; font-size: 19px; font-weight: 600; text-wrap: balance; }
.accueil p { margin: 0; color: var(--gz-doux); font-size: 14.5px; line-height: 1.5; max-width: 62ch; }
.puces { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.puce {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 5px 10px; border-radius: 999px; font-size: 13px;
  background: var(--gz-surface); --mdc-icon-size: 16px;
}
.puce b { font-weight: 600; }
.puce.accent { background: var(--gz-accent-doux); }

/* ── Recherche des réglages (tous onglets confondus) ── */
.recherche-reglages {
  position: relative; display: flex; align-items: center; gap: 10px;
  background: var(--gz-carte); border: 1px solid var(--gz-trait); border-radius: var(--gz-rayon);
  padding: 10px 16px; color: var(--gz-doux); --mdc-icon-size: 20px;
}
.recherche-reglages input {
  flex: 1; min-width: 0; border: none; background: none; outline: none;
  font: inherit; font-size: 15px; color: var(--gz-texte);
}
.recherche-reglages input::placeholder { color: var(--gz-doux); }
.recherche-resultats {
  position: absolute; left: 0; right: 0; top: calc(100% + 6px); z-index: 5;
  background: var(--gz-carte); border: 1px solid var(--gz-trait); border-radius: 14px;
  box-shadow: 0 10px 28px -10px rgba(0, 0, 0, .25); max-height: min(60vh, 420px); overflow-y: auto;
}
.recherche-resultats:empty { display: none; border: none; box-shadow: none; }
.resultat-recherche {
  display: flex; flex-direction: column; gap: 2px; width: 100%; text-align: left;
  padding: 10px 16px; border: none; border-top: 1px solid var(--gz-trait); background: none;
  font: inherit; color: var(--gz-texte); cursor: pointer;
}
.resultat-recherche:first-child { border-top: none; }
.resultat-recherche:hover, .resultat-recherche:focus-visible { background: var(--gz-surface); }
.resultat-titre { font-weight: 600; font-size: 14.5px; }
.resultat-chemin {
  display: flex; align-items: center; gap: 4px; font-size: 12.5px; color: var(--gz-doux);
  --mdc-icon-size: 14px;
}
.recherche-resultats p.vide { margin: 0; padding: 10px 16px; font-size: 13px; color: var(--gz-doux); }

/* ── Onglets ── */
.onglets {
  display: flex; gap: 6px; overflow-x: auto; scrollbar-width: none;
  scroll-snap-type: x proximity; padding: 2px;
  position: sticky; top: var(--header-height, 56px); z-index: 4;
  background: var(--gz-fond); margin: 0 -24px; padding: 8px 24px;
}
.onglets::-webkit-scrollbar { display: none; }
.onglet {
  scroll-snap-align: start; flex: none;
  display: inline-flex; align-items: center; gap: 8px;
  padding: 10px 14px; border-radius: 14px; border: 1px solid var(--gz-trait);
  background: var(--gz-carte); color: var(--gz-doux);
  cursor: pointer; font-size: 14.5px; font-weight: 500; position: relative;
  transition: background .15s, color .15s, border-color .15s;
}
.onglet:hover { color: var(--gz-texte); }
.onglet:active { background: var(--gz-surface); }
.onglet[aria-selected="true"] { background: var(--gz-accent); border-color: var(--gz-accent); color: #fff; }
.onglet[aria-selected="true"]:active { background: var(--gz-accent-fort); }
.onglet .compteur {
  min-width: 20px; height: 20px; padding: 0 6px; border-radius: 999px;
  background: var(--gz-ambre); color: #1f2937; font-size: 12px; font-weight: 700;
  display: inline-flex; align-items: center; justify-content: center;
}

.intro-onglet { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.intro-onglet p { margin: 0; color: var(--gz-doux); font-size: 14.5px; }
.bouton-texte {
  border: none; background: none; cursor: pointer; color: var(--gz-accent-fort);
  font-weight: 600; font-size: 14px; padding: 8px 10px; border-radius: 10px;
  display: inline-flex; align-items: center; gap: 6px; --mdc-icon-size: 18px;
}
:host([sombre]) .bouton-texte { color: var(--gz-accent); }
.bouton-texte:hover { background: var(--gz-accent-doux); }
.bouton-texte:active { background: color-mix(in srgb, var(--gz-accent) 26%, transparent); }
.bouton-texte[disabled] { color: var(--gz-doux); cursor: default; background: none; }

/* ── Sections ── */
.section { background: var(--gz-carte); border-radius: var(--gz-rayon); border: 1px solid var(--gz-trait); overflow: hidden; container-type: inline-size; }
/* Une carte ÉTROITE (colonne d'un portable) : moins de graduations, noms de zone plus courts. */
@container (max-width: 440px) {
  .frise-ligne, .frise-heures { grid-template-columns: 84px minmax(0, 1fr); }
  .frise-heures .graduations span:nth-child(2n) { visibility: hidden; }
}
.section-tete { padding: 18px 20px 4px; }
.section-tete h3 { margin: 0; font-size: 18px; font-weight: 600; text-wrap: balance; }
.section-tete p { margin: 4px 0 0; color: var(--gz-doux); font-size: 14px; line-height: 1.45; max-width: 64ch; }

/* ── Groupes de l'onglet « Installation » : un repère avant chaque paquet de cartes ── */
.groupe-installation { display: flex; align-items: center; gap: 8px; padding: 10px 4px 0; --mdc-icon-size: 18px; color: var(--gz-accent-fort); }
.groupe-installation h2 { margin: 0; font: inherit; font-size: 13px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; }
:host([sombre]) .groupe-installation { color: var(--gz-accent); }
.dessin { padding: 12px 20px 4px; }
.lignes { display: flex; flex-direction: column; }

/* ── Une ligne de réglage ── */
.ligne { padding: 16px 20px 14px; border-top: 1px solid var(--gz-trait); position: relative; }
.ligne:first-child { border-top: none; }
.dessin + .lignes .ligne:first-child { border-top: 1px solid var(--gz-trait); margin-top: 12px; }
.ligne-tete { display: flex; gap: 12px; align-items: flex-start; }
.ligne-icone {
  width: 36px; height: 36px; border-radius: 12px; flex: none;
  display: flex; align-items: center; justify-content: center;
  background: var(--gz-surface); color: var(--gz-doux);
}
.ligne-textes { flex: 1; min-width: 0; }
.ligne-textes h4 { margin: 1px 0 3px; font-size: 16px; font-weight: 600; line-height: 1.35; }
.ligne-textes p { margin: 0; color: var(--gz-doux); font-size: 13.5px; line-height: 1.45; }
.bulle {
  flex: none; min-width: 76px; text-align: center;
  padding: 6px 12px; border-radius: 12px;
  background: var(--gz-accent-doux); color: var(--gz-texte);
  font-size: 18px; font-weight: 700; font-variant-numeric: tabular-nums; white-space: nowrap;
}
.ligne.change .bulle { background: color-mix(in srgb, var(--gz-ambre) 22%, transparent); }
/* La valeur se lit au bout du curseur : la question garde toute la largeur (moins de lignes, page
   moins longue). Sur un téléphone, elle remonte à côté de la question pour laisser le curseur long. */
.ligne { --bulle: 104px; }
.bulle-haut { display: none; }
.bulle-bas { min-width: 94px; }
.reglette { display: flex; align-items: center; gap: 10px; margin-top: 8px; }
.pas-btn {
  width: 40px; height: 40px; border-radius: 50%; flex: none;
  border: 1px solid var(--gz-trait); background: var(--gz-surface);
  font-size: 22px; line-height: 1; cursor: pointer;
  display: inline-flex; align-items: center; justify-content: center;
  touch-action: manipulation; --mdc-icon-size: 20px;
}
.pas-btn:hover { border-color: var(--gz-accent); }
.pas-btn:active { background: var(--gz-accent); color: #fff; border-color: var(--gz-accent); }
.pas-btn[disabled] { opacity: .35; cursor: default; background: var(--gz-surface); color: inherit; }
.curseur-zone { position: relative; flex: 1; min-width: 0; height: 40px; }
.marque-conseil {
  position: absolute; top: 2px; width: 2px; height: 8px; border-radius: 2px;
  left: calc(14px + (100% - 28px) * var(--pos) / 100);
  background: var(--gz-doux); pointer-events: none; transform: translateX(-1px);
}
input[type="range"] {
  -webkit-appearance: none; appearance: none;
  position: absolute; inset: 0; width: 100%; height: 40px; margin: 0;
  background: transparent; cursor: pointer; touch-action: pan-y;
}
input[type="range"]::-webkit-slider-runnable-track {
  height: 8px; border-radius: 999px;
  background: linear-gradient(to right, var(--gz-accent) var(--rempli), var(--gz-piste) var(--rempli));
}
input[type="range"]::-webkit-slider-thumb {
  -webkit-appearance: none; width: 28px; height: 28px; margin-top: -10px; border-radius: 50%;
  background: #fff; border: 3px solid var(--gz-accent); box-shadow: 0 1px 4px rgba(0, 0, 0, .3);
}
input[type="range"]:active::-webkit-slider-thumb { background: var(--gz-accent-doux); }
input[type="range"]::-moz-range-track { height: 8px; border-radius: 999px; background: var(--gz-piste); }
input[type="range"]::-moz-range-progress { height: 8px; border-radius: 999px; background: var(--gz-accent); }
input[type="range"]::-moz-range-thumb {
  width: 22px; height: 22px; border-radius: 50%;
  background: #fff; border: 3px solid var(--gz-accent); box-shadow: 0 1px 4px rgba(0, 0, 0, .3);
}
input[type="range"]:focus { outline: none; }
input[type="range"]:focus-visible::-webkit-slider-thumb { box-shadow: 0 0 0 6px color-mix(in srgb, var(--gz-accent) 35%, transparent); }
input[type="range"]:focus-visible::-moz-range-thumb { box-shadow: 0 0 0 6px color-mix(in srgb, var(--gz-accent) 35%, transparent); }
input[type="range"][disabled] { cursor: default; opacity: .5; }
.ligne-pied {
  display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 8px;
  margin: 2px calc(50px + var(--bulle)) 0 50px; font-size: 12.5px; color: var(--gz-doux); font-variant-numeric: tabular-nums;
}
.ligne-pied .borne-max { text-align: right; }
.conseil { display: inline-flex; align-items: center; gap: 4px; --mdc-icon-size: 15px; }
.conseil button {
  border: none; cursor: pointer; border-radius: 999px; padding: 5px 11px;
  background: var(--gz-accent-doux); color: var(--gz-texte); font-size: 12.5px; font-weight: 600;
  display: inline-flex; align-items: center; gap: 5px; --mdc-icon-size: 15px;
}
.conseil button:hover { background: color-mix(in srgb, var(--gz-accent) 24%, transparent); }
.conseil button:active { background: var(--gz-accent); color: #fff; }
.a-enregistrer {
  position: absolute; top: 10px; right: 20px;
  font-size: 11px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase;
  color: #92400e; background: color-mix(in srgb, var(--gz-ambre) 26%, transparent);
  padding: 2px 8px; border-radius: 999px;
}
:host([sombre]) .a-enregistrer { color: #fcd34d; }
.ligne.change .ligne-tete { padding-top: 12px; }
.erreur {
  margin: 8px 0 0 48px; padding: 8px 12px; border-radius: 10px;
  background: color-mix(in srgb, var(--gz-rouge) 12%, transparent);
  color: var(--gz-texte); font-size: 13.5px; display: flex; gap: 8px; align-items: flex-start;
  --mdc-icon-size: 18px;
}
.erreur ha-icon { color: var(--gz-rouge); }
.ligne.en-erreur .bulle { background: color-mix(in srgb, var(--gz-rouge) 18%, transparent); }
/* Le réglage visé depuis la recherche : un bref rappel, pas une marque permanente. */
.ligne.reglage-vise, .section.reglage-vise { animation: reglage-vise 2.2s ease-out; }
@keyframes reglage-vise {
  0%, 35% { background: var(--gz-accent-doux); }
  100% { background: transparent; }
}
.avertissement-reglage {
  margin: 10px 0 0 48px; padding: 8px 12px; border-radius: 10px;
  background: color-mix(in srgb, var(--gz-ambre) 16%, transparent);
  color: var(--gz-texte); font-size: 13px; line-height: 1.4;
  display: flex; gap: 8px; align-items: flex-start; --mdc-icon-size: 18px;
}
.avertissement-reglage ha-icon { color: var(--gz-ambre); flex: none; }

/* ── Interrupteur ── */
.bascule {
  flex: none; width: 56px; height: 32px; border-radius: 999px; border: none; cursor: pointer;
  background: var(--gz-piste); position: relative; transition: background .15s;
}
.bascule::after {
  content: ""; position: absolute; top: 3px; left: 3px; width: 26px; height: 26px; border-radius: 50%;
  background: #fff; box-shadow: 0 1px 3px rgba(0, 0, 0, .3); transition: transform .15s;
}
.bascule[aria-checked="true"] { background: var(--gz-accent); }
.bascule[aria-checked="true"]::after { transform: translateX(24px); }
.bascule:active::after { width: 30px; }
.bascule:focus-visible { outline: 3px solid color-mix(in srgb, var(--gz-accent) 45%, transparent); outline-offset: 2px; }
.etat-bascule { font-size: 12.5px; color: var(--gz-doux); margin: 6px 0 0 48px; }

/* ── Frises ── */
.frise { margin-top: 4px; }
.frise-piste { position: relative; height: 44px; border-radius: 12px; overflow: hidden; background: var(--gz-gris); }
.seg {
  position: absolute; top: 0; bottom: 0; display: flex; align-items: center; justify-content: center;
  font-size: 12px; font-weight: 600; color: #fff; white-space: nowrap; overflow: hidden;
  transition: left .2s ease, width .2s ease;
}
.seg span { padding: 0 4px; overflow: hidden; text-overflow: ellipsis; }
.t-nuit { background: var(--gz-nuit); }
.t-gris { background: var(--gz-gris); color: var(--gz-texte); }
.t-vert { background: var(--gz-accent); }
.t-vert-clair { background: color-mix(in srgb, var(--gz-accent) 45%, var(--gz-carte)); color: var(--gz-texte); }
.t-ambre { background: var(--gz-ambre); color: #1f2937; }
.t-rouge { background: var(--gz-rouge); }
.t-eau { background: var(--gz-eau); }
.t-eau-clair { background: var(--gz-eau-doux); color: var(--gz-texte); }
.t-eau-raye { background: repeating-linear-gradient(135deg, var(--gz-eau) 0 6px, var(--gz-eau-doux) 6px 12px); }
.t-froid { background: var(--gz-froid); color: #0f172a; }
.t-germe { background: var(--gz-germe); color: #1f2937; }
.t-racine { background: var(--gz-racine); }
.t-pousse { background: var(--gz-pousse); color: #14532d; }
.t-gazon { background: var(--gz-accent); }
.reperes { position: relative; height: 26px; }
.reperes.haut { margin-bottom: 2px; }
.reperes.bas { margin-top: 2px; }
.repere {
  position: absolute; top: 0; transform: translateX(-50%);
  display: inline-flex; align-items: center; gap: 4px; white-space: nowrap;
  font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums;
  padding: 3px 8px; border-radius: 999px; background: var(--gz-surface);
  --mdc-icon-size: 15px;
}
.repere.gauche { transform: none; }
.repere.droite { transform: translateX(-100%); }
.repere.soleil { color: #b45309; }
:host([sombre]) .repere.soleil { color: #fbbf24; }
.repere.eau { color: var(--gz-eau); }
.repere.maintenant { background: var(--gz-texte); color: var(--gz-carte); }
.aiguille {
  position: absolute; top: 0; bottom: 0; width: 2px; margin-left: -1px; pointer-events: none;
  background: color-mix(in srgb, #fff 70%, transparent);
}
.aiguille.maintenant { background: var(--gz-texte); width: 3px; margin-left: -1.5px; }
.aiguille.soleil { background: #f59e0b; width: 3px; }
.aiguille.eau { background: var(--gz-eau); width: 3px; }
.graduations { position: relative; height: 18px; margin-top: 4px; font-size: 11.5px; color: var(--gz-doux); font-variant-numeric: tabular-nums; }
.graduations span { position: absolute; transform: translateX(-50%); white-space: nowrap; }
.graduations span:first-child { transform: none; }
.graduations span:last-child { transform: translateX(-100%); }
.legende { list-style: none; margin: 10px 0 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 6px 16px; }
.legende li { display: flex; align-items: baseline; gap: 8px; font-size: 13.5px; line-height: 1.4; }
.legende .pastille { width: 12px; height: 12px; border-radius: 4px; flex: none; transform: translateY(1px); }
.legende b { font-weight: 600; }
.legende .heures { color: var(--gz-doux); font-variant-numeric: tabular-nums; }
.note {
  margin: 10px 0 0; font-size: 13.5px; color: var(--gz-doux); line-height: 1.45;
  display: flex; gap: 8px; align-items: flex-start; --mdc-icon-size: 17px;
}
.note.alerte { color: var(--gz-texte); background: color-mix(in srgb, var(--gz-ambre) 16%, transparent); padding: 8px 12px; border-radius: 10px; }

/* ── Rythme ── */
.rythme { display: grid; grid-template-columns: repeat(14, minmax(0, 1fr)); gap: 4px; }
.jour { display: flex; flex-direction: column; align-items: center; gap: 4px; min-width: 0; }
.jour-nom { font-size: 11px; color: var(--gz-doux); white-space: nowrap; }
.jour-rond {
  width: 100%; max-width: 44px; aspect-ratio: 1; border-radius: 12px; background: var(--gz-surface);
  display: flex; align-items: center; justify-content: center; position: relative; --mdc-icon-size: 18px;
}
.jour.tonte .jour-rond { background: var(--gz-accent); color: #fff; }
.jour-rond b {
  position: absolute; right: -3px; top: -5px; font-size: 10.5px; line-height: 1;
  background: var(--gz-texte); color: var(--gz-carte); border-radius: 999px; padding: 2px 4px;
}

/* ── Hauteur par mois ── */
.mois-grille { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 6px; align-items: end; }
.mois {
  border: none; background: none; padding: 0; cursor: pointer; min-width: 0;
  display: flex; flex-direction: column; align-items: center; gap: 4px; position: relative;
}
/* La barre part de ZÉRO : 4 cm fait la moitié de 8 cm, l'écart entre les mois se voit. */
.mois-colonne {
  width: 100%; height: 150px; position: relative;
  display: flex; flex-direction: column; justify-content: flex-end; align-items: stretch;
}
.mois-valeur {
  font-size: 12px; font-weight: 700; font-variant-numeric: tabular-nums; white-space: nowrap;
  text-align: center; line-height: 18px; height: 18px;
}
.mois-barre {
  height: calc((100% - 18px) * var(--part));
  border-radius: 8px 8px 4px 4px;
  background: color-mix(in srgb, var(--gz-accent) 42%, var(--gz-carte));
  transition: height .2s ease;
}
.mois-conseil {
  position: absolute; left: -2px; right: -2px; height: 0; border-top: 2px dashed var(--gz-texte);
  bottom: calc((100% - 18px) * var(--part)); opacity: .55;
}
.mois-nom { font-size: 12px; color: var(--gz-doux); font-weight: 600; position: relative; padding-bottom: 8px; }
.mois.ce-mois .mois-nom { color: var(--gz-accent-fort); }
:host([sombre]) .mois.ce-mois .mois-nom { color: var(--gz-accent); }
.mois.ce-mois .mois-nom::after {
  content: ""; position: absolute; left: 50%; bottom: 0; transform: translateX(-50%);
  width: 6px; height: 6px; border-radius: 50%; background: var(--gz-accent);
}
.mois[aria-pressed="true"] .mois-barre { background: var(--gz-accent); }
.mois.change .mois-barre { background: var(--gz-ambre); }
.mois:focus-visible { outline: 3px solid color-mix(in srgb, var(--gz-accent) 45%, transparent); outline-offset: 2px; border-radius: 8px; }
.mois-editeur {
  margin-top: 14px; padding: 12px; border-radius: 14px; background: var(--gz-surface);
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
}
.mois-editeur strong { font-size: 16px; min-width: 96px; text-transform: capitalize; }
.mois-editeur .bulle { min-width: 84px; }
.mois-editeur .conseil { margin-left: auto; font-size: 12.5px; color: var(--gz-doux); }

/* ── Voyages (graine, sursemis) ── */
.etapes { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin-top: 12px; }
.etape { border-radius: 14px; padding: 10px 12px; background: var(--gz-surface); min-width: 0; }
.etape-tete { display: flex; align-items: center; gap: 6px; font-weight: 600; font-size: 14px; --mdc-icon-size: 18px; }
.etape-tete .pastille { width: 10px; height: 10px; border-radius: 3px; flex: none; }
.etape p { margin: 4px 0 0; font-size: 12.5px; color: var(--gz-doux); line-height: 1.4; }
.etape .jours { font-variant-numeric: tabular-nums; color: var(--gz-texte); font-weight: 600; }
.etape.en-cours { outline: 2px solid var(--gz-accent); }

/* ── Eau des graines ── */
.gouttes { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.goutte-carte { border-radius: 14px; padding: 12px; background: var(--gz-surface); min-width: 0; }
.goutte-carte h5 { margin: 0 0 6px; font-size: 14px; font-weight: 600; }
.goutte-ligne { display: flex; flex-wrap: wrap; gap: 2px; color: var(--gz-eau); --mdc-icon-size: 22px; min-height: 22px; }
.goutte-carte p { margin: 6px 0 0; font-size: 13px; color: var(--gz-doux); font-variant-numeric: tabular-nums; }
.goutte-carte p b { color: var(--gz-texte); }
.goutte-carte.soir { display: flex; gap: 12px; align-items: center; --mdc-icon-size: 30px; }
.goutte-carte.soir > ha-icon { color: #d97706; flex: none; }
.goutte-carte.soir p { margin: 0; font-size: 14px; line-height: 1.5; }

/* ── Escalier et lame ── */
/* Alignées par le HAUT : les légendes n'ont pas toutes la même hauteur, les barres si. */
.escalier { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; align-items: start; }
.marche { display: flex; flex-direction: column; align-items: center; gap: 6px; min-width: 0; text-align: center; overflow-wrap: anywhere; }
.marche.en-cours .marche-barre { box-shadow: 0 0 0 3px var(--gz-carte), 0 0 0 5px var(--gz-texte); }
.marche em { font-style: normal; font-size: 11.5px; font-weight: 700; background: var(--gz-texte); color: var(--gz-carte); border-radius: 999px; padding: 1px 7px; }
.marche-colonne { width: 100%; height: 130px; display: flex; align-items: flex-end; }
.marche-barre {
  width: 100%; border-radius: 10px 10px 4px 4px; background: var(--gz-accent);
  display: flex; align-items: flex-start; justify-content: center; padding-top: 6px;
  color: #fff; font-weight: 700; font-size: 13px; font-variant-numeric: tabular-nums;
  transition: height .2s ease;
}
.marche-barre.sans-tonte { background: repeating-linear-gradient(135deg, var(--gz-accent) 0 7px, color-mix(in srgb, var(--gz-accent) 60%, var(--gz-carte)) 7px 14px); }
.marche-barre.base { background: var(--gz-gris); color: var(--gz-texte); }
.marche b { font-size: 13px; }
.marche span { font-size: 12px; color: var(--gz-doux); line-height: 1.3; }
.lame { display: flex; align-items: stretch; gap: 10px; flex-wrap: wrap; }
.lame-carte { flex: 1 1 180px; border-radius: 14px; padding: 12px 14px; background: var(--gz-surface); }
.lame-carte small { display: block; color: var(--gz-doux); font-size: 12.5px; }
.lame-carte strong { display: block; font-size: 24px; font-variant-numeric: tabular-nums; margin-top: 2px; }
.lame-fleche { align-self: center; color: var(--gz-doux); --mdc-icon-size: 26px; }

/* ── Chargement, erreur, lecture seule ── */
.etat-page { padding: 48px 20px; text-align: center; color: var(--gz-doux); }
.etat-page h2 { color: var(--gz-texte); font-size: 18px; margin: 12px 0 6px; }
.etat-page button { margin-top: 16px; }
.bouton-plein {
  border: none; border-radius: 12px; padding: 11px 18px; font-weight: 600; font-size: 15px;
  background: var(--gz-accent); color: #fff; cursor: pointer;
}
.bouton-plein, .bouton-contour { display: inline-flex; align-items: center; justify-content: center; gap: 8px; }
.bouton-plein:hover { background: var(--gz-accent-fort); }
.bouton-plein:active { background: color-mix(in srgb, var(--gz-accent-fort) 80%, #000); }
.bouton-plein[disabled] { background: var(--gz-gris); color: var(--gz-doux); cursor: default; }
.bouton-contour {
  border: 1px solid var(--gz-trait); border-radius: 12px; padding: 10px 16px; font-weight: 600; font-size: 15px;
  background: var(--gz-carte); cursor: pointer;
}
.bouton-contour:hover { background: var(--gz-surface); }
.bouton-contour:active { background: var(--gz-piste); }
.lecture-seule { background: color-mix(in srgb, var(--gz-ambre) 16%, transparent); border-radius: 14px; padding: 12px 16px; font-size: 14px; }

/* ── Barre « Enregistrer » ── */
.barre-enregistrer {
  position: absolute; left: 50%; bottom: 16px; z-index: 6;
  transform: translate(-50%, calc(100% + 32px));
  opacity: 0; visibility: hidden; pointer-events: none;
  width: min(640px, calc(100% - 24px));
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  padding: 12px 12px 12px 18px; border-radius: 18px;
  background: var(--gz-carte); border: 1px solid var(--gz-trait);
  box-shadow: 0 10px 30px rgba(0, 0, 0, .18);
  transition: transform .22s ease, opacity .18s ease, visibility 0s linear .22s;
}
.barre-enregistrer.visible {
  transform: translate(-50%, 0); opacity: 1; visibility: visible; pointer-events: auto;
  transition: transform .22s ease, opacity .18s ease, visibility 0s;
}
.barre-enregistrer .resume { flex: 1 1 200px; font-size: 14.5px; font-weight: 600; }
.barre-enregistrer .resume small { display: block; font-weight: 400; color: var(--gz-doux); font-size: 13px; }
.barre-enregistrer .actions { display: flex; gap: 8px; margin-left: auto; }
.toast {
  position: absolute; left: 50%; top: calc(var(--header-height, 56px) + 12px); z-index: 7;
  transform: translate(-50%, -12px); opacity: 0; pointer-events: none;
  padding: 10px 16px; border-radius: 12px; font-weight: 600; font-size: 14.5px;
  background: var(--gz-texte); color: var(--gz-carte);
  display: inline-flex; align-items: center; gap: 8px; --mdc-icon-size: 18px;
  transition: opacity .2s, transform .2s; max-width: calc(100% - 32px);
}
.toast.visible { opacity: 1; transform: translate(-50%, 0); }
.toast.mauvais { background: var(--gz-rouge); color: #fff; }

/* ══ Base de contrôle (Accueil) ══════════════════════════════════════════════════════════ */

/* ── Navigation principale ── */
.bascule-vues { display: inline-flex; padding: 3px; gap: 2px; border-radius: 999px; background: var(--gz-surface); flex: none; }
.bascule-vues button {
  border: none; background: none; cursor: pointer; border-radius: 999px;
  padding: 7px 14px; font-size: 14px; font-weight: 600; color: var(--gz-doux);
  display: inline-flex; align-items: center; gap: 6px; --mdc-icon-size: 18px;
}
.bascule-vues button[aria-current="page"] { background: var(--gz-carte); color: var(--gz-texte); box-shadow: 0 1px 3px rgba(0, 0, 0, .18); }
.bascule-vues button:active { background: var(--gz-piste); }
.panneau { display: flex; flex-direction: column; gap: 16px; }
.onglet .signal { width: 8px; height: 8px; border-radius: 50%; background: var(--gz-eau); }
.onglet[aria-selected="true"] .signal { background: #fff; }
.onglet .signal.violet { background: var(--gz-produit); }

/* ── Bandeau « En ce moment » ── */
.en-ce-moment {
  --ton: #059669;
  border-radius: var(--gz-rayon); padding: 20px 22px; color: #fff; background: var(--ton);
  display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 16px 24px; align-items: start;
}
.en-ce-moment.eau { --ton: #2563eb; }
.en-ce-moment.alerte { --ton: #d97706; }
.en-ce-moment.danger { --ton: #dc2626; }
.maintenant-principal { display: flex; gap: 16px; align-items: flex-start; min-width: 0; }
.maintenant-icone {
  width: 58px; height: 58px; border-radius: 18px; flex: none;
  background: rgba(255, 255, 255, .18); display: flex; align-items: center; justify-content: center; --mdc-icon-size: 34px;
}
.maintenant-sur { font-size: 11px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; opacity: .85; }
.en-ce-moment h2 { margin: 2px 0 4px; font-size: 22px; font-weight: 700; line-height: 1.2; text-wrap: balance; }
.en-ce-moment p { margin: 0; font-size: 14px; line-height: 1.4; opacity: .95; max-width: 60ch; }
.en-ce-moment .puces { margin-top: 12px; }
.en-ce-moment .puce { background: rgba(255, 255, 255, .18); color: #fff; }
.en-ce-moment .progression { background: rgba(255, 255, 255, .28); margin-top: 12px; }
.en-ce-moment .progression i { background: #fff; }
.maintenant-session { display: flex; align-items: center; gap: 12px; margin-top: 10px; flex-wrap: wrap; font-variant-numeric: tabular-nums; }
.bouton-blanc {
  border: none; border-radius: 11px; padding: 9px 14px; cursor: pointer;
  background: #fff; color: #b91c1c; font-weight: 700; font-size: 14px;
  display: inline-flex; align-items: center; gap: 6px; --mdc-icon-size: 19px;
}
.bouton-blanc:hover { background: #fee2e2; }
.bouton-blanc:active { background: #fecaca; }
.bouton-blanc[disabled] { opacity: .6; cursor: default; }
.meteo { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; text-align: right; }
.meteo-haut { display: flex; align-items: center; gap: 9px; --mdc-icon-size: 36px; }
.meteo-temp { font-size: 26px; font-weight: 700; line-height: 1; font-variant-numeric: tabular-nums; }
.meteo-libelle { font-size: 12px; opacity: .9; margin-top: 2px; }
.meteo-ligne { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 4px 11px; font-size: 12px; opacity: .95; --mdc-icon-size: 14px; }
.meteo-ligne span { display: inline-flex; align-items: center; gap: 3px; white-space: nowrap; font-variant-numeric: tabular-nums; }
.meteo-heure { font-size: 12px; opacity: .85; }

/* ── Bulletin ── */
.bulletin {
  background: var(--gz-carte); border: 1px solid var(--gz-trait); border-radius: var(--gz-rayon);
  padding: 16px 20px; display: flex; gap: 14px; align-items: flex-start;
}
.bulletin-icone {
  width: 40px; height: 40px; border-radius: 13px; flex: none; display: flex; align-items: center; justify-content: center;
  background: var(--gz-accent-doux); color: var(--gz-accent-fort); --mdc-icon-size: 22px;
}
:host([sombre]) .bulletin-icone { color: var(--gz-accent); }
.bulletin h3 { margin: 0 0 6px; font-size: 16px; }
.bulletin p { margin: 0 0 6px; font-size: 15px; line-height: 1.5; }
.bulletin p:last-child { margin-bottom: 0; }

/* ── Actions ── */
.actions-grille { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; padding: 12px 20px 20px; }
.action {
  border: 1px solid var(--gz-trait); background: var(--gz-carte); border-radius: 16px; padding: 14px;
  text-align: left; cursor: pointer; display: flex; flex-direction: column; gap: 8px; min-height: 104px;
  transition: border-color .15s, background .15s;
}
.action-icone {
  width: 40px; height: 40px; border-radius: 12px; display: flex; align-items: center; justify-content: center;
  background: var(--gz-accent-doux); color: var(--gz-accent-fort); --mdc-icon-size: 22px;
}
:host([sombre]) .action-icone { color: var(--gz-accent); }
.action b { font-size: 15px; line-height: 1.25; }
.action small { color: var(--gz-doux); font-size: 12.5px; line-height: 1.35; }
.action:hover { border-color: var(--gz-accent); }
.action:active { background: var(--gz-accent-doux); }
.action.eau .action-icone { background: color-mix(in srgb, var(--gz-eau) 16%, transparent); color: var(--gz-eau); }
.action.eau:hover { border-color: var(--gz-eau); }
.action.danger { border-color: color-mix(in srgb, var(--gz-rouge) 45%, var(--gz-trait)); }
.action.danger .action-icone { background: var(--gz-rouge); color: #fff; }
.action.danger:active { background: color-mix(in srgb, var(--gz-rouge) 12%, transparent); }
.rangee-boutons { display: flex; flex-wrap: wrap; gap: 8px; padding: 4px 20px 18px; }

/* ── Tuiles ── */
/* Elles suivent la largeur de LEUR bloc : quatre de front sur une grande colonne, deux sur un téléphone. */
.tuiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(165px, 1fr)); gap: 10px; }
.tuiles.carre { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.tuiles.deux { grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); }
.tuile {
  background: var(--gz-carte); border: 1px solid var(--gz-trait); border-radius: 16px; padding: 14px;
  display: flex; flex-direction: column; gap: 4px; min-width: 0;
}
.section .tuiles { padding: 12px 20px 18px; }
.section .tuile { background: var(--gz-surface); border-color: transparent; }
.tuile-titre { font-size: 12.5px; font-weight: 600; color: var(--gz-doux); display: flex; align-items: center; gap: 6px; --mdc-icon-size: 16px; }
.tuile-valeur { font-size: 22px; font-weight: 700; line-height: 1.2; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.tuile-valeur.petite { font-size: 17px; }
.tuile-sous { font-size: 12.5px; color: var(--gz-doux); line-height: 1.4; }
.tuile.ok .tuile-valeur { color: var(--gz-accent-fort); }
.tuile.attention .tuile-valeur { color: #b45309; }
.tuile.danger .tuile-valeur { color: #b91c1c; }
:host([sombre]) .tuile.ok .tuile-valeur { color: var(--gz-accent); }
:host([sombre]) .tuile.attention .tuile-valeur { color: #fbbf24; }
:host([sombre]) .tuile.danger .tuile-valeur { color: #f87171; }
.jauge { height: 8px; border-radius: 999px; background: var(--gz-piste); overflow: hidden; margin-top: 6px; }
.jauge i { display: block; height: 100%; border-radius: inherit; background: var(--couleur, var(--gz-accent)); }
.puce .point { width: 8px; height: 8px; border-radius: 50%; background: var(--gz-accent); flex: none; }
.puce .point.attention { background: var(--gz-ambre); }
.puce .point.arret { background: var(--gz-doux); }
.puce .point.eau { background: var(--gz-eau); }
.puce.alerte { background: color-mix(in srgb, var(--gz-ambre) 20%, transparent); }
.section .puces { padding: 0 20px 16px; margin-top: 0; }

/* ── État de l'arrosage ── */
.etat-bandeau { display: flex; gap: 14px; align-items: flex-start; padding: 18px 20px 8px; }
.etat-bandeau .etat-icone {
  width: 48px; height: 48px; border-radius: 15px; flex: none; display: flex; align-items: center; justify-content: center;
  background: var(--gz-accent-doux); color: var(--gz-accent-fort); --mdc-icon-size: 26px;
}
.etat-bandeau.eau .etat-icone { background: color-mix(in srgb, var(--gz-eau) 16%, transparent); color: var(--gz-eau); }
.etat-bandeau.alerte .etat-icone { background: color-mix(in srgb, var(--gz-ambre) 20%, transparent); color: #b45309; }
:host([sombre]) .etat-bandeau.alerte .etat-icone { color: #fbbf24; }
.etat-bandeau small { display: block; font-size: 12px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: var(--gz-doux); }
.etat-bandeau b { display: block; font-size: 20px; line-height: 1.25; margin-top: 2px; }
.etat-bandeau p { margin: 4px 0 0; color: var(--gz-doux); font-size: 14px; line-height: 1.45; }
.progression { height: 10px; border-radius: 999px; background: var(--gz-piste); overflow: hidden; }
.progression i { display: block; height: 100%; border-radius: inherit; background: var(--gz-accent); transition: width .4s ease; }
.progression.repos i { background: var(--gz-doux); }
.progression.eau i { background: var(--gz-eau); }

/* ── Zones ── */
.zone { display: flex; align-items: center; gap: 12px; padding: 12px 20px; border-top: 1px solid var(--gz-trait); }
.zone:first-child { border-top: none; }
.zone-pastille {
  width: 38px; height: 38px; border-radius: 12px; flex: none; color: #fff; font-weight: 700; font-size: 13px;
  display: flex; align-items: center; justify-content: center; --mdc-icon-size: 20px;
}
.zone-texte { flex: 1; min-width: 0; }
.zone-texte b { display: block; font-size: 15.5px; }
.zone-texte small { color: var(--gz-doux); font-size: 13px; }
.zone.active { background: color-mix(in srgb, var(--gz-eau) 9%, transparent); }
.zone.active .zone-texte small { color: var(--gz-eau); font-weight: 600; }
.zone-boutons { display: flex; gap: 6px; flex: none; flex-wrap: wrap; justify-content: flex-end; }
.petit-bouton {
  border: 1px solid var(--gz-trait); background: var(--gz-surface); border-radius: 10px; padding: 8px 12px;
  font-size: 13.5px; font-weight: 600; cursor: pointer; white-space: nowrap;
  display: inline-flex; align-items: center; gap: 5px; --mdc-icon-size: 16px;
}
.petit-bouton:hover { border-color: var(--gz-accent); }
.petit-bouton:active { background: var(--gz-accent); border-color: var(--gz-accent); color: #fff; }
.petit-bouton.arret { background: var(--gz-rouge); border-color: var(--gz-rouge); color: #fff; }
.petit-bouton.arret:active { background: #b91c1c; }
.petit-bouton[disabled] { opacity: .55; cursor: default; }
.chrono { font-variant-numeric: tabular-nums; }

/* ── Frise des 24 heures ── */
.frise-zones { display: flex; flex-direction: column; gap: 8px; padding: 6px 20px 4px; }
.frise-ligne { display: grid; grid-template-columns: 120px minmax(0, 1fr); gap: 10px; align-items: center; }
.frise-ligne > span { font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.frise-rail { position: relative; height: 22px; border-radius: 8px; background: var(--gz-piste); overflow: hidden; }
.frise-rail i { position: absolute; top: 3px; bottom: 3px; border-radius: 5px; min-width: 3px; }
.frise-heures { display: grid; grid-template-columns: 120px minmax(0, 1fr); gap: 10px; padding: 0 20px; }
.frise-heures .graduations { margin-top: 2px; }
.frise-vide { padding: 8px 20px 0; color: var(--gz-doux); font-size: 14px; }
.totaux { display: flex; flex-wrap: wrap; gap: 6px 16px; padding: 10px 20px 18px; font-size: 13px; }
.totaux span { display: inline-flex; align-items: center; gap: 6px; font-variant-numeric: tabular-nums; }
.totaux i { width: 10px; height: 10px; border-radius: 3px; }

/* ── Budget de la semaine ── */
.budget { padding: 8px 20px 18px; }
.budget-chiffres { display: flex; justify-content: space-between; gap: 10px; flex-wrap: wrap; font-size: 14px; margin-bottom: 8px; font-variant-numeric: tabular-nums; }
.budget-chiffres b { font-size: 18px; }
.budget-rail { position: relative; height: 14px; border-radius: 999px; background: var(--gz-piste); }
.budget-rail i { display: block; height: 100%; border-radius: 999px; }
.budget-plancher { position: absolute; top: -5px; bottom: -5px; width: 3px; margin-left: -1.5px; border-radius: 2px; background: var(--gz-texte); }

/* ── Journal ── */
.session { padding: 12px 20px; border-top: 1px solid var(--gz-trait); display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 4px 12px; }
.session:first-child { border-top: none; }
.session-quand { font-weight: 600; font-size: 14.5px; }
.session-quoi { color: var(--gz-doux); font-size: 13px; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.session-mm { font-weight: 700; font-size: 17px; text-align: right; font-variant-numeric: tabular-nums; }
.session-zones { grid-column: 1 / -1; display: flex; flex-wrap: wrap; gap: 6px; }
.session-zone {
  display: inline-flex; align-items: center; gap: 5px; font-size: 12.5px; font-variant-numeric: tabular-nums;
  background: var(--gz-surface); padding: 3px 9px 3px 3px; border-radius: 999px;
}
.session-zone em {
  width: 20px; height: 20px; border-radius: 7px; color: #fff; font-style: normal; font-size: 10.5px; font-weight: 700;
  display: inline-flex; align-items: center; justify-content: center;
}
.session.technique .session-mm { color: var(--gz-doux); }
.etiquette {
  font-size: 11px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase;
  padding: 1px 7px; border-radius: 999px; background: var(--gz-surface); color: var(--gz-doux);
}
.entete-journal { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; padding: 0 20px 8px; font-variant-numeric: tabular-nums; }
.entete-journal b { font-size: 18px; }

/* ── Tondeuse ── */
.machine { display: flex; align-items: center; gap: 14px; padding: 18px 20px 12px; }
.machine-icone {
  width: 54px; height: 54px; border-radius: 17px; flex: none; display: flex; align-items: center; justify-content: center;
  background: var(--gz-accent-doux); color: var(--gz-accent-fort); --mdc-icon-size: 32px;
}
:host([sombre]) .machine-icone { color: var(--gz-accent); }
.machine-texte { flex: 1; min-width: 0; }
.machine-texte b { display: block; font-size: 18px; }
.machine-texte small { color: var(--gz-doux); font-size: 13.5px; }
.badge {
  padding: 5px 11px; border-radius: 999px; font-size: 12.5px; font-weight: 700; white-space: nowrap;
  background: var(--gz-accent-doux); color: var(--gz-accent-fort);
}
:host([sombre]) .badge { color: var(--gz-accent); }
.badge.arret { background: var(--gz-surface); color: var(--gz-doux); }
.travail { padding: 4px 20px 16px; display: flex; flex-direction: column; gap: 8px; }
.travail-tete { display: flex; justify-content: space-between; gap: 10px; font-size: 14px; font-variant-numeric: tabular-nums; }
.travail-tete b { font-size: 15px; }
.travail p { margin: 0; font-size: 13.5px; color: var(--gz-doux); line-height: 1.45; }
.travail p.ok { color: var(--gz-accent-fort); font-weight: 600; }
:host([sombre]) .travail p.ok { color: var(--gz-accent); }

/* Le déroulé d'un arrosage : un ruban dont chaque morceau dure son vrai temps. */
.deroule { padding: 4px 20px 16px; }
.deroule-tete { display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 2px 12px; margin-bottom: 8px; font-size: 13px; color: var(--gz-doux); font-variant-numeric: tabular-nums; }
.deroule-tete b { color: var(--gz-texte); font-size: 14.5px; font-weight: 600; }
.deroule-ruban { display: flex; gap: 3px; height: 30px; }
.deroule-ruban i {
  min-width: 5px; border-radius: 7px; display: flex; align-items: center; justify-content: center; overflow: hidden;
  color: #fff; font-style: normal; font-size: 11.5px; font-weight: 700; letter-spacing: .02em; white-space: nowrap;
}
.deroule-pause {
  background: repeating-linear-gradient(135deg, var(--gz-piste) 0 5px, transparent 5px 10px);
  box-shadow: inset 0 0 0 1px var(--gz-trait);
}
.deroule-ruban .deroule-pause { color: var(--gz-doux); font-weight: 600; }
.deroule-heures { display: flex; justify-content: space-between; gap: 10px; margin-top: 5px; font-size: 12px; color: var(--gz-doux); font-variant-numeric: tabular-nums; }
.deroule-legende { list-style: none; margin: 10px 0 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 6px 16px; font-size: 13px; }
.deroule-legende li { display: flex; align-items: center; gap: 7px; min-width: 0; }
.deroule-legende li > i { width: 10px; height: 10px; border-radius: 3px; flex: none; }
.deroule-legende li span { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.deroule-legende li b { font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; }
.deroule-note { margin: 8px 0 0; font-size: 12.5px; color: var(--gz-doux); line-height: 1.4; }
.deroule.compact .deroule-legende { grid-template-columns: minmax(0, 1fr); }

/* Les gros arrosages : deux rubans à la même échelle de temps. */
.decoupes { display: flex; flex-direction: column; gap: 10px; }
.decoupe-tete { display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 0 8px; margin-bottom: 4px; font-size: 13px; color: var(--gz-doux); font-variant-numeric: tabular-nums; }
.decoupe-tete b { color: var(--gz-texte); font-size: 14.5px; }
.decoupe .deroule-ruban { height: 22px; }
.decoupe .deroule-ruban i { border-radius: 5px; }

/* La terre du jardin : une carte par option. */
.choix-sols { display: flex; flex-direction: column; gap: 8px; padding: 8px 20px 4px; }
.choix-sol {
  display: flex; flex-direction: column; gap: 4px; text-align: left; width: 100%;
  padding: 10px 12px; border-radius: 14px; border: 1px solid var(--gz-trait); background: var(--gz-carte); cursor: pointer;
}
.choix-sol:hover:not([disabled]) { border-color: var(--gz-accent); }
.choix-sol.choisi { border: 2px solid var(--gz-accent); padding: 9px 11px; background: var(--gz-accent-doux); }
.choix-sol[disabled] { cursor: default; }
.choix-sol-tete { display: flex; align-items: center; gap: 8px; }
.choix-sol-tete b { font-size: 15px; flex: 1; }
.choix-sol-tete small { color: var(--gz-doux); font-size: 12px; }
.choix-sol-tete ha-icon { color: var(--gz-accent-fort); }
:host([sombre]) .choix-sol-tete ha-icon { color: var(--gz-accent); }
.choix-sol-texte { font-size: 13px; color: var(--gz-doux); line-height: 1.4; }
.choix-sol-reserve { position: relative; height: 8px; border-radius: 999px; background: var(--gz-piste); margin-top: 4px; overflow: hidden; }
.choix-sol-reserve i { position: absolute; left: 0; top: 0; bottom: 0; border-radius: inherit; background: var(--gz-eau); }
.choix-sol-reserve i.max { background: var(--gz-eau-doux); z-index: -0; }
.choix-sol-reserve i:first-child { z-index: 1; }
.choix-sol-chiffres { font-size: 12px; color: var(--gz-doux); font-variant-numeric: tabular-nums; }
.choix-sol-note { margin: 8px 20px 16px; }

/* Les fiches produit. */
.catalogue li { position: relative; }
.catalogue li:has(.catalogue-boutons) { padding-right: 72px; }
.catalogue-boutons { position: absolute; top: 6px; right: 6px; display: flex; gap: 2px; }
.bouton-icone {
  width: 32px; height: 32px; border-radius: 10px; border: none; background: none; cursor: pointer;
  display: inline-flex; align-items: center; justify-content: center; color: var(--gz-doux); --mdc-icon-size: 18px;
}
.bouton-icone:hover { background: var(--gz-piste); color: var(--gz-texte); }
.bouton-icone:focus-visible { outline: 2px solid var(--gz-accent); outline-offset: 1px; }
.champs-deux { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 0 12px; }
.plus-de-details { border: 1px solid var(--gz-trait); border-radius: 14px; padding: 4px 12px; margin: 4px 0 8px; }
.plus-de-details > summary { cursor: pointer; font-weight: 600; padding: 8px 0; }
.puces-choix { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }
.puce-choix { position: relative; }
.puce-choix input { position: absolute; opacity: 0; inset: 0; margin: 0; cursor: pointer; }
.puce-choix span { display: inline-block; padding: 6px 10px; border-radius: 999px; border: 1px solid var(--gz-trait); font-size: 13px; }
.puce-choix input:checked + span { background: var(--gz-accent-doux); border-color: var(--gz-accent); color: var(--gz-accent-fort); font-weight: 600; }
:host([sombre]) .puce-choix input:checked + span { color: var(--gz-accent); }
.puce-choix input:focus-visible + span { outline: 2px solid var(--gz-accent); outline-offset: 2px; }

/* Les modes : une case par jour. */
.modes-jours { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 12px; }
.mode-jours-tete { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; font-size: 14px; }
.mode-jours-tete span { color: var(--gz-doux); font-size: 13px; font-variant-numeric: tabular-nums; }
.mode-jours-cases { display: grid; grid-template-columns: repeat(var(--n), minmax(0, 1fr)); gap: 3px; margin: 5px 0 3px; }
.mode-jours-cases i { height: 14px; border-radius: 4px; background: var(--gz-piste); }
.mode-jours-cases i.plein { background: var(--gz-produit); }
.modes-jours small { color: var(--gz-doux); font-size: 12.5px; }

/* Pendant un arrosage : la part de la dose que chaque zone a déjà reçue. */
.avance { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.avance li { display: grid; grid-template-columns: 10px minmax(80px, 1fr) minmax(60px, 1.2fr) auto; grid-template-rows: auto auto; align-items: center; gap: 0 8px; font-size: 13px; }
.avance li > i { width: 10px; height: 10px; border-radius: 3px; }
.avance li span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.avance li b { font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; }
.avance li small { grid-column: 2 / -1; color: var(--gz-doux); font-size: 12px; }
.avance li.active small { color: var(--gz-eau); font-weight: 600; }
.avance li.faite small { color: var(--gz-accent-fort); }
:host([sombre]) .avance li.faite small { color: var(--gz-accent); }
.avance-rail { height: 8px; border-radius: 999px; background: var(--gz-piste); overflow: hidden; }
.avance-rail > div { height: 100%; border-radius: inherit; transition: width .4s ease; }
.pousse { display: flex; gap: 18px; align-items: flex-end; padding: 8px 20px 18px; }
.pousse-colonne { width: 64px; height: 128px; border-radius: 14px; background: var(--gz-surface); position: relative; overflow: hidden; flex: none; }
.pousse-herbe {
  position: absolute; left: 0; right: 0; bottom: 0; border-radius: 10px 10px 0 0;
  background: repeating-linear-gradient(90deg, var(--gz-accent) 0 6px, color-mix(in srgb, var(--gz-accent) 72%, #064e3b) 6px 9px);
}
.pousse-lame { position: absolute; left: -2px; right: -2px; height: 0; border-top: 2px dashed var(--gz-rouge); }
.pousse-texte b { display: block; font-size: 28px; line-height: 1.1; font-variant-numeric: tabular-nums; }
.pousse-texte p { margin: 4px 0 0; font-size: 14px; color: var(--gz-doux); line-height: 1.45; }
.ligne-bascule { display: flex; align-items: center; gap: 12px; padding: 14px 20px 18px; }
.ligne-bascule .ligne-textes h4 { margin: 0 0 2px; }

/* ── Gazon ── */
.reservoir { padding: 6px 20px 18px; }
.reservoir-rail { position: relative; height: 30px; border-radius: 10px; background: var(--gz-surface); overflow: hidden; border: 1px solid var(--gz-trait); }
.reservoir-eau { position: absolute; left: 0; top: 0; bottom: 0; background: var(--gz-eau); }
.reservoir-seuil { position: absolute; top: 0; bottom: 0; width: 0; border-left: 2px dashed var(--gz-rouge); }
.reservoir-legende { display: flex; justify-content: space-between; gap: 10px; flex-wrap: wrap; margin-top: 8px; font-size: 13px; color: var(--gz-doux); font-variant-numeric: tabular-nums; }
.liste-simple { list-style: none; margin: 0; padding: 0 20px 16px; display: flex; flex-direction: column; gap: 6px; }
.liste-simple li { display: flex; gap: 8px; align-items: flex-start; font-size: 14px; line-height: 1.45; --mdc-icon-size: 18px; }
.liste-simple li ha-icon { flex: none; color: var(--gz-doux); }
.liste-simple li.ok ha-icon { color: var(--gz-accent); }
.liste-simple li.retient ha-icon { color: var(--gz-ambre); }

/* ── Produits ── */
.produit-bandeau { background: #7c3aed; color: #fff; border-radius: var(--gz-rayon); padding: 18px 20px; display: flex; gap: 14px; align-items: flex-start; }
.produit-bandeau.a-preparer { background: #b45309; }
.produit-bandeau .maintenant-icone { width: 50px; height: 50px; --mdc-icon-size: 28px; }
.produit-bandeau h2 { margin: 2px 0 4px; font-size: 22px; }
.produit-bandeau p { margin: 0; opacity: .92; }
.produit-bandeau .puce { background: rgba(255, 255, 255, .2); color: #fff; margin-top: 10px; }
details.pourquoi { padding: 0 20px 16px; font-size: 14px; }
details.pourquoi summary { cursor: pointer; font-weight: 600; color: var(--gz-accent-fort); }
:host([sombre]) details.pourquoi summary { color: var(--gz-accent); }
details.pourquoi p { margin: 8px 0 0; color: var(--gz-doux); line-height: 1.5; }
.historique { list-style: none; margin: 0; padding: 0; }
.historique li { display: grid; grid-template-columns: 96px minmax(0, 1fr); gap: 12px; padding: 12px 20px; border-top: 1px solid var(--gz-trait); }
.historique li:first-child { border-top: none; }
.historique time { font-size: 13px; color: var(--gz-doux); font-variant-numeric: tabular-nums; padding-top: 2px; }
.historique b { font-size: 15px; }
.historique .meta { font-size: 13px; color: var(--gz-doux); }
.note-produit {
  margin-top: 4px; font-size: 13px; line-height: 1.45; cursor: pointer; border: none; background: none; padding: 0; text-align: left; color: inherit;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.note-produit.ouverte { display: block; }
.catalogue { list-style: none; margin: 0; padding: 0 20px 16px; display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 8px; }
.catalogue li { background: var(--gz-surface); border-radius: 14px; padding: 10px 12px; font-size: 13px; color: var(--gz-doux); line-height: 1.4; }
.catalogue li b { display: block; color: var(--gz-texte); font-size: 14.5px; }
.catalogue-mode { grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); }
.catalogue-mode li { padding: 14px; }
.parametres-produit { margin: 10px 0 0; display: grid; gap: 6px; }
.parametres-produit div { display: grid; grid-template-columns: minmax(82px, .4fr) minmax(0, 1fr); gap: 10px; }
.parametres-produit dt { color: var(--gz-doux); }
.parametres-produit dd { margin: 0; color: var(--gz-texte); overflow-wrap: anywhere; }
.regles-mode { padding-bottom: 14px; }
@container page (max-width: 520px) {
  .catalogue-mode { grid-template-columns: minmax(0, 1fr); }
  .parametres-produit div { grid-template-columns: minmax(0, 1fr); gap: 1px; }
  .parametres-produit dt { font-size: 12px; }
}
.vide { padding: 4px 20px 18px; color: var(--gz-doux); font-size: 14px; }

/* ── Fenêtres ── */
dialog.dialogue {
  border: none; padding: 0; border-radius: 22px; width: min(500px, calc(100vw - 24px));
  width: min(500px, calc(var(--gz-page-width, 100vw) - 24px));
  max-height: calc(100vh - 32px); max-height: calc(100dvh - 32px);
  background: var(--gz-carte); color: var(--gz-texte); box-shadow: 0 24px 64px rgba(0, 0, 0, .38);
  font-family: inherit; overflow: hidden;
}
dialog.dialogue[open] { display: flex; flex-direction: column; }
dialog.dialogue::backdrop { background: rgba(15, 23, 42, .5); }
/* Le formulaire est le SEUL enfant de la fenêtre : sans hauteur bornée, il prenait toute la
   hauteur de son contenu, la fenêtre (overflow: hidden) le coupait, le corps ne défilait jamais
   et le bouton de validation restait hors d'atteinte (« Changer de mode », fiche produit, sur
   téléphone). Borné à la hauteur de la fenêtre, il laisse le corps défiler entre l'en-tête et
   les boutons, qui restent visibles. */
dialog.dialogue > form { display: flex; flex-direction: column; min-height: 0; max-height: inherit; }
.dialogue-tete { display: flex; align-items: center; gap: 12px; padding: 18px 20px 8px; flex: none; }
.dialogue-tete .action-icone { flex: none; }
.dialogue-tete h2 { margin: 0; font-size: 19px; flex: 1; line-height: 1.3; }
.dialogue-corps {
  padding: 4px 20px 8px; display: flex; flex-direction: column; gap: 14px;
  flex: 1 1 auto; min-height: 0; overflow-y: auto; overscroll-behavior: contain;
}
/* C'est le corps qui défile, jamais ses blocs qui rétrécissent : un bloc qui coupe son contenu
   (le plan des zones de « Arroser ») se laissait écraser et n'affichait plus que la zone A. */
.dialogue-corps > * { flex-shrink: 0; }
.dialogue-corps > p { margin: 0; font-size: 14.5px; color: var(--gz-doux); line-height: 1.5; }
.dialogue-pied { display: flex; gap: 8px; justify-content: flex-end; flex-wrap: wrap; padding: 12px 20px 20px; border-top: 1px solid var(--gz-trait); flex: none; }
.champ { display: flex; flex-direction: column; gap: 6px; }
.champ > label, .champ > span { font-weight: 600; font-size: 14.5px; }
.champ input:not([type="checkbox"]):not([type="radio"]), .champ select, .champ textarea {
  font: inherit; font-size: 16px; padding: 10px 12px; border-radius: 12px;
  border: 1px solid var(--gz-trait); background: var(--gz-surface); color: var(--gz-texte);
}
.champ input:focus-visible, .champ select:focus-visible, .champ textarea:focus-visible { outline: 3px solid color-mix(in srgb, var(--gz-accent) 40%, transparent); outline-offset: 1px; }
.champ small { color: var(--gz-doux); font-size: 13px; line-height: 1.4; }
.case { display: flex; gap: 10px; align-items: flex-start; font-size: 14.5px; cursor: pointer; }
.case input { margin-top: 3px; width: 18px; height: 18px; accent-color: var(--gz-accent); flex: none; }
.case small { display: block; color: var(--gz-doux); font-size: 13px; }
.dose { display: flex; align-items: center; gap: 12px; }
.dose output { font-size: 30px; font-weight: 700; min-width: 120px; text-align: center; font-variant-numeric: tabular-nums; }
.raccourcis { display: flex; gap: 6px; flex-wrap: wrap; }
/* ── Onglet Météo ── */
.meteo-maintenant { padding-bottom: 14px; }
.meteo-principal { display: flex; gap: 16px; align-items: center; padding: 18px 20px 8px; --mdc-icon-size: 64px; }
.meteo-principal > ha-icon { color: var(--gz-eau); flex: none; }
.meteo-principal small { display: block; font-size: 12px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: var(--gz-doux); }
.meteo-grande { font-size: 44px; font-weight: 700; line-height: 1.05; font-variant-numeric: tabular-nums; }
.meteo-etat { font-size: 16px; font-weight: 600; }
.meteo-principal .note { margin-top: 4px; }
.mesures-meteo { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 8px; padding: 4px 20px 0; }
.mesure-meteo { display: grid; grid-template-columns: auto 1fr auto; column-gap: 8px; align-items: center; padding: 8px 10px; border-radius: 12px; background: var(--gz-surface); --mdc-icon-size: 18px; min-width: 0; }
.mesure-meteo > ha-icon { color: var(--gz-doux); grid-row: span 2; }
.mesure-meteo > span { font-size: 12.5px; color: var(--gz-doux); }
.mesure-meteo > b { grid-column: 2; font-size: 16px; font-variant-numeric: tabular-nums; }
.mesure-meteo > .origine { grid-column: 3; grid-row: 1 / span 2; }
.mesure-meteo > small:not(.origine) { grid-column: 2 / span 2; font-size: 12px; color: var(--gz-doux); }
.origine { font-size: 11px; font-weight: 700; padding: 2px 7px; border-radius: 999px; background: var(--gz-piste); color: var(--gz-doux); }
.origine.jardin { background: var(--gz-accent-doux); color: var(--gz-accent-fort); }
:host([sombre]) .origine.jardin { color: var(--gz-accent); }
.jours-meteo { list-style: none; margin: 0; padding: 4px 20px 16px; display: flex; flex-direction: column; }
.jours-meteo li { display: grid; grid-template-columns: minmax(0, 1fr) 28px auto minmax(70px, auto); gap: 10px; align-items: center; padding: 7px 0; border-top: 1px solid var(--gz-trait); font-size: 14px; --mdc-icon-size: 24px; }
.jours-meteo li:first-child { border-top: none; }
.jour-nom { font-weight: 600; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.jour-temp, .jour-pluie { font-variant-numeric: tabular-nums; text-align: end; white-space: nowrap; }
.jour-pluie { color: var(--gz-doux); }
.jour-pluie.mouille, .heure-meteo .mouille { color: var(--gz-eau); font-weight: 600; }
.jour-pluie small { color: var(--gz-doux); font-weight: 400; }
.heures-meteo { display: flex; gap: 6px; overflow-x: auto; padding: 6px 20px 16px; scroll-snap-type: x proximity; }
.heure-meteo { flex: none; width: 78px; display: flex; flex-direction: column; align-items: center; gap: 3px; padding: 8px 4px; border-radius: 14px; background: var(--gz-surface); font-size: 12.5px; scroll-snap-align: start; --mdc-icon-size: 26px; font-variant-numeric: tabular-nums; }
.heure-meteo b { font-size: 16px; }
.heure-meteo span { display: inline-flex; align-items: center; gap: 2px; color: var(--gz-doux); --mdc-icon-size: 14px; text-align: center; }
.lignes-meteo { list-style: none; margin: 0; padding: 0 20px 16px; display: flex; flex-direction: column; }
.lignes-meteo li { display: grid; grid-template-columns: 22px minmax(0, 1fr) auto; gap: 10px; align-items: center; padding: 8px 0; border-top: 1px solid var(--gz-trait); --mdc-icon-size: 20px; }
.lignes-meteo li:first-child { border-top: none; }
.lignes-meteo li > ha-icon { color: var(--gz-doux); }
.lignes-meteo li > span { font-size: 14px; min-width: 0; }
.lignes-meteo li > span small { display: block; font-size: 12.5px; color: var(--gz-doux); line-height: 1.35; }
.lignes-meteo li > b { font-size: 15.5px; font-variant-numeric: tabular-nums; white-space: nowrap; text-align: end; }
.lignes-meteo li.avec-jauge .jauge { grid-column: 2 / span 2; }
.discret { color: var(--gz-doux); font-weight: 400; }
.voyants-meteo { display: flex; flex-wrap: wrap; gap: 6px; padding: 4px 20px 16px; }
.voyant { display: inline-flex; align-items: center; gap: 4px; padding: 5px 10px; border-radius: 999px; font-size: 13px; font-weight: 600; background: var(--gz-accent-doux); color: var(--gz-accent-fort); --mdc-icon-size: 16px; }
.voyant.retient { background: color-mix(in srgb, var(--gz-ambre) 18%, transparent); color: #b45309; }
:host([sombre]) .voyant { color: var(--gz-accent); }
:host([sombre]) .voyant.retient { color: #fbbf24; }
.entrees-deux { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 600px), 1fr)); column-gap: 8px; }
.tableau-defilant { overflow-x: auto; padding: 0 20px 16px; }
.entrees-meteo { width: 100%; border-collapse: collapse; font-size: 14px; min-width: 560px; }
.entrees-meteo th { text-align: start; font-size: 12px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase; color: var(--gz-doux); padding: 8px 10px 6px 0; }
.entrees-meteo tr.groupe th { padding-top: 16px; color: var(--gz-texte); font-size: 12.5px; }
.entrees-meteo td { padding: 9px 10px 9px 0; border-top: 1px solid var(--gz-trait); vertical-align: top; }
.entrees-meteo td small { display: block; font-size: 12.5px; color: var(--gz-doux); line-height: 1.35; margin-top: 2px; }
.entrees-meteo td:first-child { width: 30%; }
.entree-entite code { display: block; font-size: 12px; color: var(--gz-doux); overflow-wrap: anywhere; }
.entree-entite .idee { color: var(--gz-texte); background: var(--gz-accent-doux); border-radius: 8px; padding: 4px 8px; margin-top: 6px; }
.entree-valeur { white-space: nowrap; font-variant-numeric: tabular-nums; font-weight: 600; }
.statut { display: inline-flex; align-items: center; gap: 4px; font-size: 12.5px; font-weight: 600; white-space: nowrap; color: var(--gz-doux); --mdc-icon-size: 16px; }
.statut.ok { color: var(--gz-accent-fort); }
.statut.retient { color: #b45309; }
:host([sombre]) .statut.ok { color: var(--gz-accent); }
:host([sombre]) .statut.retient { color: #fbbf24; }
.puce-mini { display: inline-block !important; font-size: 11px !important; padding: 1px 6px; border-radius: 999px; background: var(--gz-piste); margin-top: 4px !important; }
.appareils-meteo { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 12px; padding: 0 20px 16px; }
.appareil-meteo h4 { margin: 4px 0 8px; font-size: 15px; display: flex; flex-wrap: wrap; align-items: center; gap: 6px; --mdc-icon-size: 18px; }
.appareil-meteo h4 small { font-weight: 400; color: var(--gz-doux); font-size: 12.5px; }
.voisines { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 6px; }
.voisine { display: flex; flex-direction: column; gap: 2px; padding: 7px 10px; border-radius: 12px; border: 1px solid var(--gz-trait); min-width: 0; }
.voisine span { font-size: 12px; color: var(--gz-doux); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.voisine b { font-size: 14.5px; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.voisine.branchee { border-color: var(--gz-accent); background: var(--gz-accent-doux); }
.voisine.idee { border-style: dashed; border-color: var(--gz-accent); }
@media (max-width: 600px) {
  .meteo-principal { --mdc-icon-size: 48px; }
  .meteo-grande { font-size: 36px; }
}
/* Tableau des entrées sur petit écran : chaque entrée devient un bloc, sans défilement de côté. */
@container (max-width: 620px) {
  .tableau-defilant { overflow-x: visible; }
  .entrees-meteo { min-width: 0; }
  .entrees-meteo thead { display: none; }
  .entrees-meteo tbody, .entrees-meteo tr.groupe, .entrees-meteo tr.groupe th { display: block; }
  .entrees-meteo tr:not(.groupe) { display: grid; grid-template-columns: minmax(0, 1fr) auto; column-gap: 10px; padding: 10px 0; border-top: 1px solid var(--gz-trait); }
  .entrees-meteo td { border-top: none; padding: 2px 0; }
  .entrees-meteo td:first-child { width: auto; grid-column: 1; }
  .entrees-meteo .entree-statut { grid-column: 2; grid-row: 1; }
  .entrees-meteo .entree-entite, .entrees-meteo .entree-valeur { grid-column: 1 / -1; }
  .entrees-meteo .entree-valeur small { display: inline; margin-left: 6px; }
}
/* Carte étroite : deux mesures par ligne, l'origine passe sous la valeur plutôt que d'être coupée. */
@container (max-width: 520px) {
  .mesures-meteo { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .mesure-meteo { grid-template-columns: auto minmax(0, 1fr); }
  .mesure-meteo > .origine { grid-column: 2; grid-row: auto; justify-self: start; margin-top: 3px; }
}
.champ-pompe { margin: 10px 0 0 48px; }
.champ-pompe select { width: 100%; }
.etat-garage {
  margin: 10px 0 0 48px; padding: 9px 11px; border-radius: 8px;
  background: var(--gz-surface); border: 1px solid var(--gz-trait);
  display: flex; align-items: center; justify-content: space-between; gap: 10px;
}
.etat-garage .statut { flex: none; }
.garage-reglages {
  margin: 10px 20px 18px; border: 1px solid var(--gz-trait); border-radius: 12px; overflow: hidden;
}
.garage-groupe + .garage-groupe { border-top: 1px solid var(--gz-trait); }
.garage-groupe > summary {
  list-style: none; padding: 12px 14px; cursor: pointer;
  display: grid; grid-template-columns: 34px minmax(0, 1fr) auto; gap: 10px; align-items: center;
}
.garage-groupe > summary::-webkit-details-marker { display: none; }
.garage-groupe > summary:hover { background: var(--gz-surface); }
.garage-groupe > summary:focus-visible { outline: 2px solid var(--gz-accent); outline-offset: -3px; }
.garage-scenario-icone {
  width: 34px; height: 34px; border-radius: 10px; background: var(--gz-accent-doux);
  color: var(--gz-accent-fort); display: inline-flex; align-items: center; justify-content: center;
  --mdc-icon-size: 19px;
}
:host([sombre]) .garage-scenario-icone { color: var(--gz-accent); }
.garage-scenario-texte { min-width: 0; }
.garage-scenario-texte b { display: block; font-size: 14px; }
.garage-scenario-texte small { display: block; margin-top: 2px; color: var(--gz-doux); font-size: 12px; line-height: 1.35; }
.garage-chevron { color: var(--gz-doux); transition: transform .16s; --mdc-icon-size: 18px; }
.garage-groupe[open] .garage-chevron { transform: rotate(180deg); }
.garage-groupe[open] > summary { background: var(--gz-surface); }
.garage-groupe > .lignes { border-top: 1px solid var(--gz-trait); }
.garage-groupe > .lignes .ligne:first-child { border-top: 0; }
.garage-groupe .avertissement-reglage { margin-right: 0; }
.programme-reglages {
  display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px;
}
.programme-reglages > .reglage-tout { grid-column: 1 / -1; }
.mode-reglages {
  display: grid; grid-template-columns: minmax(0, 2fr) minmax(280px, 1fr); gap: 16px;
  align-items: start;
}
.programme-groupe {
  min-width: 0; align-self: start; border: 1px solid var(--gz-trait); border-radius: 8px;
  overflow: hidden; background: var(--gz-carte);
}
.programme-groupe > summary {
  list-style: none; padding: 12px 14px; cursor: pointer;
  display: grid; grid-template-columns: 34px minmax(0, 1fr) auto; gap: 10px; align-items: center;
}
.programme-groupe > summary::-webkit-details-marker { display: none; }
.programme-groupe > summary:hover,
.programme-groupe[open] > summary { background: var(--gz-surface); }
.programme-groupe > summary:focus-visible { outline: 2px solid var(--gz-accent); outline-offset: -3px; }
.programme-groupe[open] .garage-chevron { transform: rotate(180deg); }
.programme-groupe > .dessin,
.programme-groupe > .lignes { border-top: 1px solid var(--gz-trait); }
.programme-groupe > .dessin + .lignes { border-top: 0; }
.programme-groupe > .lignes .ligne:first-child { border-top: 0; }
.programme-groupe .avertissement-reglage { margin-right: 0; }
.programme-commun { color: var(--gz-accent-fort); }
:host([sombre]) .programme-commun { color: var(--gz-accent); }
.reglage-groupe-corps > .dessin { border-top: 1px solid var(--gz-trait); }
.reglage-groupe-corps > .lignes { border-top: 1px solid var(--gz-trait); }
.reglage-groupe-corps > .dessin + .lignes { border-top: 0; }
.reglage-groupe-corps > .lignes .ligne:first-child { border-top: 0; }
@container (max-width: 460px) {
  .garage-reglages { margin-left: 16px; margin-right: 16px; }
  .garage-groupe > summary { padding: 10px 12px; }
  .programme-reglages { grid-template-columns: minmax(0, 1fr); gap: 10px; }
  .programme-reglages > .reglage-tout { grid-column: auto; }
  .mode-reglages { grid-template-columns: minmax(0, 1fr); gap: 10px; }
  .programme-groupe > summary { padding: 10px 12px; }
}
@media (max-width: 600px) { .champ-pompe { margin-left: 0; } }
@media (max-width: 600px) {
  .etat-garage { margin-left: 0; align-items: flex-start; flex-direction: column; }
}
/* Une carte pleine largeur : ses réglages se rangent côte à côte quand la place le permet. */
@container (min-width: 820px) {
  .section-rangee .lignes { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .section-rangee .ligne { border-top: none; }
  .section-rangee .ligne + .ligne { border-left: 1px solid var(--gz-trait); }
  .section-rangee[data-alertes] > .lignes { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .section-rangee [data-cle="alertes-actives"] { grid-column: 1 / -1; border-bottom: 1px solid var(--gz-trait); }
  .section-rangee [data-cle="alertes-mode"] { grid-column: 1 / -1; border-left: none !important; border-bottom: 1px solid var(--gz-trait); }
  .section-rangee [data-cle="alertes-niveau"],
  .section-rangee [data-cle="alertes-heures-calmes"] { border-bottom: 1px solid var(--gz-trait); }
  .section-rangee [data-cle="alertes-categories"] { grid-column: 1 / -1; border-left: none !important; border-bottom: 1px solid var(--gz-trait); }
  .section-rangee .alertes-categories { grid-template-columns: repeat(4, minmax(0, 1fr)); margin: 12px -20px -14px; border-top: 1px solid var(--gz-trait); }
  .section-rangee .alertes-categories .ligne { padding: 14px 16px; }
}
.heures-calmes-champs { display: flex; align-items: end; gap: 10px; margin-top: 12px; }
.heures-calmes-champs label { display: grid; gap: 5px; min-width: 0; color: var(--gz-doux); font-size: 12px; }
.heures-calmes-champs input { width: 126px; max-width: 100%; box-sizing: border-box; border: 1px solid var(--gz-trait); border-radius: 6px; padding: 8px; color: var(--gz-texte); background: var(--gz-carte); font: inherit; }
.profil-gazon { margin-bottom: 12px; }
.profil-gazon .section-tete { padding-bottom: 12px; }
.profils-selecteur {
  display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
  margin: 0 20px 16px; border: 1px solid var(--gz-trait); border-radius: 12px; overflow: hidden;
}
.profil-option {
  min-width: 0; min-height: 96px; padding: 10px 8px; border: 0; background: transparent;
  cursor: pointer; display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 3px; text-align: center; --mdc-icon-size: 22px;
}
.profil-option + .profil-option { border-left: 1px solid var(--gz-trait); }
.profil-option:hover:not([disabled]) { background: var(--gz-surface); }
.profil-option:focus-visible { outline: 2px solid var(--gz-accent); outline-offset: -3px; }
.profil-option[disabled] { cursor: default; opacity: 1; }
.profil-option.actif { background: var(--gz-accent-doux); color: var(--gz-accent-fort); }
:host([sombre]) .profil-option.actif { color: var(--gz-accent); }
.profil-option b { font-size: 14px; line-height: 1.25; }
.profil-option small { color: var(--gz-doux); font-size: 11.5px; line-height: 1.25; }
.profil-option-etat {
  display: inline-flex; align-items: center; gap: 3px; margin-top: 2px;
  color: var(--gz-doux); font-size: 11px; font-weight: 600; --mdc-icon-size: 13px;
}
.profil-option.actif .profil-option-etat { color: inherit; }
@container (max-width: 420px) {
  .heures-calmes-champs { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); align-items: end; }
  .heures-calmes-champs input { width: 100%; }
}
.alertes-categories { margin-top: 10px; }
.alertes-categories .ligne.compacte { padding-top: 12px; padding-bottom: 12px; }
/* Puces à cocher des alertes : de vrais boutons, pour passer par le même clic que le reste. */
.puces-bascule { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0 0 48px; }
.puce-bascule {
  font: inherit; font-size: 13.5px; cursor: pointer; color: inherit;
  display: inline-flex; align-items: center; gap: 4px; --mdc-icon-size: 16px;
  padding: 6px 12px; border-radius: 999px; border: 1px solid var(--gz-trait); background: var(--gz-carte);
}
.puce-bascule:hover:not([disabled]) { border-color: var(--gz-accent); }
.puce-bascule.active { background: var(--gz-accent-doux); border-color: var(--gz-accent); color: var(--gz-accent-fort); font-weight: 600; }
:host([sombre]) .puce-bascule.active { color: var(--gz-accent); }
.puce-bascule:focus-visible { outline: 2px solid var(--gz-accent); outline-offset: 2px; }
.puce-bascule[disabled] { cursor: default; opacity: .7; }
@media (max-width: 600px) { .puces-bascule { margin-left: 0; } }
/* Une question proposée est une phrase : elle passe à la ligne plutôt que de sortir de la fenêtre. */
.raccourcis.questions .petit-bouton { white-space: normal; text-align: start; max-width: 100%; }
.reponse-ia {
  border: 1px solid var(--gz-trait); border-radius: 14px; padding: 12px 14px;
  background: var(--gz-accent-doux); display: flex; flex-direction: column; gap: 6px;
}
.reponse-ia small { color: var(--gz-doux); font-size: 13px; }
.reponse-ia p { margin: 0; font-size: 15px; line-height: 1.55; }
.plan-zones { border: 1px solid var(--gz-trait); border-radius: 14px; overflow: hidden; }
.plan-zones .deroule { padding: 12px 14px; }
.plan-zones .vide { padding: 12px 14px; margin: 0; }
.choix-modes { display: flex; flex-direction: column; gap: 8px; }
.choix-mode { display: flex; gap: 10px; padding: 10px 12px; border: 1px solid var(--gz-trait); border-radius: 14px; cursor: pointer; align-items: flex-start; }
.choix-mode input { margin-top: 3px; accent-color: var(--gz-accent); flex: none; }
.choix-mode b { display: block; font-size: 15px; }
.choix-mode small { color: var(--gz-doux); font-size: 13px; line-height: 1.4; }
.choix-mode:has(input:checked) { border-color: var(--gz-accent); background: var(--gz-accent-doux); }
/* Réglages → Modes : une seule liste de modes, qui montre ; la carte d'action change. */
/* Neuf modes : une rangée sur grande page, trois fois trois en dessous. */
.modes-choix {
  display: grid; grid-template-columns: repeat(9, minmax(0, 1fr)); gap: 8px;
  margin: 0 0 16px;
}
.mode-puce {
  position: relative; min-width: 0; min-height: 76px; padding: 10px 8px 9px;
  border: 1px solid var(--gz-trait); border-radius: 14px; background: var(--gz-carte);
  color: var(--gz-texte); font: inherit; font-size: 13.5px; font-weight: 600; cursor: pointer;
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px; text-align: center;
  transition: border-color .16s, background .16s;
}
.mode-puce ha-icon { --mdc-icon-size: 22px; color: var(--gz-doux); }
.mode-puce:hover { border-color: var(--gz-accent); }
.mode-puce:focus-visible { outline: 2px solid var(--gz-accent); outline-offset: 2px; }
.mode-puce[aria-pressed="true"] { border: 2px solid var(--gz-accent); background: var(--gz-accent-doux); padding: 9px 7px 8px; }
.mode-puce[aria-pressed="true"] ha-icon { color: var(--gz-accent-fort); }
.mode-puce small { display: inline-flex; align-items: center; gap: 4px; font-size: 11.5px; font-weight: 600; color: var(--gz-accent-fort); }
.mode-puce small i { width: 7px; height: 7px; border-radius: 50%; background: var(--gz-accent); }
:host([sombre]) .mode-puce[aria-pressed="true"] ha-icon, :host([sombre]) .mode-puce small { color: var(--gz-accent); }
.mode-detail-tete { display: flex; gap: 14px; align-items: flex-start; padding: 18px 20px 6px; }
.mode-detail-tete h3 { margin: 0 0 4px; font-size: 18px; }
.mode-detail-tete p { margin: 0; color: var(--gz-doux); font-size: 14px; line-height: 1.45; max-width: 62ch; }
.mode-detail .regles-mode { padding: 6px 20px 12px; }
.mode-liens { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 4px 20px 18px; font-size: 14px; color: var(--gz-doux); }
.mode-action-corps { display: flex; flex-direction: column; align-items: stretch; gap: 10px; padding: 4px 20px 20px; }
.mode-action-corps > p { margin: 0; font-size: 14px; line-height: 1.45; color: var(--gz-doux); }
.mode-action-corps > .note { margin: 0; }
.mode-action-corps > button { display: flex; --mdc-icon-size: 20px; text-align: center; }
.mode-etat { font-weight: 600; color: var(--gz-texte) !important; }
.bouton-contour.danger { color: var(--gz-rouge); border-color: color-mix(in srgb, var(--gz-rouge) 45%, var(--gz-trait)); }
.mode-raccourci {
  min-width: 0; min-height: 92px; padding: 14px 16px; border: 0; border-top: 1px solid var(--gz-trait);
  background: transparent; color: inherit; cursor: pointer; text-align: left;
  display: grid; grid-template-columns: 36px minmax(0, 1fr) auto; gap: 10px; align-items: start;
  transition: background .16s, color .16s;
}
.mode-raccourci:not(:nth-child(3n + 1)) { border-left: 1px solid var(--gz-trait); }
.mode-raccourci:hover:not([disabled]) { background: var(--gz-surface); }
.mode-raccourci:focus-visible { outline: 2px solid var(--gz-accent); outline-offset: -3px; }
.mode-raccourci[disabled] { cursor: default; }
.mode-raccourci[disabled]:not(.actif) { opacity: .6; }
.mode-raccourci.actif { background: var(--gz-accent-doux); }
.mode-raccourci > ha-icon {
  width: 36px; height: 36px; border-radius: 10px; background: var(--gz-surface);
  color: var(--gz-accent-fort); align-items: center; justify-content: center;
}
:host([sombre]) .mode-raccourci > ha-icon { color: var(--gz-accent); }
.mode-raccourci-texte { min-width: 0; }
.mode-raccourci-texte b { display: block; font-size: 14.5px; line-height: 1.3; }
.mode-raccourci-texte small { display: block; margin-top: 3px; color: var(--gz-doux); font-size: 12.5px; line-height: 1.35; }
.mode-raccourci > .chevron { align-self: center; color: var(--gz-doux); --mdc-icon-size: 18px; }
.mode-confirmation { min-height: 0; border: 1px solid var(--gz-accent); border-radius: 8px; cursor: default; }
.choix-entite small { overflow-wrap: anywhere; }
.choix-entites .vide { padding: 4px 2px; }
.bouton-entree { margin-top: 8px; }
.bouton-plein.eau { background: var(--gz-eau); }
.bouton-plein.eau:hover { background: #2563eb; }
.bouton-plein.danger { background: var(--gz-rouge); }
.bouton-plein.danger:hover { background: #dc2626; }
/* Page moyenne : trois colonnes, pastilles couchées (l'icône à gauche du nom). */
@container page (max-width: 900px) {
  .modes-choix { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; }
  .mode-puce {
    min-height: 48px; padding: 7px 12px; text-align: left;
    display: grid; grid-template-columns: 22px minmax(0, 1fr); column-gap: 10px; row-gap: 0; align-content: center;
  }
  .mode-puce ha-icon { grid-row: 1 / span 2; }
  .mode-puce small { grid-column: 2; }
  .mode-puce[aria-pressed="true"] { padding: 6px 11px; }
}
/* Téléphone : trois colonnes, pastilles debout et compactes. */
@container page (max-width: 600px) {
  .mode-puce {
    min-height: 60px; padding: 8px 4px; text-align: center; font-size: 12.5px;
    display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 3px;
  }
  .mode-puce[aria-pressed="true"] { padding: 7px 3px; }
}
@media (max-width: 600px) {
  dialog.dialogue { width: 100vw; max-width: 100vw; margin: auto 0 0; border-radius: 22px 22px 0 0; max-height: 92vh; max-height: 92dvh; }
}

/* GRANDS ÉCRANS : plus serré, pour que la page descende moins. Le téléphone garde ses tailles. */
@container page (min-width: 901px) {
  .accueil { padding: 14px 18px; grid-template-columns: auto minmax(0, 1fr) minmax(0, auto); align-items: center; }
  .accueil-icone { width: 44px; height: 44px; border-radius: 14px; --mdc-icon-size: 26px; }
  .accueil h2 { font-size: 17px; margin-bottom: 2px; }
  .accueil p { font-size: 13.5px; }
  .accueil > .puces { grid-column: 3; margin: 0; justify-content: flex-end; max-width: 620px; }
  .ligne { padding: 12px 18px 10px; --bulle: 96px; }
  .ligne-tete { gap: 10px; }
  .ligne-icone { width: 32px; height: 32px; border-radius: 10px; --mdc-icon-size: 18px; }
  .ligne-textes h4 { font-size: 15px; margin: 0 0 2px; }
  .ligne-textes p { font-size: 13px; line-height: 1.4; }
  .reglette { margin-top: 6px; gap: 8px; }
  .pas-btn { width: 34px; height: 34px; }
  .curseur-zone, input[type="range"] { height: 34px; }
  .bulle { font-size: 16px; padding: 4px 10px; }
  .bulle-bas { min-width: 88px; }
  .ligne-pied { margin: 0 calc(42px + var(--bulle)) 0 42px; font-size: 12px; }
  .erreur, .avertissement-reglage, .etat-bascule { margin-left: 42px; }
  .section-tete { padding: 14px 18px 2px; }
  .section-tete h3 { font-size: 16.5px; }
  .section-tete p { font-size: 13.5px; }
  .dessin { padding: 10px 18px 2px; }
  .dessin + .lignes .ligne:first-child { margin-top: 8px; }
  .frise-piste { height: 36px; }
  .reperes { height: 24px; }
  .legende { margin-top: 8px; gap: 4px 14px; }
  .legende li { font-size: 13px; }
  .note { font-size: 13px; margin-top: 8px; }
  .mois-colonne { height: 120px; }
  .mois-editeur { margin-top: 10px; padding: 8px 12px; }
  .goutte-carte { padding: 10px 12px; }
}

/* Les couloirs de la mosaïque : --m sur une page moyenne, --l sur une grande. */
@container page (min-width: 901px) {
  .mosaique > .tesselle { grid-column: var(--m, 1 / -1); }
}
@container page (min-width: 1280px) {
  .mosaique > .tesselle { grid-column: var(--l, var(--m, 1 / -1)); }
}

@container page (max-width: 900px) {
  .en-ce-moment { grid-template-columns: minmax(0, 1fr); }
  .en-ce-moment h2 { font-size: 19px; }
  .en-ce-moment p { font-size: 13px; line-height: 1.35; }
  .meteo-temp { font-size: 22px; }
  .meteo { align-items: flex-start; text-align: left; }
  .meteo-ligne { justify-content: flex-start; }
}

/* Un cadre ÉTROIT, même sur ordinateur (couloir de droite) : la valeur passe au-dessus du curseur,
   comme sur un téléphone, et les boutons d'une zone passent sous son nom. */
@container (max-width: 460px) {
  .ligne { --bulle: 0px; }
  .bulle-haut { display: block; }
  .bulle-bas { display: none; }
  .ligne-pied { margin: 2px 0 0; }
  .erreur, .avertissement-reglage, .etat-bascule { margin-left: 0; }
  .zone { flex-wrap: wrap; }
  .zone-boutons { width: 100%; justify-content: flex-start; padding-left: 50px; }
}

@container page (max-width: 600px) {
  .contenu { padding: 12px 12px 140px; gap: 12px; }
  .mosaique { column-gap: 12px; }
  .mosaique > .tesselle { gap: 12px; }
  .onglets { margin: 0 -12px; padding: 8px 12px; }
  .profils-selecteur { margin: 0 16px 14px; }
  .profil-option { min-height: 88px; padding: 8px 4px; }
  .profil-option b { font-size: 13px; }
  .profil-option small { font-size: 10.5px; }
  .profil-option-etat { font-size: 10.5px; }
  .mode-raccourci { min-height: 0; }
  .mode-detail-tete { padding: 16px 16px 4px; }
  .mode-detail .regles-mode, .mode-liens, .mode-action-corps { padding-left: 16px; padding-right: 16px; }
  .accueil { padding: 16px; }
  .intro-reglages {
    padding: 12px; grid-template-columns: 38px minmax(0, 1fr); gap: 0 10px; align-items: center;
  }
  .intro-reglages .accueil-icone { width: 38px; height: 38px; border-radius: 11px; --mdc-icon-size: 22px; }
  .intro-reglages h2 { margin: 0; font-size: 16px; }
  .intro-reglages p { display: none; }
  .intro-reglages > .puces {
    grid-column: 1 / -1; flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none;
    margin: 9px -2px 0; padding: 0 2px 2px;
  }
  .intro-reglages > .puces::-webkit-scrollbar { display: none; }
  .intro-reglages .puce { flex: none; padding: 4px 8px; font-size: 12px; }
  .section-tete { padding: 16px 16px 2px; }
  .dessin { padding: 10px 16px 2px; }
  .ligne { padding: 14px 16px 12px; }
  .a-enregistrer { right: 16px; }
  .ligne-pied { margin: 2px 0 0; }
  .ligne { --bulle: 0px; }
  .bulle-haut { display: block; }
  .bulle-bas { display: none; }
  .erreur, .etat-bascule { margin-left: 0; }
  .ligne-textes h4 { font-size: 15.5px; }
  .bulle { min-width: 64px; font-size: 16px; padding: 6px 10px; }
  .etapes { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .gouttes { grid-template-columns: 1fr; }
  .rythme { gap: 2px; }
  .jour-nom { font-size: 9.5px; }
  .jour-rond { border-radius: 8px; --mdc-icon-size: 14px; }
  .mois-grille { gap: 3px; }
  .mois-valeur { font-size: 10px; }
  .escalier { gap: 5px; }
  .marche span { font-size: 11px; }
  .lame { flex-direction: column; gap: 6px; }
  .lame-carte { flex: none; }
  .lame-fleche { transform: rotate(90deg); }
  .onglet { padding: 9px 12px; font-size: 14px; }
  /* Base de contrôle */
  .en-ce-moment { padding: 10px 12px; gap: 7px; border-radius: 14px; }
  .maintenant-principal { gap: 8px; }
  .maintenant-sur {
    font-size: 9.5px; line-height: 1.2; white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis;
  }
  .en-ce-moment h2 { margin: 1px 0 2px; font-size: 16.5px; line-height: 1.15; }
  .en-ce-moment p { font-size: 11.75px; line-height: 1.3; }
  .maintenant-icone { width: 34px; height: 34px; border-radius: 10px; --mdc-icon-size: 20px; }
  .en-ce-moment .puces {
    display: flex; flex-wrap: nowrap; gap: 5px; margin-top: 7px;
    max-width: 100%; overflow-x: auto; scrollbar-width: none; overscroll-behavior-inline: contain;
  }
  .en-ce-moment .puces::-webkit-scrollbar, .meteo-ligne::-webkit-scrollbar { display: none; }
  .en-ce-moment .puce {
    flex: 0 0 auto; max-width: 260px; min-height: 24px; padding: 3px 7px;
    border-radius: 7px; font-size: 10.75px; line-height: 1.2; white-space: nowrap;
  }
  .meteo {
    display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 2px 10px;
    padding-top: 7px; border-top: 1px solid rgba(255, 255, 255, .24);
    align-items: center; text-align: left;
  }
  .meteo-haut { grid-row: 1 / span 2; gap: 0; --mdc-icon-size: 0; }
  .meteo-haut > ha-icon { display: none; }
  .meteo-temp { font-size: 17.5px; }
  .meteo-libelle { font-size: 10px; margin-top: 1px; }
  .meteo-ligne {
    display: flex; flex-wrap: nowrap; gap: 5px 10px; width: 100%;
    min-width: 0; overflow-x: auto; scrollbar-width: none; justify-content: flex-start;
  }
  .meteo-ligne span {
    flex: 0 0 auto; min-width: 0; min-height: 0; padding: 0; border-radius: 0;
    font-size: 10.75px; background: none; white-space: nowrap;
  }
  .meteo-ligne span:nth-child(n + 5) { display: none; }
  .meteo-heure { display: none; }
  .en-ce-moment .bouton-blanc {
    padding: 7px 10px; border-radius: 9px; font-size: 12.5px; --mdc-icon-size: 17px;
  }
  .en-ce-moment .maintenant-session { gap: 8px; margin-top: 7px; }
  .tuile-valeur { font-size: 19px; }
  .actions-grille { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; padding: 10px 16px 16px; }
  .action { min-height: 100px; padding: 12px; }
  .zone { padding: 12px 16px; flex-wrap: wrap; }
  .zone-boutons { width: 100%; justify-content: flex-start; padding-left: 50px; }
  .frise-ligne, .frise-heures { grid-template-columns: 70px minmax(0, 1fr); }
  .frise-zones { padding: 6px 16px 4px; }
  .frise-heures { padding: 0 16px; }
  .frise-vide, .totaux, .entete-journal { padding-left: 16px; padding-right: 16px; }
  .session { padding: 12px 16px; }
  .historique li { grid-template-columns: minmax(0, 1fr); gap: 2px; padding: 12px 16px; }
  .etat-bandeau, .machine, .budget, .reservoir, .travail, .pousse, .ligne-bascule,
  .liste-simple, .catalogue, .vide, details.pourquoi { padding-left: 16px; padding-right: 16px; }
  .rangee-boutons { padding: 4px 16px 16px; }
  .section .tuiles { padding: 10px 16px 16px; }
  .section .puces { padding: 0 16px 14px; }
  .bascule-vues button { padding: 7px 11px; }
  .barre h1 { font-size: 18px; }
  .accueil-titre-integration { display: none; }
}
@container page (max-width: 460px) {
  .barre:has(.bascule-vues) h1 {
    position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
    overflow: hidden; clip-path: inset(50%); white-space: nowrap; border: 0;
  }
  .barre:has(.bascule-vues) .bascule-vues { margin-left: auto; }
}

/* Typographie commune : la hiérarchie reste la même dans toutes les pages, mais elle s'adapte à
   la largeur réellement disponible dans Home Assistant. Les dimensions tactiles ne changent pas. */
.page { font-size: 13.5px; }
.barre h1 { font-size: 18px; }
.choix-instance, .bascule-vues button, .onglet { font-size: 13px; }
.recherche-reglages input { font-size: 14px; }
.resultat-titre, .intro-onglet p, .bouton-texte { font-size: 13.5px; }
.resultat-chemin, .puce, .groupe-installation h2 { font-size: 12px; }
.accueil h2, .produit-bandeau h2 { font-size: 17px; }
.en-ce-moment h2 { font-size: 20px; }
.en-ce-moment p { font-size: 13.5px; }
.accueil p, .section-tete p, .mode-detail-tete p, .mode-liens,
.mode-action-corps > p, .liste-simple li, details.pourquoi, .vide { font-size: 13px; }
.section-tete h3, .mode-detail-tete h3 { font-size: 16px; }
.ligne-textes h4, .historique b, .catalogue li b, .session-quand { font-size: 14.5px; }
.ligne-textes p, .legende li, .note, .erreur, .avertissement-reglage,
.lecture-seule, .frise-vide, .budget-chiffres { font-size: 12.5px; }
.ligne-textes p { overflow-wrap: anywhere; }
.bulle, .budget-chiffres b, .session-mm { font-size: 16px; }
.tuile-valeur, .etat-bandeau b, .machine-texte b { font-size: 19px; }
.tuile-valeur.petite { font-size: 16px; }
.pousse-texte b { font-size: 24px; }
.pousse-texte p, .etat-bandeau p, .machine-texte small { font-size: 13px; }
.lame-carte strong { font-size: 22px; }
.dose output { font-size: 26px; }
.meteo-temp { font-size: 24px; }
.meteo-grande { font-size: 38px; }
.meteo-etat { font-size: 15px; }
.mesure-meteo > b { font-size: 15px; }
.jours-meteo li, .lignes-meteo li > span, .entrees-meteo { font-size: 13px; }
.lignes-meteo li > b { font-size: 14.5px; }
.action b { font-size: 14px; }
.action small, .session-quoi, .historique time, .historique .meta,
.catalogue li, .note-produit, .totaux, .reservoir-legende { font-size: 12px; }
.bouton-plein, .bouton-contour { font-size: 14px; }
.petit-bouton, .bouton-blanc { font-size: 13px; }
.barre-enregistrer .resume, .toast { font-size: 13.5px; }
.barre-enregistrer .resume small { font-size: 12px; }
.dialogue-tete h2 { font-size: 18px; }
.dialogue-corps > p { font-size: 13.5px; }
.champ > label, .champ > span, .case, .choix-mode b { font-size: 14px; }
.champ small, .case small, .choix-mode small { font-size: 12.5px; }
.mode-raccourci-texte b { font-size: 14px; }
.mode-raccourci-texte small { font-size: 12px; }

@container page (max-width: 900px) {
  .page { font-size: 13.25px; }
  .barre h1 { font-size: 17.5px; }
  .accueil h2, .produit-bandeau h2 { font-size: 16.5px; }
  .en-ce-moment h2 { font-size: 18px; }
  .en-ce-moment p { font-size: 12.75px; }
  .section-tete h3, .mode-detail-tete h3 { font-size: 15.5px; }
  .ligne-textes h4, .historique b, .catalogue li b, .session-quand { font-size: 14px; }
  .tuile-valeur, .etat-bandeau b, .machine-texte b { font-size: 18px; }
  .pousse-texte b { font-size: 22px; }
  .lame-carte strong { font-size: 21px; }
  .dose output { font-size: 25px; }
  .meteo-temp { font-size: 21px; }
  .meteo-grande { font-size: 34px; }
}

@container page (max-width: 600px) {
  .page { font-size: 13px; }
  .barre h1 { font-size: 17px; }
  .choix-instance, .bascule-vues button, .onglet { font-size: 12.5px; }
  /* 16 px empêche le navigateur mobile de zoomer au focus d'un champ. */
  .recherche-reglages input,
  .champ input:not([type="checkbox"]):not([type="radio"]), .champ select, .champ textarea { font-size: 16px; }
  .resultat-titre, .intro-onglet p, .bouton-texte { font-size: 13px; }
  .accueil h2, .produit-bandeau h2 { font-size: 16px; }
  .en-ce-moment h2 { font-size: 16.5px; }
  .en-ce-moment p { font-size: 11.75px; }
  .accueil p, .section-tete p, .mode-detail-tete p, .mode-liens,
  .mode-action-corps > p, .liste-simple li, details.pourquoi, .vide { font-size: 12.5px; }
  .section-tete h3, .mode-detail-tete h3 { font-size: 15px; }
  .ligne-textes h4, .historique b, .catalogue li b, .session-quand { font-size: 14px; }
  .ligne-textes p, .legende li, .note, .erreur, .avertissement-reglage,
  .lecture-seule, .frise-vide, .budget-chiffres { font-size: 12px; }
  .bulle, .budget-chiffres b, .session-mm { font-size: 15px; }
  .tuile-valeur, .etat-bandeau b, .machine-texte b { font-size: 17px; }
  .tuile-valeur.petite { font-size: 15px; }
  .pousse-texte b { font-size: 20px; }
  .pousse-texte p, .etat-bandeau p, .machine-texte small { font-size: 12.5px; }
  .lame-carte strong { font-size: 20px; }
  .dose output { font-size: 24px; }
  .meteo-temp { font-size: 17.5px; }
  .meteo-grande { font-size: 30px; }
  .meteo-etat { font-size: 14px; }
  .mesure-meteo > b { font-size: 14px; }
  .jours-meteo li, .lignes-meteo li > span, .entrees-meteo { font-size: 12.5px; }
  .lignes-meteo li > b { font-size: 14px; }
  .action b { font-size: 13.5px; }
  .bouton-plein, .bouton-contour { font-size: 13.5px; }
}
:host([narrow]) .dialogue-tete h2 { font-size: 17px; }
:host([narrow]) .dialogue-corps > p { font-size: 12.5px; }
:host([narrow]) .champ > label, :host([narrow]) .champ > span,
:host([narrow]) .case, :host([narrow]) .choix-mode b { font-size: 13.5px; }
:host([narrow]) .champ small, :host([narrow]) .case small,
:host([narrow]) .choix-mode small { font-size: 12px; }
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { transition: none !important; animation: none !important; scroll-behavior: auto !important; }
}
`;

// ─── Le composant ────────────────────────────────────────────────────────────────────────

class GazonIntelligentPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._narrow = false;
    this._etat = "chargement"; // chargement | pret | erreur
    this._messageErreur = "";
    this._donnees = null; // réponse de `reglages/get`
    this._vue = "accueil"; // accueil | reglages
    this._ongletAccueil = "apercu";
    this._brouillon = {}; // réglages du registre modifiés, pas encore enregistrés
    this._brouillonEntites = {}; // réglages de l'installation modifiés
    this._brouillonChoix = {}; // choix modifiés (type de sol), pas encore enregistrés
    this._brouillonAlertes = {}; // téléphones, alertes, IA modifiés (0.93.0), pas encore enregistrés
    this._brouillonPompe = undefined; // pompe choisie (0.94.0) : undefined = pas de changement, "" = aucune
    this._brouillonGarageTondeuse = undefined;
    this._attenteEntites = {}; // valeurs envoyées, en attente du retour d'état
    this._onglet = "tonte";
    this._rechercheReglages = ""; // barre de recherche des réglages, tous onglets confondus
    this._modeReglage = null; // mode regardé dans Réglages → Modes (par défaut : celui du moment)
    this._moisChoisi = {}; // clé du tableau → mois choisi (0 à 11)
    this._enregistrement = false;
    this._refs = null;
    this._minuteurToast = null;
    this._dialogue = null;
    this._historique = null; // entity_id → [{debut, fin}] (ms)
    this._historiqueDate = 0;
    this._prevision = null;
    this._previsionDate = 0;
    this._historiqueTout = false;
    this._commandesEnCours = new Set();
    // Squelette PERSISTANT : seule la page est reconstruite. La barre d'enregistrement garde son
    // animation d'entrée, un message affiché survit à une mise à jour de Home Assistant, et une
    // fenêtre ouverte n'est jamais recréée pendant qu'on y tape.
    this.shadowRoot.innerHTML = `<style>${STYLES}</style>
      <div class="page"></div>
      <div class="barre-enregistrer" role="region" aria-label="Changements"></div>
      <div class="toast" role="status" aria-live="polite"></div>
      <dialog class="dialogue" aria-labelledby="titre-dialogue"></dialog>`;
    this._page = this.shadowRoot.querySelector(".page");
    this._barre = this.shadowRoot.querySelector(".barre-enregistrer");
    this._toast = this.shadowRoot.querySelector(".toast");
    this._fenetre = this.shadowRoot.querySelector("dialog");
    // `close` arrive APRÈS COUP : si une autre fenêtre s'est ouverte entre-temps, son état reste.
    this._fenetre.addEventListener("close", () => {
      if (!this._fenetre.open) this._dialogue = null;
    });
    this.shadowRoot.addEventListener("click", (e) => this._surClic(e));
    this.shadowRoot.addEventListener("input", (e) => this._surSaisie(e));
    this.shadowRoot.addEventListener("change", (e) => this._surChangement(e));

    // ⚠️ ON NE REMPLACE RIEN SOUS LE DOIGT (leçon de la carte, 10/09/2026). Un `click` n'existe
    // que si l'appui et le relâchement tombent sur le MÊME élément : un rendu entre les deux le
    // supprime. Tout rendu dû à Home Assistant attend donc la fin du geste. C'est le `click` qui
    // libère (après sa propre tâche), `pointerup` n'est qu'un filet, et deux secondes au plus
    // évitent une page figée si aucun des deux n'arrive.
    this._gesteEnCours = false;
    this._renduEnAttente = false;
    this._relacher = () => {
      if (!this._gesteEnCours) return;
      this._gesteEnCours = false;
      clearTimeout(this._filetGeste);
      this._rendreSiEnAttente();
    };
    // ⚠️ NI PENDANT UN DÉFILEMENT (0.94.1). Une position remise pendant que le doigt, la molette
    // ou l'élan fait défiler ne tient pas : un rendu à ce moment-là laissait la page tout en haut
    // (17/09, onglet Météo redessiné à chaque relevé de la station). Le rendu attend que
    // rien n'ait bougé depuis 400 ms.
    this._defilementEnCours = false;
    this._page.addEventListener("scroll", () => {
      this._defilementEnCours = true;
      clearTimeout(this._finDefilement);
      this._finDefilement = setTimeout(() => {
        this._defilementEnCours = false;
        this._rendreSiEnAttente();
      }, 400);
    }, { passive: true });
    this.shadowRoot.addEventListener("pointerdown", () => {
      this._gesteEnCours = true;
      clearTimeout(this._filetGeste);
      this._filetGeste = setTimeout(this._relacher, 2000);
    }, true);
    this.shadowRoot.addEventListener("click", () => setTimeout(this._relacher, 0), true);
    this._surPointeurRelache = () => {
      clearTimeout(this._apresGeste);
      this._apresGeste = setTimeout(this._relacher, 150);
    };

    this._avantDepart = (e) => {
      if (this._nombreChangements() > 0) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    // Les étiquettes des frises sont rangées d'après la largeur : on redessine quand elle change.
    this._largeurConnue = 0;
    this._observateur = typeof ResizeObserver === "function"
      ? new ResizeObserver(() => {
        const largeur = this._page.clientWidth;
        this.style.setProperty("--gz-page-width", `${largeur}px`);
        if (this._etat !== "pret" || Math.abs(largeur - this._largeurConnue) < 24) return;
        this._largeurConnue = largeur;
        this._rafraichirDessins();
      })
      : null;
    // Une case de la mosaïque qui grandit (note dépliée, dessin redessiné, autre largeur) reprend
    // aussitôt la bonne hauteur.
    this._observateurCases = typeof ResizeObserver === "function"
      ? new ResizeObserver((entrees) => this._caserMosaique(entrees.map((e) => e.target)))
      : null;
  }

  connectedCallback() {
    this.style.setProperty("--gz-page-width", `${this._page.clientWidth}px`);
    this._observateur?.observe(this._page);
    for (const c of this._page.querySelectorAll(".mosaique > .tesselle")) this._observateurCases?.observe(c);
    window.addEventListener("beforeunload", this._avantDepart);
    window.addEventListener("pointerup", this._surPointeurRelache, true);
    window.addEventListener("pointercancel", this._relacher, true);
    clearInterval(this._minuteur);
    this._minuteur = setInterval(() => this._tic(), 1000);
  }

  disconnectedCallback() {
    this._observateur?.disconnect();
    this._observateurCases?.disconnect();
    window.removeEventListener("beforeunload", this._avantDepart);
    window.removeEventListener("pointerup", this._surPointeurRelache, true);
    window.removeEventListener("pointercancel", this._relacher, true);
    clearInterval(this._minuteur);
    // ⚠️ Les arrêts différés du bouton « 5 min » ne sont PAS annulés : quitter la page ne doit
    // pas laisser une vanne ouverte. Ils partent même page fermée (voir `_signalerEchec`).
  }

  set hass(hass) {
    const premier = !this._hass;
    this._hass = hass;
    this.toggleAttribute("sombre", Boolean(hass?.themes?.darkMode));
    if (premier) {
      this._rendre();
      this._charger();
      return;
    }
    this._oublierAttentesArrivees();
    const sombreAvant = this._sombreConnu;
    if (this._etat !== "pret" || !this._aChange()) return;
    const themeChange = sombreAvant !== this._sombreConnu;
    if (this._vue === "reglages" && !themeChange) {
      this._rafraichirValeursReglages();
      return;
    }
    this._rendreQuandLibre();
  }

  get hass() {
    return this._hass;
  }

  set narrow(valeur) {
    const avant = this._narrow;
    this._narrow = Boolean(valeur);
    this.toggleAttribute("narrow", this._narrow);
    if (avant !== this._narrow && this._hass) this._rendre();
  }

  get narrow() {
    return this._narrow;
  }

  set panel(panel) {
    this._panel = panel;
  }

  // Home Assistant passe le chemin sous le panneau : « /reglages » ouvre les réglages, le reste
  // la base de contrôle. Le bouton « retour » du navigateur fonctionne donc entre les deux.
  set route(route) {
    this._route = route;
    const vue = String(route?.path || "").startsWith("/reglages") ? "reglages" : "accueil";
    if (vue !== this._vue) {
      this._vue = vue;
      if (this._hass && this._etat === "pret") this._rendre();
    }
  }

  _choisirVue(vue) {
    if (vue === this._vue) return;
    this._vue = vue;
    const prefixe = this._route?.prefix;
    if (prefixe) {
      const cible = vue === "reglages" ? `${prefixe}/reglages` : prefixe;
      if (window.location.pathname !== cible) {
        window.history.pushState(null, "", cible);
        window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
      }
    }
    this._rendre();
    this._page.scrollTo({ top: 0 });
  }

  // Une seconde : les chronomètres des vannes. Trente secondes : l'heure affichée. Et, quand leur
  // délai est passé, l'historique des vannes (5 min) et la prévision météo (30 min).
  _tic() {
    if (this._etat !== "pret" || this._vue !== "accueil") return;
    const maintenant = Date.now();
    for (const el of this._page.querySelectorAll("[data-chrono]")) {
      const depuis = Date.parse(el.dataset.chrono);
      if (Number.isFinite(depuis)) el.textContent = chronoFr(maintenant - depuis);
    }
    if (maintenant - (this._dernierTicLent || 0) >= 30000) {
      this._dernierTicLent = maintenant;
      for (const el of this._page.querySelectorAll("[data-heure]")) el.textContent = this._texteHeure();
      this._chargerPrevision();
      if (this._ongletAccueil === "arrosage") this._chargerHistorique();
    }
  }

  // ── Données ──

  async _charger(entryId) {
    this._etat = "chargement";
    this._rendre();
    try {
      const message = { type: WS_LIRE };
      const voulu = entryId || this._panel?.config?.entry_id;
      if (voulu) message.entry_id = voulu;
      const donnees = await this._hass.callWS(message);
      this._donnees = donnees;
      this._brouillon = {};
      this._brouillonEntites = {};
      this._brouillonChoix = {};
      this._brouillonAlertes = {};
      this._brouillonPompe = undefined;
      this._brouillonGarageTondeuse = undefined;
      this._attenteEntites = {};
      this._etat = "pret";
      if (!this._groupeExiste(this._onglet)) this._onglet = donnees.registre.groupes[0]?.cle || ONGLET_INSTALLATION.cle;
      this._refs = null;
      this._aChange();
      this._chargerPrevision();
    } catch (e) {
      this._etat = "erreur";
      this._messageErreur = erreurLisible(e);
    }
    this._rendre();
  }

  _groupeExiste(cle) {
    return cle === ONGLET_INSTALLATION.cle || Boolean(this._donnees?.registre.groupes.some((g) => g.cle === cle));
  }

  get _registre() {
    return this._donnees.registre;
  }

  _reglage(cle) {
    if (!this._parCle || this._parCleSource !== this._donnees) {
      this._parCle = new Map(this._registre.reglages.map((r) => [r.cle, r]));
      this._parCleSource = this._donnees;
    }
    return this._parCle.get(cle);
  }

  _defaut(cle) {
    return this._reglage(cle).defaut;
  }

  _enregistree(cle) {
    const v = this._donnees.valeurs?.[cle];
    return v === undefined ? this._defaut(cle) : v;
  }

  _valeur(cle) {
    return cle in this._brouillon ? this._brouillon[cle] : this._enregistree(cle);
  }

  _toutesLesValeurs() {
    const v = {};
    for (const r of this._registre.reglages) v[r.cle] = this._valeur(r.cle);
    return v;
  }

  _changer(cle, valeur) {
    if (egal(valeur, this._enregistree(cle))) delete this._brouillon[cle];
    else this._brouillon[cle] = copie(valeur);
  }

  _entite(cle) {
    const id = this._donnees?.entites?.[cle];
    return id ? this._hass.states[id] : undefined;
  }

  _valeurEntite(cle) {
    if (cle in this._brouillonEntites) return this._brouillonEntites[cle];
    if (cle in this._attenteEntites) return this._attenteEntites[cle].valeur;
    return this._valeurEntiteReelle(cle);
  }

  _valeurEntiteReelle(cle) {
    const etat = this._entite(cle);
    if (!etat) return undefined;
    if (this._donnees.entites[cle].startsWith("switch.")) return etat.state === "on";
    const n = Number.parseFloat(etat.state);
    return Number.isFinite(n) ? n : undefined;
  }

  _oublierAttentesArrivees() {
    const maintenant = Date.now();
    for (const [cle, attente] of Object.entries(this._attenteEntites)) {
      if (egal(this._valeurEntiteReelle(cle), attente.valeur) || maintenant - attente.depuis > 15000) {
        delete this._attenteEntites[cle];
      }
    }
  }

  // Tout ce que la page lit dans Home Assistant.
  _etatsSuivis() {
    const ids = new Set(Object.values(this._donnees?.entites || {}));
    for (const z of this._donnees?.zones || []) {
      if (z.switch) ids.add(z.switch);
      if (z.etat) ids.add(z.etat);
    }
    if (this._donnees?.pompe) ids.add(this._donnees.pompe);
    if (this._donnees?.meteo) ids.add(this._donnees.meteo);
    if (this._vue === "reglages" && this._onglet === ONGLET_ENTITES.cle) {
      for (const source of [...(this._donnees?.sources || []), ...(this._donnees?.liaisons_materiel || [])]) {
        if (source.entity_id) ids.add(source.entity_id);
      }
      if (this._donnees?.garage_tondeuse?.choisie) ids.add(this._donnees.garage_tondeuse.choisie);
    }
    // Onglet Météo ouvert : ses entrées aussi (le vent bouge toutes les minutes, pas besoin de
    // redessiner les autres onglets pour autant). Leurs voisines se relisent au même moment.
    if (this._vue === "accueil" && this._ongletAccueil === "meteo") {
      for (const s of this._donnees?.sources || []) if (s.entity_id) ids.add(s.entity_id);
    }
    ids.add("sun.sun");
    return [...ids];
  }

  // Home Assistant remplace l'objet d'état d'une entité qui change, et garde les autres tels quels :
  // comparer les RÉFÉRENCES suffit, sans sérialiser des attributs de plusieurs kilo-octets à
  // chacune des mises à jour de la maison (plusieurs par seconde).
  _aChange() {
    const refs = this._etatsSuivis().map((id) => this._hass?.states?.[id]);
    const sombre = Boolean(this._hass?.themes?.darkMode);
    const change = !this._refs || this._sombreConnu !== sombre
      || refs.length !== this._refs.length || refs.some((r, i) => r !== this._refs[i]);
    this._refs = refs;
    this._sombreConnu = sombre;
    return change;
  }

  _nombreChangements() {
    return Object.keys(this._brouillon).length + Object.keys(this._brouillonEntites).length
      + Object.keys(this._brouillonChoix).length + Object.keys(this._brouillonAlertes).length
      + (this._brouillonPompe !== undefined ? 1 : 0)
      + (this._brouillonGarageTondeuse !== undefined ? 1 : 0);
  }

  _estAdmin() {
    return this._hass?.user?.is_admin !== false;
  }

  // ── Contexte réel : soleil, mode, semis ──

  _fuseau() {
    return this._hass?.config?.time_zone;
  }

  _soleil() {
    const s = this._hass?.states?.["sun.sun"];
    const lever = s?.attributes?.next_rising;
    const coucher = s?.attributes?.next_setting;
    if (!lever || !coucher) return null;
    const fuseau = this._fuseau();
    return {
      lever: partiesLocales(new Date(lever), fuseau).minute,
      coucher: partiesLocales(new Date(coucher), fuseau).minute,
    };
  }

  _contexte() {
    const fuseau = this._fuseau();
    const maintenant = partiesLocales(new Date(), fuseau);
    const mode = this._entite("mode")?.state;
    const hauteur = this._entite("hauteur_tonte");
    const a = hauteur?.attributes || {};
    const age = Number(a.semis_age_jours);
    const semis = a.semis_mode && Number.isFinite(age)
      ? { mode: a.semis_mode, age, coupes: Number(a.plantules_coupes) || 0 }
      : null;
    const conseillee = Number.parseFloat(hauteur?.state);
    const joursRestants = nombreOuNul(this._a("phase", "jours_restants"));
    return {
      maintenant,
      soleil: this._soleil(),
      mode,
      semis,
      // Combien de jours il reste au mode actif (Traitement, Fertilisation…) : absent pour
      // Normal (mode.jours_restants = 0) et sans objet pour l'Hivernage (durée non bornée).
      joursRestantsMode: mode && !semis && mode !== "Normal" && mode !== "Hivernage" ? joursRestants : null,
      hauteurConseillee: Number.isFinite(conseillee) ? conseillee : null,
      motif: a.hauteur_tonte_motif,
    };
  }

  // ── Rendu ──

  // Un rendu dû à Home Assistant (ou à une réponse qui arrive) attend la fin du geste et du défilement.
  _rendreQuandLibre() {
    if (this._gesteEnCours || this._defilementEnCours) this._renduEnAttente = true;
    else this._rendre();
  }

  _rendreSiEnAttente() {
    if (!this._renduEnAttente || this._gesteEnCours || this._defilementEnCours) return;
    this._renduEnAttente = false;
    setTimeout(() => this._rendre(), 0);
  }

  _rendre() {
    const defilement = this._page.scrollTop;
    const lateraux = new Map([...this._page.querySelectorAll("[data-garde-defilement]")].map((el) => [el.dataset.gardeDefilement, el.scrollLeft]));
    const focus = this._memoriserFocus();
    // ⚠️ LA PAGE NE SE TASSE PAS PENDANT LE RENDU (0.94.1). Une case neuve n'a pas encore sa
    // hauteur (une rangée de 4 px) : mesuré le 17/09 dans l'onglet Météo, la page tombait de
    // 3 688 à 1 671 px le temps de mesurer, et le défilement reculait d'autant. La page garde donc
    // sa hauteur, et chaque case reprend d'abord la hauteur de celle qu'elle remplace.
    const hauteurAvant = this._page.querySelector(":scope > main.contenu")?.offsetHeight || 0;
    const rangeesAvant = [...this._page.querySelectorAll(".mosaique > .tesselle")].map((c) => c.style.gridRowEnd);
    let corps;
    try {
      corps = this._corpsHtml();
    } catch (e) {
      // Un rendu qui plante laissait l'ancien écran en place : un clic « qui ne fait rien ».
      console.error("Réglages du gazon : rendu impossible", e);
      corps = `<div class="etat-page">
        <ha-icon icon="mdi:alert-circle-outline" style="--mdc-icon-size:40px"></ha-icon>
        <h2>Cette partie de la page n'a pas pu s'afficher</h2>
        <p>${esc(erreurLisible(e))}</p>
        <button class="bouton-plein" data-action="recharger">Recharger</button>
      </div>`;
    }
    this._observateurCases?.disconnect();
    this._page.innerHTML = `${this._barreHtml()}<main class="contenu"${hauteurAvant ? ` style="min-height:${hauteurAvant}px"` : ""}>${corps}</main>`;
    // Les cases prennent leur hauteur AVANT de rendre la position : sinon la page, encore
    // tassée, ramènerait le défilement vers le haut.
    const cases = [...this._page.querySelectorAll(".mosaique > .tesselle")];
    cases.forEach((c, i) => {
      if (rangeesAvant[i]) c.style.gridRowEnd = rangeesAvant[i];
    });
    this._caserMosaique(cases);
    for (const c of cases) this._observateurCases?.observe(c);
    if (this._page.scrollTop !== defilement) this._page.scrollTop = defilement;
    this._page.querySelector(":scope > main.contenu")?.style.removeProperty("min-height");
    for (const el of this._page.querySelectorAll("[data-garde-defilement]")) {
      const x = lateraux.get(el.dataset.gardeDefilement);
      if (x) el.scrollLeft = x;
    }
    this._majBarre();
    this._restaurerFocus(focus);
  }

  // Chaque case descend d'autant de rangées que sa hauteur, plus l'écart entre deux cadres.
  // Toutes les hauteurs sont lues AVANT la première écriture : une seule mise en page.
  _caserMosaique(cases) {
    const ecarts = new Map();
    const mesures = cases.filter((c) => c.isConnected && c.parentElement).map((c) => {
      const grille = c.parentElement;
      if (!ecarts.has(grille)) ecarts.set(grille, Number.parseFloat(getComputedStyle(grille).columnGap) || 16);
      const hauteur = c.getBoundingClientRect().height;
      return [c, `span ${Math.max(1, Math.ceil((hauteur + ecarts.get(grille)) / RANGEE_MOSAIQUE_PX))}`];
    });
    for (const [c, rangees] of mesures) {
      if (c.style.gridRowEnd !== rangees) c.style.gridRowEnd = rangees;
    }
  }

  // Une case : `[html, couloir sur grande page, couloir sur page moyenne]`. Vide, elle disparaît.
  _mosaique(cases) {
    const pleines = cases.filter((c) => c && String(c[0] || "").trim());
    if (!pleines.length) return "";
    return `<div class="mosaique">${pleines.map(([html, l, m]) =>
      `<div class="tesselle" style="--l:${COULOIRS[l]};--m:${COULOIRS[m || l]}">${html}</div>`).join("")}</div>`;
  }

  _memoriserFocus() {
    const actif = this.shadowRoot.activeElement;
    if (!actif) return null;
    const ligne = actif.closest?.("[data-cle]");
    return {
      cle: ligne?.dataset.cle,
      action: actif.dataset?.action,
      mois: actif.dataset?.mois,
      onglet: actif.dataset?.onglet,
      range: actif.matches?.('input[type="range"]'),
    };
  }

  _restaurerFocus(f) {
    if (!f) return;
    let cible = null;
    if (f.onglet) cible = this.shadowRoot.querySelector(`[data-onglet="${f.onglet}"]`);
    else if (f.mois !== undefined) cible = this.shadowRoot.querySelector(`[data-cle="${f.cle}"] [data-mois="${f.mois}"]`);
    else if (f.cle) {
      const ligne = this.shadowRoot.querySelector(`[data-cle="${f.cle}"]`);
      if (ligne) cible = f.range ? ligne.querySelector('input[type="range"]') : ligne.querySelector(`[data-action="${f.action}"]`);
    }
    cible?.focus({ preventScroll: true });
  }

  _barreHtml() {
    const instances = this._donnees?.instances || [];
    const choix = instances.length > 1
      ? `<select class="choix-instance" data-role="instance" aria-label="Quel gazon ?">
          ${instances.map((i) => `<option value="${esc(i.entry_id)}" ${i.entry_id === this._donnees.entry_id ? "selected" : ""}>${esc(i.titre)}</option>`).join("")}
        </select>`
      : "";
    const menu = this._narrow
      ? `<button class="bouton-rond" data-action="menu" aria-label="Ouvrir le menu"><ha-icon icon="mdi:menu"></ha-icon></button>`
      : "";
    const vues = this._etat === "pret"
      ? `<nav class="bascule-vues" aria-label="Pages">
          <button data-vue="accueil" aria-current="${this._vue === "accueil" ? "page" : "false"}"><ha-icon icon="mdi:home-variant-outline"></ha-icon>Accueil</button>
          <button data-vue="reglages" aria-current="${this._vue === "reglages" ? "page" : "false"}"><ha-icon icon="mdi:tune-variant"></ha-icon>Réglages</button>
        </nav>`
      : "";
    const titre = this._donnees?.titre || "Gazon";
    return `<header class="barre">${menu}<h1>${esc(titre)}</h1>${vues}${choix}</header>`;
  }

  _corpsHtml() {
    if (this._etat === "chargement") {
      return `<div class="etat-page"><ha-icon icon="mdi:sprout" style="--mdc-icon-size:40px"></ha-icon><h2>Un instant…</h2><p>Lecture des réglages du gazon.</p></div>`;
    }
    if (this._etat === "erreur") {
      return `<div class="etat-page">
        <ha-icon icon="mdi:alert-circle-outline" style="--mdc-icon-size:40px"></ha-icon>
        <h2>Impossible de lire les réglages</h2>
        <p>${esc(this._messageErreur)}</p>
        <button class="bouton-plein" data-action="recharger">Réessayer</button>
      </div>`;
    }
    return this._vue === "reglages" ? this._corpsReglagesHtml() : this._corpsAccueilHtml();
  }

  _corpsReglagesHtml() {
    // Les réglages « graines » sont communs aux deux programmes. Les laisser dans un troisième
    // onglet rendait Semis et Sursemis artificiellement incomplets ; ils sont désormais affichés
    // dans chacun de ces deux onglets, avec une seule valeur réellement enregistrée.
    const groupes = this._registre.groupes.filter((g) => g.cle !== "graines");
    if (!groupes.some((g) => g.cle === ONGLET_INSTALLATION.cle)) groupes.push(ONGLET_INSTALLATION);
    if (!groupes.some((g) => g.cle === ONGLET_ENTITES.cle)) groupes.push(ONGLET_ENTITES);
    const courant = groupes.find((g) => g.cle === this._onglet) || groupes[0];
    return `
      ${this._introReglagesHtml()}
      ${this._estAdmin() ? "" : `<div class="lecture-seule">Seul un administrateur de Home Assistant peut modifier ces réglages. La consultation reste disponible.</div>`}
      ${this._rechercheReglagesHtml()}
      ${this._profilGazonHtml()}
      <nav class="onglets" role="tablist" aria-label="Familles de réglages">
        ${groupes.map((g) => this._ongletHtml(g, g.cle === courant.cle)).join("")}
      </nav>
      <div role="tabpanel" aria-label="${esc(courant.titre)}" style="display:flex;flex-direction:column;gap:16px">
        ${courant.cle === ONGLET_INSTALLATION.cle ? this._installationHtml()
          : courant.cle === ONGLET_ENTITES.cle ? this._entitesHtml()
          : this._groupeHtml(courant)}
      </div>`;
  }

  // Figé tant que `_donnees` ne change pas (chargement, changement de pelouse, sauvegarde) :
  // sinon ce bandeau, nourri par le moteur de décision, se redessine à chaque cycle (~2 min) même
  // pendant que l'utilisateur règle un curseur plus bas, et décale toute la page sans qu'il ait touché à
  // rien (rapporté le 19/09/2026 : « pourquoi ma page bouge tout seul », sur toutes les pages de
  // réglages puisqu'il est commun à tous les onglets).
  _introReglagesHtml() {
    if (this._introFigeeSource !== this._donnees) {
      this._introFigeeHtml = this._calculerIntroReglagesHtml();
      this._introFigeeSource = this._donnees;
    }
    return this._introFigeeHtml;
  }

  _calculerIntroReglagesHtml() {
    const c = this._contexte();
    const puces = [];
    if (c.mode) puces.push(`<span class="puce accent"><ha-icon icon="mdi:grass"></ha-icon>Mode <b>${esc(c.mode)}</b>${c.semis ? ` · jour ${c.semis.age}` : ""}</span>`);
    if (c.hauteurConseillee !== null) puces.push(`<span class="puce"><ha-icon icon="mdi:ruler"></ha-icon>Hauteur conseillée <b>${esc(cmFr(c.hauteurConseillee))}</b></span>`);
    puces.push(...this._pucesProgrammeGraines(c));
    puces.push(...this._pucesProgrammeMode(c));
    if (c.soleil) puces.push(`<span class="puce"><ha-icon icon="mdi:weather-sunny"></ha-icon>Soleil <b>${heureFr(c.soleil.lever)} → ${heureFr(c.soleil.coucher)}</b></span>`);
    const perso = this._registre.reglages.filter((r) => !egal(this._enregistree(r.cle), r.defaut)).length;
    puces.push(`<span class="puce"><ha-icon icon="mdi:tune-variant"></ha-icon>${perso === 0 ? "Tout est sur les valeurs conseillées" : `<b>${perso}</b> réglage${perso > 1 ? "s" : ""} personnalisé${perso > 1 ? "s" : ""}`}</span>`);
    const titre = this._donnees.titre
      ? `<span class="accueil-titre-integration"> · ${esc(this._donnees.titre)}</span>`
      : "";
    return `<section class="accueil intro-reglages">
      <div class="accueil-icone"><ha-icon icon="mdi:sprout"></ha-icon></div>
      <div>
        <h2>Réglages du gazon${titre}</h2>
        <p>Chaque réglage répond à une question. Déplacer le curseur permet de voir le résultat avant d'utiliser « Enregistrer ». Le bouton « Revenir » restaure la valeur conseillée.</p>
      </div>
      <div class="puces">${puces.join("")}</div>
    </section>`;
  }

  _profilGazonHtml() {
    const admin = this._estAdmin();
    const profils = PROFILS_GAZON.map((profil) => {
      const cles = Object.keys(profil.valeurs).filter((cle) => this._reglage(cle));
      if (!cles.length) return "";
      const choix = Object.entries(profil.choix || {}).filter(([cle]) => (this._registre.choix || []).some((c) => c.cle === cle));
      const actif = cles.every((cle) => egal(this._valeur(cle), profil.valeurs[cle]))
        && choix.every(([cle, valeur]) => this._valeurChoix(cle) === valeur);
      const modifie = cles.filter((cle) => !egal(this._valeur(cle), profil.valeurs[cle])).length
        + choix.filter(([cle, valeur]) => this._valeurChoix(cle) !== valeur).length;
      const etat = actif
        ? `<ha-icon icon="mdi:check-circle"></ha-icon>Actif`
        : `<ha-icon icon="mdi:arrow-right-circle-outline"></ha-icon>Appliquer · ${modifie}`;
      return `<button class="profil-option${actif ? " actif" : ""}" data-action="profil-gazon"
        data-profil="${esc(profil.cle)}" ${actif || !admin ? "disabled" : ""}
        aria-label="${actif ? "Profil actif" : "Appliquer"} : ${esc(profil.titre)}" title="${esc(profil.phrase)}">
        <ha-icon icon="${profil.icone}"></ha-icon>
        <b>${esc(profil.titreCourt)}</b>
        <small>${esc(profil.resume)}</small>
        <span class="profil-option-etat">${etat}</span>
      </button>`;
    }).join("");
    if (!profils) return "";
    return `<section class="section profil-gazon" data-profil-gazon="1">
      <div class="section-tete"><h3>Profil du gazon</h3><p>Ajuste la hauteur, le rythme et la confiance dans la pluie. Il ne modifie jamais les protections des vannes, de la pompe ou des zones.</p></div>
      <div class="profils-selecteur" role="group" aria-label="Profils du gazon">${profils}</div>
    </section>`;
  }

  // Un réglage, où qu'il vive : quel onglet, quelle section — pour la recherche ci-dessous.
  // Reconstruit à chaque appel (55 entrées, sans commune mesure avec le coût d'un rendu).
  _indexReglages() {
    if (!this._registre) return [];
    const groupes = new Map(this._registre.groupes.map((g) => [g.cle, g]));
    const sections = new Map();
    for (const dispositionGroupe of Object.values(DISPOSITION)) {
      for (const s of dispositionGroupe) for (const cle of s.cles) sections.set(cle, s.titre);
    }
    const versEntree = (r) => {
      if (r.groupe === "graines") {
        const modeActuel = this._hass && this._donnees?.entites ? this._s("mode") : null;
        const ongletCle = ["semis", "sursemis"].includes(this._onglet)
          ? this._onglet
          : modeActuel === "Sursemis" ? "sursemis" : "semis";
        const cible = groupes.get(ongletCle);
        return {
          cle: r.cle, titre: r.titre, aide: r.aide, ongletCle,
          ongletTitre: "Semis et Sursemis", ongletIcone: cible?.icone || "mdi:sprout",
          section: sections.get(r.cle) || "Arrosage commun",
        };
      }
      const g = groupes.get(r.groupe);
      if (!g) return null;
      return { cle: r.cle, titre: r.titre, aide: r.aide, ongletCle: g.cle, ongletTitre: g.titre, ongletIcone: g.icone, section: sections.get(r.cle) || "" };
    };
    return [...this._registre.reglages, ...(this._registre.choix || [])].map(versEntree).filter(Boolean);
  }

  _rechercheReglagesHtml() {
    return `<div class="recherche-reglages">
      <ha-icon icon="mdi:magnify"></ha-icon>
      <input id="recherche-reglages" type="search" placeholder="Chercher un réglage… (ex. vent, hauteur, graines)"
        value="${esc(this._rechercheReglages)}" autocomplete="off" aria-label="Chercher un réglage, où qu'il vive">
      <div class="recherche-resultats" data-liste-recherche>${this._rechercheResultatsHtml()}</div>
    </div>`;
  }

  _rechercheResultatsHtml() {
    const cherche = sansAccents(this._rechercheReglages).trim();
    if (!cherche) return "";
    const trouves = this._indexReglages().filter((it) =>
      sansAccents(`${it.titre} ${it.aide} ${it.cle} ${it.ongletTitre} ${it.section}`).includes(cherche));
    if (!trouves.length) return `<p class="vide">Aucun réglage ne correspond à la recherche.</p>`;
    const MONTRES = 8;
    const montres = trouves.slice(0, MONTRES);
    const reste = trouves.length - montres.length;
    return `${montres.map((it) => `
      <button type="button" class="resultat-recherche" data-action="aller-reglage" data-cle="${esc(it.cle)}" data-cible-onglet="${esc(it.ongletCle)}">
        <span class="resultat-titre">${esc(it.titre)}</span>
        <span class="resultat-chemin"><ha-icon icon="${esc(it.ongletIcone)}"></ha-icon>${esc(it.ongletTitre)}${it.section ? ` › ${esc(it.section)}` : ""}</span>
      </button>`).join("")}
      ${reste > 0 ? `<p class="vide">Et ${reste} autre${reste > 1 ? "s" : ""} : préciser la recherche.</p>` : ""}`;
  }

  _allerAuReglage(cle, ongletCible) {
    this._rechercheReglages = "";
    this._onglet = ongletCible;
    this._moisChoisi = {};
    this._rendre();
    const visee = this.shadowRoot.querySelector(`[data-cle="${cle}"]`);
    if (!visee) return;
    const sousMenu = visee.closest("details");
    if (sousMenu) sousMenu.open = true;
    const reduireMouvement = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
    visee.scrollIntoView({ behavior: reduireMouvement ? "auto" : "smooth", block: "center" });
    visee.classList.add("reglage-vise");
    setTimeout(() => visee.classList.remove("reglage-vise"), 2200);
  }

  _ongletHtml(g, actif) {
    const alertesEntites = ["cibles", "ia"].filter((cle) => cle in this._brouillonAlertes).length;
    const groupesReglages = [g.cle, ...(["semis", "sursemis"].includes(g.cle) ? ["graines"] : [])];
    const n = g.cle === ONGLET_INSTALLATION.cle
      ? Object.keys(this._brouillonEntites).length + Object.keys(this._brouillonChoix).length
        + Object.keys(this._brouillonAlertes).length - alertesEntites
        + Object.keys(this._brouillon).filter((cle) => this._reglage(cle)?.groupe === "installation").length
      : g.cle === ONGLET_ENTITES.cle
        ? alertesEntites + (this._brouillonPompe !== undefined ? 1 : 0)
          + (this._brouillonGarageTondeuse !== undefined ? 1 : 0)
      : Object.keys(this._brouillon).filter((cle) => groupesReglages.includes(this._reglage(cle)?.groupe)).length;
    return `<button class="onglet" role="tab" data-onglet="${esc(g.cle)}" aria-selected="${actif}">
      <ha-icon icon="${esc(g.icone)}"></ha-icon>${esc(g.titre)}${n ? `<span class="compteur" aria-label="${n} à enregistrer">${n}</span>` : ""}
    </button>`;
  }

  _groupeHtml(g) {
    if (g.cle === "semis" || g.cle === "sursemis") return this._programmeSemisHtml(g);
    const zonesConnues = Array.isArray(this._donnees?.zones) ? new Set(this._donnees.zones.map((z) => Number(z.numero))) : null;
    const cles = this._registre.reglages
      .filter((r) => r.groupe === g.cle)
      .map((r) => r.cle)
      .filter((cle) => {
        const ombre = /^arrosage_reduction_ombre_zone_(\d)$/.exec(cle);
        return !ombre || zonesConnues === null || zonesConnues.has(Number(ombre[1]));
      });
    const places = new Set();
    const sections = (DISPOSITION[g.cle] || []).map((s) => {
      const presentes = s.cles.filter((cle) => cles.includes(cle));
      presentes.forEach((cle) => places.add(cle));
      return presentes.length || s.statique ? { ...s, cles: presentes } : null;
    }).filter(Boolean);
    const orphelines = cles.filter((cle) => !places.has(cle));
    if (orphelines.length) sections.push({ titre: "Autres réglages", cles: orphelines, place: ["gauche", "large"] });
    if (g.cle === "modes") return this._ongletModesHtml(g, sections);
    const aRevenir = cles.some((cle) => !egal(this._valeur(cle), this._defaut(cle)));
    return `
      <div class="intro-onglet">
        <p>${esc(g.phrase)}</p>
        <button class="bouton-texte" data-action="tout-revenir" data-groupe="${esc(g.cle)}" ${aRevenir && this._estAdmin() ? "" : "disabled"}>
          <ha-icon icon="mdi:backup-restore"></ha-icon>Tout remettre comme conseillé
        </button>
      </div>
      <div class="programme-reglages">${sections.map((s) => this._sectionHtml(s)).join("")}</div>`;
  }

  _resumeProgrammeSection(s) {
    const valeur = (cle) => valeurFr(this._reglage(cle), this._valeur(cle));
    const a = s.cles;
    if (a.includes("graines_duree")) return `${valeur("graines_duree")} · quatre étapes`;
    if (a.includes("graines_fin_germination")) {
      return `Germination J${this._valeur("graines_fin_germination")} · racines J${this._valeur("graines_fin_enracinement")} · reprise J${this._valeur("graines_fin_reprise")}`;
    }
    if (a.includes("graines_germination_dose")) return `${valeur("graines_germination_dose")} × ${valeur("graines_germination_cycles")}`;
    if (a.includes("graines_enracinement_dose")) return `${valeur("graines_enracinement_dose")} × ${valeur("graines_enracinement_cycles")}`;
    if (a.includes("graines_reprise_dose")) return `${valeur("graines_reprise_dose")} × ${valeur("graines_reprise_cycles")}`;
    if (a.includes("graines_fenetre_debut")) return `${valeur("graines_fenetre_debut")} → ${valeur("graines_fenetre_fin")}`;
    if (a.includes("graines_vent_max")) return `minimum ${valeur("graines_temperature_min")} · vent maximal ${valeur("graines_vent_max")}`;
    if (a.includes("graines_alerte_retard")) return `prévenir après ${valeur("graines_alerte_retard")}`;
    if (a.includes("semis_reprise_tonte_jours")) return `reprise à J${this._valeur("semis_reprise_tonte_jours")}`;
    if (a.includes("semis_hauteur_germination")) return `${valeur("semis_hauteur_germination")} → ${valeur("semis_hauteur_enracinement")}`;
    if (a.includes("semis_hauteur_reprise")) return `${valeur("semis_hauteur_reprise")} → ${valeur("semis_hauteur_stabilisation")}`;
    if (a.includes("sursemis_levee")) return `reprise à J${Number(this._valeur("sursemis_levee")) + 1} · écart ${valeur("sursemis_ecart_tontes")}`;
    if (a.includes("sursemis_pousse_plantules")) return `${valeur("sursemis_pousse_plantules")} · première coupe à ${valeur("sursemis_premiere_coupe")}`;
    if (a.includes("sursemis_lame")) return `${valeur("sursemis_lame")} → ${valeur("sursemis_lame_finale")}`;
    if (a.includes("sursemis_coupes_avant_remontee")) return `après ${valeur("sursemis_coupes_avant_remontee")}`;
    return `${a.length} réglage${a.length > 1 ? "s" : ""}`;
  }

  _programmeSemisHtml(g) {
    const commun = DISPOSITION.graines || [];
    const propre = DISPOSITION[g.cle] || [];
    const cles = [...new Set([...commun, ...propre].flatMap((s) => s.cles))];
    const aRevenir = cles.some((cle) => !egal(this._valeur(cle), this._defaut(cle)));
    const section = (s, estCommune) => {
      const ouverte = s.cles.some((cle) => Object.hasOwn(this._brouillon, cle));
      const dessin = s.dessin ? `<div class="dessin" data-dessin="${s.dessin}">${this._dessinHtml(s.dessin)}</div>` : "";
      return `<details class="programme-groupe" data-programme-groupe="${esc(s.titre)}" ${!this._narrow || ouverte ? "open" : ""}>
        <summary>
          <span class="garage-scenario-icone ${estCommune ? "programme-commun" : ""}"><ha-icon icon="${estCommune ? "mdi:water-outline" : g.icone}"></ha-icon></span>
          <span class="garage-scenario-texte"><b>${esc(s.titre)}</b><small>${estCommune ? "Commun Semis / Sursemis · " : ""}${esc(this._resumeProgrammeSection(s))}</small></span>
          <ha-icon class="garage-chevron" icon="mdi:chevron-down"></ha-icon>
        </summary>
        ${dessin}${s.cles.length ? `<div class="lignes">${s.cles.map((cle) => this._ligneHtml(this._reglage(cle))).join("")}</div>` : ""}
      </details>`;
    };
    const phrase = g.cle === "semis"
      ? "Terrain nu : le programme complet réunit ici l'arrosage des graines et la tonte progressive du jeune gazon."
      : "Gazon déjà en place : le programme complet réunit ici l'arrosage des graines et les précautions de tonte du sursemis.";
    return `<div class="intro-onglet">
        <p>${esc(phrase)} Les réglages marqués « Commun Semis / Sursemis » pilotent l'arrosage des deux modes de la même façon ; leur effet sur la tonte peut différer d'un mode à l'autre (voir la case correspondante).</p>
        <button class="bouton-texte" data-action="tout-revenir" data-groupes="graines,${esc(g.cle)}" ${aRevenir && this._estAdmin() ? "" : "disabled"}>
          <ha-icon icon="mdi:backup-restore"></ha-icon>Tout remettre comme conseillé
        </button>
      </div>
      <div class="programme-reglages">
        ${commun.map((s) => section(s, true)).join("")}
        ${propre.map((s) => section(s, false)).join("")}
      </div>`;
  }

  // ── Réglages → Modes : une seule liste de modes, puis le mode regardé ──
  // Choisir un mode dans la liste le MONTRE ; en changer passe par la carte d'action, avec
  // confirmation. Grande page : l'explication et les réglages à gauche, l'action à droite.

  _modeVisible() {
    const choisi = this._modeReglage;
    if (choisi && MODES[choisi]) return choisi;
    const actuel = this._s("mode");
    return MODES[actuel] ? actuel : "Normal";
  }

  _ongletModesHtml(g, sections) {
    const mode = this._modeVisible();
    const section = sections.find((s) => s.mode === mode) || null;
    const cles = section?.cles || [];
    const aRevenir = cles.some((cle) => !egal(this._valeur(cle), this._defaut(cle)));
    return `
      <div class="intro-onglet">
        <p>${esc(g.phrase)}</p>
        ${cles.length ? `<button class="bouton-texte" data-action="mode-revenir" data-groupe="modes" ${aRevenir && this._estAdmin() ? "" : "disabled"}>
          <ha-icon icon="mdi:backup-restore"></ha-icon>Remettre ${esc(mode)} comme conseillé
        </button>` : ""}
      </div>
      ${this._choixModesHtml(mode)}
      <div class="mode-reglages">
        ${this._detailModeHtml(mode, section)}
        ${this._actionModeHtml(mode)}
      </div>
      ${MODES_PRODUIT.includes(mode) ? this._catalogueHtml(mode) : ""}`;
  }

  _choixModesHtml(vu) {
    const actuel = this._s("mode");
    return `<nav class="modes-choix" aria-label="Les modes">${Object.keys(MODES).map((mode) => {
      const enCours = mode === actuel;
      return `<button type="button" class="mode-puce ${enCours ? "en-cours" : ""}" data-mode-reglage="${esc(mode)}"
          aria-pressed="${mode === vu}" title="${esc(MODES[mode])}">
        <ha-icon icon="${esc(ICONES_MODES[mode] || "mdi:grass")}"></ha-icon>
        <span>${esc(mode)}</span>
        ${enCours ? `<small><i aria-hidden="true"></i>en ce moment</small>` : ""}
      </button>`;
    }).join("")}</nav>`;
  }

  _detailModeHtml(mode, section) {
    const regles = REGLES_MODES[mode] || [];
    const dessin = section?.dessin ? `<div class="dessin" data-dessin="${section.dessin}">${this._dessinHtml(section.dessin)}</div>` : "";
    const cles = section?.cles || [];
    const liens = LIENS_MODES[mode] || [];
    const phrase = section?.phrase || "";
    const titre = section?.titre || `Mode ${mode}`;
    const corps = `
      ${regles.length ? `<ul class="liste-simple regles-mode">${regles.map((r) => `<li><ha-icon icon="mdi:check-circle-outline"></ha-icon><span>${esc(r)}</span></li>`).join("")}</ul>` : ""}
      ${dessin}
      ${cles.length ? `<div class="lignes">${cles.map((cle) => this._ligneHtml(this._reglage(cle))).join("")}</div>` : ""}
      ${liens.length ? `<div class="mode-liens"><span>Ses réglages :</span>${liens.map(([onglet, titreLien]) => `<button type="button" class="petit-bouton" data-onglet="${esc(onglet)}"><ha-icon icon="mdi:arrow-right"></ha-icon>${esc(titreLien)}</button>`).join("")}</div>` : ""}`;
    return this._sectionReglageHtml({
      titre,
      phrase: `${MODES[mode]}${phrase ? ` ${phrase}` : ""}`,
      icone: ICONES_MODES[mode] || "mdi:grass",
      cles,
      corps,
      classes: "mode-detail",
    });
  }

  _actionModeHtml(mode) {
    const actuel = this._s("mode");
    const options = new Set(this._entite("mode")?.attributes?.options || Object.keys(MODES));
    const admin = this._estAdmin();
    const lignes = [];
    let titre;
    if (mode === actuel) {
      titre = "C'est le mode du moment";
      const semis = this._contexte().semis;
      if (semis && (mode === "Semis" || mode === "Sursemis")) {
        lignes.push(`<p class="mode-etat">Jour ${esc(String(semis.age))} depuis le semis.</p>`);
      }
      if (mode !== "Normal") {
        lignes.push(`<button class="bouton-contour danger" data-dialogue="normal" ${admin ? "" : "disabled"}><ha-icon icon="mdi:backup-restore"></ha-icon>Revenir au mode Normal</button>`);
        lignes.push(`<p class="note alerte"><ha-icon icon="mdi:alert-outline"></ha-icon><span>Revenir au mode Normal efface le suivi en cours.</span></p>`);
      } else {
        lignes.push(`<p>Aucun évènement en cours : le gazon suit l'entretien de tous les jours.</p>`);
      }
    } else if (!options.has(mode)) {
      titre = `Mode ${mode}`;
      lignes.push(`<p>Ce mode n'est pas proposé par l'entité « mode » de Home Assistant.</p>`);
    } else {
      titre = `Passer en mode ${mode}`;
      if (MODES_PRODUIT.includes(mode)) {
        const produit = (this._a("catalogue_produits", "products_summary") || [])
          .find((p) => String(p.type || "").trim().toLocaleLowerCase("fr") === mode.toLocaleLowerCase("fr"));
        lignes.push(`<p>Après l'application d'un produit, le déclarer permet d'adapter le mode, de conserver une trace et d'appliquer la dose et les délais de sa fiche.</p>`);
        lignes.push(`<button class="bouton-plein" data-dialogue="produit" ${produit ? `data-produit="${esc(produit.id)}"` : ""} ${admin ? "" : "disabled"}><ha-icon icon="mdi:flask-outline"></ha-icon>Déclarer un produit</button>`);
        lignes.push(`<button class="bouton-contour" data-dialogue="mode" data-mode="${esc(mode)}" ${admin ? "" : "disabled"}>Passer en ${esc(mode)} sans produit</button>`);
      } else {
        lignes.push(`<button class="bouton-plein" data-dialogue="mode" data-mode="${esc(mode)}" ${admin ? "" : "disabled"}><ha-icon icon="${esc(ICONES_MODES[mode] || "mdi:swap-horizontal")}"></ha-icon>Passer en mode ${esc(mode)}</button>`);
      }
      if (mode === "Semis" || mode === "Sursemis") {
        const preparation = mode === "Semis"
          ? "le travail complet du sol est terminé et les graines sont au sol"
          : "la scarification est terminée et les graines sont au sol";
        lignes.push(`<p class="note alerte"><ha-icon icon="mdi:alert-outline"></ha-icon><span>À choisir une fois que ${preparation} : un arrosage des graines peut partir dès l'ouverture de leur fenêtre.</span></p>`);
      }
      if (mode === "Scarification") {
        lignes.push(`<p class="note"><ha-icon icon="mdi:information-outline"></ha-icon><span>Ce mode correspond à une scarification seule, sans graines. Pour semer ensuite, choisir directement Semis ou Sursemis : ces chantiers comprennent déjà leur préparation du sol et aucun programme de Semis ou de Sursemis n'est lancé ici.</span></p>`);
      }
      if (mode === "Normal" && actuel && actuel !== "Normal") {
        lignes.push(`<p class="note alerte"><ha-icon icon="mdi:alert-outline"></ha-icon><span>Revenir au mode Normal efface le suivi en cours (${esc(actuel)}).</span></p>`);
        if (this._verrouSecuriteActif()) {
          lignes.push(`<p class="note alerte"><ha-icon icon="mdi:shield-alert-outline"></ha-icon><span>Le verrou de sécurité restera posé. Il se lève séparément après vérification des vannes.</span></p>`);
        }
      }
      if (actuel) lignes.push(`<p class="mode-etat">En ce moment : ${esc(actuel)}.</p>`);
    }
    if (!admin) lignes.push(`<p class="note">Seul un administrateur de Home Assistant peut changer de mode.</p>`);
    return `<section class="section mode-action">
      <div class="section-tete"><h3>${esc(titre)}</h3></div>
      <div class="mode-action-corps">${lignes.join("")}</div>
    </section>`;
  }

  _sectionReglageHtml({ titre, phrase = "", icone = "mdi:tune-variant", cles = [], corps = "", classes = "", attributs = "", ouverte = false }) {
    const modifiee = cles.some((cle) => Object.hasOwn(this._brouillon || {}, cle)
      || Object.hasOwn(this._brouillonEntites || {}, cle)
      || Object.hasOwn(this._brouillonChoix || {}, cle)
      || Object.hasOwn(this._brouillonAlertes || {}, cle));
    return `<details class="section programme-groupe reglage-groupe ${esc(classes)}" ${attributs} ${!this._narrow || modifiee || ouverte ? "open" : ""}>
      <summary>
        <span class="garage-scenario-icone"><ha-icon icon="${esc(icone)}"></ha-icon></span>
        <span class="garage-scenario-texte"><b>${esc(titre)}</b>${phrase ? `<small>${esc(phrase)}</small>` : ""}</span>
        <ha-icon class="garage-chevron" icon="mdi:chevron-down"></ha-icon>
      </summary>
      <div class="reglage-groupe-corps">${corps}</div>
    </details>`;
  }

  _sectionHtml(s) {
    const dessin = s.dessin ? `<div class="dessin" data-dessin="${s.dessin}">${this._dessinHtml(s.dessin)}</div>` : "";
    const corps = `${dessin}${s.cles.length ? `<div class="lignes">${s.cles.map((cle) => this._ligneHtml(this._reglage(cle))).join("")}</div>` : ""}`;
    const premier = s.cles.map((cle) => this._reglage(cle)).find(Boolean);
    return this._sectionReglageHtml({
      titre: s.titre,
      phrase: s.phrase || "",
      icone: premier ? iconeDe(premier) : "mdi:tune-variant",
      cles: s.cles,
      corps,
    });
  }

  _ligneHtml(r) {
    const ombre = /^arrosage_reduction_ombre_zone_(\d)$/.exec(r.cle);
    if (ombre) {
      const numero = Number(ombre[1]);
      const zone = (this._donnees?.zones || []).find((z) => Number(z.numero) === numero);
      const nomZone = zone?.nom || `Zone ${numero}`;
      r = { ...r, titre: `${nomZone} · réduction pour l'ombre` };
    }
    if (r.genre === "table_mois") return this._moisHtml(r);
    if (r.genre === "interrupteur") return this._interrupteurReglageHtml(r);
    if (r.cle === "arrosage_sensibilite_pluie") return this._sensibilitePluieHtml(r);
    const v = this._valeur(r.cle);
    const d = r.defaut;
    const { affichees } = valider(this._registre, this._toutesLesValeurs());
    const erreur = affichees[r.cle];
    const enAttente = r.cle in this._brouillon;
    const lecture = !this._estAdmin();
    return `<div class="ligne ${enAttente ? "change" : ""} ${erreur ? "en-erreur" : ""}" data-cle="${esc(r.cle)}">
      ${enAttente ? `<span class="a-enregistrer">à enregistrer</span>` : ""}
      <div class="ligne-tete">
        <span class="ligne-icone"><ha-icon icon="${iconeDe(r)}"></ha-icon></span>
        <div class="ligne-textes"><h4>${esc(r.titre)}</h4><p>${esc(r.aide)}</p></div>
        <output class="bulle bulle-haut">${esc(valeurFr(r, v))}</output>
      </div>
      <div class="reglette">
        <button class="pas-btn" data-action="moins" aria-label="Moins" ${lecture || v <= r.minimum ? "disabled" : ""}><ha-icon icon="mdi:minus"></ha-icon></button>
        <div class="curseur-zone">
          <span class="marque-conseil" style="--pos:${pourcent(d, r.minimum, r.maximum)}" title="Valeur conseillée : ${esc(valeurFr(r, d))}"></span>
          <input type="range" min="${r.minimum}" max="${r.maximum}" step="${r.pas}" value="${v}"
            style="--rempli:${pourcent(v, r.minimum, r.maximum)}%"
            aria-label="${esc(r.titre)}" aria-valuetext="${esc(valeurFr(r, v))}" ${lecture ? "disabled" : ""}>
        </div>
        <button class="pas-btn" data-action="plus" aria-label="Plus" ${lecture || v >= r.maximum ? "disabled" : ""}><ha-icon icon="mdi:plus"></ha-icon></button>
        <output class="bulle bulle-bas" aria-hidden="true">${esc(valeurFr(r, v))}</output>
      </div>
      <div class="ligne-pied">
        <span>${esc(valeurFr(r, r.minimum))}</span>
        <span class="conseil">${this._conseilHtml(r, v)}</span>
        <span class="borne-max">${esc(valeurFr(r, r.maximum))}</span>
      </div>
      ${r.avertissement ? `<p class="avertissement-reglage"><ha-icon icon="mdi:alert-outline"></ha-icon><span>${esc(r.avertissement)}</span></p>` : ""}
      ${erreur ? `<p class="erreur" role="alert"><ha-icon icon="mdi:alert-circle-outline"></ha-icon><span>${esc(erreur)}</span></p>` : ""}
    </div>`;
  }

  _interrupteurReglageHtml(r) {
    const v = this._valeur(r.cle) === true;
    const enAttente = r.cle in this._brouillon;
    const lecture = !this._estAdmin();
    return `<div class="ligne ${enAttente ? "change" : ""}" data-cle="${esc(r.cle)}">
      ${enAttente ? `<span class="a-enregistrer">à enregistrer</span>` : ""}
      <div class="ligne-tete">
        <span class="ligne-icone"><ha-icon icon="mdi:garage-variant"></ha-icon></span>
        <div class="ligne-textes"><h4>${esc(r.titre)}</h4><p>${esc(r.aide)}</p></div>
        <button class="bascule" role="switch" data-action="basculer-reglage" aria-checked="${v}" aria-label="${esc(r.titre)}" ${lecture ? "disabled" : ""}></button>
      </div>
      <p class="etat-bascule">${v ? "Automatique" : "Manuel"}${enAttente ? " (pas encore enregistré)" : ""}</p>
      ${r.avertissement ? `<p class="avertissement-reglage"><ha-icon icon="mdi:alert-outline"></ha-icon><span>${esc(r.avertissement)}</span></p>` : ""}
    </div>`;
  }

  _sensibilitePluieHtml(r) {
    const v = this._valeur(r.cle);
    const enAttente = r.cle in this._brouillon;
    const lecture = !this._estAdmin();
    const profils = [
      [1.25, "Prudente pour le gazon", "Attend davantage avant de compter sur la pluie prévue."],
      [1.0, "Équilibrée", "Conserve les seuils conseillés de l'intégration."],
      [0.75, "Économe en eau", "Reporte plus tôt quand une pluie suffisante est annoncée."],
    ];
    return `<div class="ligne ${enAttente ? "change" : ""}" data-cle="${esc(r.cle)}">
      ${enAttente ? `<span class="a-enregistrer">à enregistrer</span>` : ""}
      <div class="ligne-tete">
        <span class="ligne-icone"><ha-icon icon="mdi:weather-rainy"></ha-icon></span>
        <div class="ligne-textes"><h4>${esc(r.titre)}</h4><p>${esc(r.aide)}</p></div>
      </div>
      <div class="puces-bascule" role="radiogroup" aria-label="Sensibilité à la pluie annoncée">
        ${profils.map(([valeur, titre, aide]) => `<button class="puce-bascule ${egal(v, valeur) ? "active" : ""}" data-action="profil-pluie" data-valeur="${valeur}" aria-pressed="${egal(v, valeur)}" title="${esc(aide)}" ${lecture ? "disabled" : ""}>${egal(v, valeur) ? `<ha-icon icon="mdi:check"></ha-icon>` : ""}${esc(titre)}</button>`).join("")}
      </div>
      ${r.avertissement ? `<p class="avertissement-reglage"><ha-icon icon="mdi:alert-outline"></ha-icon><span>${esc(r.avertissement)}</span></p>` : ""}
    </div>`;
  }

  _conseilHtml(r, v) {
    if (egal(v, r.defaut)) return `<ha-icon icon="mdi:check"></ha-icon>Valeur conseillée`;
    if (!this._estAdmin()) return `Conseillé : ${esc(valeurFr(r, r.defaut))}`;
    return `<button data-action="revenir"><ha-icon icon="mdi:restore"></ha-icon>Revenir à ${esc(valeurFr(r, r.defaut))}</button>`;
  }

  _moisHtml(r) {
    const valeurs = this._valeur(r.cle);
    const enregistrees = this._enregistree(r.cle);
    const c = this._contexte();
    const ceMois = c.maintenant.mois - 1;
    const choisi = this._moisChoisi[r.cle] ?? ceMois;
    const textes = TABLES_MOIS[r.cle] || { groupe: r.titre, moins: "Moins", plus: "Plus", note: "" };
    const texte = (x) => (r.unite === "cm" ? cmFr(x) : valeurFr(r, x));
    const part = (x) => Math.min(1, Math.max(0, x / r.maximum));
    const colonnes = valeurs.map((x, i) => {
      const change = !egal(x, enregistrees[i]);
      return `<button class="mois ${i === ceMois ? "ce-mois" : ""} ${change ? "change" : ""}" data-mois="${i}"
          aria-pressed="${i === choisi}" aria-label="${MOIS_LONGS[i]} : ${esc(texte(x))}">
        <span class="mois-colonne">
          <span class="mois-valeur">${nombreFr(x, 1)}</span>
          <span class="mois-barre" style="--part:${part(x)}"></span>
          ${egal(x, r.defaut[i]) ? "" : `<span class="mois-conseil" style="--part:${part(r.defaut[i])}" title="Conseillé : ${esc(texte(r.defaut[i]))}"></span>`}
        </span>
        <span class="mois-nom">${INITIALES_MOIS[i]}</span>
      </button>`;
    }).join("");
    const x = valeurs[choisi];
    const d = r.defaut[choisi];
    const lecture = !this._estAdmin();
    const enAttente = r.cle in this._brouillon;
    return `<div class="ligne ${enAttente ? "change" : ""}" data-cle="${esc(r.cle)}">
      ${enAttente ? `<span class="a-enregistrer">à enregistrer</span>` : ""}
      <div class="ligne-tete">
        <span class="ligne-icone"><ha-icon icon="${iconeDe(r)}"></ha-icon></span>
        <div class="ligne-textes"><h4>${esc(r.titre)}</h4><p>${esc(r.aide)}</p></div>
      </div>
      <div class="dessin" style="padding:14px 0 0">
        <div class="mois-grille" role="group" aria-label="${esc(textes.groupe)}">${colonnes}</div>
        <div class="mois-editeur">
          <strong>${MOIS_LONGS[choisi]}</strong>
          <button class="pas-btn" data-action="mois-moins" aria-label="${esc(textes.moins)}" ${lecture || x <= r.minimum ? "disabled" : ""}><ha-icon icon="mdi:minus"></ha-icon></button>
          <output class="bulle">${esc(texte(x))}</output>
          <button class="pas-btn" data-action="mois-plus" aria-label="${esc(textes.plus)}" ${lecture || x >= r.maximum ? "disabled" : ""}><ha-icon icon="mdi:plus"></ha-icon></button>
          <span class="conseil">${egal(x, d)
            ? `<ha-icon icon="mdi:check"></ha-icon>Valeur conseillée`
            : lecture ? `Conseillé : ${esc(texte(d))}` : `<button data-action="mois-revenir"><ha-icon icon="mdi:restore"></ha-icon>Revenir à ${esc(texte(d))}</button>`}</span>
        </div>
        ${textes.note ? `<p class="note"><ha-icon icon="mdi:information-outline"></ha-icon><span>${esc(textes.note)}</span></p>` : ""}
      </div>
    </div>`;
  }

  // ── Dessins ──

  _dessinHtml(nom) {
    const v = this._toutesLesValeurs();
    const c = this._contexte();
    switch (nom) {
      case "journee_tonte": return this._dessinJourneeTonte(v, c);
      case "feu_vent": return this._feuHtml({
        min: 0, max: 60, unite: "km/h",
        zones: [
          { de: 0, a: v.tonte_vent_a_eviter, teinte: "vert", nom: "On tond" },
          { de: v.tonte_vent_a_eviter, a: v.tonte_vent_bloque, teinte: "ambre", nom: "Mieux vaut attendre" },
          { de: v.tonte_vent_bloque, a: 60, teinte: "rouge", nom: "Interdit" },
        ],
        precisions: `À ${nombreFr(v.tonte_vent_a_eviter)} km/h, on attend déjà. À ${nombreFr(v.tonte_vent_bloque)} km/h pile, c'est encore « attendre » : interdit seulement au-delà.`,
      });
      case "feu_chaleur": return this._feuHtml({
        min: 0, max: 40, unite: "°C",
        zones: [
          { de: 0, a: 8, teinte: "froid", nom: "Trop froid" },
          { de: 8, a: v.tonte_temperature_a_eviter, teinte: "vert", nom: "On tond" },
          { de: v.tonte_temperature_a_eviter, a: v.tonte_temperature_bloquee, teinte: "ambre", nom: "Mieux vaut attendre" },
          { de: v.tonte_temperature_bloquee, a: 40, teinte: "rouge", nom: "Interdit" },
        ],
        precisions: "Sous 8 °C, la tondeuse attend toujours (ce seuil-là n'est pas réglable).",
      });
      case "feu_humidite": return this._feuHtml({
        min: 40, max: 100, unite: "%",
        zones: [
          { de: 40, a: v.tonte_humidite_bloquee, teinte: "vert", nom: "On tond" },
          { de: v.tonte_humidite_bloquee, a: 100, teinte: "rouge", nom: "Interdit", texte: `à partir de ${nombreFr(v.tonte_humidite_bloquee)} %` },
        ],
      });
      case "rythme_tonte": return this._dessinRythme(v, c);
      case "matin_arrosage": return this._dessinMatin(v, c);
      case "decoupage": return this._dessinDecoupage(v);
      case "rafraichissement": return this._dessinRafraichissement(v);
      case "voyage_graine": return this._dessinVoyageGraine(v, c);
      case "soir_tonte": return this._dessinSoirTonte(v, c);
      case "eau_germination": return this._carteEau("Germination", v.graines_germination_dose, v.graines_germination_cycles, true, v, 120);
      case "eau_enracinement": return this._carteEau("Enracinement", v.graines_enracinement_dose, v.graines_enracinement_cycles, false, v, 270);
      case "eau_reprise": return this._carteEau("Reprise et stabilisation", v.graines_reprise_dose, v.graines_reprise_cycles, false, v, 240);
      case "journee_graines": return this._dessinJourneeGraines(v);
      case "feux_graines": return this._dessinFeuxGraines(v);
      case "voyage_sursemis": return this._dessinVoyageSursemis(v, c);
      case "lame_sursemis": return this._dessinLame(v, c);
      case "escalier_semis": return this._dessinEscalier(v, c);
      default:
        // « jours:cle1,cle2 » : les jours des modes nommés.
        if (nom.startsWith("jours:")) {
          const cles = nom.slice(6).split(",");
          return this._dessinJoursModes(v, c, MODES_DUREES.filter((m) => cles.includes(m.cle)));
        }
        return "";
    }
  }

  _friseHtml({ debut, fin, segments, classes, reperes = [], pasGraduation = 360, legende = true }) {
    const pct = (m) => pourcent(m, debut, fin);
    const segs = segments.map((s) => {
      const k = classes[s.classe];
      const largeur = pct(s.fin) - pct(s.debut);
      return `<div class="seg t-${k.teinte}" style="left:${pct(s.debut)}%;width:${largeur}%" title="${esc(k.nom)} · ${heureFr(s.debut)} → ${heureFr(s.fin)}">${largeur > 13 ? `<span>${esc(k.nom)}</span>` : ""}</div>`;
    }).join("");
    const visibles = reperes.filter((r) => r.min >= debut && r.min <= fin).map((r) => ({ ...r, p: pct(r.min) }));
    const rangee = (ligne) => this._rangeesHtml(visibles.filter((r) => r.ligne === ligne), ligne);
    const heureBord = (m) => (m <= 0 || m >= 1440 ? "minuit" : heureFr(m));
    const plage = (s) => {
      if (s.debut === debut && debut > 0) return `avant ${heureFr(s.fin)}`;
      if (s.fin === fin && fin < 1440) return `à partir de ${heureFr(s.debut)}`;
      return `${heureBord(s.debut)} → ${heureBord(s.fin)}`;
    };
    const aiguilles = visibles.map((r) => `<span class="aiguille ${r.genre}" style="left:${r.p}%"></span>`).join("");
    const graduations = [];
    for (let m = debut; m <= fin; m += pasGraduation) graduations.push(`<span style="left:${pct(m)}%">${Math.floor(m / 60)} h</span>`);
    let legendeHtml = "";
    if (legende) {
      const ordre = [];
      const plages = {};
      for (const s of segments) {
        if (!plages[s.classe]) { plages[s.classe] = []; ordre.push(s.classe); }
        plages[s.classe].push(plage(s));
      }
      legendeHtml = `<ul class="legende">${ordre.map((cl) => {
        const k = classes[cl];
        return `<li><span class="pastille t-${k.teinte}"></span><span><b>${esc(k.nom)}</b>${k.phrase ? ` — ${esc(k.phrase)}` : ""}<br><span class="heures">${plages[cl].join(" et ")}</span></span></li>`;
      }).join("")}</ul>`;
    }
    return `<div class="frise">
      ${rangee("haut")}
      <div class="frise-piste">${segs}${aiguilles}</div>
      ${rangee("bas")}
      <div class="graduations">${graduations.join("")}</div>
      ${legendeHtml}
    </div>`;
  }

  // Largeur utile d'un dessin : la page, moins les marges de la carte et du dessin.
  _largeurDessin() {
    const page = this._page?.clientWidth || 0;
    if (!page) return 600;
    const etroit = page <= 600;
    return Math.min(page, 880) - (etroit ? 56 : 72);
  }

  // `items` : {p (0-100), texte, icone?, genre?}. Au-dessus de la frise, la première rangée est
  // la plus proche de la piste, donc rendue en dernier.
  _rangeesHtml(items, ligne) {
    if (!items.length) return "";
    const n = rangerEtiquettes(items, this._largeurDessin());
    const rangees = [];
    for (let i = 0; i < n; i += 1) {
      rangees.push(`<div class="reperes ${ligne}">${items.filter((it) => it.rang === i).map((it) => (
        `<span class="repere ${it.genre || ""} ${it.cote}" style="left:${it.p}%">${it.icone ? `<ha-icon icon="${it.icone}"></ha-icon>` : ""}${esc(it.texte)}</span>`
      )).join("")}</div>`);
    }
    if (ligne === "haut") rangees.reverse();
    return rangees.join("");
  }

  _dessinJourneeTonte(v, c) {
    const classes = {
      nuit: { nom: "Nuit", phrase: "la tondeuse reste à sa base", teinte: "nuit" },
      tot: { nom: "Trop tôt", phrase: "l'herbe est encore mouillée", teinte: "gris" },
      ideal: { nom: "Idéal", phrase: "le meilleur moment", teinte: "vert" },
      eviter: { nom: "À éviter", phrase: "souvent trop chaud", teinte: "ambre" },
      possible: { nom: "Possible", phrase: "la fraîcheur du soir", teinte: "vert-clair" },
    };
    const segments = segmenter((m) => classeTonte(m, v, c.soleil), 0, 1440);
    const reperes = [];
    if (c.soleil) {
      reperes.push({ min: c.soleil.lever, ligne: "haut", genre: "soleil", icone: "mdi:weather-sunset-up", texte: heureFr(c.soleil.lever) });
      reperes.push({ min: c.soleil.coucher, ligne: "haut", genre: "soleil", icone: "mdi:weather-sunset-down", texte: heureFr(c.soleil.coucher) });
    }
    reperes.push({ min: c.maintenant.minute, ligne: "bas", genre: "maintenant", texte: `maintenant ${heureFr(c.maintenant.minute)}` });
    const note = c.soleil
      ? ""
      : `<p class="note alerte"><ha-icon icon="mdi:weather-sunny-off"></ha-icon><span>Le soleil est inconnu : le dessin utilise les heures de secours (soir 17 h → 19 h, nuit à 22 h).</span></p>`;
    return this._friseHtml({ debut: 0, fin: 1440, segments, classes, reperes }) + note +
      `<p class="note"><ha-icon icon="mdi:information-outline"></ha-icon><span>La pluie, la rosée, le vent et la chaleur peuvent encore tout bloquer.</span></p>`;
  }

  _feuHtml({ min, max, unite, zones, precisions }) {
    const pct = (x) => pourcent(x, min, max);
    const segs = zones.filter((z) => z.a > z.de).map((z) => {
      const largeur = pct(z.a) - pct(z.de);
      return `<div class="seg t-${z.teinte}" style="left:${pct(z.de)}%;width:${largeur}%">${largeur > 16 ? `<span>${esc(z.nom)}</span>` : ""}</div>`;
    }).join("");
    const bornes = [min, ...zones.slice(0, -1).map((z) => z.a), max];
    const graduations = [...new Set(bornes)].map((b) => `<span style="left:${pct(b)}%">${nombreFr(b)}${b === max ? ` ${unite}` : ""}</span>`).join("");
    const legende = zones.filter((z) => z.a > z.de).map((z, i, liste) => {
      const texte = z.texte || (i === 0
        ? `moins de ${nombreFr(z.a)} ${unite}`
        : i === liste.length - 1 ? `plus de ${nombreFr(z.de)} ${unite}` : `de ${nombreFr(z.de)} à ${nombreFr(z.a)} ${unite}`);
      return `<li><span class="pastille t-${z.teinte}"></span><span><b>${esc(z.nom)}</b> <span class="heures">${esc(texte)}</span></span></li>`;
    }).join("");
    return `<div class="frise">
      <div class="frise-piste">${segs}</div>
      <div class="graduations">${graduations}</div>
      <ul class="legende">${legende}</ul>
      ${precisions ? `<p class="note"><ha-icon icon="mdi:information-outline"></ha-icon><span>${esc(precisions)}</span></p>` : ""}
    </div>`;
  }

  _dessinRythme(v, c) {
    const base = c.maintenant;
    const jours = [];
    for (let j = 0; j < 14; j += 1) {
      const tonte = j % v.tonte_ecart_min_jours === 0;
      const nom = j === 0 ? "auj." : jourPlus(base, j, { weekday: "short" }).replace(".", "");
      jours.push(`<div class="jour ${tonte ? "tonte" : ""}">
        <span class="jour-nom">${esc(nom)}</span>
        <span class="jour-rond">${tonte ? `<ha-icon icon="mdi:robot-mower"></ha-icon>${v.tonte_max_par_jour > 1 ? `<b>×${v.tonte_max_par_jour}</b>` : ""}` : ""}</span>
      </div>`);
    }
    const n = Math.ceil(14 / v.tonte_ecart_min_jours);
    return `<div class="rythme" role="img" aria-label="Au plus ${n} jours de tonte sur deux semaines">${jours.join("")}</div>
      <p class="note"><ha-icon icon="mdi:information-outline"></ha-icon><span>Au plus <b>${n} jours de tonte</b> sur deux semaines${v.tonte_max_par_jour > 1 ? `, et jusqu'à ${v.tonte_max_par_jour} tontes ces jours-là (×${v.tonte_max_par_jour})` : ""}. En vrai, la tondeuse sort moins : ça dépend de la pousse du mois.</span></p>`;
  }

  _dessinMatin(v, c) {
    const classes = {
      tot: { nom: "Trop tôt", phrase: "on attend", teinte: "gris" },
      ideal: { nom: "Le meilleur moment", phrase: "l'eau ne s'évapore presque pas", teinte: "eau" },
      possible: { nom: "Encore possible", phrase: "le soleil commence à chauffer", teinte: "eau-clair" },
      tard: { nom: "Trop tard", phrase: "on attend le lendemain", teinte: "gris" },
    };
    const segments = segmenter((m) => classeMatin(m, v), 0, 12 * 60);
    const reperes = [];
    if (c.soleil) {
      const fin = c.soleil.lever - v.arrosage_marge_avant_lever;
      reperes.push({ min: c.soleil.lever, ligne: "haut", genre: "soleil", icone: "mdi:weather-sunset-up", texte: `lever ${heureFr(c.soleil.lever)}` });
      reperes.push({ min: fin, ligne: "bas", genre: "eau", icone: "mdi:water-check", texte: `l'arrosage finit ${heureFr(fin)}` });
    }
    if (c.maintenant.minute < 12 * 60) {
      reperes.push({ min: c.maintenant.minute, ligne: c.soleil ? "haut" : "bas", genre: "maintenant", texte: "maintenant" });
    }
    const avertissement = c.soleil && c.soleil.lever - v.arrosage_marge_avant_lever <= v.arrosage_ouverture
      ? `<p class="note alerte"><ha-icon icon="mdi:alert-outline"></ha-icon><span>Avec ces réglages, l'arrosage devrait finir avant même de pouvoir commencer : il partira à l'ouverture et finira un peu plus tard.</span></p>`
      : "";
    return this._friseHtml({ debut: 0, fin: 12 * 60, segments, classes, reperes, pasGraduation: 120 }) + avertissement +
      `<p class="note"><ha-icon icon="mdi:information-outline"></ha-icon><span>L'arrosage démarre juste assez tôt pour finir ${dureeFr(v.arrosage_marge_avant_lever)} avant le lever, jamais avant ${heureFr(v.arrosage_ouverture)}.</span></p>`;
  }

  _dessinRafraichissement(v) {
    const eteint = this._valeurEntite("rafraichissement_soir") === false;
    const feu = this._feuHtml({
      min: 15, max: 42, unite: "°C",
      zones: [
        { de: 15, a: v.rafraichissement_temperature, teinte: "gris", nom: "Pas besoin" },
        {
          de: v.rafraichissement_temperature, a: 42, teinte: "eau", nom: `${mmFr(v.rafraichissement_dose)} le soir`,
          texte: `à partir de ${nombreFr(v.rafraichissement_temperature)} °C`,
        },
      ],
      precisions: "Il faut aussi que le gazon souffre de la chaleur, que l'air soit sec et qu'aucune pluie ne s'annonce. L'arrosage se fait avant le coucher du soleil.",
    });
    const etat = eteint
      ? `<p class="note alerte"><ha-icon icon="mdi:toggle-switch-off-outline"></ha-icon><span>Le rafraîchissement du soir est <b>éteint</b> : ces deux réglages ne servent pas pour l'instant. Il s'allume dans « Installation ».</span></p>`
      : "";
    return feu + etat;
  }

  _dessinVoyageGraine(v, c) {
    const etapes = etapesGraines(v);
    const age = c.semis ? c.semis.age : null;
    const base = c.maintenant;
    const decalage = age ?? 0;
    const date = (jour) => jourPlus(base, jour - decalage, { day: "numeric", month: "short" });
    const pct = (j) => pourcent(j, 0, v.graines_duree);
    const segs = etapes.map((e) => {
      const largeur = pct(e.a + 1) - pct(e.de);
      return `<div class="seg t-${e.teinte}" style="left:${pct(e.de)}%;width:${largeur}%">${largeur > 18 ? `<span>${esc(e.nom)}</span>` : ""}</div>`;
    }).join("");
    const ici = age !== null && age < v.graines_duree
      ? this._rangeesHtml([{ p: pct(age + 0.5), texte: `aujourd'hui · jour ${age}`, icone: "mdi:flag-variant", genre: "maintenant" }], "bas")
      : "";
    const aiguille = age !== null && age < v.graines_duree ? `<span class="aiguille" style="left:${pct(age + 0.5)}%"></span>` : "";
    const graduations = [0, ...etapes.slice(1).map((e) => e.de), v.graines_duree]
      .map((j) => `<span style="left:${pct(j)}%">J${j}</span>`).join("");
    const cartes = etapes.map((e) => {
      const enCours = age !== null && age >= e.de && age <= e.a;
      return `<div class="etape ${enCours ? "en-cours" : ""}">
        <div class="etape-tete"><span class="pastille t-${e.teinte}"></span>${esc(e.nom)}</div>
        <p><span class="jours">J${e.de} → J${e.a}</span> · ${date(e.de)} → ${date(e.a)}</p>
        <p>${esc(e.phrase)}</p>
      </div>`;
    }).join("");
    const intro = age === null
      ? `<p class="note"><ha-icon icon="mdi:calendar-start"></ha-icon><span>Les dates montrent le déroulement d'un semis commencé <b>aujourd'hui</b>.</span></p>`
      : `<p class="note"><ha-icon icon="mdi:calendar-check"></ha-icon><span>${esc(c.semis.mode)} du ${jourPlus(base, -age, { day: "numeric", month: "long" })} : le gazon en est au jour ${age}.</span></p>`;
    return `<div class="frise">
      <div class="frise-piste">${segs}${aiguille}</div>
      ${ici}
      <div class="graduations">${graduations}</div>
    </div>
    <div class="etapes">${cartes}</div>
    ${intro}`;
  }

  // Une carte par étape : chaque goutte est un arrosage de la journée.
  // Deux arrosages avec TES arroseurs : pile au seuil (d'une traite), puis 2 mm au-dessus.
  _dessinDecoupage(v) {
    const zones = this._zonesAvecDebit();
    if (!zones.length) {
      return `<p class="note"><ha-icon icon="mdi:information-outline"></ha-icon><span>Régler le débit des arroseurs dans « Installation » pour afficher la durée des arrosages.</span></p>`;
    }
    // La borne haute du seuil EST la plus grosse séance du mode Normal (vérifié par les tests).
    const seance = this._reglage("arrosage_decoupage_seuil")?.maximum ?? 15;
    // guidance._profile_for_normal : au-delà de la plus grosse séance, des passages qui n'en
    // dépassent pas ; sinon deux passages au-delà du seuil. La pause, seulement pour une grosse dose.
    const decoupe = (mm) => {
      const passages = mm > seance ? Math.ceil(mm / seance) : mm > v.arrosage_decoupage_seuil ? 2 : 1;
      const pauseS = passages > 1 && mm >= v.arrosage_pause_dose_min ? v.arrosage_pause_duree * 60 : 0;
      return planArrosage(mm, zones, passages, pauseS);
    };
    const exemples = [v.arrosage_decoupage_seuil, v.arrosage_decoupage_seuil + 2]
      .map((mm) => ({ mm, plan: decoupe(mm) }))
      .filter((e) => e.plan);
    const echelle = Math.max(1, ...exemples.map((e) => e.plan.totalS));
    const lignes = exemples.map(({ mm, plan }) => {
      const morceaux = plan.etapes.map((e) => (e.genre === "pause"
        ? `<i class="deroule-pause" style="flex-grow:${e.secondes}"></i>`
        : `<i style="flex-grow:${e.secondes};background:${e.zone.couleur}"></i>`)).join("");
      const comment = plan.passages > 1
        ? `en ${plan.passages} fois, ${plan.pauseS ? `${dureeSecondesFr(plan.pauseS)} de pause` : "sans pause"}`
        : "d'une traite";
      return `<div class="decoupe">
        <div class="decoupe-tete"><b>${esc(mmFr(mm))}</b><span>${esc(comment)} · ${esc(dureeSecondesFr(plan.totalS))}</span></div>
        <div class="deroule-ruban" style="width:${((plan.totalS / echelle) * 100).toFixed(1)}%">${morceaux}</div>
      </div>`;
    }).join("");
    // Les vrais arrosages récents (hors arrosages techniques), relus dans le journal.
    const doses = (this._a("dernier_arrosage", "derniers_arrosages") || [])
      .filter((e) => !CAUSES_TECHNIQUES.includes(String(e.watering_cause || "").toLowerCase()))
      .map((e) => nombreOuNul(e.total_mm))
      .filter((x) => x !== null && x > 0);
    let bilan = "";
    if (doses.length) {
      const coupes = doses.filter((x) => x > v.arrosage_decoupage_seuil).length;
      const verdict = coupes === 0 ? "tous seraient partis d'une traite"
        : coupes === doses.length ? "tous seraient coupés en deux" : `${coupes} sur ${doses.length} seraient coupés en deux`;
      bilan = `Les ${doses.length} derniers arrosages allaient de ${mmFr(Math.min(...doses))} à ${mmFr(Math.max(...doses))} : ${verdict}.`;
    }
    return `<div class="decoupes">${lignes}</div>
      ${bilan ? `<p class="note"><ha-icon icon="mdi:history"></ha-icon><span>${esc(bilan)}</span></p>` : ""}`;
  }

  // Une case par jour, si le mode est déclaré aujourd'hui : le jour même compte.
  _dessinJoursModes(v, c, modes) {
    const presents = modes.filter((m) => Number.isFinite(v[m.cle]));
    if (!presents.length) return "";
    const echelle = Math.max(7, ...presents.map((m) => v[m.cle]));
    const lignes = presents.map((m) => {
      const n = v[m.cle];
      const cases = Array.from({ length: echelle }, (_, i) => `<i class="${i < n ? "plein" : ""}"></i>`).join("");
      const fin = n <= 1 ? "le jour même" : `jusqu'au ${jourPlus(c.maintenant, n - 1, { weekday: "long", day: "numeric", month: "long" })}`;
      return `<li>
        <div class="mode-jours-tete"><b>${esc(m.nom)}</b><span>${esc(valeurFr(this._reglage(m.cle), n))}</span></div>
        <div class="mode-jours-cases" style="--n:${echelle}" aria-hidden="true">${cases}</div>
        <small>${esc(fin)}${m.effet ? ` · ${esc(m.effet)}` : ""}</small>
      </li>`;
    }).join("");
    return `<ul class="modes-jours">${lignes}</ul>
      <p class="note"><ha-icon icon="mdi:calendar-today"></ha-icon><span>Les dates supposent une déclaration aujourd'hui. Ensuite, tout revient au mode Normal.</span></p>`;
  }

  _carteEau(titre, dose, cycles, avecNote, v, minimum) {
    const gouttes = Array.from({ length: cycles }, () => `<ha-icon icon="mdi:water"></ha-icon>`).join("");
    const horaires = repartirCreneauxGraines(v, cycles, minimum).map(heureFr).join(" · ");
    return `<div class="goutte-carte">
        <div class="goutte-ligne" aria-hidden="true">${gouttes}</div>
        <p>${cycles} arrosage${cycles > 1 ? "s" : ""} de ${mmFr(dose)} = <b>${mmFr(cycles * dose)} par jour</b></p>
        <p><ha-icon icon="mdi:clock-outline"></ha-icon> Départs prévus : <b>${esc(horaires)}</b></p>
      </div>
      ${avecNote ? `<p class="note"><ha-icon icon="mdi:information-outline"></ha-icon><span>Chaque goutte est un arrosage. Il peut y en avoir un de plus les jours de grand vent ou de forte chaleur.</span></p>` : ""}`;
  }

  _dessinSoirTonte(v, c) {
    if (!c.soleil) {
      return `<p class="note alerte"><ha-icon icon="mdi:weather-sunny-off"></ha-icon><span>Le soleil est inconnu : le soir se replie sur 17 h → 19 h.</span></p>`;
    }
    const debut = c.soleil.coucher - v.tonte_soir_avant_coucher;
    const fin = c.soleil.coucher + v.tonte_soir_apres_coucher;
    // Quand l'ouverture tombe avant la fin du meilleur moment, c'est lui qui passe le relais.
    const relais = debut <= v.tonte_fenetre_ideale_fin;
    return `<div class="goutte-carte soir">
        <ha-icon icon="mdi:weather-sunset-down"></ha-icon>
        <p>Aujourd'hui, le soleil se couche à <b>${heureFr(c.soleil.coucher)}</b> : la tondeuse peut tondre de <b>${heureFr(relais ? v.tonte_fenetre_ideale_fin : debut)}</b> à <b>${heureFr(fin)}</b>.${relais ? " (Le soir commence dès la fin du meilleur moment.)" : ""}</p>
      </div>`;
  }

  _dessinJourneeGraines(v) {
    const classes = {
      tot: { nom: "Pas encore", phrase: "la surface est encore humide", teinte: "gris" },
      ouvert: { nom: "On arrose les graines", phrase: "", teinte: "eau" },
      parfois: { nom: "Certains jours seulement", phrase: "fermé s'il a plu, s'il va pleuvoir, si l'air est humide, s'il fait plus de 30 °C ou s'il y a du vent", teinte: "eau-raye" },
      soir: { nom: "Jamais le soir", phrase: "les pousses mouillées la nuit pourrissent", teinte: "nuit" },
    };
    const segments = segmenter((m) => classeGraines(m, v), 6 * 60, 21 * 60);
    return this._friseHtml({ debut: 6 * 60, fin: 21 * 60, segments, classes, pasGraduation: 180 });
  }

  _dessinFeuxGraines(v) {
    const vent = this._feuHtml({
      min: 0, max: 30, unite: "km/h",
      zones: [
        { de: 0, a: v.graines_vent_max, teinte: "eau", nom: "On arrose" },
        { de: v.graines_vent_max, a: 30, teinte: "gris", nom: "On attend demain", texte: `à partir de ${nombreFr(v.graines_vent_max)} km/h` },
      ],
    });
    const froid = this._feuHtml({
      min: 0, max: 30, unite: "°C",
      zones: [
        { de: 0, a: v.graines_temperature_min, teinte: "froid", nom: "Trop froid", texte: `${nombreFr(v.graines_temperature_min)} °C ou moins` },
        { de: v.graines_temperature_min, a: 30, teinte: "eau", nom: "On arrose" },
      ],
    });
    return vent + froid;
  }

  _dessinVoyageSursemis(v, c) {
    const duree = v.graines_duree;
    const repriseTonte = v.sursemis_levee + 1;
    const premiere = joursAvantPremiereCoupe(v);
    const n = v.sursemis_coupes_avant_remontee;
    const remontee = premiere + (n - 1) * v.sursemis_ecart_tontes;
    const pct = (j) => pourcent(j, 0, duree);
    const zones = [
      { de: 0, a: repriseTonte, teinte: "ambre", nom: "La tondeuse attend" },
      { de: repriseTonte, a: Math.min(remontee, duree), teinte: "vert-clair", nom: `Lame à ${cmFr(v.sursemis_lame)}` },
      { de: Math.min(remontee, duree), a: duree, teinte: "vert", nom: `Lame à ${cmFr(v.sursemis_lame_finale)}` },
    ].filter((z) => z.a > z.de);
    const segs = zones.map((z) => {
      const largeur = pct(z.a) - pct(z.de);
      return `<div class="seg t-${z.teinte}" style="left:${pct(z.de)}%;width:${largeur}%">${largeur > 20 ? `<span>${esc(z.nom)}</span>` : ""}</div>`;
    }).join("");
    const age = c.semis?.mode === "Sursemis" ? c.semis.age : null;
    const base = c.maintenant;
    const date = (jour) => jourPlus(base, jour - (age ?? 0), { weekday: "short", day: "numeric", month: "short" });
    const reperesHaut = [];
    if (premiere < duree) reperesHaut.push({ j: premiere, texte: `${ordinal(1)} coupe J${premiere}`, icone: "mdi:content-cut" });
    const reperesBas = [{ j: repriseTonte, texte: `la tondeuse repart J${repriseTonte}`, icone: "mdi:robot-mower" }];
    if (age !== null && age < duree) reperesBas.push({ j: age + 0.5, texte: `jour ${age}`, icone: "mdi:flag-variant", genre: "maintenant" });
    const rangee = (items, ligne) => this._rangeesHtml(items.map((r) => ({ ...r, p: pct(r.j) })), ligne);
    const aiguilles = [...reperesHaut, ...reperesBas].map((r) => `<span class="aiguille ${r.genre || ""}" style="left:${pct(r.j)}%"></span>`).join("");
    const hauteurCoupe = v.sursemis_premiere_coupe * v.sursemis_lame;
    const lignes = [
      `<li><span class="pastille t-ambre"></span><span><b>Jusqu'au jour ${v.sursemis_levee}</b> — la tondeuse attend que les graines s'accrochent<br><span class="heures">reprise au jour ${repriseTonte}, le ${date(repriseTonte)}</span></span></li>`,
      premiere < duree
        ? `<li><span class="pastille t-vert-clair"></span><span><b>Jour ${premiere} : ${ordinal(1)} coupe des pousses</b> — elles mesurent alors ${cmFr(hauteurCoupe)} (${nombreFr(v.sursemis_premiere_coupe)} × ${cmFr(v.sursemis_lame)})<br><span class="heures">vers le ${date(premiere)}</span></span></li>`
        : `<li><span class="pastille t-vert-clair"></span><span><b>Première coupe après la fin du suivi</b> — les pousses n'atteignent ${cmFr(hauteurCoupe)} qu'au jour ${premiere}</span></li>`,
      remontee < duree
        ? `<li><span class="pastille t-vert"></span><span><b>Après ${n} coupe${n > 1 ? "s" : ""} : lame à ${cmFr(v.sursemis_lame_finale)}</b> — au plus tôt le jour ${remontee}<br><span class="heures">vers le ${date(remontee)}</span></span></li>`
        : `<li><span class="pastille t-vert"></span><span><b>Lame à ${cmFr(v.sursemis_lame_finale)}</b> — pas avant la fin du suivi (jour ${duree})</span></li>`,
    ];
    const intro = age === null
      ? `<p class="note"><ha-icon icon="mdi:calendar-start"></ha-icon><span>Les dates montrent le déroulement d'un sursemis commencé <b>aujourd'hui</b>. Pousse estimée : ${nombreFr(v.sursemis_pousse_plantules)} cm par jour après la levée, une tonte tous les ${v.sursemis_ecart_tontes} jours au plus.</span></p>`
      : `<p class="note"><ha-icon icon="mdi:calendar-check"></ha-icon><span>Sursemis en cours : jour ${age}, ${c.semis.coupes} coupe${c.semis.coupes > 1 ? "s" : ""} des pousses comptée${c.semis.coupes > 1 ? "s" : ""}.</span></p>`;
    return `<div class="frise">
      ${rangee(reperesHaut, "haut")}
      <div class="frise-piste">${segs}${aiguilles}</div>
      ${rangee(reperesBas, "bas")}
      <div class="graduations"><span style="left:0%">J0</span><span style="left:100%">J${duree}</span></div>
      <ul class="legende">${lignes.join("")}</ul>
    </div>${intro}`;
  }

  _dessinLame(v, c) {
    const n = v.sursemis_coupes_avant_remontee;
    const reelle = this._valeurEntiteReelle("hauteur_coupe_tondeuse");
    const enCours = c.semis?.mode === "Sursemis";
    const consigne = enCours && c.semis.coupes >= n ? v.sursemis_lame_finale : v.sursemis_lame;
    let note = "";
    if (typeof reelle === "number" && enCours && !egal(reelle / 10, consigne)) {
      note = `<p class="note alerte"><ha-icon icon="mdi:content-cut"></ha-icon><span>La lame est à <b>${cmFr(reelle / 10)}</b>, le sursemis demande <b>${cmFr(consigne)}</b> : la ${reelle / 10 < consigne ? "remonter" : "descendre"} avant la prochaine tonte, d'abord sur la tondeuse puis dans « Installation ».</span></p>`;
    } else if (typeof reelle === "number") {
      note = `<p class="note"><ha-icon icon="mdi:content-cut"></ha-icon><span>La lame est réglée à <b>${cmFr(reelle / 10)}</b> en ce moment${enCours ? ", conformément au besoin du sursemis" : " (pas de sursemis en cours)"}.</span></p>`;
    }
    return `<div class="lame">
      <div class="lame-carte"><small>Pendant le sursemis</small><strong>${cmFr(v.sursemis_lame)}</strong><small>pour laisser passer la lumière</small></div>
      <span class="lame-fleche"><ha-icon icon="mdi:arrow-right-bold"></ha-icon></span>
      <div class="lame-carte"><small>Après ${n} coupe${n > 1 ? "s" : ""} des pousses</small><strong>${cmFr(v.sursemis_lame_finale)}</strong><small>jusqu'à la fin du suivi</small></div>
    </div>${note}`;
  }

  _dessinEscalier(v, c) {
    const ceMois = c.maintenant.mois - 1;
    const base = v.tonte_hauteur_par_mois[ceMois];
    const etapes = etapesGraines(v);
    // Césures douces : « Enracinement » ne tient pas dans une colonne de téléphone.
    const marches = [
      { nom: "Germi&shy;nation", h: v.semis_hauteur_germination, sousTitre: "jeunes pousses", classe: "", etape: etapes[0] },
      { nom: "Enraci&shy;nement", h: v.semis_hauteur_enracinement, sousTitre: "racines en formation", classe: "", etape: etapes[1] },
      { nom: "Reprise", h: v.semis_hauteur_reprise, sousTitre: "hauteur protégée", classe: "", etape: etapes[2] },
      { nom: "Stabili&shy;sation", h: v.semis_hauteur_stabilisation, sousTitre: "on descend", classe: "", etape: etapes[3] },
      { nom: "Ensuite", h: base, sousTitre: `hauteur de ${MOIS_LONGS[ceMois]}`, classe: "base", etape: null },
    ];
    const age = c.semis?.mode === "Semis" ? c.semis.age : null;
    const max = 10;
    return `<div class="escalier">${marches.map((m) => {
      const ici = age !== null && m.etape && age >= m.etape.de && age <= m.etape.a;
      return `<div class="marche ${ici ? "en-cours" : ""}">
        <div class="marche-colonne"><div class="marche-barre ${m.classe}" style="height:${Math.max(14, (m.h / max) * 100)}%">${nombreFr(m.h, 1)}</div></div>
        <b>${m.nom}</b><span>${esc(m.sousTitre)}</span>${ici ? `<em>jour ${age}</em>` : ""}
      </div>`;
    }).join("")}</div>
      <p class="note"><ha-icon icon="mdi:information-outline"></ha-icon><span>Hauteurs en centimètres. Ce sont des minimums : la hauteur conseillée ne descend jamais en dessous pendant le semis.</span></p>
      <p class="note"><ha-icon icon="mdi:robot-mower"></ha-icon><span>La tondeuse reste à l'arrêt jusqu'au jour ${v.semis_reprise_tonte_jours - 1} inclus et peut reprendre à J${v.semis_reprise_tonte_jours}. Ce délai est réglé dans « Semis » et ne modifie pas les étapes d'arrosage.</span></p>`;
  }

  // ══ Base de contrôle (Accueil) ══════════════════════════════════════════════════════════

  // Lecture des entités de l'instance, par clé logique (`entites` du serveur).
  _a(cle, nom) {
    return this._entite(cle)?.attributes?.[nom];
  }

  _s(cle) {
    const e = this._entite(cle);
    return e ? e.state : null;
  }

  _allume(id) {
    return Boolean(id) && this._hass?.states?.[id]?.state === "on";
  }

  _zones() {
    return (this._donnees?.zones || []).map((z, i) => ({
      ...z,
      index: i,
      numero: z.numero || i + 1,
      nom: z.nom || `Zone ${z.numero || i + 1}`,
      couleur: COULEURS_ZONES[i % COULEURS_ZONES.length],
    }));
  }

  _zoneActive(z) {
    return this._allume(z.switch) || this._allume(z.etat);
  }

  _sessionActive() {
    return this._a("arrosage_en_cours", "active") === true;
  }

  _verrouSecuriteActif() {
    return this._a("blocage_arrosage", "safety_lock_actif") === true;
  }

  _arrosageEnCours() {
    return this._sessionActive() || this._zones().some((z) => this._zoneActive(z));
  }

  _tonduAujourdhui(c) {
    const j = jourDe(this._a("tonte_autorisee", "derniere_tonte_date"), this._fuseau());
    return Boolean(j) && ecartJours(j, c.maintenant) === 0;
  }

  // ⚠️ On LIT la retenue de l'intégration, on ne la recalcule pas (carte, 31/07/2026) : elle
  // retient dès le PLANCHER, sous conditions ; le plafond dur n'est qu'un repli.
  _retenuParLeBudget() {
    const code = String(this._a("prochain_arrosage", "block_reason") || "");
    if (code.includes("garde_fou") || code.includes("guardrail")) return true;
    // ⚠️ Ce repli suppose un lien entre dépassement et retenue qui n'existe pas en Semis/Sursemis :
    // `guidance._profile_for_sursemis` ne regarde jamais ce plafond (23/09/2026, relevé en direct
    // à 119 % du plafond pendant un cycle graines normalement autorisé).
    if (this._budgetEstInformatifSeul()) return false;
    const utilise = nombreOuNul(this._a("reserve", "arrosage_recent_7j"));
    const plafond = nombreOuNul(this._a("fenetre_optimale", "weekly_guardrail_mm_max"));
    return utilise !== null && plafond !== null && plafond > 0 && utilise >= plafond;
  }

  // ⚠️ `_profile_for_normal` (`guidance.py`) est le SEUL profil où `guardrail_max_effective`
  // borne réellement `mm_cible`. Tous les autres (`_profile_for_sursemis`, `_profile_for_
  // traitement`, `_profile_for_agro_phases` — Fertilisation/Biostimulant/Agent Mouillant/
  // Scarification —, `_profile_for_generic`, `_profile_for_blocked` pour l'Hivernage) ne font
  // que faire traverser `guardrail_min_mm`/`guardrail_max_mm` dans le payload sans jamais les
  // utiliser pour décider — vérifié dans les cinq fonctions, pas seulement Semis/Sursemis (revue
  // du 23/09/2026 sur la PR #63 : la première version de ce garde blanchissait Semis/Sursemis
  // seuls et traitait Traitement comme une vraie limite, alors qu'il ne l'est pas davantage).
  // Présenter ce plafond comme une limite bloquante hors phase Normal promettrait donc une
  // sécurité qui n'existe pas.
  //
  // ⚠️ LISTE BLANCHE, PAS `!== "Normal"` (revue du 23/09/2026) : si le capteur de phase est
  // indisponible, désactivé ou pas encore chargé, `_s("phase")` rend `null`, ce que `!== "Normal"`
  // aurait classé « pas Normal » et donc masqué un plafond qui, par défaut (`phases.py`,
  // `phase_dominante` vaut « Normal » tant que rien d'autre n'est actif), s'applique réellement.
  // Un plafond affiché par excès de prudence est sans conséquence (texte seul) ; un plafond
  // masqué à tort cache une vraie limite.
  _budgetEstInformatifSeul() {
    const phase = this._s("phase");
    return _PHASES_SANS_PLAFOND_HEBDO.has(phase);
  }

  // L'orange est une ALERTE : un blocage sain (déjà arrosé, pluie prévue) reste calme.
  _blocageMeriteAlerte() {
    const risque = String(this._s("risque") || "").toLowerCase();
    if (risque === "eleve" || risque === "critique") return true;
    const reserve = nombreOuNul(this._s("reserve"));
    const seuil = nombreOuNul(this._a("etat_hydrique", "reserve_minimale_mm") ?? this._a("reserve", "reserve_minimale_mm"));
    return reserve !== null && seuil !== null && reserve < seuil;
  }

  // Heure du prochain départ (0.90.0+) : publiée seulement pour un départ réellement attendu.
  _prochainDepart(c) {
    const hhmm = (v) => {
      const m = typeof v === "string" ? v.trim().match(/^(\d{2}):(\d{2})$/) : null;
      return m ? heureFr(Number(m[1]) * 60 + Number(m[2])) : "";
    };
    const depart = hhmm(this._a("prochain_arrosage", "departure_time"));
    if (!depart) return null;
    const cible = this._a("prochain_arrosage", "target_datetime");
    return {
      depart,
      fin: hhmm(this._a("prochain_arrosage", "end_time")),
      jour: cible ? dateHumaine(cible, c.maintenant, this._fuseau()) : "",
    };
  }

  _jourEstime(c) {
    const n = nombreOuNul(this._a("prochain_arrosage", "jours_avant_arrosage_estime"));
    const iso = this._a("prochain_arrosage", "date_prochain_arrosage_estime");
    if (n === null || !iso) return "";
    if (n <= 0) return "très bientôt";
    if (n <= 6) return dateHumaine(iso, c.maintenant, this._fuseau());
    return `dans ${Math.round(n)} jours environ`;
  }

  // La fenêtre « 03:45–10:00 » dite comme le reste de la page.
  _fenetreFr(texte) {
    return String(texte || "").replace(/(\d{1,2}):(\d{2})/g, (_, h, m) => heureFr(Number(h) * 60 + Number(m))).replace(/\s*[–-]\s*/, " → ");
  }

  // Semis et Sursemis : les graines sont arrosées CHAQUE jour par petits cycles. Leur prochain
  // arrosage n'est pas l'estimation du régime Normal (0.96.1 : le 17/09, en germination, la page
  // annonçait « Prochain arrosage : dimanche 20 septembre » ; le cycle suivant partait le
  // lendemain à 8 h 30).
  _suiviGraines(c) {
    const f = (k) => this._a("fenetre_optimale", k);
    if (f("watering_strategy") !== "semis_frequent") return null;
    const etat = String(f("semis_followup_state") || "");
    const motif = String(f("seeding_block_reason") || "");
    const echeance = f("semis_followup_due_at");
    const ouverture = nombreOuNul(f("watering_window_start_minute"));
    const iso = this._a("prochain_arrosage", "date_prochain_arrosage_estime");
    return {
      fini: etat === "complete" || motif === "semis_cycle_daily_target_reached",
      enAttente: etat === "waiting" || motif === "semis_cycle_pending",
      faits: nombreOuNul(f("semis_cycles_completed_today")),
      prevus: nombreOuNul(f("semis_daily_cycles_target") ?? f("daily_cycles_target")),
      dose: nombreOuNul(f("surface_cycle_mm")),
      heure: echeance ? heureFr(partiesLocales(new Date(echeance), this._fuseau()).minute) : "",
      ouverture: ouverture !== null ? heureFr(ouverture) : "",
      jour: iso ? dateHumaine(iso, c.maintenant, this._fuseau()) : "",
    };
  }

  // Le programme Semis/Sursemis reste visible dans le bandeau commun de toutes les pages et dans
  // l'introduction des réglages. Ce sont les valeurs effectivement choisies après adaptation
  // météo, pas les valeurs de base du registre.
  _pucesProgrammeGraines(c) {
    if (!c.semis || !["Semis", "Sursemis"].includes(c.semis.mode)) return [];
    const f = (k) => this._a("fenetre_optimale", k);
    const suivi = this._suiviGraines(c);
    const etapeBrute = this._a("objectif", "sous_phase") || f("watering_stage") || "";
    const etapes = { germination: "Germination", enracinement: "Enracinement", levee: "Reprise", reprise: "Reprise", stabilisation: "Stabilisation" };
    const etape = etapes[String(etapeBrute).toLowerCase()] || majuscule(String(etapeBrute));
    const fenetre = this._fenetreFr(f("watering_window_display"));
    const statutTonte = String(this._a("tonte_autorisee", "tonte_statut") || "");
    const tonte = statutTonte === "autorisee" ? "Tonte possible" : statutTonte ? `Tonte ${minuscule(libelleDe(STATUTS_TONTE, statutTonte))}` : "";
    const hauteur = c.hauteurConseillee !== null ? `${cmFr(c.hauteurConseillee)} conseillés` : "";
    const puces = [];
    if (etape) puces.push(`<span class="puce" data-programme-graines="etape"><ha-icon icon="mdi:seed-outline"></ha-icon><b>${esc(etape)}</b> · J${esc(String(c.semis.age))}</span>`);
    if (suivi && (suivi.dose !== null || suivi.prevus !== null)) {
      const eau = [suivi.dose !== null ? `${mmFr(suivi.dose)} par cycle` : "", suivi.prevus !== null ? `objectif météo ${nombreFr(suivi.prevus, 0)}` : ""].filter(Boolean).join(" · ");
      puces.push(`<span class="puce" data-programme-graines="eau"><ha-icon icon="mdi:water-outline"></ha-icon>${esc(eau)}</span>`);
    }
    if (fenetre) puces.push(`<span class="puce" data-programme-graines="fenetre"><ha-icon icon="mdi:clock-outline"></ha-icon>${esc(fenetre)}</span>`);
    if (tonte || hauteur) puces.push(`<span class="puce" data-programme-graines="tonte"><ha-icon icon="mdi:robot-mower"></ha-icon>${esc([tonte, hauteur].filter(Boolean).join(" · "))}</span>`);
    return puces;
  }

  // Même principe pour les modes produit (Traitement, Fertilisation…) et l'hivernage (0.96.2) :
  // le bandeau et l'intro des réglages disent le besoin du mode, pas seulement son nom. Rien pour
  // Normal (déjà le régime par défaut) ni pour Semis/Sursemis (`_pucesProgrammeGraines` s'en charge).
  _pucesProgrammeMode(c) {
    // Une seule garde : la liste blanche suffit (elle exclut déjà Normal, un mode inconnu, et
    // Semis/Sursemis passe par `_pucesProgrammeGraines`). Un « c.mode !== Normal && !c.semis »
    // en plus serait retombé sur exactement le même verdict dans tous les cas.
    if (!MODES_PRODUIT.includes(c.mode) && c.mode !== "Hivernage") return [];
    const puces = [];
    // L'hivernage n'a pas de durée bornée (`PHASE_DURATIONS_DAYS.Hivernage = 999`) : jamais de
    // compte de jours pour lui, même si un appelant fournissait quand même une valeur.
    if (c.mode !== "Hivernage" && c.joursRestantsMode !== null) {
      const texte = c.joursRestantsMode <= 0 ? "dernier jour du mode" : `encore ${nombreFr(c.joursRestantsMode, 0)} jour${c.joursRestantsMode > 1 ? "s" : ""}`;
      puces.push(`<span class="puce" data-programme-mode="jours"><ha-icon icon="mdi:calendar-clock"></ha-icon>${esc(texte)}</span>`);
    }
    const besoin = BESOIN_MODES[c.mode];
    if (besoin) puces.push(`<span class="puce" data-programme-mode="besoin"><ha-icon icon="mdi:information-outline"></ha-icon>${esc(besoin)}</span>`);
    const statutTonte = String(this._a("tonte_autorisee", "tonte_statut") || "");
    const tonte = statutTonte === "autorisee" ? "Tonte possible" : statutTonte ? `Tonte ${minuscule(libelleDe(STATUTS_TONTE, statutTonte))}` : "";
    if (tonte) puces.push(`<span class="puce" data-programme-mode="tonte"><ha-icon icon="mdi:robot-mower"></ha-icon>${esc(tonte)}</span>`);
    return puces;
  }

  // Les mots des graines, pour la tuile, le bulletin et l'onglet Arrosage.
  _motsGraines(g) {
    const fait = g.faits === null ? "" : g.faits === 1 ? "1 cycle fait" : `${nombreFr(g.faits, 0)} cycles faits`;
    const sur = fait && g.prevus !== null && g.faits < g.prevus ? ` sur ${nombreFr(g.prevus, 0)}` : "";
    const dose = g.dose !== null && g.dose > 0 ? `${mmFr(g.dose)} par cycle` : "";
    const des = g.ouverture ? ` dès ${g.ouverture}` : "";
    if (g.fini) {
      return {
        titre: "Graines : c'est fini pour aujourd'hui",
        texte: `${fait ? `${majuscule(fait)} aujourd'hui. ` : ""}Prochain cycle demain${des} ; leur nombre suivra la météo.`,
        valeur: `Demain${des}`,
        sous: ["graines", fait ? `${fait} aujourd'hui` : ""].filter(Boolean).join(" · "),
        phrase: `Graines : ${fait ? `<b>${esc(fait)} aujourd'hui</b>` : "<b>c'est fini pour aujourd'hui</b>"}. Prochain cycle demain${esc(des)}.`,
      };
    }
    if (g.enAttente) {
      const vers = g.heure ? `vers ${g.heure}` : "bientôt";
      return {
        titre: `Prochain cycle de graines ${vers}`,
        texte: [fait ? `${majuscule(fait)}${sur} aujourd'hui.` : "", dose ? `${majuscule(dose)}.` : ""].filter(Boolean).join(" "),
        valeur: majuscule(vers),
        sous: ["graines", fait ? `${fait}${sur}` : dose].filter(Boolean).join(" · "),
        phrase: `Graines : prochain cycle <b>${esc(vers)}</b>${fait ? ` (${esc(fait)}${esc(sur)} aujourd'hui)` : ""}.`,
      };
    }
    const quand = g.jour || "bientôt";
    // « Aujourd'hui dès 8 h 30 » ne veut rien dire à 10 h : l'heure d'ouverture sert pour demain.
    const desQuand = quand === "aujourd'hui" || quand === "bientôt" ? "" : des;
    return {
      titre: `Prochain cycle de graines : ${quand}${desQuand}`,
      texte: [fait ? `${majuscule(fait)}${sur} aujourd'hui.` : "", dose ? `${majuscule(dose)}, selon la météo.` : ""].filter(Boolean).join(" "),
      valeur: `${majuscule(quand)}${desQuand}`,
      sous: ["graines", dose].filter(Boolean).join(" · "),
      phrase: `Graines : prochain cycle <b>${esc(quand)}${esc(desQuand)}</b>.`,
    };
  }

  // Un seul endroit décide de ce qu'on dit de l'arrosage : la tuile, le bulletin et l'onglet
  // Arrosage ne peuvent plus se contredire (ils ont divergé une fois sur la carte).
  _etatArrosage(c) {
    const a = (k) => this._a("prochain_arrosage", k);
    const etat = String(this._s("prochain_arrosage") || "");
    const fenetre = this._fenetreFr(a("watering_window_display"));
    const motif = String(a("block_reason_label") || "").trim();
    const code = String(a("block_reason") || "");
    const mm = nombreOuNul(a("objective_mm"));
    if (this._arrosageEnCours()) return { genre: "session", fenetre };
    // L'attente normale entre deux cycles de graines n'est pas un blocage : l'état publie pourtant
    // « Bloqué » pendant qu'un cycle attend son heure.
    const graines = this._suiviGraines(c);
    if (graines && (graines.fini || graines.enAttente)) return { genre: "graines", graines, fenetre };
    // Blocage lu sur l'ÉTAT : le libellé peut traîner alors que l'état dit « Non requis ».
    if (etat === "Bloqué" || etat === "Retenu") {
      return {
        genre: "bloque", titre: motif || "Arrosage bloqué", fenetre,
        pluie: code.includes("pluie") || code.includes("rain"), alerte: this._blocageMeriteAlerte(),
      };
    }
    if (mm !== null && mm > 0) return { genre: "prevu", mm, depart: this._prochainDepart(c), fenetre };
    if (this._retenuParLeBudget()) {
      return {
        genre: "retenu", titre: motif || "Semaine couverte", fenetre,
        besoin: nombreOuNul(this._a("objectif", "besoin_mm")), alerte: this._blocageMeriteAlerte(),
      };
    }
    if (graines) return { genre: "graines", graines, fenetre };
    const jour = this._jourEstime(c);
    if (jour) return { genre: "estime", jour, fenetre };
    return { genre: "rien", titre: String(a("summary") || etat || "Pas d'arrosage prévu"), fenetre };
  }

  _texteHeure() {
    const p = partiesLocales(new Date(), this._fuseau());
    return `${majuscule(jourPlus(p, 0, { weekday: "long", day: "numeric", month: "long" }))} · ${heureFr(p.minute)}`;
  }

  _corpsAccueilHtml() {
    const c = this._contexte();
    const courant = ONGLETS_ACCUEIL.find((o) => o.cle === this._ongletAccueil) || ONGLETS_ACCUEIL[0];
    const contenu = {
      apercu: () => this._ongletApercuHtml(c),
      arrosage: () => this._ongletArrosageHtml(c),
      tonte: () => this._ongletTonteHtml(c),
      gazon: () => this._ongletGazonHtml(c),
      meteo: () => this._ongletMeteoHtml(c),
      produits: () => this._ongletProduitsHtml(c),
    }[courant.cle]();
    const signaux = {
      arrosage: this._arrosageEnCours() ? `<span class="signal" aria-label="arrosage en cours"></span>` : "",
      produits: ["recommande", "recommended"].includes(String(this._s("prochaine_intervention") || ""))
        ? `<span class="signal violet" aria-label="produit conseillé"></span>` : "",
    };
    return `
      ${this._maintenantHtml(c)}
      <nav class="onglets" role="tablist" aria-label="Tableau de bord">
        ${ONGLETS_ACCUEIL.map((o) => `<button class="onglet" role="tab" data-onglet-accueil="${o.cle}" aria-selected="${o.cle === courant.cle}">
          <ha-icon icon="${o.icone}"></ha-icon>${esc(o.titre)}${signaux[o.cle] || ""}</button>`).join("")}
      </nav>
      <div class="panneau" role="tabpanel" aria-label="${esc(courant.titre)}">${contenu}</div>`;
  }

  // ── Le bandeau « En ce moment » ──

  _maintenantHtml(c) {
    const a = (k) => this._a("assistant", k);
    const action = String(a("action") || this._s("assistant") || "aucune_action");
    const statut = String(a("status") || "");
    // Canicule = arrosage de SURVIE signalé par l'intégration, pas le score composite de chaleur.
    const canicule = a("survie_canicule_active") === true;
    const enCours = this._arrosageEnCours();
    const bloque = statut.includes("block") || ["aucune_action", "attente_conditions"].includes(action);
    const ton = canicule ? "danger" : enCours || (action === "arrosage" && !bloque) ? "eau"
      : bloque && this._blocageMeriteAlerte() ? "alerte" : "calme";
    const fiche = ACTIONS[action];
    let titre = fiche ? (bloque && fiche.attente) || fiche.titre : majuscule(action.replace(/_/g, " "));
    let icone = fiche?.icone || "mdi:timer-sand";
    if (action === "aucune_action" && statut === "no_need") titre = "Tout va bien";
    // L'assistant range « autorisee_avec_precaution » et « a_surveiller » dans le même statut
    // « pas bloqué » que « autorisee » (assistant.py, actionable_statuses) : le titre suivait donc
    // ce regroupement et annonçait « possible » sans nuance, même en précaution ou à surveiller.
    if (action === "tonte" && !bloque) {
      const statutTonte = String(this._a("tonte_autorisee", "tonte_statut") || "");
      if (statutTonte === "autorisee_avec_precaution") titre = "La tonte est possible, avec précaution";
      else if (statutTonte && statutTonte !== "autorisee") titre = `Tonte ${minuscule(libelleDe(STATUTS_TONTE, statutTonte))}`;
    }
    let sous = majuscule(a("reason") || "");
    let session = "";
    if (enCours) {
      titre = "Arrosage en cours";
      icone = "mdi:sprinkler-variant";
      sous = this._texteSession();
      const pct = Math.max(0, Math.min(100, nombreOuNul(this._a("arrosage_en_cours", "progress_percent")) ?? 0));
      const arret = this._commandesEnCours.has("arreter");
      session = `${this._sessionActive() ? `<div class="progression" role="progressbar" aria-valuenow="${Math.round(pct)}" aria-valuemin="0" aria-valuemax="100"><i style="width:${pct}%"></i></div>` : ""}
        <div class="maintenant-session">
          ${this._sessionActive() ? `<b>${nombreFr(pct, 0)} %</b>` : ""}
          <button class="bouton-blanc" data-commande="arreter" ${arret ? "disabled" : ""}><ha-icon icon="mdi:stop-circle-outline"></ha-icon>${arret ? "Arrêt en cours…" : "Arrêter l'arrosage"}</button>
        </div>`;
    }
    const puces = [];
    const moment = String(a("moment") || "");
    const mm = nombreOuNul(a("quantity_mm"));
    if (!enCours && moment && moment !== "attendre" && moment !== "none") {
      puces.push(`<span class="puce"><ha-icon icon="mdi:clock-outline"></ha-icon>${esc(majuscule(MOMENTS[moment] || moment.replace(/_/g, " ")))}</span>`);
    }
    if (!enCours && mm !== null && mm > 0) puces.push(`<span class="puce"><ha-icon icon="mdi:water"></ha-icon>${esc(mmFr(mm))}</span>`);
    if (c.mode && c.mode !== "Normal" && !["Semis", "Sursemis"].includes(c.semis?.mode)) {
      puces.push(`<span class="puce"><ha-icon icon="mdi:sprout"></ha-icon>${esc(c.mode)}${c.semis ? ` · jour ${c.semis.age}` : ""}</span>`);
    }
    puces.push(...this._pucesProgrammeGraines(c));
    puces.push(...this._pucesProgrammeMode(c));
    const auto = this._valeurEntiteReelle("arrosage_automatique");
    if (auto !== undefined) {
      puces.push(`<span class="puce" data-maintenant="auto"><ha-icon icon="${auto ? "mdi:autorenew" : "mdi:hand-back-right-outline"}"></ha-icon>Arrosage automatique ${auto ? "allumé" : "éteint"}</span>`);
    }
    const sur = ["En ce moment", this._donnees?.sous_titre].filter(Boolean).map(esc).join(" · ");
    return `<section class="en-ce-moment ${ton}">
      <div class="maintenant-principal">
        <div class="maintenant-icone"><ha-icon icon="${icone}"></ha-icon></div>
        <div style="min-width:0">
          <div class="maintenant-sur">${sur}</div>
          <h2>${esc(titre)}</h2>
          ${sous ? `<p>${esc(sous)}</p>` : ""}
          ${canicule ? `<p><b>Canicule :</b> la survie du gazon passe avant tout.</p>` : ""}
          ${session}
          ${puces.length ? `<div class="puces">${puces.join("")}</div>` : ""}
        </div>
      </div>
      ${this._meteoHtml()}
    </section>`;
  }

  _texteSession() {
    const a = (k) => this._a("arrosage_en_cours", k);
    const morceaux = [];
    const debut = a("started_at_utc");
    if (debut && !Number.isNaN(Date.parse(debut))) {
      morceaux.push(`commencé à ${heureFr(partiesLocales(new Date(debut), this._fuseau()).minute)}`);
    }
    const reste = nombreOuNul(a("remaining_session_seconds"));
    if (reste !== null && reste > 0) morceaux.push(`encore ${dureeFr(Math.ceil(reste / 60))} environ`);
    const actives = this._zones().filter((z) => this._zoneActive(z)).map((z) => z.nom);
    if (actives.length) morceaux.push(`en ce moment : ${actives.join(", ")}`);
    else if (this._sessionActive() && (nombreOuNul(a("current_passage")) ?? 1) > 1) morceaux.push("pause entre deux passages");
    return majuscule(morceaux.join(" · ")) || majuscule(a("detail") || "");
  }

  _meteoHtml() {
    const id = this._donnees?.meteo;
    const e = id ? this._hass.states[id] : null;
    const heure = `<div class="meteo-heure" data-heure>${esc(this._texteHeure())}</div>`;
    if (!e) return `<div class="meteo">${heure}</div>`;
    const a = e.attributes || {};
    const [icone, libelle] = METEOS[e.state] || ["mdi:weather-cloudy-alert", majuscule(String(e.state).replace(/[-_]/g, " "))];
    const unite = a.temperature_unit || "°C";
    const p = this._prevision;
    const temp = nombreOuNul(a.temperature);
    const lignes = [];
    if (p && nombreOuNul(p.templow) !== null && nombreOuNul(p.temperature) !== null) {
      lignes.push(`<span title="Plus bas et plus haut du jour">${nombreFr(p.templow, 0)} → ${nombreFr(p.temperature, 0)} ${esc(unite)}</span>`);
    }
    if (nombreOuNul(a.humidity) !== null) lignes.push(`<span title="Humidité de l'air"><ha-icon icon="mdi:water-percent"></ha-icon>${nombreFr(a.humidity, 0)} %</span>`);
    if (nombreOuNul(a.wind_speed) !== null) lignes.push(`<span title="Vent"><ha-icon icon="mdi:weather-windy"></ha-icon>${nombreFr(a.wind_speed, 0)} ${esc(a.wind_speed_unit || "km/h")}</span>`);
    if (p && nombreOuNul(p.precipitation) !== null) lignes.push(`<span title="Pluie attendue aujourd'hui"><ha-icon icon="mdi:weather-rainy"></ha-icon>${nombreFr(p.precipitation, 1)} mm</span>`);
    // UV et point de rosée : utiles POUR UN GAZON (stress lumineux, rosée du matin qui retarde la tonte).
    if (nombreOuNul(a.uv_index) !== null) lignes.push(`<span title="Indice UV : au-delà de 6, le gazon encaisse"><ha-icon icon="mdi:white-balance-sunny"></ha-icon>UV ${nombreFr(a.uv_index, 1)}</span>`);
    if (nombreOuNul(a.dew_point) !== null) lignes.push(`<span title="Point de rosée : proche de la température, la rosée arrive au petit matin"><ha-icon icon="mdi:water-outline"></ha-icon>Point de rosée ${nombreFr(a.dew_point, 0)} ${esc(unite)}</span>`);
    return `<div class="meteo">
      <div class="meteo-haut"><ha-icon icon="${icone}"></ha-icon><div>
        <div class="meteo-temp">${temp !== null ? `${nombreFr(temp, 1)} ${esc(unite)}` : "—"}</div>
        <div class="meteo-libelle">${esc(libelle)}</div>
      </div></div>
      ${lignes.length ? `<div class="meteo-ligne">${lignes.join("")}</div>` : ""}
      ${heure}
    </div>`;
  }

  // ── Aperçu ──

  // Le bulletin se lit en phrases (couloir large), les quatre chiffres tiennent en carré à côté,
  // et les boutons s'alignent sur toute la largeur.
  _ongletApercuHtml(c) {
    return this._mosaique([
      [this._bulletinHtml(c) + this._pastillesHtml(), "large", "large"],
      [this._tuilesHtml(c, { carre: true }), "etroit", "etroit"],
      [this._actionsHtml(c), "tout", "tout"],
    ]);
  }

  // Le bulletin : des PHRASES composées sur les valeurs réelles. Rien à dire = rien d'écrit.
  _bulletinHtml(c) {
    const fuseau = this._fuseau();
    const lignes = [];
    const dernier = nombreOuNul(this._s("dernier_arrosage"));
    const quand = String(this._a("dernier_arrosage", "last_watering_when") || "");
    const jQuand = jourDe(quand, fuseau);
    if (jQuand && dernier !== null && dernier > 0) {
      const heure = (quand.split(" à ")[1] || "").trim();
      const m = heure.match(/^(\d{1,2}):(\d{2})$/);
      const aHeure = m ? ` à ${heureFr(Number(m[1]) * 60 + Number(m[2]))}` : "";
      if (ecartJours(jQuand, c.maintenant) === 0) {
        const n = nombreOuNul(this._a("dernier_arrosage", "zone_count"));
        lignes.push(`<b>${esc(mmFr(dernier))}</b> ont été arrosés aujourd'hui${aHeure}${n ? `, sur ${n} zone${n > 1 ? "s" : ""}` : ""}.`);
      } else {
        lignes.push(`Dernier arrosage : <b>${esc(mmFr(dernier))}</b>, ${esc(dateHumaine(isoDuJour(jQuand), c.maintenant, fuseau))}${aHeure}.`);
      }
    }
    const reserve = nombreOuNul(this._s("reserve"));
    const utile = nombreOuNul(this._a("reserve", "reserve_utile_mm")) ?? 12;
    const seuil = nombreOuNul(this._a("objectif", "reserve_minimale_mm") ?? this._a("etat_hydrique", "reserve_minimale_mm") ?? this._a("reserve", "reserve_minimale_mm"));
    if (reserve !== null) {
      const etat = seuil !== null && reserve < seuil ? "le sol commence à manquer d'eau"
        : reserve >= utile * 0.85 ? "le sol est bien pourvu" : "le sol est confortable";
      lignes.push(`La réserve du sol est à <b>${esc(mmFr(reserve))}</b> sur ${nombreFr(utile, 0)} : ${etat}.`);
    }
    const ea = this._etatArrosage(c);
    if (ea.genre === "session") lignes.push("<b>Un arrosage est en cours.</b>");
    else if (ea.genre === "bloque") lignes.push(`Pas d'arrosage pour l'instant : <b>${esc(minuscule(premierePhrase(ea.titre)))}</b>.`);
    else if (ea.genre === "prevu") {
      const quandDepart = ea.depart ? `, ${ea.depart.jour ? `${esc(ea.depart.jour)} ` : ""}à ${esc(ea.depart.depart)}` : "";
      lignes.push(`Arrosage prévu : <b>${esc(mmFr(ea.mm))}</b>${quandDepart}.`);
    } else if (ea.genre === "retenu") lignes.push("Pas d'arrosage : <b>la semaine est couverte</b>. Ça reprend dès que le gazon a de nouveau soif.");
    else if (ea.genre === "estime") lignes.push(`Pas besoin d'arroser pour l'instant. Prochain arrosage estimé : <b>${esc(ea.jour)}</b>, à l'aube.`);
    else if (ea.genre === "graines") lignes.push(this._motsGraines(ea.graines).phrase);
    // La tonte : le gazon et la machine sont deux choses distinctes.
    const gazonOk = this._a("assistant", "gazon_permet_tonte");
    const machineOk = this._a("assistant", "machine_permet_tonte");
    const motifTonte = this._a("tonte_autorisee", "raison_blocage_tonte");
    if (gazonOk === false) {
      const court = motifTonte
        ? String(motifTonte).split(/\s*:\s*/)[0].split(/\.\s/)[0].replace(/\.$/, "")
        : "conditions non réunies";
      const prochaine = this._a("prochaine_tonte", "target_date");
      const quandTonte = prochaine ? ` Prochaine tonte possible : <b>${esc(dateHumaine(prochaine, c.maintenant, fuseau))}</b>.` : "";
      lignes.push(`La tonte attend : <b>${esc(minuscule(court))}</b>.${quandTonte}`);
    } else if (gazonOk === true && machineOk === false) {
      lignes.push("Le gazon est prêt à être tondu, mais <b>la tondeuse n'est pas disponible</b>.");
    } else if (gazonOk === true && machineOk === true) {
      const statut = String(this._a("tonte_autorisee", "tonte_statut") || "");
      if (statut === "autorisee_avec_precaution") {
        lignes.push("La tonte est <b>possible avec précaution</b>.");
      } else if (statut === "a_surveiller" || statut === "deconseillee" || statut === "interdite") {
        lignes.push(`La tonte est <b>${esc(minuscule(libelleDe(STATUTS_TONTE, statut)))}</b> pour l'instant.`);
      } else {
        lignes.push("La tonte est <b>possible dès maintenant</b>.");
      }
    }
    if (["recommande", "recommended"].includes(String(this._s("prochaine_intervention") || ""))) {
      lignes.push(`Un produit est conseillé : <b>${esc(this._a("prochaine_intervention", "product_name") || "voir l'onglet Produits")}</b>.`);
    }
    if (!lignes.length) return "";
    return `<section class="bulletin">
      <div class="bulletin-icone"><ha-icon icon="mdi:message-text-outline"></ha-icon></div>
      <div><h3>Ce qu'il faut savoir</h3>${lignes.map((l) => `<p>${l}</p>`).join("")}</div>
    </section>`;
  }

  _boutonAction(b) {
    const attr = b.commande ? `data-commande="${b.commande}"` : `data-dialogue="${b.dialogue}"`;
    const occupe = b.commande && this._commandesEnCours.has(b.commande);
    return `<button class="action ${b.genre || ""}" ${attr} ${occupe ? "disabled" : ""}>
      <span class="action-icone"><ha-icon icon="${b.icone}"></ha-icon></span>
      <b>${esc(occupe ? "Un instant…" : b.titre)}</b>
      ${b.aide ? `<small>${esc(b.aide)}</small>` : ""}
    </button>`;
  }

  _actionsHtml(c) {
    const enCours = this._arrosageEnCours();
    const objectif = nombreOuNul(this._s("objectif")) ?? 0;
    const liste = [];
    if (this._verrouSecuriteActif()) {
      liste.push({
        dialogue: "deverrouiller", icone: "mdi:shield-alert-outline",
        titre: "Lever le verrou de sécurité", genre: "danger",
        aide: "Seulement après avoir vérifié les vannes.",
      });
    }
    if (enCours) {
      liste.push({ commande: "arreter", icone: "mdi:stop", titre: "Arrêter l'arrosage", aide: "Fermeture immédiate des vannes.", genre: "danger" });
    } else {
      liste.push({
        dialogue: "arroser", icone: "mdi:sprinkler-variant", titre: "Arroser maintenant", genre: "eau",
        aide: objectif > 0 ? `Conseillé : ${mmFr(objectif)}` : "Quantité à définir.",
      });
      liste.push({ dialogue: "arrose_main", icone: "mdi:watering-can-outline", titre: "Déclarer un arrosage manuel", aide: "Pour que cette eau soit comptée." });
    }
    // Proposer « Déclarer une tonte » le jour d'une tonte déjà inscrite n'aurait pas de sens.
    if (!this._tonduAujourdhui(c)) {
      liste.push({ dialogue: "tondu", icone: "mdi:robot-mower-outline", titre: "Déclarer une tonte", aide: "Pour repartir de la bonne hauteur." });
    }
    liste.push({ dialogue: "produit", icone: "mdi:flask-outline", titre: "Déclarer un produit", aide: "Engrais, biostimulant, traitement…" });
    liste.push({ dialogue: "mode", icone: "mdi:swap-horizontal", titre: "Changer de mode", aide: `En ce moment : ${c.mode || "—"}` });
    liste.push({ dialogue: "reserve", icone: "mdi:cup-water", titre: "Recaler la réserve", aide: "Après une mesure dans le sol." });
    return `<section class="section">
      <div class="section-tete"><h3>Actions disponibles</h3><p>Chaque bouton ouvre une fenêtre qui décrit l'action avant validation.</p></div>
      <div class="actions-grille">${liste.map((b) => this._boutonAction(b)).join("")}</div>
    </section>`;
  }

  _tuile({ icone, titre, valeur, sous = "", ton = "", petite = false, jauge = null, couleur = "" }) {
    return `<div class="tuile ${ton}">
      <div class="tuile-titre"><ha-icon icon="${icone}"></ha-icon>${esc(titre)}</div>
      <div class="tuile-valeur ${petite ? "petite" : ""}">${valeur}</div>
      ${sous ? `<div class="tuile-sous">${sous}</div>` : ""}
      ${jauge !== null ? `<div class="jauge" style="--couleur:${couleur}"><i style="width:${Math.max(0, Math.min(100, jauge))}%"></i></div>` : ""}
    </div>`;
  }

  _tuileReserve() {
    const ratio = nombreOuNul(this._a("etat_hydrique", "reserve_available_ratio") ?? this._a("reserve", "reserve_available_ratio"));
    const mm = nombreOuNul(this._a("etat_hydrique", "reserve_actuelle_mm") ?? this._s("reserve"));
    const pct = ratio !== null ? Math.round(ratio * 100) : null;
    const ton = ratio === null ? "" : ratio < 0.25 ? "danger" : ratio < 0.5 ? "attention" : "ok";
    const couleur = ton === "danger" ? "var(--gz-rouge)" : ton === "attention" ? "var(--gz-ambre)" : "var(--gz-accent)";
    return this._tuile({
      icone: "mdi:cup-water", titre: "Réserve du sol", ton,
      valeur: pct !== null ? `${pct} %` : mm !== null ? esc(mmFr(mm)) : "—",
      sous: mm !== null ? esc(mmFr(mm)) : "", jauge: pct, couleur,
    });
  }

  _tuileRisque() {
    const risque = String(this._s("risque") || "");
    const ton = risque === "eleve" || risque === "critique" ? "danger" : risque === "modere" ? "attention" : "ok";
    const raisons = this._a("risque", "risque_gazon_raisons");
    const premiere = Array.isArray(raisons) && raisons.length ? majuscule(raisons[0]) : "";
    return this._tuile({ icone: "mdi:shield-half-full", titre: "Risque pour le gazon", ton, valeur: esc(libelleDe(RISQUES, risque)), sous: esc(premiere), petite: true });
  }

  _tuileProchainArrosage(c) {
    const ea = this._etatArrosage(c);
    let valeur = "—";
    let sous = "";
    if (ea.genre === "session") {
      valeur = "En cours";
      const pct = nombreOuNul(this._a("arrosage_en_cours", "progress_percent"));
      sous = pct !== null && this._sessionActive() ? `${nombreFr(pct, 0)} % fait` : "une vanne est ouverte";
    } else if (ea.genre === "bloque") {
      valeur = esc(premierePhrase(ea.titre));
    } else if (ea.genre === "prevu") {
      valeur = ea.depart ? `${esc(ea.depart.depart)}${ea.depart.fin ? ` → ${esc(ea.depart.fin)}` : ""}` : esc(ea.fenetre || "—");
      sous = [mmFr(ea.mm), ea.depart?.jour].filter(Boolean).map(esc).join(" · ");
    } else if (ea.genre === "retenu") {
      valeur = "Semaine couverte";
      sous = "reprise dès que le gazon a soif";
    } else if (ea.genre === "estime") {
      valeur = esc(majuscule(ea.jour));
      sous = `estimé, à l'aube${ea.fenetre ? ` · ${esc(ea.fenetre)}` : ""}`;
    } else if (ea.genre === "graines") {
      const mots = this._motsGraines(ea.graines);
      valeur = esc(mots.valeur);
      sous = esc(mots.sous);
    } else {
      valeur = esc(ea.titre);
    }
    return this._tuile({ icone: "mdi:sprinkler-variant", titre: "Prochain arrosage", valeur, sous, petite: true, ton: ea.genre === "bloque" && ea.alerte ? "attention" : "" });
  }

  _tuileProchaineTonte(c) {
    const date = this._a("prochaine_tonte", "target_date") || this._s("prochaine_tonte");
    const statut = String(this._a("tonte_autorisee", "tonte_statut") || this._a("prochaine_tonte", "tonte_statut") || "");
    return this._tuile({
      icone: "mdi:robot-mower", titre: "Prochaine tonte", petite: true,
      valeur: date ? esc(majuscule(dateHumaine(date, c.maintenant, this._fuseau()))) : "—",
      sous: statut ? `Tonte : ${esc(minuscule(libelleDe(STATUTS_TONTE, statut)))}` : "",
    });
  }

  _tuilesHtml(c, { carre = false } = {}) {
    return `<div class="tuiles ${carre ? "carre" : ""}">${this._tuileReserve()}${this._tuileRisque()}${this._tuileProchainArrosage(c)}${this._tuileProchaineTonte(c)}</div>`;
  }

  _pastillesHtml() {
    const puces = [];
    const phase = this._s("phase");
    if (phase) puces.push(`<span class="puce"><ha-icon icon="mdi:leaf"></ha-icon>Phase ${esc(phase)}</span>`);
    const et0 = nombreOuNul(this._a("objectif", "et0_mm") ?? this._a("reserve", "et0_mm"));
    if (et0 !== null) puces.push(`<span class="puce" title="Évapotranspiration de référence (ET₀) du jour"><ha-icon icon="mdi:weather-sunny"></ha-icon>Le soleil et le vent boivent ${esc(mmFr(et0))} aujourd'hui</span>`);
    // La qualité de l'ET₀ ne se montre que si un repli est actif : en marche normale, rien.
    const sante = this._a("reserve", "sensor_health") || this._a("risque", "sensor_health") || {};
    if (sante.eto_hourly_available === false) {
      puces.push(`<span class="puce alerte"><ha-icon icon="mdi:alert-outline"></ha-icon>Évaporation estimée, pas mesurée</span>`);
    } else if (sante.eto_radiation_measured === false || sante.eto_pressure_measured === false) {
      const manquants = [sante.eto_radiation_measured === false ? "rayonnement" : "", sante.eto_pressure_measured === false ? "pression" : ""].filter(Boolean).join(" et ");
      puces.push(`<span class="puce alerte" title="Calculée sans ${esc(manquants)} mesuré"><ha-icon icon="mdi:alert-outline"></ha-icon>Évaporation approchée</span>`);
    }
    const pluie = nombreOuNul(this._a("objectif", "pluie_demain"));
    if (pluie !== null && pluie > 0) puces.push(`<span class="puce"><ha-icon icon="mdi:weather-rainy"></ha-icon>${esc(mmFr(pluie))} de pluie attendus demain</span>`);
    return puces.length ? `<div class="puces">${puces.join("")}</div>` : "";
  }

  // ── Arrosage ──

  // Grande page : ce qui se commande (l'état, les vannes) à gauche, ce qui se regarde (la frise, la
  // jauge) au milieu, le journal dans le couloir étroit. Page moyenne : deux couloirs.
  _ongletArrosageHtml(c) {
    return this._mosaique([
      [this._etatArrosageHtml(c), "gauche", "large"],
      [this._zonesHtml(), "gauche", "large"],
      [this._friseArrosageHtml(), "milieu", "etroit"],
      [this._budgetHtml(), "milieu", "large"],
      [this._journalHtml(c), "droite", "etroit"],
    ]);
  }

  _etatArrosageHtml(c) {
    const ea = this._etatArrosage(c);
    let icone = "mdi:water-check-outline";
    let ton = "";
    let titre = "";
    let texte = "";
    let extra = "";
    if (ea.genre === "session") {
      icone = "mdi:sprinkler-variant";
      ton = "eau";
      titre = "Arrosage en cours";
      texte = this._texteSession();
      const a = (k) => this._a("arrosage_en_cours", k);
      const pct = Math.max(0, Math.min(100, nombreOuNul(a("progress_percent")) ?? 0));
      // La lame d'eau sur la PELOUSE (moyenne des zones) : `total_mm_applied` additionne les zones.
      const verse = nombreOuNul(a("surface_mm_applied") ?? a("total_mm_applied"));
      extra = `${this._sessionActive() ? `<div class="travail"><div class="travail-tete"><span>Avancement</span><b>${nombreFr(pct, 0)} %${verse !== null && verse > 0 ? ` · ${esc(mmFr(verse))} versés` : ""}</b></div>
        <div class="progression eau"><i style="width:${pct}%"></i></div></div>${this._avancementZonesHtml()}` : ""}
        <div class="rangee-boutons"><button class="bouton-plein danger" data-commande="arreter" ${this._commandesEnCours.has("arreter") ? "disabled" : ""}>Arrêter l'arrosage</button></div>`;
    } else if (ea.genre === "bloque") {
      icone = ea.pluie ? "mdi:weather-rainy" : "mdi:timer-sand";
      ton = ea.pluie ? "eau" : ea.alerte ? "alerte" : "";
      titre = premierePhrase(ea.titre);
      texte = ea.fenetre ? `Fenêtre du matin : ${ea.fenetre}.` : "";
    } else if (ea.genre === "prevu") {
      icone = "mdi:water";
      ton = "eau";
      titre = `${mmFr(ea.mm)} prévus`;
      texte = ea.depart
        ? [ea.depart.jour ? majuscule(ea.depart.jour) : "", `départ ${ea.depart.depart}`, ea.depart.fin ? `fin vers ${ea.depart.fin}` : ""].filter(Boolean).join(" · ")
        : ea.fenetre ? `Dans la fenêtre ${ea.fenetre}.` : "";
      extra = this._derouleHtml(this._planPrevu(), {
        depart: ea.depart ? `départ ${ea.depart.depart}` : "",
        fin: ea.depart?.fin ? `fin ${ea.depart.fin}` : "",
      });
    } else if (ea.genre === "retenu") {
      icone = "mdi:pause-circle-outline";
      ton = ea.alerte ? "alerte" : "";
      titre = premierePhrase(ea.titre);
      // BESOIN ≠ DOSE : l'objectif vaut 0 pendant la retenue, le sol, lui, peut réclamer.
      texte = `La semaine est couverte : ça reprend dès que le gazon a de nouveau soif.${ea.besoin !== null && ea.besoin > 0 ? ` Le sol réclame encore ${mmFr(ea.besoin)}.` : ""}`;
    } else if (ea.genre === "estime") {
      icone = "mdi:calendar-clock";
      titre = `Prochain arrosage : ${ea.jour}`;
      texte = `C'est une estimation, à l'aube${ea.fenetre ? ` (fenêtre ${ea.fenetre})` : ""}. Elle suit la soif du sol.`;
    } else if (ea.genre === "graines") {
      const mots = this._motsGraines(ea.graines);
      icone = ea.graines.fini ? "mdi:check-circle-outline" : "mdi:sprout-outline";
      titre = mots.titre;
      texte = mots.texte;
    } else {
      titre = ea.titre;
      texte = ea.fenetre ? `Fenêtre du matin : ${ea.fenetre}.` : "";
    }
    const objectif = nombreOuNul(this._s("objectif")) ?? 0;
    const boutons = ea.genre === "session" ? "" : `<div class="rangee-boutons">
      <button class="bouton-plein eau" data-dialogue="arroser"><ha-icon icon="mdi:sprinkler-variant"></ha-icon> Arroser maintenant${objectif > 0 ? ` (${esc(mmFr(objectif))} conseillés)` : ""}</button>
      <button class="bouton-contour" data-dialogue="arrose_main">Déclarer un arrosage manuel</button>
    </div>`;
    return `<section class="section">
      <div class="etat-bandeau ${ton}">
        <div class="etat-icone"><ha-icon icon="${icone}"></ha-icon></div>
        <div><small>L'arrosage</small><b>${esc(majuscule(titre))}</b>${texte ? `<p>${esc(texte)}</p>` : ""}</div>
      </div>
      ${extra}${boutons}
    </section>`;
  }

  // ── Le plan d'arrosage ──

  // Les zones que le moteur arrose : un débit réglé, dans l'ordre des zones.
  _zonesAvecDebit() {
    return this._zones()
      .map((z) => ({ ...z, debit: nombreOuNul(this._s(`debit_zone_${z.numero}`)) }))
      .filter((z) => z.debit !== null && z.debit > 0);
  }

  // Le découpage du jour (capteur « Cycle calculé »). ⚠️ Le moteur l'applique aussi à un arrosage
  // lancé à la main, QUELLE QUE SOIT la dose choisie (coordinator._get_canonical_watering_plan).
  _decoupageDuJour() {
    const a = (k) => nombreOuNul(this._a("plan_arrosage", k));
    return {
      passages: a("passages") ?? 1,
      pauseS: a("pause_between_passages_s") ?? (a("pause_between_passages_minutes") ?? 0) * 60,
    };
  }

  // Le plan du prochain arrosage, tel que le moteur l'exécutera : il relit ce capteur au départ.
  _planPrevu() {
    const brutes = this._a("plan_arrosage", "zones");
    if (!Array.isArray(brutes) || !brutes.length) return null;
    const parSwitch = new Map(this._zones().map((z) => [z.switch, z]));
    const zones = brutes.map((b, i) => {
      const id = String(b.entity_id || b.zone || "");
      const z = parSwitch.get(id);
      return {
        switch: id,
        numero: z?.numero ?? i + 1,
        nom: z?.nom || id,
        couleur: z?.couleur || COULEURS_ZONES[i % COULEURS_ZONES.length],
        debit: nombreOuNul(b.rate_mm_h),
        secondes: nombreOuNul(b.duration_seconds ?? b.duration_s) ?? 0,
      };
    }).filter((z) => z.secondes > 0);
    if (!zones.length) return null;
    const { passages, pauseS } = this._decoupageDuJour();
    return planDepuisZones(zones, passages, pauseS);
  }

  // Le ruban d'un arrosage : chaque morceau dure son vrai temps, la pause est rayée.
  _derouleHtml(plan, { depart = "", fin = "", compact = false } = {}) {
    if (!plan) return "";
    const total = plan.totalS || 1;
    const morceaux = plan.etapes.map((e) => {
      const part = (e.secondes / total) * 100;
      if (e.genre === "pause") {
        return `<i class="deroule-pause" style="flex-grow:${e.secondes}" title="Pause : ${esc(dureeSecondesFr(e.secondes))}">${part >= 10 ? "pause" : ""}</i>`;
      }
      return `<i style="flex-grow:${e.secondes};background:${e.zone.couleur}" title="${esc(e.zone.nom)}${plan.passages > 1 ? ` (${ordinalM(e.passage)} passage)` : ""} : ${esc(dureeSecondesFr(e.secondes))}">${part >= 5 ? `Z${esc(e.zone.numero)}` : ""}</i>`;
    }).join("");
    const legende = plan.zones.map((z) => {
      const parPassage = plan.passages > 1 ? `${plan.passages} × ${dureeSecondesFr(z.secondes / plan.passages)}` : dureeSecondesFr(z.secondes);
      return `<li><i style="background:${z.couleur}"></i><span>${esc(z.nom)}</span><b>${esc(parPassage)}</b></li>`;
    });
    if (plan.pauseS > 0) {
      legende.push(`<li><i class="deroule-pause"></i><span>Pause</span><b>${esc(dureeSecondesFr(plan.pauseS))}</b></li>`);
    }
    const eau = dureeSecondesFr(plan.eauS);
    const resume = plan.passages > 1
      ? `${plan.passages} passages · ${eau} d'eau${plan.pauseS > 0 ? ` · ${dureeSecondesFr(plan.totalS)} en tout` : ""}`
      : `${plan.zones.length > 1 ? "Les zones l'une après l'autre" : "Une zone"} · ${eau}`;
    return `<div class="deroule ${compact ? "compact" : ""}">
      <div class="deroule-tete"><b>${compact ? "Comment ça va se passer" : "Le déroulé"}</b><span>${esc(resume)}</span></div>
      <div class="deroule-ruban" role="img" aria-label="${esc(resume)}">${morceaux}</div>
      ${depart || fin ? `<div class="deroule-heures"><span>${esc(depart)}</span><span>${esc(fin)}</span></div>` : ""}
      <ul class="deroule-legende">${legende.join("")}</ul>
      ${plan.pauseS > 0 ? `<p class="deroule-note">La pause laisse l'eau du premier passage s'enfoncer dans la terre avant le second.</p>` : ""}
    </div>`;
  }

  // Pendant un arrosage : combien chaque zone a déjà reçu, sur SA PROPRE dose planifiée. ⚠️
  // Trouvé en revue (24/09/2026) : `target_mm` de la session est `plan.planned_surface_mm`, une
  // MOYENNE entre zones (tirée vers le bas par toute zone en réduction d'ombre, ex. zone 3) —
  // jamais la cible d'une zone précise. Comparer chaque zone à cette moyenne faisait paraître une
  // zone sans réduction en dépassement (ex. 1,3 / 1,1 mm) alors qu'elle atteignait tout juste SA
  // propre cible (`ZonePlan.mm`, publiée par zone via `zone_target_mm`, avant moyennage). Que des
  // valeurs publiées par l'intégration, aucune reconstruction ; repli sur la moyenne de session
  // si une zone n'a pas de cible propre publiée (anciennes sessions, ou zone hors plan courant).
  _avancementZonesHtml() {
    const a = (k) => this._a("arrosage_en_cours", k);
    const cibleMoyenne = nombreOuNul(a("target_mm"));
    const ciblesParZone = a("zone_target_mm") && typeof a("zone_target_mm") === "object" ? a("zone_target_mm") : {};
    const verses = a("zone_mm_applied") && typeof a("zone_mm_applied") === "object" ? a("zone_mm_applied") : {};
    const arrosees = new Set(this._zonesAvecDebit().map((z) => z.switch));
    const zones = this._zones().filter((z) => arrosees.has(z.switch) || this._zoneActive(z) || nombreOuNul(verses[z.switch]) !== null);
    if (cibleMoyenne === null || cibleMoyenne <= 0 || !zones.length) return "";
    const passages = nombreOuNul(a("passage_count")) ?? 1;
    const passage = nombreOuNul(a("current_passage"));
    const actives = zones.filter((z) => this._zoneActive(z));
    // Pendant la pause, le moteur annonce déjà le passage suivant et ne garde aucune vanne ouverte.
    const enPause = this._sessionActive() && passages > 1 && (passage ?? 1) > 1 && !actives.length;
    const lignes = zones.map((z) => {
      const cible = nombreOuNul(ciblesParZone[z.switch]) ?? cibleMoyenne;
      const mm = nombreOuNul(verses[z.switch]) ?? 0;
      const fait = mm >= cible - 0.05;
      const active = this._zoneActive(z);
      // Une zone reçoit la même part à chaque passage : ce qui manque dit combien de tours restent.
      const tours = Math.max(1, Math.round(((cible - mm) / cible) * passages));
      const etat = active ? "en cours" : fait ? "fini" : mm <= 0 ? "à venir"
        : passages > 1 ? `encore ${tours} passage${tours > 1 ? "s" : ""}` : "pas fini";
      return `<li class="${active ? "active" : fait ? "faite" : ""}">
        <i style="background:${z.couleur}"></i><span>${esc(z.nom)}</span>
        <div class="avance-rail"><div style="width:${pourcent(mm, 0, cible)}%;background:${z.couleur}"></div></div>
        <b>${esc(nombreFr(mm, 1))}&nbsp;/&nbsp;${esc(mmFr(cible))}</b><small>${etat}</small>
      </li>`;
    }).join("");
    const tete = [
      passages > 1 && passage !== null ? `${ordinalM(Math.min(passage, passages))} passage sur ${passages}` : "",
      enPause ? "pause : l'eau s'enfonce avant la suite" : actives.length ? `en ce moment : ${actives.map((z) => z.nom).join(", ")}` : "",
    ].filter(Boolean).join(" · ");
    return `<div class="deroule">
      <div class="deroule-tete"><b>Chaque zone</b><span>${esc(majuscule(tete))}</span></div>
      <ul class="avance">${lignes}</ul>
    </div>`;
  }

  _zonesHtml() {
    const zones = this._zones();
    const tete = `<div class="section-tete"><h3>Les zones</h3><p>Une vanne peut être ouverte manuellement. Pour comptabiliser l'eau dans la réserve, utiliser de préférence « Arroser maintenant ».</p></div>`;
    if (!zones.length) return `<section class="section">${tete}<p class="vide">Aucune zone configurée.</p></section>`;
    const lignes = zones.map((z) => {
      const active = this._zoneActive(z);
      const debit = nombreOuNul(this._s(`debit_zone_${z.numero}`));
      const depuis = active ? this._hass.states[z.switch]?.last_changed : null;
      const occupe = this._commandesEnCours.has(`zone-${z.switch}`);
      const detail = active
        ? `Arrose depuis <span class="chrono" data-chrono="${esc(depuis || "")}">${depuis ? chronoFr(Date.now() - Date.parse(depuis)) : "…"}</span>`
        : `${debit !== null && debit > 0 ? `${nombreFr(debit, 0)} mm/h · ` : ""}à l'arrêt`;
      const boutons = active
        ? `<button class="petit-bouton arret" data-commande="zone-arret" data-switch="${esc(z.switch)}" ${occupe ? "disabled" : ""}><ha-icon icon="mdi:stop"></ha-icon>Arrêter</button>`
        : `<button class="petit-bouton" data-commande="zone-marche" data-switch="${esc(z.switch)}" ${occupe ? "disabled" : ""}><ha-icon icon="mdi:play"></ha-icon>Ouvrir</button>
           <button class="petit-bouton" data-commande="zone-5min" data-switch="${esc(z.switch)}" ${occupe ? "disabled" : ""} title="Home Assistant referme automatiquement la vanne après 5 minutes, même si cette page est fermée">5 min</button>`;
      return `<div class="zone ${active ? "active" : ""}">
        <span class="zone-pastille" style="background:${z.couleur}">Z${z.numero}</span>
        <div class="zone-texte"><b>${esc(z.nom)}</b><small>${detail}</small></div>
        <div class="zone-boutons">${boutons}</div>
      </div>`;
    });
    const pompe = this._donnees?.pompe;
    if (pompe && this._hass.states[pompe]) {
      const marche = this._allume(pompe);
      lignes.push(`<div class="zone ${marche ? "active" : ""}">
        <span class="zone-pastille" style="background:var(--gz-nuit)"><ha-icon icon="mdi:pump"></ha-icon></span>
        <div class="zone-texte"><b>Pompe</b><small>${marche ? "En marche" : "À l'arrêt"}</small></div>
        <div class="zone-boutons">${marche
          ? `<button class="petit-bouton arret" data-commande="pompe-arret">Arrêter</button>`
          : `<button class="petit-bouton" data-commande="pompe-marche">Mettre en marche</button>`}</div>
      </div>`);
    }
    return `<section class="section">${tete}<div>${lignes.join("")}</div></section>`;
  }

  // Sessions d'une vanne dans la fenêtre. L'historique des vannes est la VÉRITÉ TERRAIN ; la
  // reconstruction depuis le journal n'est qu'un REPLI (elle ignore la pause entre passages).
  _sessionsFenetre(zones, debut, fin) {
    const reconstruites = {};
    for (const session of this._a("dernier_arrosage", "derniers_arrosages") || []) {
      const finSession = Date.parse(session.recorded_at);
      if (!Number.isFinite(finSession) || finSession < debut) continue;
      let curseur = finSession;
      for (const z of [...(session.zones || [])].reverse()) {
        const duree = (Number(z.duration_min) || 0) * 60000;
        (reconstruites[z.entity_id] ||= []).push({ debut: curseur - duree, fin: curseur });
        curseur -= duree;
      }
    }
    const dansFenetre = (s) => s.fin >= debut && s.debut <= fin;
    const resultat = {};
    const actif = this._sessionActive();
    const debutActif = Date.parse(this._a("arrosage_en_cours", "started_at_utc") || "");
    for (const z of zones) {
      const brutes = (this._historique?.[z.switch] || []).filter(dansFenetre);
      const sessions = [...(brutes.length ? brutes : (reconstruites[z.switch] || []).filter(dansFenetre))];
      if (this._zoneActive(z)) {
        const depuis = Date.parse(this._hass.states[z.switch]?.last_changed || "") || (actif && Number.isFinite(debutActif) ? debutActif : fin - 60000);
        const derniere = sessions[sessions.length - 1];
        if (derniere && derniere.fin >= depuis) derniere.fin = fin;
        else sessions.push({ debut: depuis, fin });
      }
      resultat[z.switch] = sessions;
    }
    return resultat;
  }

  _friseArrosageHtml() {
    const zones = this._zones();
    if (!zones.length) return "";
    this._chargerHistorique();
    // Ancrée à la minute : la frise ne change pas toutes les secondes sous le doigt.
    const fin = Math.floor(Date.now() / 60000) * 60000;
    const debut = fin - 24 * 3600 * 1000;
    const sessions = this._sessionsFenetre(zones, debut, fin);
    const pct = (t) => pourcent(t, debut, fin);
    const lignes = zones.map((z) => {
      const barres = sessions[z.switch].map((s) => {
        const gauche = pct(s.debut);
        const largeur = Math.max(0.5, pct(s.fin) - gauche);
        return `<i style="left:${gauche.toFixed(2)}%;width:${largeur.toFixed(2)}%;background:${z.couleur}" title="${esc(z.nom)} : ${heureFr(partiesLocales(new Date(s.debut), this._fuseau()).minute)} → ${heureFr(partiesLocales(new Date(s.fin), this._fuseau()).minute)}"></i>`;
      }).join("");
      // Le nom complet de l'entité (ex. « Zone 1 Arrosage ») ne tient pas dans la colonne
      // étroite d'un téléphone : on y affiche « Zone 1 », le nom complet reste au survol.
      return `<div class="frise-ligne"><span title="${esc(z.nom)}">Zone ${esc(z.numero)}</span><div class="frise-rail">${barres}</div></div>`;
    }).join("");
    const graduations = [0, 6, 12, 18, 24].map((h) => {
      const t = debut + h * 3600 * 1000;
      return `<span style="left:${(h / 24) * 100}%">${heureFr(partiesLocales(new Date(t), this._fuseau()).minute)}</span>`;
    }).join("");
    const totaux = zones.map((z) => {
      const liste = sessions[z.switch];
      if (!liste.length) return "";
      const minutes = liste.reduce((s, x) => s + (Math.min(x.fin, fin) - Math.max(x.debut, debut)), 0) / 60000;
      return `<span><i style="background:${z.couleur}"></i>${esc(z.nom)} : <b>${esc(dureeFr(Math.max(1, Math.round(minutes))))}</b> · ${liste.length} fois</span>`;
    }).join("");
    const vide = !zones.some((z) => sessions[z.switch].length);
    return `<section class="section">
      <div class="section-tete"><h3>Les 24 dernières heures</h3><p>Chaque barre est une vanne ouverte.</p></div>
      <div class="frise-zones">${lignes}</div>
      <div class="frise-heures"><span></span><div class="graduations">${graduations}</div></div>
      ${vide ? `<p class="frise-vide">${this._historique === null ? "Lecture de l'historique des vannes…" : "Aucun arrosage ces dernières 24 heures."}</p>` : ""}
      ${totaux ? `<div class="totaux">${totaux}</div>` : `<div style="height:14px"></div>`}
    </section>`;
  }

  // Les deux chiffres viennent de l'intégration, qui seule connaît la vraie fenêtre de 7 jours.
  _budgetHtml() {
    const utilise = nombreOuNul(this._a("reserve", "arrosage_recent_7j"));
    const recu = nombreOuNul(this._a("reserve", "arrosage_applique_7j"));
    const plafond = nombreOuNul(this._a("fenetre_optimale", "weekly_guardrail_mm_max"));
    const plancher = nombreOuNul(this._a("fenetre_optimale", "weekly_guardrail_mm_min"));
    if (utilise === null || plafond === null || plafond <= 0) return "";
    const retenu = this._retenuParLeBudget();
    // Un motif de blocage qui cite EXPLICITEMENT le garde-fou hebdomadaire (`retenu` via ce motif
    // nommé, pas via la simple présomption de phase) prime sur la présentation informative : le
    // moteur affirme alors une vraie retenue, la carte ne doit pas dire le contraire au même endroit.
    const informatifSeul = this._budgetEstInformatifSeul() && !retenu;
    const pct = Math.round((utilise / plafond) * 100);
    const depasse = !informatifSeul && utilise >= plafond;
    // « Semaine couverte » n'est PAS une alerte : l'orange est réservé à l'approche du plafond dur.
    const couleur = informatifSeul ? "var(--gz-accent)" : depasse ? "var(--gz-rouge)" : pct >= 80 ? "var(--gz-ambre)" : "var(--gz-accent)";
    const horsBudget = recu !== null ? Math.max(0, recu - utilise) : 0;
    const plancherPct = !informatifSeul && plancher !== null && plancher > 0 ? Math.min(100, (plancher / plafond) * 100) : null;
    const motLimite = informatifSeul ? "ce repère" : "cette limite";
    const notes = [];
    if (informatifSeul) {
      // Texte volontairement neutre vis-à-vis de la phase (revue du 23/09/2026, PR #63) : le
      // mécanisme réel diffère selon la phase (fenêtre/pluie/saturation pour Semis/Sursemis,
      // fiche produit pour Traitement/Fertilisation/Biostimulant/Agent Mouillant/Scarification,
      // arrosage bloqué pour Hivernage) — nommer « Semis/Sursemis » ou « les graines » ici serait
      // faux pour les autres phases de la liste blanche `_PHASES_SANS_PLAFOND_HEBDO`.
      notes.push("Hors de la phase Normal, l'arrosage suit d'autres règles que ce plafond hebdomadaire : ce cumul est informatif, pas une limite qui le retiendrait.");
    } else if (plancherPct !== null) {
      notes.push(`Le trait marque <b>${esc(mmFr(plancher))}</b> : au-delà, l'arrosage peut se retenir si le gazon a peu soif.`);
    }
    if (retenu && !depasse) notes.push("<b>Semaine couverte</b> : ça reprend dès que le gazon a de nouveau soif.");
    if (horsBudget >= 0.1) notes.push(`En plus : <b>${esc(mmFr(horsBudget))}</b> qui ne comptent pas dans ${motLimite}. Total reçu : <b>${esc(mmFr(recu))}</b>.`);
    return `<section class="section">
      <div class="section-tete"><h3>L'eau de la semaine</h3><p>${informatifSeul ? "Cumul informatif des 7 derniers jours, sans limiter l'arrosage prévu pendant cette phase." : "Pour ne pas trop arroser, l'intégration surveille ce qui a été versé sur 7 jours."}</p></div>
      <div class="budget">
        <div class="budget-chiffres"><span><b>${esc(mmFr(utilise))}</b> sur 7 jours</span><span>${informatifSeul ? "repère" : "limite"} ${esc(mmFr(plafond))} · ${pct} %</span></div>
        <div class="budget-rail" role="img" aria-label="${pct} % ${informatifSeul ? "du repère" : "de la limite"}">
          <i style="width:${Math.min(100, pct)}%;background:${couleur}"></i>
          ${plancherPct !== null ? `<span class="budget-plancher" style="left:${plancherPct}%"></span>` : ""}
        </div>
      </div>
      ${notes.length ? `<ul class="liste-simple">${notes.map((n) => `<li><ha-icon icon="mdi:information-outline"></ha-icon><span>${n}</span></li>`).join("")}</ul>` : ""}
    </section>`;
  }

  _journalHtml(c) {
    const fuseau = this._fuseau();
    const zonesParSwitch = new Map(this._zones().map((z) => [z.switch, z]));
    // Même fenêtre que le budget : 7 jours calendaires.
    const sessions = (this._a("dernier_arrosage", "derniers_arrosages") || []).filter((e) => {
      const j = jourDe(e.date || e.recorded_at, fuseau);
      return !j || ecartJours(j, c.maintenant) <= 6;
    });
    const tete = `<div class="section-tete"><h3>Les derniers arrosages</h3><p>Les 7 derniers jours, du plus récent au plus ancien.</p></div>`;
    if (!sessions.length) return `<section class="section">${tete}<p class="vide">Aucun arrosage ces 7 derniers jours.</p></section>`;
    const minutesTotales = sessions.reduce((s, e) => s + (e.zones || []).reduce((t, z) => t + (Number(z.duration_min) || 0), 0), 0);
    const lignes = sessions.map((e) => {
      // Le DÉBUT du cycle : `recorded_at` est la fermeture de la dernière vanne.
      const instant = new Date(e.started_at || e.recorded_at);
      const p = partiesLocales(instant, fuseau);
      const quand = `${majuscule(dateHumaine(isoDuJour(p), c.maintenant, fuseau))} · ${heureFr(p.minute)}`;
      const cause = String(e.watering_cause || "").toLowerCase();
      const technique = CAUSES_TECHNIQUES.includes(cause);
      const source = libelleDe(SOURCES_ARROSAGE, e.source);
      const pourquoi = cause && cause !== e.source ? CAUSES_ARROSAGE[cause] || cause.replace(/_/g, " ") : "";
      // Un cycle fractionné répète les zones : on cumule par zone et on compte les passages.
      const parZone = new Map();
      for (const z of e.zones || []) {
        const cur = parZone.get(z.entity_id) || { minutes: 0, passages: 0 };
        cur.minutes += Number(z.duration_min) || 0;
        cur.passages += 1;
        parZone.set(z.entity_id, cur);
      }
      const passages = parZone.size ? Math.max(...[...parZone.values()].map((v) => v.passages)) : 0;
      const puces = [...parZone.entries()].map(([id, v]) => {
        const z = zonesParSwitch.get(id);
        const duree = v.minutes >= 1 ? dureeFr(Math.round(v.minutes)) : `${Math.round(v.minutes * 60)} s`;
        return `<span class="session-zone"><em style="background:${z ? z.couleur : "var(--gz-doux)"}">${z ? `Z${z.numero}` : "?"}</em>${esc(z ? z.nom : id)} · ${esc(duree)}</span>`;
      }).join("");
      const mm = nombreOuNul(e.total_mm);
      return `<div class="session ${technique ? "technique" : ""}">
        <div><div class="session-quand">${esc(quand)}</div>
          <div class="session-quoi">${esc(source)}${pourquoi ? ` · ${esc(pourquoi)}` : ""}${technique ? ` <span class="etiquette">hors budget</span>` : ""}${passages > 1 ? ` <span class="etiquette">${passages} passages</span>` : ""}</div></div>
        <div class="session-mm">${mm !== null && mm >= 0.1 ? esc(mmFr(mm)) : "< 0,1 mm"}</div>
        ${puces ? `<div class="session-zones">${puces}</div>` : ""}
      </div>`;
    }).join("");
    return `<section class="section">${tete}
      <div class="entete-journal"><span><b>${esc(dureeFr(Math.round(minutesTotales)))}</b> d'arrosage</span><span>${sessions.length} arrosage${sessions.length > 1 ? "s" : ""}</span></div>
      <div>${lignes}</div>
    </section>`;
  }

  async _chargerHistorique() {
    if (this._historiqueEnCours || Date.now() - this._historiqueDate < 5 * 60000) return;
    const ids = this._zones().map((z) => z.switch).filter(Boolean);
    if (!ids.length || typeof this._hass?.callApi !== "function") return;
    this._historiqueEnCours = true;
    this._historiqueDate = Date.now();
    try {
      const debut = new Date(Date.now() - 7 * 86400000).toISOString();
      const listes = await this._hass.callApi("GET",
        `history/period/${debut}?filter_entity_id=${ids.join(",")}&minimal_response=true&no_attributes=true`);
      const resultat = {};
      (listes || []).forEach((liste, rang) => {
        if (!Array.isArray(liste) || !liste.length) return;
        // Par POSITION d'abord : les entrées compactées n'ont pas toujours d'`entity_id`.
        const id = typeof liste[0].entity_id === "string" && liste[0].entity_id ? liste[0].entity_id : ids[rang];
        const sessions = [];
        let ouverte = null;
        for (const s of liste) {
          const t = Date.parse(s.last_changed);
          if (s.state === "on" && ouverte === null) ouverte = t;
          else if (s.state !== "on" && ouverte !== null) {
            sessions.push({ debut: ouverte, fin: t });
            ouverte = null;
          }
        }
        // Une session encore ouverte n'est réelle que si la vanne l'est ENCORE (barre de 144 h).
        if (ouverte !== null && this._allume(id)) sessions.push({ debut: ouverte, fin: Date.now() });
        resultat[id] = sessions.filter((s) => Number.isFinite(s.debut) && Number.isFinite(s.fin)
          && s.fin > s.debut && s.fin - s.debut <= SESSION_PLAUSIBLE_MAX_MS);
      });
      this._historique = resultat;
    } catch (e) {
      console.warn("Gazon Intelligent : historique des vannes illisible", e);
      this._historique = this._historique || {};
    } finally {
      this._historiqueEnCours = false;
    }
    if (this._vue === "accueil" && this._ongletAccueil === "arrosage") {
      this._rendreQuandLibre();
    }
  }

  async _chargerPrevision() {
    const id = this._donnees?.meteo;
    const connexion = this._hass?.connection;
    if (!id || !connexion?.sendMessagePromise || this._previsionEnCours || Date.now() - this._previsionDate < 30 * 60000) return;
    this._previsionEnCours = true;
    this._previsionDate = Date.now();
    // Par jour ET par heure (onglet Météo). Une entité peut ne pas savoir l'un des deux : chacun
    // est demandé à part, un refus n'emporte pas l'autre.
    const demander = async (type) => {
      try {
        const reponse = await connexion.sendMessagePromise({
          type: "call_service", domain: "weather", service: "get_forecasts",
          service_data: { entity_id: id, type }, return_response: true,
        });
        return reponse?.response?.[id]?.forecast || [];
      } catch (e) {
        console.warn(`Gazon Intelligent : prévision météo « ${type} » illisible`, e);
        return null;
      }
    };
    try {
      const [jours, heures] = await Promise.all([demander("daily"), demander("hourly")]);
      this._previsions = { jours: jours || [], heures: heures || [], jourRefuse: jours === null, heureRefusee: heures === null };
      this._prevision = (jours || [])[0] || null;
    } finally {
      this._previsionEnCours = false;
    }
    if (this._vue === "accueil" && (this._prevision || this._ongletAccueil === "meteo")) {
      this._rendreQuandLibre();
    }
  }

  // ── Météo ──

  _sourceMeteo(cle) {
    return [...(this._donnees?.sources || []), ...(this._donnees?.liaisons_materiel || [])]
      .find((s) => s.cle === cle) || null;
  }

  // L'état d'une entrée : branchée ou non, et si sa valeur est utilisable.
  _lectureSource(ligne) {
    if (!ligne?.entity_id) return { statut: "absente", etat: null };
    const etat = this._hass.states[ligne.entity_id];
    if (!etat) return { statut: "introuvable", etat: null };
    const brut = String(etat.state ?? "").toLowerCase();
    if (ETATS_SANS_VALEUR.has(brut)) return { statut: "indisponible", etat };
    if (ligne.numerique && nombreOuNul(etat.state) === null) return { statut: "illisible", etat };
    return { statut: "ok", etat, nombre: nombreOuNul(etat.state) };
  }

  // Une mesure du jardin si elle est lisible, sinon celle de l'entité météo : `{valeur, jardin}`.
  _mesureMeteo(cle, attribut) {
    const lecture = this._lectureSource(this._sourceMeteo(cle));
    if (lecture.statut === "ok" && lecture.nombre !== null) {
      return { valeur: lecture.nombre, unite: lecture.etat.attributes?.unit_of_measurement || "", jardin: true, etat: lecture.etat };
    }
    const meteo = this._donnees?.meteo ? this._hass.states[this._donnees.meteo] : null;
    const v = nombreOuNul(meteo?.attributes?.[attribut]);
    if (v === null) return null;
    const unites = { temperature: "temperature_unit", dew_point: "temperature_unit", apparent_temperature: "temperature_unit", wind_speed: "wind_speed_unit", wind_gust_speed: "wind_speed_unit", pressure: "pressure_unit", visibility: "visibility_unit" };
    const unite = unites[attribut] ? meteo.attributes[unites[attribut]] || "" : attribut === "humidity" || attribut === "cloud_coverage" ? "%" : "";
    return { valeur: v, unite, jardin: false };
  }

  _sante() {
    const s = this._a("risque", "sensor_health") ?? this._a("reserve", "sensor_health");
    return s && typeof s === "object" ? s : {};
  }

  // L'herbe mouillée, jugée comme le moteur (0.94.1) : le capteur « Rosée sur l'herbe » s'il
  // répond (au-dessus de 0 : mouillée), sinon `estimate_rosee` — l'air à 2 °C ou moins du point
  // de rosée de l'entité météo, une humidité d'au moins 88 %, du brouillard ou de la pluie.
  _herbeMouillee() {
    const ligne = this._sourceMeteo("capteur_rosee");
    const lecture = this._lectureSource(ligne);
    // Un point de rosée branché là est ignoré par le moteur (0.96.0) : la page l'ignore aussi.
    if (lecture.statut === "ok" && lecture.nombre !== null && !lectureInterdite(ligne, lecture.etat.attributes || {})) {
      return { mouillee: lecture.nombre > 0, raison: `${ligne.nom || ligne.entity_id} : ${valeurEtat(lecture.etat)}` };
    }
    const meteo = this._donnees?.meteo ? this._hass.states[this._donnees.meteo] : null;
    const temp = this._mesureMeteo("capteur_temperature", "temperature");
    const pointDeRosee = nombreOuNul(meteo?.attributes?.dew_point ?? meteo?.attributes?.native_dew_point);
    const ecart = temp && pointDeRosee !== null ? temp.valeur - pointDeRosee : null;
    const air = ecart !== null ? `air à ${nombreFr(ecart, 1)} °C de son point de rosée` : "";
    if (ecart !== null && ecart <= 2) return { mouillee: true, raison: air };
    const humidite = this._mesureMeteo("capteur_humidite", "humidity");
    if (humidite && humidite.valeur >= 88) return { mouillee: true, raison: `humidité de l'air ${nombreFr(humidite.valeur, 0)} %` };
    if (["fog", "rainy", "pouring"].includes(meteo?.state)) return { mouillee: true, raison: minuscule(METEOS[meteo.state][1]) };
    if (!temp && !humidite) return null;
    return { mouillee: false, raison: air || "ni air saturé, ni brouillard, ni pluie" };
  }

  _ongletMeteoHtml(c) {
    if (!this._previsions && !this._previsionEnCours) this._chargerPrevision();
    return this._mosaique([
      [this._meteoMaintenantHtml(c), "large", "large"],
      [this._meteoJoursHtml(c), "etroit", "etroit"],
      [this._meteoHeuresHtml(), "tout", "tout"],
      [this._meteoPluieHtml(c), "gauche", "etroitG"],
      [this._meteoEvaporationHtml(), "milieu", "largeD"],
      [this._meteoVentHtml(), "droite", "etroitG"],
      [this._meteoSanteHtml(), "droite", "largeD"],
      [this._meteoAppareilsHtml(), "tout", "tout"],
    ]);
  }

  _meteoMaintenantHtml() {
    const id = this._donnees?.meteo;
    const meteo = id ? this._hass.states[id] : null;
    const [icone, libelle] = meteo ? (METEOS[meteo.state] || ["mdi:weather-cloudy-alert", majuscule(String(meteo.state).replace(/[-_]/g, " "))]) : ["mdi:weather-cloudy-alert", "Entité météo introuvable"];
    const temp = this._mesureMeteo("capteur_temperature", "temperature");
    const origine = (m) => (m ? `<small class="origine ${m.jardin ? "jardin" : ""}">${m.jardin ? "jardin" : "prévision"}</small>` : "");
    const mesure = (icone_, titre, m, formatage) => (m ? `<div class="mesure-meteo"><ha-icon icon="${icone_}"></ha-icon><span>${esc(titre)}</span><b>${formatage(m)}</b>${origine(m)}</div>` : "");
    const avecUnite = (decimales) => (m) => `${esc(nombreFr(m.valeur, decimales))}${m.unite ? `\u00a0${esc(m.unite)}` : ""}`;
    const a = meteo?.attributes || {};
    const vent = this._mesureMeteo("capteur_vent", "wind_speed");
    const rafales = nombreOuNul(a.wind_gust_speed);
    // La direction vient de l'entité météo : l'afficher à côté d'un vent MESURÉ mélangerait deux sources.
    const direction = vent && !vent.jardin ? directionFr(a.wind_bearing) : null;
    const lignes = [
      mesure("mdi:water-percent", "Humidité", this._mesureMeteo("capteur_humidite", "humidity"), avecUnite(0)),
      vent ? `<div class="mesure-meteo"><ha-icon icon="mdi:weather-windy"></ha-icon><span>Vent</span><b>${avecUnite(1)(vent)}${direction ? ` · ${esc(direction)}` : ""}</b>${origine(vent)}${rafales !== null ? `<small>rafales prévues ${esc(nombreFr(rafales, 0))}\u00a0${esc(a.wind_speed_unit || "km/h")}</small>` : ""}</div>` : "",
      mesure("mdi:gauge", "Pression", this._mesureMeteo("capteur_pression", "pressure"), avecUnite(1)),
      mesure("mdi:white-balance-sunny", "Rayonnement", this._mesureMeteo("capteur_rayonnement", "__aucun__"), avecUnite(0)),
      // Celui de l'entité météo : « Rosée sur l'herbe » n'est pas un point de rosée (0.94.1).
      mesure("mdi:water-outline", "Point de rosée", this._mesureMeteo(null, "dew_point"), avecUnite(1)),
      nombreOuNul(a.apparent_temperature) !== null ? mesure("mdi:thermometer-lines", "Ressenti", { valeur: nombreOuNul(a.apparent_temperature), unite: a.temperature_unit || "°C", jardin: false }, avecUnite(0)) : "",
      nombreOuNul(a.uv_index) !== null ? mesure("mdi:sun-wireless-outline", "Indice UV", { valeur: nombreOuNul(a.uv_index), unite: "", jardin: false }, avecUnite(1)) : "",
      nombreOuNul(a.cloud_coverage) !== null ? mesure("mdi:cloud-outline", "Nuages", { valeur: nombreOuNul(a.cloud_coverage), unite: "%", jardin: false }, avecUnite(0)) : "",
    ].filter(Boolean);
    const releve = temp?.jardin && temp.etat ? `Relevé au jardin ${esc(ilYA(temp.etat.last_updated))}.` : meteo ? `Prévision mise à jour ${esc(ilYA(meteo.last_updated))}.` : "";
    return `<section class="section meteo-maintenant">
      <div class="meteo-principal">
        <ha-icon icon="${icone}"></ha-icon>
        <div>
          <small>Au jardin, en ce moment</small>
          <div class="meteo-grande">${temp ? `${esc(nombreFr(temp.valeur, 1))}\u00a0${esc(temp.unite || "°C")}` : "—"}</div>
          <div class="meteo-etat">${esc(libelle)}${temp && !temp.jardin ? " · température prévue" : ""}</div>
          ${releve ? `<p class="note">${releve}</p>` : ""}
        </div>
      </div>
      ${lignes.length ? `<div class="mesures-meteo">${lignes.join("")}</div>` : ""}
    </section>`;
  }

  _meteoJoursHtml(c) {
    const p = this._previsions;
    const jours = (p?.jours || []).slice(0, 7);
    const fuseau = this._fuseau();
    let corps;
    if (!p) corps = `<p class="vide">Prévisions en cours de lecture…</p>`;
    else if (!jours.length) corps = `<p class="vide">${p.jourRefuse ? "L'entité météo ne donne pas de prévision par jour." : "Aucune prévision pour les prochains jours."}</p>`;
    else {
      corps = `<ol class="jours-meteo">${jours.map((j) => {
        const [icone, libelle] = METEOS[j.condition] || ["mdi:weather-cloudy", majuscule(String(j.condition || "").replace(/[-_]/g, " "))];
        const pluie = nombreOuNul(j.precipitation);
        const proba = nombreOuNul(j.precipitation_probability);
        const bas = nombreOuNul(j.templow);
        const haut = nombreOuNul(j.temperature);
        return `<li>
          <span class="jour-nom">${esc(jourCourt(j.datetime, c.maintenant, fuseau))}</span>
          <ha-icon icon="${icone}" title="${esc(libelle)}"></ha-icon>
          <span class="jour-temp">${bas !== null ? `${esc(nombreFr(bas, 0))}°` : ""}${bas !== null && haut !== null ? " → " : ""}${haut !== null ? `<b>${esc(nombreFr(haut, 0))}°</b>` : ""}</span>
          <span class="jour-pluie ${pluie ? "mouille" : ""}">${pluie !== null ? esc(mmFr(pluie)) : ""}${proba !== null ? ` <small>${esc(nombreFr(proba, 0))}\u00a0%</small>` : ""}</span>
        </li>`;
      }).join("")}</ol>`;
    }
    return `<section class="section">
      <div class="section-tete"><h3>Les prochains jours</h3><p>La prévision de l'entité météo : c'est elle qui annonce la pluie à l'intégration.</p></div>
      ${corps}
    </section>`;
  }

  _meteoHeuresHtml() {
    const p = this._previsions;
    const heures = (p?.heures || []).filter((h) => Date.parse(h.datetime) >= Date.now() - 3600000).slice(0, 24);
    if (!p || (!heures.length && !p.heureRefusee)) return "";
    const fuseau = this._fuseau();
    const corps = heures.length
      ? `<div class="heures-meteo" data-garde-defilement="heures">${heures.map((h) => {
        const [icone, libelle] = METEOS[h.condition] || ["mdi:weather-cloudy", majuscule(String(h.condition || "").replace(/[-_]/g, " "))];
        const temp = nombreOuNul(h.temperature);
        const pluie = nombreOuNul(h.precipitation);
        const proba = nombreOuNul(h.precipitation_probability);
        const vent = nombreOuNul(h.wind_speed);
        return `<div class="heure-meteo">
          <small>${esc(heureFr(partiesLocales(new Date(h.datetime), fuseau).minute))}</small>
          <ha-icon icon="${icone}" title="${esc(libelle)}"></ha-icon>
          <b>${temp !== null ? `${esc(nombreFr(temp, 0))}°` : "—"}</b>
          <span class="${pluie ? "mouille" : ""}">${pluie !== null ? esc(mmFr(pluie)) : ""}${proba !== null && proba > 0 ? ` · ${esc(nombreFr(proba, 0))}\u00a0%` : ""}</span>
          ${vent !== null ? `<span><ha-icon icon="mdi:weather-windy"></ha-icon>${esc(nombreFr(vent, 0))}</span>` : ""}
        </div>`;
      }).join("")}</div>`
      : `<p class="vide">L'entité météo ne donne pas de prévision heure par heure.</p>`;
    return `<section class="section">
      <div class="section-tete"><h3>Les prochaines heures</h3><p>Température, pluie et vent annoncés, heure par heure.</p></div>
      ${corps}
    </section>`;
  }

  _meteoPluieHtml(c) {
    const s = this._sante();
    const ligne = (icone, titre, valeur, detail = "") => `<li><ha-icon icon="${icone}"></ha-icon><span>${esc(titre)}${detail ? `<small>${detail}</small>` : ""}</span><b>${valeur}</b></li>`;
    const lignes = [];
    const pleut = s.pluie_actuelle_active === true || s.pluie_mesuree_active === true;
    const actuelle = this._lectureSource(this._sourceMeteo("capteur_pluie_actuelle"));
    lignes.push(ligne(pleut ? "mdi:weather-pouring" : "mdi:weather-cloudy", "En ce moment", pleut ? "il pleut" : "pas de pluie",
      actuelle.statut === "ok" ? esc(`${this._sourceMeteo("capteur_pluie_actuelle").nom} : ${valeurEtat(actuelle.etat)}`) : ""));
    const cumul = nombreOuNul(s.pluie_cumul_jour_mm);
    if (cumul !== null) lignes.push(ligne("mdi:cup-water", "Aujourd'hui au jardin", esc(mmFr(cumul)), "compteur de la station, remis à zéro à minuit"));
    const jour = this._lectureSource(this._sourceMeteo("capteur_pluie_24h"));
    if (jour.statut === "ok") lignes.push(ligne("mdi:weather-rainy", cumul !== null ? "Aujourd'hui, second capteur" : "Aujourd'hui", esc(valeurEtat(jour.etat)), esc(this._sourceMeteo("capteur_pluie_24h").nom || "")));
    const depuis = nombreOuNul(s.pluie_mesuree_minutes_depuis_hausse);
    if (depuis !== null) lignes.push(ligne("mdi:history", "Dernière pluie mesurée", esc(depuis < 1 ? "à l'instant" : `il y a ${ageFr(depuis)}`)));
    const efficace = nombreOuNul(this._a("reserve", "pluie_efficace"));
    if (efficace !== null) lignes.push(ligne("mdi:sprout-outline", "Comptée pour le sol", esc(mmFr(efficace)), "la part de la pluie récente créditée à la réserve"));
    const demain = nombreOuNul(this._a("objectif", "pluie_demain"));
    const origineDemain = String(this._a("phase", "pluie_demain_source") || "");
    if (demain !== null) lignes.push(ligne("mdi:calendar-arrow-right", "Demain", esc(mmFr(demain)), esc(origineDemain.startsWith("capteur") ? "capteur de pluie de demain" : "prévision de l'entité météo")));
    const jours = (this._previsions?.jours || []).slice(1, 4);
    const trois = jours.reduce((total, j) => total + (nombreOuNul(j.precipitation) || 0), 0);
    if (jours.length) lignes.push(ligne("mdi:calendar-range", `Les ${jours.length} prochains jours`, esc(mmFr(trois)), "somme des prévisions par jour"));
    return `<section class="section">
      <div class="section-tete"><h3>La pluie</h3><p>Mesurée au jardin pour ce qui est tombé, prévue pour ce qui vient.</p></div>
      <ul class="lignes-meteo">${lignes.join("")}</ul>
    </section>`;
  }

  _meteoEvaporationHtml() {
    const s = this._sante();
    const et0 = nombreOuNul(this._s("et0"));
    const source = String(this._a("et0", "et0_source") || "");
    const horaire = nombreOuNul(this._s("eto_horaire"));
    const etc = nombreOuNul(this._s("etc"));
    const kc = nombreOuNul(this._a("etc", "kc_gazon"));
    const ecoulee = nombreOuNul(s.etp_ecoulee_mm);
    const estimee = nombreOuNul(s.etp_jour_estime_mm);
    const rayonnement = nombreOuNul(this._a("eto_horaire", "radiation_wm2"));
    const mesuree = (v) => (v === "capteur" ? "mesuré" : v ? "estimé" : "");
    const ligne = (icone, titre, valeur, detail = "") => `<li><ha-icon icon="${icone}"></ha-icon><span>${esc(titre)}${detail ? `<small>${detail}</small>` : ""}</span><b>${valeur}</b></li>`;
    const lignes = [];
    if (et0 !== null) lignes.push(ligne("mdi:weather-sunny", "Évaporation du jour (ET0)", esc(mmFr(et0)), esc(SOURCES_ET0[source] || source.replace(/_/g, " "))));
    if (ecoulee !== null) {
      const pct = estimee ? Math.min(100, (ecoulee / estimee) * 100) : null;
      lignes.push(`<li class="avec-jauge"><ha-icon icon="mdi:timer-sand"></ha-icon><span>Déjà partie aujourd'hui<small>ce que le sol a vraiment perdu depuis minuit${estimee !== null ? `, sur ${esc(mmFr(estimee))} estimés pour la journée` : ""}</small></span><b>${esc(mmFr(ecoulee))}</b>${pct !== null ? `<div class="jauge" style="--couleur:var(--gz-ambre)"><i style="width:${pct}%"></i></div>` : ""}</li>`);
    }
    if (horaire !== null) {
      const details = [
        rayonnement !== null ? `soleil ${nombreFr(rayonnement, 0)} W/m² (${mesuree(this._a("eto_horaire", "radiation_source"))})` : "",
        this._a("eto_horaire", "pressure_source") ? `pression ${mesuree(this._a("eto_horaire", "pressure_source"))}e` : "",
      ].filter(Boolean).join(", ");
      lignes.push(ligne("mdi:water-thermometer-outline", "En ce moment", `${esc(nombreFr(horaire, 2))}\u00a0mm/h`, esc(details)));
    }
    if (etc !== null) lignes.push(ligne("mdi:grass", "Pour le gazon (ETc)", esc(mmFr(etc)), kc !== null ? esc(`coefficient du gazon ${nombreFr(kc, 2)}`) : ""));
    const reference = nombreOuNul(this._a("et0", "temperature_reference_hydrique"));
    const prevue = nombreOuNul(this._a("et0", "forecast_temperature_today"));
    if (reference !== null) lignes.push(ligne("mdi:thermometer", "Température de référence", `${esc(nombreFr(reference, 1))}\u00a0°C`, prevue !== null ? esc(`plus haut prévu pour le reste du jour : ${nombreFr(prevue, 1)} °C`) : ""));
    if (!lignes.length) return "";
    return `<section class="section">
      <div class="section-tete"><h3>L'évaporation</h3><p>L'eau que le soleil, l'air et le vent prennent au sol : c'est elle qui vide la réserve.</p></div>
      <ul class="lignes-meteo">${lignes.join("")}</ul>
    </section>`;
  }

  _meteoVentHtml() {
    const s = this._sante();
    const v = this._donnees?.valeurs || {};
    const vent = nombreOuNul(s.vent_utilise_kmh);
    const feux = [];
    if (vent !== null) {
      const graines = nombreOuNul(v.graines_vent_max);
      const eviter = nombreOuNul(v.tonte_vent_a_eviter);
      const bloque = nombreOuNul(v.tonte_vent_bloque);
      if (graines !== null) feux.push([vent < graines ? "ok" : "retient", `Arroser les graines : ${vent < graines ? "oui" : "non"}`, `limite ${nombreFr(graines, 0)} km/h`]);
      if (eviter !== null && bloque !== null) {
        const etat = vent >= bloque ? ["retient", "Tondre : non", `bloqué dès ${nombreFr(bloque, 0)} km/h`] : vent >= eviter ? ["attention", "Tondre : à éviter", `déconseillé dès ${nombreFr(eviter, 0)} km/h`] : ["ok", "Tondre : oui", `déconseillé dès ${nombreFr(eviter, 0)} km/h`];
        feux.push(etat);
      }
    }
    const herbe = this._herbeMouillee();
    const niveau = String(this._a("risque", "fungal_risk_level") || "");
    const raisons = this._a("risque", "fungal_risk_reasons");
    const chaleur = String(this._a("fenetre_optimale", "heat_stress_level") || "");
    return `<section class="section">
      <div class="section-tete"><h3>Vent, rosée et maladies</h3><p>Ce que la météo autorise en ce moment.</p></div>
      <ul class="liste-simple">
        ${vent !== null ? `<li><ha-icon icon="mdi:weather-windy"></ha-icon><span>Vent pris en compte : <b>${esc(nombreFr(vent, 1))}\u00a0km/h</b></span></li>` : ""}
        ${feux.map(([ton, texte, detail]) => `<li class="${ton === "ok" ? "ok" : "retient"}"><ha-icon icon="${ton === "ok" ? "mdi:check-circle-outline" : ton === "attention" ? "mdi:alert-outline" : "mdi:close-circle-outline"}"></ha-icon><span>${esc(texte)} <small class="discret">(${esc(detail)})</small></span></li>`).join("")}
        ${herbe ? `<li class="${herbe.mouillee ? "retient" : "ok"}"><ha-icon icon="mdi:water-outline"></ha-icon><span>${herbe.mouillee ? "Herbe mouillée : la tonte attend" : "Herbe sèche"} <small class="discret">(${esc(herbe.raison)})</small></span></li>` : ""}
        ${niveau ? `<li class="${["low", "faible"].includes(niveau) ? "ok" : "retient"}"><ha-icon icon="mdi:mushroom-outline"></ha-icon><span>Risque de maladies : <b>${esc(NIVEAUX_RISQUE[niveau] || niveau)}</b>${Array.isArray(raisons) && raisons.length ? ` <small class="discret">(${esc(raisons.join(", "))})</small>` : ""}</span></li>` : ""}
        ${chaleur ? `<li><ha-icon icon="mdi:thermometer-high"></ha-icon><span>Stress du gazon : <b>${esc(libelleDe(NIVEAUX_RISQUE, chaleur))}</b></span></li>` : ""}
      </ul>
    </section>`;
  }

  _meteoSanteHtml() {
    const s = this._sante();
    if (!Object.keys(s).length) return "";
    const voyants = [
      ["temperature_valid", "Température", "la température vient du capteur"],
      ["humidity_valid", "Humidité", "l'humidité vient du capteur"],
      ["wind_valid", "Vent", "le vent vient du capteur"],
      ["pluie_valid", "Pluie du jour", "la pluie du jour vient du capteur"],
      ["etp_valid", "Évaporation lue", "l'évaporation du jour est lisible"],
      ["eto_radiation_measured", "Soleil mesuré", "le soleil est mesuré, pas déduit des nuages"],
      ["eto_pressure_measured", "Pression mesurée", "la pression est mesurée"],
      ["weather_profile_available", "Prévisions", "l'entité météo répond"],
      ["eto_hourly_available", "Évaporation horaire", "l'évaporation heure par heure est calculée"],
    ].filter(([cle]) => typeof s[cle] === "boolean");
    const repli = voyants.filter(([cle]) => !s[cle]).length;
    return `<section class="section">
      <div class="section-tete"><h3>Ce que l'intégration utilise vraiment</h3><p>${repli
        ? `${repli} voyant${repli > 1 ? "s" : ""} en orange : une valeur prévue remplace la mesure.`
        : "Tout est au vert : les calculs utilisent les mesures configurées."}</p></div>
      <div class="voyants-meteo">${voyants.map(([cle, court, long]) => `<span class="voyant ${s[cle] ? "ok" : "retient"}" title="${esc(majuscule(long))}${s[cle] ? "" : " : non"}"><ha-icon icon="${s[cle] ? "mdi:check-circle-outline" : "mdi:alert-outline"}"></ha-icon>${esc(court)}</span>`).join("")}</div>
    </section>`;
  }

  _meteoEntreesHtml(repliable = false) {
    const lignes = this._donnees?.sources || [];
    if (!lignes.length) return "";
    const pourrait = new Map();
    for (const appareil of this._donnees?.appareils || []) {
      for (const e of appareil.entites || []) for (const cle of e.pourrait || []) {
        if (!pourrait.has(cle)) pourrait.set(cle, []);
        pourrait.get(cle).push(`« ${nomCourt(e.nom, appareil.nom)} »${appareil.nom ? ` (${appareil.nom})` : ""}`);
      }
    }
    const statuts = {
      ok: ["ok", "mdi:check-circle-outline", "mesure lue"],
      absente: ["", "mdi:minus-circle-outline", "non branchée"],
      introuvable: ["retient", "mdi:help-circle-outline", "entité introuvable"],
      indisponible: ["retient", "mdi:alert-outline", "indisponible"],
      illisible: ["retient", "mdi:alert-outline", "valeur illisible"],
    };
    const admin = this._estAdmin();
    const tableau = (cles) => cles.map((cle) => [cle, GROUPES_METEO[cle]]).map(([cle, titre]) => {
      const rangees = lignes.filter((l) => l.groupe === cle).map((l) => {
        const lecture = this._lectureSource(l);
        // Une entité branchée que le moteur lirait de travers (branchée avant la 0.95.0).
        const deTravers = lecture.etat && l.domaine && !entreeAcceptee(l, l.entity_id, lecture.etat.attributes || {}, lecture.etat.state);
        const [ton, icone, libelleBrut] = deTravers ? ["retient", "mdi:alert-outline", "unité inattendue"] : statuts[lecture.statut];
        const libelle = lecture.statut === "ok" && !l.numerique && !deTravers ? "répond" : libelleBrut;
        const idees = pourrait.get(l.cle) || [];
        const bouton = admin
          ? `<button class="petit-bouton bouton-entree" data-dialogue="entree" data-entree="${esc(l.cle)}"><ha-icon icon="${l.entity_id ? "mdi:swap-horizontal" : "mdi:power-plug-outline"}"></ha-icon>${l.entity_id ? "Changer" : "Brancher"}</button>`
          : "";
        const entite = l.entity_id
          ? `<b>${esc(l.nom || l.entity_id)}</b><code>${esc(l.entity_id)}</code>${l.partagee ? `<small class="puce-mini">partagée entre pelouses</small>` : ""}`
          : `<span class="discret">Sans elle : ${esc(minuscule(l.sans_elle))}</span>${idees.length ? `<small class="idee">Entités disponibles : ${esc(idees.join(", "))}.</small>` : ""}`;
        return `<tr class="${ton}" data-source-meteo="${esc(l.cle)}">
          <td><b>${esc(l.titre)}</b><small>${esc(l.apporte)}</small></td>
          <td class="entree-entite">${entite}${bouton}</td>
          <td class="entree-valeur">${lecture.etat ? esc(valeurEtat(lecture.etat)) : "—"}${lecture.etat ? `<small>${esc(ilYA(lecture.etat.last_updated))}</small>` : ""}</td>
          <td class="entree-statut"><span class="statut ${ton}"${deTravers ? ` title="${esc(this._unitesAttendues(l))}"` : ""}><ha-icon icon="${icone}"></ha-icon>${esc(libelle)}</span></td>
        </tr>`;
      }).join("");
      return rangees ? `<tr class="groupe"><th colspan="4">${esc(titre)}</th></tr>${rangees}` : "";
    }).join("");
    const table = (cles) => `<div class="tableau-defilant"><table class="entrees-meteo">
        <thead><tr><th>Rôle</th><th>Entité</th><th>Valeur</th><th>État</th></tr></thead>
        <tbody>${tableau(cles)}</tbody>
      </table></div>`;
    const titre = "Entrées de l'intégration";
    const phrase = `Chaque entité configurée, son rôle et sa valeur actuelle. Une entrée non branchée est remplacée comme indiqué.${admin ? " « Changer » et « Brancher » permettent de sélectionner une autre entité." : ""}`;
    const corps = `<div class="entrees-deux">${table(["meteo", "air"])}${table(["pluie", "sol"])}</div>`;
    if (repliable) return this._sectionReglageHtml({
      titre, phrase, icone: "mdi:weather-partly-cloudy", corps, attributs: 'data-entrees-meteo="1"',
    });
    return `<section class="section"><div class="section-tete"><h3>${titre}</h3><p>${phrase}</p></div>${corps}</section>`;
  }

  _meteoAppareilsHtml() {
    const appareils = this._donnees?.appareils || [];
    if (!appareils.length) return "";
    const titres = new Map((this._donnees?.sources || []).map((s) => [s.cle, s.titre]));
    return `<section class="section">
      <div class="section-tete"><h3>Stations et appareils météo détectés</h3><p>Les stations personnelles compatibles sont reconnues par leurs mesures. Elles sont proposées sans être branchées automatiquement. En vert, les entités déjà utilisées.</p></div>
      <div class="appareils-meteo">${appareils.map((ap) => `<div class="appareil-meteo">
        <h4><ha-icon icon="mdi:${ap.station_personnelle ? "weather-partly-cloudy" : "access-point"}"></ha-icon>${esc(ap.nom || "Appareil")}${ap.fabricant || ap.modele ? `<small>${esc([ap.fabricant, ap.modele].filter(Boolean).join(" · "))}</small>` : ""}${ap.station_personnelle ? `<small class="puce-mini">Station météo personnelle${ap.detectee ? " détectée" : ""}</small>` : ""}</h4>
        <div class="voisines">${ap.entites.map((e) => {
          const etat = this._hass.states[e.entity_id];
          const titre = e.branchee ? `lue par l'intégration : ${titres.get(e.branchee) || e.branchee}` : e.pourrait?.length ? `pourrait servir : ${e.pourrait.map((c) => titres.get(c) || c).join(", ")}` : e.entity_id;
          return `<div class="voisine ${e.branchee ? "branchee" : ""} ${e.pourrait?.length ? "idee" : ""}" title="${esc(titre)}">
            <span>${esc(nomCourt(e.nom, ap.nom))}</span><b>${esc(valeurEtat(etat))}</b>
          </div>`;
        }).join("")}</div>
      </div>`).join("")}</div>
    </section>`;
  }

  // ── Changer une entrée (0.95.0) ──

  _unitesAttendues(ligne) {
    if (ligne.domaine === "weather") return "Une entité météo de Home Assistant.";
    const unites = (ligne.unites || []).filter((u) => u !== "W/m2");
    if (!unites.length) return ligne.domaine === "sensor" ? "Un capteur." : "";
    const liste = unites.length === 1 ? unites[0] : `${unites.slice(0, -1).join(", ")} ou ${unites[unites.length - 1]}`;
    return `Un capteur en ${liste}${ligne.sans_unite ? ", ou sans unité" : ""}.`;
  }

  _choixEntitesHtml(d, ligne) {
    const propres = new Set(Object.values(this._donnees?.entites || {}));
    const appareils = new Map();
    for (const ap of this._donnees?.appareils || []) for (const e of ap.entites || []) appareils.set(e.entity_id, {
      nom: ap.nom || "",
      stationPersonnelle: Boolean(ap.station_personnelle),
    });
    const utilisees = new Map((this._donnees?.sources || [])
      .filter((s) => s.entity_id && s.cle !== ligne.cle).map((s) => [s.entity_id, s.titre]));
    const actuelle = ligne.entity_id || "";
    const cherche = sansAccents(d.recherche).trim();
    const autorisees = Array.isArray(ligne.choix) ? new Set(ligne.choix.map((c) => c.entity_id)) : null;
    const tous = candidatsEntree(ligne, this._hass.states, { propres, appareils })
      .filter((c) => !autorisees || autorisees.has(c.id));
    const trouves = cherche ? tous.filter((c) => sansAccents(`${c.nom} ${c.id}`).includes(cherche)) : tous;
    const montres = trouves.slice(0, CANDIDATS_MONTRES);
    // L'entité branchée reste visible, même quand elle ne convient pas (branchée avant la 0.95.0).
    if (actuelle && !cherche && !montres.some((c) => c.id === actuelle)) {
      const etat = this._hass.states[actuelle];
      montres.unshift({ id: actuelle, nom: String(etat?.attributes?.friendly_name || actuelle), appareil: appareils.get(actuelle) || null, deTravers: true });
    }
    const choix = (valeur, titre, details) => `<label class="choix-mode choix-entite">
        <input type="radio" name="dlg-entite" value="${esc(valeur)}" data-dlg="entite" ${d.choix === valeur ? "checked" : ""}>
        <span><b>${esc(titre)}</b><small>${esc(details.filter(Boolean).join(" · "))}</small></span></label>`;
    const options = montres.map((c) => {
      const etat = this._hass.states[c.id];
      return choix(c.id, nomCourt(c.nom, c.appareil), [
        etat ? valeurEtat(etat) : "introuvable",
        c.appareil,
        c.stationPersonnelle ? "station météo personnelle" : "",
        c.id === actuelle ? "branchée en ce moment" : "",
        utilisees.has(c.id) ? `déjà lue pour « ${utilisees.get(c.id)} »` : "",
        c.deTravers && etat ? "ne convient pas à ce rôle" : "",
        c.id,
      ]);
    }).join("");
    const reste = trouves.length - montres.filter((c) => !c.deTravers).length;
    return `${ligne.obligatoire ? "" : choix("", "Aucune", [ligne.sans_elle])}${options}
      ${trouves.length ? "" : `<p class="vide">${cherche ? "Aucune entité ne correspond à la recherche." : "Aucune entité de Home Assistant ne convient à ce rôle."}</p>`}
      ${reste > 0 ? `<p class="vide">Et ${reste} autre${reste > 1 ? "s" : ""} : cherche par nom.</p>` : ""}`;
  }

  _libelleEntree(d, actuelle) {
    if (d.enCours) return "Un instant…";
    if (d.choix === actuelle) return "Rien à changer";
    return d.choix ? "Brancher" : "Retirer";
  }

  // Un autre choix ne redessine que le bouton : la liste garde sa position.
  _majPiedEntree() {
    const d = this._dialogue;
    const ligne = this._sourceMeteo(d?.cle);
    const bouton = this._fenetre.querySelector("[data-valider]");
    if (!ligne || !bouton) return;
    const actuelle = ligne.entity_id || "";
    bouton.disabled = Boolean(d.enCours) || d.choix === actuelle;
    bouton.textContent = this._libelleEntree(d, actuelle);
    this._fenetre.querySelector("[data-erreur-entree]")?.remove();
  }

  async _changerEntree(d) {
    const ligne = this._sourceMeteo(d.cle);
    if (d.enCours || !ligne) return;
    if (!this._estAdmin()) {
      this._afficherToast("Seul un administrateur peut faire ça.", true);
      return;
    }
    const actuelle = ligne.entity_id || "";
    if (d.choix === actuelle) {
      this._fermerDialogue();
      return;
    }
    d.enCours = true;
    d.erreur = null;
    this._majPiedEntree();
    try {
      const materiel = (this._donnees?.liaisons_materiel || []).some((l) => l.cle === d.cle);
      const reponse = await this._hass.callWS({
        type: WS_ECRIRE,
        entry_id: this._donnees.entry_id,
        [materiel ? "liaisons_materiel" : "entrees"]: { [d.cle]: d.choix || null },
      });
      if (reponse?.ok === false) throw new Error(Object.values(reponse.erreurs || {})[0] || "entrée refusée");
      this._donnees = {
        ...this._donnees,
        ...(reponse.sources ? { sources: reponse.sources, appareils: reponse.appareils || [] } : {}),
        ...(reponse.liaisons_materiel ? { liaisons_materiel: reponse.liaisons_materiel } : {}),
        ...(reponse.zones ? { zones: reponse.zones } : {}),
        ...(reponse.meteo !== undefined ? { meteo: reponse.meteo } : {}),
      };
      if (d.cle === "entite_meteo") {
        // Les prévisions viennent de l'entité météo : on redemande celles de la nouvelle.
        this._previsions = null;
        this._prevision = null;
        this._previsionDate = 0;
        this._chargerPrevision();
      }
      const nom = d.choix ? String(this._hass.states[d.choix]?.attributes?.friendly_name || d.choix) : "";
      const message = d.choix
        ? `« ${nom} » sert maintenant pour « ${ligne.titre} ».`
        : `« ${ligne.titre} » n'a plus d'entité : ${minuscule(ligne.sans_elle)}`;
      d.enCours = false;
      if (this._dialogue === d) this._fermerDialogue();
      this._refs = null;
      this._aChange();
      this._rendre();
      this._afficherToast(reponse.recharge ? `${message} L'intégration se recharge, quelques secondes.` : message);
    } catch (e) {
      console.error("Gazon Intelligent : entrée non changée", e);
      d.enCours = false;
      d.erreur = erreurLisible(e);
      this.dispatchEvent(new CustomEvent("haptic", { detail: "failure", bubbles: true, composed: true }));
      if (this._dialogue === d) {
        this._redessinerDialogue();
        this._fenetre.querySelector(".dialogue-corps")?.scrollTo({ top: 0 });
      }
    }
  }

  // ── Tonte ──

  _ongletTonteHtml(c) {
    const t = (k) => this._a("tonte_autorisee", k);
    const statut = String(t("tonte_statut") || "");
    const motifBlocage = String(t("mowing_block_reason_label") || "").trim();
    const codeBlocage = String(t("mowing_block_reason_code") || "");
    const pluie = codeBlocage.includes("pluie") || codeBlocage.includes("rain");
    const gazonOk = t("gazon_permet_tonte");
    const machineOk = t("machine_permet_tonte");
    const batterie = nombreOuNul(t("tondeuse_batterie"));
    // ⚠️ DEUX AXES, DEUX BADGES : la machine (disponible ?) et le gazon (prêt ?). Jamais fusionnés.
    const machine = `<div class="machine">
        <div class="machine-icone"><ha-icon icon="mdi:robot-mower"></ha-icon></div>
        <div class="machine-texte"><b>${esc(t("tondeuse_nom") || "Tondeuse")}</b>
          <small>${esc(t("tondeuse_statut_libelle") || "")}${batterie !== null ? ` · batterie ${nombreFr(batterie, 0)} %` : ""}</small></div>
        ${machineOk === undefined ? "" : `<span class="badge ${machineOk ? "" : "arret"}">${machineOk ? "Disponible" : "Pas disponible"}</span>`}
      </div>`;
    const puces = [];
    const libelleGazon = {
      autorisee: "prêt",
      autorisee_avec_precaution: "prêt avec précaution",
      a_surveiller: "à surveiller",
      deconseillee: "tonte à éviter",
      interdite: "pas prêt",
    }[statut] || (gazonOk === undefined ? "" : gazonOk ? "prêt" : "pas prêt");
    if (libelleGazon) {
      const tonGazon = statut ? TONS_TONTE[statut] : gazonOk ? "ok" : "arret";
      puces.push(`<span class="puce"><span class="point ${tonGazon === "ok" ? "" : tonGazon || "arret"}"></span>Gazon : ${esc(libelleGazon)}</span>`);
    }
    if (t("mowing_window_label")) {
      const etat = t("mowing_window_state");
      puces.push(`<span class="puce" title="${esc(t("mowing_window_reason") || "")}"><span class="point ${etat === "discouraged" ? "attention" : etat === "blocked" ? "arret" : ""}"></span>Créneau : ${esc(minuscule(t("mowing_window_label")))}</span>`);
    }
    const frequence = t("mowing_frequency_label");
    if (frequence) {
      const modeGraines = ["Semis", "Sursemis"].includes(c.semis?.mode) ? c.semis.mode : null;
      const libelleFrequence = modeGraines
        ? `Rythme actuel : ${frequence} (${modeGraines})`
        : `Ce mois-ci : ${frequence}`;
      puces.push(`<span class="puce"><ha-icon icon="mdi:calendar-sync"></ha-icon>${esc(libelleFrequence)}</span>`);
    }
    const pourquoi = motifBlocage
      ? `<ul class="liste-simple"><li><ha-icon icon="${pluie ? "mdi:weather-rainy" : "mdi:timer-sand"}"></ha-icon><span>${esc(motifBlocage)}</span></li></ul>`
      : gazonOk === false && t("raison_blocage_tonte")
        ? `<ul class="liste-simple"><li><ha-icon icon="mdi:timer-sand"></ha-icon><span>${esc(premierePhrase(t("raison_blocage_tonte")))}.</span></li></ul>`
        : "";
    const actions = this._tonduAujourdhui(c)
      ? `<p class="vide">Une tonte est déjà inscrite aujourd'hui.</p>`
      : `<div class="rangee-boutons"><button class="bouton-plein" data-dialogue="tondu">Déclarer une tonte</button></div>`;
    const carteMachine = `<section class="section">${machine}${puces.length ? `<div class="puces" style="padding:0 20px 14px">${puces.join("")}</div>` : ""}${pourquoi}${actions}</section>`;
    return this._mosaique([
      [carteMachine, "gauche", "large"],
      [this._coordinationHtml(), "gauche", "etroit"],
      [this._pilotageTondeuseEtatHtml(), "gauche", "etroit"],
      [this._travailHtml(), "milieu", "large"],
      [this._hauteursHtml(c), "milieu", "etroit"],
      [this._pousseHtml(), "droite", "etroit"],
    ]);
  }

  // Le travail de la tondeuse. Chaque valeur n'est montrée que si elle EXISTE : null = injoignable.
  _travailHtml() {
    const a = (k) => this._a("tonte_etat", k);
    const progres = nombreOuNul(a("mower_job_progress_pct"));
    const etat = a("mower_job_completion_state");
    const declaration = a("mower_auto_declaration_state");
    const reprisePossible = a("mower_job_resume_possible") === true;
    const pauseDepuis = a("mower_job_paused_since");
    const minutes = nombreOuNul(a("mower_mowing_minutes_today"));
    if (progres === null && !declaration && minutes === null) return "";
    const passes = nombreOuNul(a("mower_pass_count_today"));
    const mediane = nombreOuNul(a("mower_full_pass_minutes_median"));
    const plancher = nombreOuNul(a("mower_auto_declaration_threshold_minutes"));
    const fin = a("mower_last_pass_end_reason");
    const etatTexte = etat === "termine" ? "terminé" : etat === "repos" ? "aucun travail en cours" : etat === "en_pause" ? "en pause à la base" : etat === "en_cours" ? "en cours" : "";
    const inscrit = declaration === "declaree" || declaration === "deja_declaree";
    const details = [];
    let ancienTravail = "";
    if (reprisePossible && progres !== null) {
      const instant = pauseDepuis ? new Date(pauseDepuis) : null;
      const valide = instant && !Number.isNaN(instant.getTime());
      const quand = valide
        ? `${dateHumaine(pauseDepuis, partiesLocales(new Date(), this._fuseau()), this._fuseau())} à ${heureFr(partiesLocales(instant, this._fuseau()).minute)}`
        : "à une date inconnue";
      ancienTravail = `<p><b>Travail précédent :</b> ${nombreFr(progres, 0)} % · interrompu ${esc(quand)} · reprise possible.</p>`;
    }
    // Zéro est une MESURE (pas encore tourné aujourd'hui), pas une absence.
    if (minutes !== null) details.push(`Tondu aujourd'hui : <b>${minutes > 0 ? esc(dureeFr(Math.round(minutes))) : "0 min"}</b>`);
    if (passes !== null && passes > 0) details.push(`${nombreFr(passes, 0)} passe${passes > 1 ? "s" : ""}`);
    if (fin) details.push(`dernière passe : ${esc(libelleDe(FINS_DE_PASSE, fin))}`);
    if (mediane !== null) details.push(`une passe complète dure ${esc(dureeFr(Math.round(mediane)))}`);
    return `<section class="section">
      <div class="section-tete"><h3>Le travail de la tondeuse</h3><p>L'activité actuelle et le dernier travail qui peut reprendre.</p></div>
      <div class="travail">
        ${progres !== null && !reprisePossible ? `<div class="travail-tete"><span>Progression${etatTexte ? ` · ${esc(etatTexte)}` : ""}</span><b>${nombreFr(progres, 0)} %</b></div>
        <div class="progression ${etat === "repos" ? "repos" : ""}" role="progressbar" aria-valuenow="${Math.round(progres)}" aria-valuemin="0" aria-valuemax="100"><i style="width:${Math.max(0, Math.min(100, progres))}%"></i></div>` : ""}
        ${ancienTravail}
        ${declaration ? `<p class="${inscrit ? "ok" : ""}">Inscription de la tonte : ${esc(minuscule(libelleDe(DECLARATIONS, declaration)))}${!inscrit && declaration === "travail_trop_court" && plancher !== null ? ` (il faut ${esc(dureeFr(plancher))})` : ""}</p>` : ""}
        ${details.length ? `<p>${details.join(" · ")}</p>` : ""}
      </div>
    </section>`;
  }

  // ⚠️ DEUX HAUTEURS, ET C'EST LA LAME RÉELLE QUI FAIT FOI (arbitrage du 30/08/2026).
  _hauteursHtml(c) {
    const date = this._a("prochaine_tonte", "target_date") || this._s("prochaine_tonte");
    const resume = this._a("prochaine_tonte", "summary");
    const h = (k) => this._a("hauteur_tonte", k);
    const lameMm = nombreOuNul(this._a("tonte_etat", "tondeuse_hauteur_coupe_mm") ?? h("tondeuse_hauteur_coupe_mm"));
    const lame = lameMm !== null ? lameMm / 10 : null;
    const conseil = nombreOuNul(this._s("hauteur_tonte"));
    const motif = typeof h("hauteur_tonte_motif") === "string" ? h("hauteur_tonte_motif").trim().replace(/\.$/, "") : "";
    const min = nombreOuNul(h("hauteur_tonte_min_cm"));
    const max = nombreOuNul(h("hauteur_tonte_max_cm"));
    const gardeFou = h("hauteur_tonte_garde_fou_label");
    const sousLame = [];
    if (lame !== null) {
      sousLame.push("réglée sur la lame");
      if (conseil !== null && Math.abs(conseil - lame) > 0.05) sousLame.push(`conseillé : ${cmFr(conseil)}`);
    }
    if (motif) sousLame.push(motif);
    if (min !== null && max !== null) sousLame.push(`la tondeuse va de ${cmFr(min)} à ${cmFr(max)}`);
    if (gardeFou) sousLame.push(String(gardeFou));
    return `<div class="tuiles deux">
      ${this._tuile({ icone: "mdi:calendar-arrow-right", titre: "Prochaine tonte", petite: true,
        valeur: date ? esc(majuscule(dateHumaine(date, c.maintenant, this._fuseau()))) : "—",
        sous: !date && resume ? esc(resume) : "" })}
      ${this._tuile({ icone: "mdi:content-cut", titre: "Hauteur de coupe", petite: true, ton: "ok",
        valeur: lame !== null ? esc(cmFr(lame)) : conseil !== null ? esc(cmFr(conseil)) : "—",
        sous: sousLame.map(esc).join(" · ") })}
    </div>`;
  }

  _pousseHtml() {
    const estimee = nombreOuNul(this._s("hauteur_gazon_estimee"));
    if (estimee === null) return "";
    const lameMm = nombreOuNul(this._a("tonte_etat", "tondeuse_hauteur_coupe_mm"));
    const cible = lameMm !== null ? lameMm / 10 : nombreOuNul(this._s("hauteur_tonte"));
    const haut = Math.max(estimee, cible ?? 0) * 1.25 || 1;
    const aCouper = cible !== null && estimee > cible ? estimee - cible : 0;
    let phrase = "pile à la hauteur de coupe";
    if (aCouper > 0.05) phrase = `soit ${cmFr(aCouper)} à couper pour revenir à ${cmFr(cible)}`;
    else if (cible !== null && estimee < cible - 0.05) phrase = `${cmFr(cible - estimee)} sous la lame, réglée à ${cmFr(cible)}`;
    const jour = nombreOuNul(this._a("hauteur_gazon_estimee", "gazon_pousse_jour_cm"));
    return `<section class="section">
      <div class="section-tete"><h3>La hauteur de l'herbe</h3><p>Une estimation : l'herbe repousse depuis la dernière tonte.</p></div>
      <div class="pousse">
        <div class="pousse-colonne" role="img" aria-label="Herbe ${esc(cmFr(estimee))}">
          <div class="pousse-herbe" style="height:${Math.max(6, (estimee / haut) * 100)}%"></div>
          ${cible !== null ? `<div class="pousse-lame" style="bottom:${(cible / haut) * 100}%" title="Lame à ${esc(cmFr(cible))}"></div>` : ""}
        </div>
        <div class="pousse-texte">
          <b>${esc(cmFr(estimee))}</b>
          <p>de haut aujourd'hui, ${esc(phrase)}.</p>
          ${jour !== null && jour > 0 ? `<p>+ ${nombreFr(jour, 2)} cm poussés aujourd'hui.</p>` : ""}
          ${cible !== null ? `<p>Le trait rouge montre la lame.</p>` : ""}
        </div>
      </div>
    </section>`;
  }

  _coordinationHtml() {
    const id = this._donnees?.entites?.coordination_tondeuse;
    if (!id || !this._hass.states[id]) return "";
    const allume = this._allume(id);
    return `<section class="section"><div class="ligne-bascule">
      <span class="ligne-icone"><ha-icon icon="mdi:robot-mower"></ha-icon></span>
      <div class="ligne-textes"><h4>Attendre la tondeuse avant d'arroser</h4>
        <p>${allume ? "Allumé : les vannes restent fermées tant que la tondeuse travaille ou rentre." : "Éteint : l'arrosage ne regarde pas la tondeuse."}</p></div>
      <button class="bascule" role="switch" aria-checked="${allume}" data-dialogue="coordination" aria-label="Attendre la tondeuse avant d'arroser"></button>
    </div></section>`;
  }

  _pilotageTondeuseEtatHtml() {
    const a = (cle) => this._a("tonte_etat", cle);
    const mode = a("mower_control_mode") || this._donnees?.choix?.pilotage_tondeuse || "desactive";
    const etat = a("mower_control_state");
    const raison = a("mower_control_reason");
    const action = a("mower_control_pending_action");
    const erreur = a("mower_control_last_error");
    const cycle = a("mower_control_cycle_state");
    const motifReprise = a("mower_control_resume_reason");
    const titres = { desactive: "Pilotage désactivé", observation: "Pilotage en observation", actif: "Pilotage actif" };
    const actions = { start_mowing: "départ", dock: "retour à la base", open_cover: "ouverture du garage", close_cover: "fermeture du garage" };
    const cycles = {
      depart_envoye: "Départ envoyé, attente de sortie",
      cycle_autonome: "Cycle autonome : recharges gérées par la tondeuse",
      reprise_attendue: "Reprise attendue après un rappel de l'intégration",
    };
    const suiviCycle = mode === "actif" && cycles[cycle]
      ? `<p><b>${esc(cycles[cycle])}</b>${cycle === "reprise_attendue" && motifReprise ? ` · ${esc(motifReprise)}` : ""}</p>`
      : "";
    return `<section class="section"><div class="section-tete"><h3>${esc(titres[mode] || "Pilotage de la tondeuse")}</h3><p>${mode === "observation" ? "Aucune commande n'est envoyée." : mode === "actif" ? "Gazon Intelligent commande la tondeuse selon ses sécurités." : "La tondeuse reste gérée par son système actuel."}</p></div>
      <div class="lignes"><div class="ligne compacte">
        <div class="ligne-tete"><span class="ligne-icone"><ha-icon icon="${mode === "actif" ? "mdi:robot-mower" : mode === "observation" ? "mdi:eye-outline" : "mdi:power-off"}"></ha-icon></span>
          <div class="ligne-textes"><h4>${action ? `Décision : ${esc(actions[action] || action)}` : esc(etat || "En attente")}</h4><p>${esc(erreur || raison || "Le prochain cycle précisera la décision.")}</p></div>
        </div>
        ${suiviCycle}
      </div></div>
    </section>`;
  }

  // ── Gazon ──

  _ongletGazonHtml(c) {
    const mode = c.mode || this._s("phase") || "—";
    const risque = String(this._s("risque") || "");
    const hydrique = String(this._s("etat_hydrique") || "");
    const raisons = this._a("risque", "risque_gazon_raisons");
    const fongique = this._a("risque", "fungal_risk_reasons");
    const niveauFongique = { low: "faible", moderate: "modéré", medium: "modéré", high: "élevé", critical: "critique" }[this._a("risque", "fungal_risk_level")] || this._a("risque", "fungal_risk_level");
    const auto = this._valeurEntiteReelle("arrosage_automatique");
    const lignesRisque = [
      ...(Array.isArray(raisons) ? raisons : []).map((r) => `<li><ha-icon icon="mdi:shield-half-full"></ha-icon><span>${esc(majuscule(r))}</span></li>`),
      ...(Array.isArray(fongique) ? fongique : []).map((r) => `<li><ha-icon icon="mdi:mushroom-outline"></ha-icon><span>Maladies${niveauFongique ? ` (risque ${esc(niveauFongique)})` : ""} : ${esc(r)}</span></li>`),
    ];
    const arros7 = nombreOuNul(this._a("reserve", "arrosage_recent_7j"));
    const pluie = nombreOuNul(this._a("reserve", "pluie_efficace"));
    const bilan = [
      arros7 !== null ? `Arrosage sur 7 jours : <b>${esc(mmFr(arros7))}</b>` : "",
      pluie !== null && pluie > 0 ? `pluie utile : <b>${esc(mmFr(pluie))}</b>` : "",
    ].filter(Boolean).join(" · ");
    const carteMode = `<section class="section">
        <div class="etat-bandeau">
          <div class="etat-icone"><ha-icon icon="mdi:sprout"></ha-icon></div>
          <div><small>Le mode du gazon</small><b>${esc(mode)}${c.semis ? ` · jour ${c.semis.age}` : ""}</b><p>${esc(MODES[mode] || "")}</p></div>
        </div>
        <div class="rangee-boutons">
          <button class="bouton-plein" data-dialogue="mode">Changer de mode</button>
          ${mode !== "Normal" ? `<button class="bouton-contour" data-dialogue="normal">Revenir au mode Normal</button>` : ""}
        </div>
      </section>`;
    const tuiles = `<div class="tuiles">
        ${this._tuile({ icone: "mdi:leaf", titre: "Phase", valeur: esc(this._s("phase") || "—"), petite: true })}
        ${this._tuileRisque()}
        ${this._tuileReserve()}
        ${this._tuile({ icone: "mdi:ruler", titre: "Hauteur conseillée", petite: true, valeur: c.hauteurConseillee !== null ? esc(cmFr(c.hauteurConseillee)) : "—", sous: esc(c.motif || "") })}
      </div>`;
    const risques = lignesRisque.length
      ? `<section class="section"><div class="section-tete"><h3>Ce qui menace le gazon</h3></div><ul class="liste-simple">${lignesRisque.join("")}</ul></section>`
      : "";
    const outils = `<section class="section">
        <div class="section-tete"><h3>Les outils</h3><p>À utiliser de temps en temps, quand quelque chose ne colle pas.</p></div>
        <div class="rangee-boutons">
          <button class="bouton-contour" data-dialogue="reserve">Recaler la réserve du sol</button>
          ${auto !== undefined ? `<button class="bouton-contour" data-dialogue="auto">${auto ? "Couper" : "Allumer"} l'arrosage automatique</button>` : ""}
          ${this._verrouSecuriteActif() ? `<button class="bouton-contour danger" data-dialogue="deverrouiller"><ha-icon icon="mdi:shield-alert-outline"></ha-icon>Lever le verrou de sécurité</button>` : ""}
        </div>
      </section>`;
    return this._mosaique([
      [tuiles, "tout", "tout"],
      [carteMode, "etroitG", "etroitG"],
      [this._reservoirHtml(hydrique, bilan), "largeD", "largeD"],
      [outils, "etroitG", "etroitG"],
      [this._conseilsHtml(), "largeD", "largeD"],
      [risques, "etroitG", "etroitG"],
    ]);
  }

  // Les alertes (téléphones, trace dans Home Assistant) et le conseil de l'IA (0.93.0).
  _conseilsHtml() {
    const n = this._donnees?.notifications;
    if (!n) return "";
    const cibles = Array.isArray(n.cibles) ? n.cibles : [];
    const noms = cibles.map((x) => x.nom || x.entity_id);
    const categories = n.categories || {};
    const categoriesActives = [
      ["arrosage_graines", "arrosage et graines"],
      ["securite_arrosage", "sécurité arrosage"],
      ["capteurs_meteo", "capteurs et météo"],
      ["tondeuse", "tondeuse"],
    ].filter(([cle]) => categories[cle] !== false).map(([, nom]) => nom);
    const alertes = n.alertes === false
      ? "Alertes coupées (Réglages → Installation)."
      : !categoriesActives.length
        ? "Aucune catégorie de notification n'est cochée."
        : noms.length
          ? `${esc(categoriesActives.join(", "))} : ${esc(noms.join(", "))} ${noms.length > 1 ? "sont prévenus" : "est prévenu"}. Une trace reste aussi dans Home Assistant.`
          : `${esc(categoriesActives.join(", "))} : les alertes restent dans Home Assistant. Sélectionner un appareil pour les recevoir également.`;
    const ia = n.ia_disponible
      ? `L'IA lit l'état du gazon et répond aux questions${n.ia_nom ? ` (${esc(n.ia_nom)})` : ""}. Elle ne commande rien.`
      : "Aucune IA dans Home Assistant : ajoute une intégration qui en fournit une (OpenAI, Google Gemini, Ollama…).";
    const occupe = this._commandesEnCours.has("envoyer_etat");
    return `<section class="section">
        <div class="section-tete"><h3>Conseils et alertes</h3></div>
        <ul class="liste-simple">
          <li class="${n.alertes === false ? "retient" : "ok"}"><ha-icon icon="${n.alertes === false ? "mdi:bell-off-outline" : "mdi:bell-ring-outline"}"></ha-icon><span>${alertes}</span></li>
          <li class="${n.ia_disponible ? "ok" : "retient"}"><ha-icon icon="mdi:robot-outline"></ha-icon><span>${ia}</span></li>
        </ul>
        <div class="rangee-boutons">
          <button class="bouton-plein" data-dialogue="conseil_ia" ${n.ia_disponible ? "" : "disabled"}><ha-icon icon="mdi:robot-outline"></ha-icon> Demander conseil à l'IA</button>
          ${noms.length ? `<button class="bouton-contour" data-commande="envoyer_etat" ${occupe ? "disabled" : ""}>${occupe ? "Un instant…" : "Envoyer l'état aux appareils configurés"}</button>` : ""}
        </div>
      </section>`;
  }

  // Le réservoir du sol : l'eau disponible, et le trait sous lequel l'arrosage se déclenche.
  _reservoirHtml(hydrique, bilan) {
    const utile = nombreOuNul(this._a("reserve", "reserve_utile_mm")) ?? 12;
    const actuelle = nombreOuNul(this._a("etat_hydrique", "reserve_actuelle_mm") ?? this._s("reserve"));
    const seuil = nombreOuNul(this._a("etat_hydrique", "reserve_minimale_mm") ?? this._a("reserve", "reserve_minimale_mm"));
    const manque = nombreOuNul(this._a("etat_hydrique", "depletion_mm"));
    if (actuelle === null) return "";
    return `<section class="section">
      <div class="section-tete"><h3>Le réservoir du sol</h3><p>${esc(libelleDe(ETATS_HYDRIQUES, hydrique))}. L'arrosage se déclenche quand l'eau passe sous le trait rouge.</p></div>
      <div class="reservoir">
        <div class="reservoir-rail" role="img" aria-label="${esc(mmFr(actuelle))} sur ${esc(mmFr(utile))}">
          <div class="reservoir-eau" style="width:${pourcent(actuelle, 0, utile)}%"></div>
          ${seuil !== null ? `<div class="reservoir-seuil" style="left:${pourcent(seuil, 0, utile)}%"></div>` : ""}
        </div>
        <div class="reservoir-legende">
          <span><b>${esc(mmFr(actuelle))}</b> sur ${esc(mmFr(utile))}</span>
          ${manque !== null ? `<span>il manque ${esc(mmFr(manque))} pour être plein</span>` : ""}
          ${seuil !== null ? `<span>trait rouge : ${esc(mmFr(seuil))}</span>` : ""}
        </div>
      </div>
      ${bilan ? `<p class="vide">${bilan}</p>` : ""}
    </section>`;
  }

  // ── Produits ──

  _ongletProduitsHtml(c) {
    const i = (k) => this._a("prochaine_intervention", k);
    const etat = String(this._s("prochaine_intervention") || "");
    const inactifs = ["", "unavailable", "unknown", "non_requis", "not_required", "none"];
    const recommande = etat === "recommande" || etat === "recommended";
    const score = nombreOuNul(i("score"));
    const bandeau = inactifs.includes(etat) ? "" : `<section class="produit-bandeau ${recommande ? "" : "a-preparer"}">
        <div class="maintenant-icone"><ha-icon icon="mdi:flask-outline"></ha-icon></div>
        <div style="min-width:0">
          <div class="maintenant-sur">Prochain produit</div>
          <h2>${esc(i("product_name") || i("produit_nom") || "—")}</h2>
          ${i("hint") ? `<p>${esc(i("hint"))}</p>` : ""}
          <span class="puce">${esc(libelleDe(ETATS_INTERVENTION, etat))}${score !== null && score > 0 ? ` · pertinence ${nombreFr(score, 0)} %` : ""}</span>
        </div>
      </section>`;
    const contraintes = Array.isArray(i("application_constraints")) && i("application_constraints").length
      ? i("application_constraints").map((x) => ({ texte: String(x.label || ""), classe: x.met ? "ok" : x.blocking ? "retient" : "" }))
      : String(i("reason") || "").split("·").map((x) => ({ texte: x.trim(), classe: "" }));
    const liste = contraintes.filter((x) => x.texte).map((x) => `<li class="${x.classe}"><ha-icon icon="${x.classe === "ok" ? "mdi:check-circle" : x.classe === "retient" ? "mdi:pause-circle" : "mdi:circle-small"}"></ha-icon><span>${esc(x.texte)}</span></li>`).join("");
    const conditions = liste || i("why_now") ? `<section class="section">
        <div class="section-tete"><h3>Les conditions</h3><p>Coche verte : c'est bon. Pause orange : c'est ce qui retient le produit.</p></div>
        ${liste ? `<ul class="liste-simple">${liste}</ul>` : ""}
        ${i("why_now") ? `<details class="pourquoi"><summary>Pourquoi maintenant ?</summary><p>${esc(i("why_now"))}</p></details>` : ""}
      </section>` : "";
    const resume = !bandeau && i("summary") ? `<section class="section"><p class="vide" style="padding-top:18px">${esc(i("summary"))}</p></section>` : "";
    const aucun = !bandeau && !i("summary") ? `<section class="section"><p class="vide" style="padding-top:18px">Aucun produit conseillé pour l'instant.</p></section>` : "";
    // Grande page : le conseil puis les fiches à gauche (leurs boutons ont besoin de largeur), le
    // carnet au milieu, les conditions à droite. Mesuré à 1 664 px : 1 136 px, contre 1 256 quand
    // le carnet prenait un couloir de 7 colonnes à côté d'une pile de trois cadres.
    // Page moyenne : les fiches ont besoin de largeur, le carnet passe à droite.
    return this._mosaique([
      [bandeau + resume + aucun, "gauche", "large"],
      [conditions, "droite", "large"],
      [this._historiqueProduitsHtml(), "milieu", "etroit"],
      [this._catalogueHtml(), "gauche", "large"],
    ]);
  }

  _historiqueProduitsHtml() {
    const historique = [...(this._a("derniere_application", "application_history") || [])].reverse();
    const boutons = `<div class="rangee-boutons">
      <button class="bouton-plein" data-dialogue="produit"><ha-icon icon="mdi:plus"></ha-icon> Déclarer un produit</button>
      ${historique.length ? `<button class="bouton-contour" data-dialogue="annuler_application">Annuler la dernière</button>` : ""}
    </div>`;
    if (!historique.length) {
      return `<section class="section"><div class="section-tete"><h3>Produits appliqués</h3></div><p class="vide">Rien n'est encore noté.</p>${boutons}</section>`;
    }
    const n = this._historiqueTout ? historique.length : 5;
    const fuseau = this._fuseau();
    const lignes = historique.slice(0, n).map((e) => {
      const j = jourDe(e.date_action || e.date, fuseau);
      const date = j ? `${deuxChiffres(j.jour)}/${deuxChiffres(j.mois)}/${j.annee}` : "";
      return `<li>
        <time>${esc(date)}</time>
        <div style="min-width:0">
          <b>${esc(e.libelle || e.produit || e.type || "—")}</b>
          <div class="meta">${[e.type, e.dose].filter(Boolean).map(esc).join(" · ")}</div>
          ${e.note ? `<button class="note-produit" data-bascule-note title="Toucher pour tout lire">${esc(e.note)}</button>` : ""}
        </div>
      </li>`;
    }).join("");
    return `<section class="section">
      <div class="section-tete"><h3>Produits appliqués · ${historique.length}</h3><p>Du plus récent au plus ancien. Sélectionner une note pour la lire en entier.</p></div>
      <ul class="historique">${lignes}</ul>
      ${historique.length > 5 ? `<div class="rangee-boutons"><button class="bouton-texte" data-action-locale="historique-tout">${this._historiqueTout ? "Réduire" : `Voir les ${historique.length - 5} plus anciennes`}</button></div>` : ""}
      ${boutons}
    </section>`;
  }

  // Les boutons n'apparaissent que si la page a reçu les fiches COMPLÈTES : sinon une
  // modification effacerait ce que le résumé du capteur ne montre pas.
  _catalogueHtml(type = null) {
    const tous = this._a("catalogue_produits", "products_summary") || [];
    const complets = Array.isArray(this._donnees?.produits) ? this._donnees.produits : [];
    const source = type && complets.length ? complets : tous;
    const produits = type
      ? source.filter((p) => String(p.type || "").trim().toLocaleLowerCase("fr") === type.toLocaleLowerCase("fr"))
      : source;
    const modifiable = Array.isArray(this._donnees?.produits) && this._estAdmin();
    const lignes = produits.map((p) => `<li>
      <b>${esc(p.nom || p.id)}</b>${type ? this._resumeProduitModeHtml(p) : `${esc([p.type, p.dose_conseillee].filter(Boolean).join(" · "))}${p.application_months_label ? `<br>${esc(p.application_months_label)}` : ""}${p.max_applications_per_year ? ` · ${esc(String(p.max_applications_per_year))} fois par an au plus` : ""}`}
      ${modifiable ? `<span class="catalogue-boutons">
        <button class="bouton-icone" data-dialogue="fiche_produit" data-produit="${esc(p.id)}" aria-label="Modifier ${esc(p.nom || p.id)}" title="Modifier la fiche"><ha-icon icon="mdi:pencil-outline"></ha-icon></button>
        <button class="bouton-icone" data-dialogue="retirer_produit" data-produit="${esc(p.id)}" aria-label="Retirer ${esc(p.nom || p.id)}" title="Retirer de la liste"><ha-icon icon="mdi:delete-outline"></ha-icon></button>
      </span>` : ""}
    </li>`).join("");
    if (!produits.length && !modifiable) return "";
    const titre = type ? `Produits · ${type}` : "Produits enregistrés";
    return `<section class="section">
      <div class="section-tete"><h3>${esc(titre)} · ${produits.length}</h3><p>${modifiable ? "Une fiche par produit peut être modifiée ou ajoutée." : "Une fiche est disponible pour chaque produit."}</p></div>
      ${produits.length ? `<ul class="catalogue ${type ? "catalogue-mode" : ""}">${lignes}</ul>` : `<p class="vide">Aucun produit pour l'instant.</p>`}
      ${modifiable ? `<div class="rangee-boutons"><button class="bouton-contour" data-dialogue="fiche_produit" ${type ? `data-mode="${esc(type)}"` : ""}><ha-icon icon="mdi:plus"></ha-icon> Ajouter un produit</button></div>` : ""}
    </section>`;
  }

  _resumeProduitModeHtml(f) {
    const application = f.application_type === "foliaire" ? "Foliaire" : f.application_type === "sol" || f.application_type === "racinaire" ? "Racinaire" : "Non précisé";
    const arrosage = f.application_requires_watering_after
      ? `${mmFr(nombreOuNul(f.application_post_watering_mm) ?? 0)} après l'application`
      : "Aucun arrosage après";
    const pilotage = MODES_ARROSAGE_PRODUIT[f.application_irrigation_mode] || "Selon la sorte";
    const attente = nombreOuNul(f.application_irrigation_delay_minutes);
    const blocage = nombreOuNul(f.application_irrigation_block_hours);
    const temperatureMin = nombreOuNul(f.temperature_min);
    const temperatureMax = nombreOuNul(f.temperature_max);
    const temperature = temperatureMin !== null || temperatureMax !== null
      ? `${temperatureMin !== null ? `${nombreFr(temperatureMin, 1)} °C` : "—"} à ${temperatureMax !== null ? `${nombreFr(temperatureMax, 1)} °C` : "—"}`
      : "Non précisée";
    const tonte = nombreOuNul(f.delai_avant_tonte_jours);
    const maximumAnnuel = nombreOuNul(f.max_applications_per_year);
    const rappel = nombreOuNul(f.reapplication_after_days);
    const frequence = [
      maximumAnnuel !== null ? `${nombreFr(maximumAnnuel, 0)} fois/an max.` : "",
      rappel !== null ? `${nombreFr(rappel, 0)} jours avant rappel` : "",
    ].filter(Boolean).join(" · ") || "Non précisée";
    const phases = Array.isArray(f.phase_compatible) && f.phase_compatible.length ? f.phase_compatible.join(", ") : "Toutes";
    const lignes = [
      ["Application", `${application}${f.dose_conseillee ? ` · ${f.dose_conseillee}` : ""}`],
      ["Arrosage", `${arrosage} · ${pilotage}`],
      ["Attente", `${attente !== null ? `${nombreFr(attente, 0)} min` : "0 min"}${blocage ? ` · blocage ${nombreFr(blocage, 1)} h` : ""}`],
      ["Température", temperature],
      ["Tonte", tonte !== null ? `${nombreFr(tonte, 0)} jours sans tondre` : "Aucun délai précisé"],
      ["Période", f.application_months_label || "Toute l'année"],
      ["Fréquence", frequence],
      ["Phases", phases],
    ];
    return `<dl class="parametres-produit">${lignes.map(([nom, valeur]) => `<div><dt>${esc(nom)}</dt><dd>${esc(valeur)}</dd></div>`).join("")}</dl>`;
  }

  // ── Fenêtres d'action ──

  _ouvrirDialogue(nom, { produit = null, entree = null, mode = null } = {}) {
    const objectif = nombreOuNul(this._s("objectif")) ?? 0;
    const etat = { nom };
    if (nom === "entree") {
      const ligne = this._sourceMeteo(entree);
      if (!ligne) return;
      Object.assign(etat, { cle: ligne.cle, choix: ligne.entity_id || "", recherche: "" });
    }
    if (nom === "arroser") etat.mm = objectif > 0 ? objectif : 3;
    if (nom === "produit" && produit) etat.produit = produit;
    if (nom === "mode") {
      const options = this._entite("mode")?.attributes?.options || Object.keys(MODES);
      etat.choix = mode && options.includes(mode) ? mode : this._s("mode") || "Normal";
      etat.direct = Boolean(mode && options.includes(mode));
    }
    if (nom === "fiche_produit" || nom === "retirer_produit") {
      const fiche = produit ? this._ficheProduit(produit) : null;
      // Une fiche introuvable ne s'édite pas : on la réécrirait à moitié.
      if (produit && !fiche) {
        this._afficherToast("Cette fiche n'est plus là. Recharge la page.", true);
        return;
      }
      etat.id = produit;
      etat.fiche = fiche ? structuredClone(fiche) : (mode ? { type: mode } : {});
    }
    this._dialogue = etat;
    this._fenetre.innerHTML = this._dialogueHtml();
    if (!this._fenetre.open) this._fenetre.showModal();
    // Le choix en cours plutôt que la recherche : sur téléphone, le clavier cacherait la liste.
    const premier = nom === "entree"
      ? this._fenetre.querySelector('[data-dlg="entite"]:checked') || this._fenetre.querySelector('[data-dlg="entite"]')
      : this._fenetre.querySelector("input:not([type=hidden]), select, [data-valider]");
    premier?.focus();
  }

  _fermerDialogue() {
    if (this._fenetre.open) this._fenetre.close();
    this._dialogue = null;
  }

  _redessinerDialogue() {
    if (!this._dialogue) return;
    const focus = this._fenetre.querySelector(":focus");
    const cle = focus?.dataset?.dlg || focus?.id;
    this._fenetre.innerHTML = this._dialogueHtml();
    if (cle) this._fenetre.querySelector(`[data-dlg="${cle}"], #${CSS.escape(cle)}`)?.focus();
  }

  _dialogueHtml() {
    const d = this._dialogue;
    if (!d) return "";
    const c = this._contexte();
    const aujourdhui = isoDuJour(c.maintenant);
    const champDate = (libelle = "Quand ?") => `<div class="champ"><label for="dlg-date">${libelle}</label><input id="dlg-date" type="date" value="${aujourdhui}" max="${aujourdhui}"></div>`;
    const cadre = ({ icone, genre = "", titre, corps, bouton, genreBouton = "", annuler = "Annuler", occupe = false }) => `
      <form method="dialog" data-formulaire="${d.nom}">
        <div class="dialogue-tete"><span class="action-icone ${genre}"><ha-icon icon="${icone}"></ha-icon></span><h2 id="titre-dialogue">${esc(titre)}</h2>
          <button type="button" class="bouton-rond" data-fermer aria-label="Fermer"><ha-icon icon="mdi:close"></ha-icon></button></div>
        <div class="dialogue-corps">${corps}</div>
        <div class="dialogue-pied">
          <button type="button" class="bouton-contour" data-fermer>${annuler}</button>
          <button type="button" class="bouton-plein ${genreBouton}" data-valider ${occupe ? "disabled" : ""}>${bouton}</button>
        </div>
      </form>`;

    if (d.nom === "arroser") {
      const objectif = nombreOuNul(this._s("objectif")) ?? 0;
      const reserve = nombreOuNul(this._a("reserve", "reserve_actuelle_mm") ?? this._s("reserve"));
      const utile = nombreOuNul(this._a("reserve", "reserve_utile_mm"));
      const motif = this._a("prochain_arrosage", "block_reason_label");
      const heure = partiesLocales(new Date(), this._fuseau()).minute;
      const raccourcis = [...new Set([objectif > 0 ? objectif : null, 2, 5, 8].filter((v) => v !== null))];
      const corps = `
        <p>L'arrosage part tout de suite, zone après zone. Il compte dans la réserve du sol.</p>
        <div class="champ"><span>Combien d'eau ?</span>
          <div class="dose">
            <button type="button" class="pas-btn" data-dlg="dose-moins" aria-label="Moins" ${d.mm <= 0.5 ? "disabled" : ""}><ha-icon icon="mdi:minus"></ha-icon></button>
            <output data-dose>${esc(mmFr(d.mm))}</output>
            <button type="button" class="pas-btn" data-dlg="dose-plus" aria-label="Plus" ${d.mm >= 30 ? "disabled" : ""}><ha-icon icon="mdi:plus"></ha-icon></button>
          </div>
          <div class="raccourcis">${raccourcis.map((v) => `<button type="button" class="petit-bouton" data-dlg="dose-${v}" data-mm="${v}">${v === objectif ? "Conseillé : " : ""}${esc(mmFr(v))}</button>`).join("")}</div>
        </div>
        <div class="plan-zones">${this._planZonesHtml(d.mm)}</div>
        ${reserve !== null && utile !== null ? `<p>Réserve du sol : ${esc(mmFr(reserve))} → <b>${esc(mmFr(Math.min(reserve + d.mm, utile)))}</b> sur ${esc(mmFr(utile))}.</p>` : ""}
        ${motif ? `<p class="note alerte"><ha-icon icon="mdi:information-outline"></ha-icon><span>L'arrosage automatique attend en ce moment (${esc(minuscule(premierePhrase(motif)))}). Un arrosage lancé ici passe outre.</span></p>` : ""}
        ${heure >= 10 * 60 && heure < 18 * 60 ? `<p class="note alerte"><ha-icon icon="mdi:weather-sunny-alert"></ha-icon><span>En plein soleil, une partie de l'eau s'évapore. Le petit matin est plus efficace.</span></p>` : ""}`;
      return cadre({ icone: "mdi:sprinkler-variant", genre: "eau", titre: "Arroser maintenant", corps, bouton: `Arroser ${esc(mmFr(d.mm))}`, genreBouton: "eau" });
    }

    if (d.nom === "arrose_main") {
      const corps = `
        <p>Un arrosage réalisé hors de Gazon Intelligent (tuyau, arrosoir) peut être noté ici afin que cette eau soit comptabilisée.</p>
        ${champDate()}
        <div class="champ"><label for="dlg-mm">Combien de millimètres ?</label><input id="dlg-mm" type="number" min="0" max="30" step="0.5" value="5" inputmode="decimal">
          <small>Un verre à fond plat posé dans la zone permet de mesurer ce débit.</small></div>`;
      return cadre({ icone: "mdi:watering-can-outline", genre: "eau", titre: "Déclarer un arrosage manuel", corps, bouton: "Noter l'arrosage", genreBouton: "eau" });
    }

    if (d.nom === "tondu") {
      const lame = nombreOuNul(this._s("hauteur_coupe_tondeuse"));
      const corps = `
        <p>La hauteur de l'herbe repart de la lame à partir de cette tonte.</p>
        ${champDate()}
        <div class="champ"><label for="dlg-lame">Hauteur de la lame (mm), si elle a changé</label><input id="dlg-lame" type="number" min="10" max="120" step="5" placeholder="${lame !== null ? esc(nombreFr(lame, 0)) : ""}" inputmode="numeric">
          <small>Laisser vide si la lame n'a pas été réglée${lame !== null ? ` (${esc(nombreFr(lame, 0))} mm)` : ""}.</small></div>`;
      return cadre({ icone: "mdi:robot-mower-outline", titre: "Déclarer une tonte", corps, bouton: "Noter la tonte" });
    }

    if (d.nom === "produit") {
      const produits = this._a("catalogue_produits", "products_summary") || [];
      if (!produits.length) {
        return cadre({ icone: "mdi:flask-outline", titre: "Déclarer un produit", bouton: "Fermer",
          corps: "<p>Aucun produit n'est encore enregistré. Ajouter d'abord sa fiche dans l'onglet Produits (« Ajouter un produit »).</p>" });
      }
      const choisi = d.produit || produits[0]?.id;
      const fiche = produits.find((p) => p.id === choisi) || produits[0];
      const corps = `
        <div class="champ"><label for="dlg-produit">Quel produit ?</label>
          <select id="dlg-produit" data-dlg="produit">${produits.map((p) => `<option value="${esc(p.id)}" ${p.id === fiche.id ? "selected" : ""}>${esc(p.nom || p.id)}</option>`).join("")}</select>
          <small>${esc([fiche.type, fiche.dose_conseillee ? `dose conseillée ${fiche.dose_conseillee}` : "", fiche.application_requires_watering_after ? "demande un arrosage après" : ""].filter(Boolean).join(" · "))}</small></div>
        ${champDate()}
        <div class="champ"><label for="dlg-note">Une note ? (facultatif)</label><textarea id="dlg-note" rows="3" placeholder="Par exemple : dose réelle, surface, météo…"></textarea></div>`;
      return cadre({ icone: "mdi:flask-outline", titre: "Déclarer un produit", corps, bouton: "Noter le produit" });
    }

    if (d.nom === "annuler_application") {
      const historique = this._a("derniere_application", "application_history") || [];
      const dernier = historique[historique.length - 1];
      const j = dernier ? jourDe(dernier.date_action || dernier.date, this._fuseau()) : null;
      const corps = dernier
        ? `<p>Ceci retire la dernière application notée : <b>${esc(dernier.libelle || dernier.produit || dernier.type)}</b>${j ? `, du ${esc(dateHumaine(isoDuJour(j), c.maintenant, this._fuseau()))}` : ""}.</p><p>À utiliser en cas d'erreur de saisie.</p>`
        : "<p>Il n'y a rien à annuler.</p>";
      return cadre({ icone: "mdi:delete-outline", genre: "danger", titre: "Annuler la dernière application", corps, bouton: "Oui, l'annuler", genreBouton: "danger" });
    }

    if (d.nom === "mode") {
      const options = this._entite("mode")?.attributes?.options || Object.keys(MODES);
      const actuel = this._s("mode");
      const avertissements = [];
      if (d.choix === "Normal" && actuel && actuel !== "Normal") avertissements.push("Revenir au mode Normal efface le suivi en cours (semis, traitement…).");
      if (d.choix === "Normal" && this._verrouSecuriteActif()) avertissements.push("Le verrou de sécurité de l'arrosage restera posé : il se lève séparément, après vérification des vannes.");
      if (d.choix === "Semis") avertissements.push("À choisir une fois le travail complet du sol terminé et les graines au sol : un arrosage des graines peut partir dès l'ouverture de leur fenêtre.");
      if (d.choix === "Sursemis") avertissements.push("À choisir une fois la scarification terminée et les graines au sol : un arrosage des graines peut partir dès l'ouverture de leur fenêtre.");
      if (d.choix === "Scarification") avertissements.push("Ce mode note une scarification seule. Il ne lance aucun programme de Semis ou de Sursemis.");
      if (d.direct) {
        const produit = ["Traitement", "Fertilisation", "Biostimulant", "Agent Mouillant", "Scarification"].includes(d.choix);
        const corps = `
          <div class="mode-raccourci actif mode-confirmation">
            <ha-icon icon="${esc(ICONES_MODES[d.choix] || "mdi:grass")}"></ha-icon>
            <span class="mode-raccourci-texte"><b>${esc(d.choix)}</b><small>${esc(MODES[d.choix] || "")}</small></span>
          </div>
          ${produit ? `<p>Pour enregistrer aussi le produit utilisé, passer plutôt par « Déclarer un produit ».</p>` : ""}
          ${avertissements.map((t) => `<p class="note alerte"><ha-icon icon="mdi:alert-outline"></ha-icon><span>${esc(t)}</span></p>`).join("")}`;
        return cadre({ icone: ICONES_MODES[d.choix] || "mdi:swap-horizontal", titre: `Passer en mode ${d.choix}`, corps,
          bouton: `Confirmer le mode ${d.choix}` });
      }
      const corps = `
        <p>Le mode indique à Gazon Intelligent ce qui arrive au gazon. Pour une application, utiliser de préférence « Déclarer un produit » afin de la noter en même temps.</p>
        <div class="choix-modes" role="radiogroup">${options.map((m) => `<label class="choix-mode"><input type="radio" name="mode" value="${esc(m)}" data-dlg="mode" ${m === d.choix ? "checked" : ""}><span><b>${esc(m)}${m === actuel ? " · en ce moment" : ""}</b><small>${esc(MODES[m] || "")}</small></span></label>`).join("")}</div>
        ${avertissements.map((t) => `<p class="note alerte"><ha-icon icon="mdi:alert-outline"></ha-icon><span>${esc(t)}</span></p>`).join("")}`;
      return cadre({ icone: "mdi:swap-horizontal", titre: "Changer de mode", corps, bouton: d.choix === actuel ? "Garder ce mode" : `Passer en ${esc(d.choix)}` });
    }

    if (d.nom === "normal") {
      const avertissement = this._verrouSecuriteActif()
        ? `<p class="note alerte"><ha-icon icon="mdi:shield-alert-outline"></ha-icon><span>Le verrou de sécurité restera posé. Il se lève séparément après avoir vérifié les vannes.</span></p>`
        : "";
      const corps = `<p>Le gazon est en mode <b>${esc(this._s("mode") || "—")}</b>. Revenir au mode Normal efface ce suivi : les arrosages et la tonte reprennent le rythme de tous les jours.</p>${avertissement}`;
      return cadre({ icone: "mdi:backup-restore", genre: "danger", titre: "Revenir au mode Normal", corps, bouton: "Revenir au mode Normal", genreBouton: "danger" });
    }

    if (d.nom === "deverrouiller") {
      const corps = `<p>Cette action doit être utilisée seulement après avoir vérifié physiquement que toutes les vannes sont fermées et que la pompe est arrêtée.</p>
        <p class="note alerte"><ha-icon icon="mdi:alert-outline"></ha-icon><span>La levée sera refusée si une zone est encore active. Le mode du gazon et le suivi Semis ou Sursemis sont conservés.</span></p>`;
      return cadre({ icone: "mdi:shield-check-outline", genre: "danger", titre: "Lever le verrou de sécurité", corps, bouton: "Confirmer la vérification et lever le verrou", genreBouton: "danger" });
    }

    if (d.nom === "reserve") {
      const actuelle = nombreOuNul(this._a("reserve", "reserve_stock_mm") ?? this._s("reserve"));
      const corps = `
        <p>Après une mesure dans le sol (au tournevis ou à la sonde), donne la vraie quantité d'eau. Le calcul repart de là.</p>
        <div class="champ"><label for="dlg-reserve">Eau dans le sol (mm)</label><input id="dlg-reserve" type="number" min="0" max="100" step="0.1" value="${actuelle !== null ? actuelle : 10}" inputmode="decimal">
          <small>En ce moment, le calcul dit ${actuelle !== null ? esc(mmFr(actuelle)) : "—"}.</small></div>
        <label class="case"><input id="dlg-figer" type="checkbox" checked><span>Garder cette valeur jusqu'à minuit
          <small>Coché, la réserve ne bouge plus aujourd'hui. Décoché, le calcul de la journée continue à partir de la valeur saisie.</small></span></label>`;
      return cadre({ icone: "mdi:cup-water", titre: "Recaler la réserve du sol", corps, bouton: "Recaler" });
    }

    if (d.nom === "fiche_produit") {
      return cadre({
        icone: d.id ? "mdi:pencil-outline" : "mdi:flask-plus-outline",
        titre: d.id ? `Modifier « ${d.fiche.nom || d.id} »` : "Ajouter un produit",
        corps: this._ficheProduitHtml(d),
        bouton: d.id ? "Enregistrer la fiche" : "Ajouter le produit",
      });
    }

    if (d.nom === "retirer_produit") {
      const corps = `<p>Retirer <b>${esc(d.fiche.nom || d.id)}</b> de la liste ?</p>
        <p>Les applications déjà notées restent dans le carnet. Pour réutiliser ce produit, une nouvelle fiche devra être créée.</p>`;
      return cadre({ icone: "mdi:delete-outline", genre: "danger", titre: "Retirer un produit", corps, bouton: "Oui, le retirer", genreBouton: "danger" });
    }

    if (d.nom === "entree") {
      const ligne = this._sourceMeteo(d.cle);
      if (!ligne) return "";
      const actuelle = ligne.entity_id || "";
      // Le refus en tête : en bas, il restait sous la liste, hors de vue.
      const corps = `
        ${d.erreur ? `<p class="note alerte" role="alert" data-erreur-entree><ha-icon icon="mdi:alert-circle-outline"></ha-icon><span>Pas enregistré : ${esc(d.erreur)}</span></p>` : ""}
        <p>${esc(ligne.apporte)} Sans elle : ${esc(minuscule(ligne.sans_elle))}</p>
        ${d.cle === "capteur_rosee" ? `<p class="note"><ha-icon icon="mdi:information-outline"></ha-icon><span>Un point de rosée est une température : branché ici, il ferait croire l'herbe toujours mouillée. Il n'est pas proposé.</span></p>` : ""}
        <div class="champ"><label for="dlg-recherche">Quelle entité ?</label>
          <input id="dlg-recherche" type="search" placeholder="Chercher par nom" value="${esc(d.recherche || "")}" autocomplete="off">
          <small>${esc(this._unitesAttendues(ligne))} Seules celles que l'intégration sait lire sont proposées.</small></div>
        <div class="choix-modes choix-entites" role="radiogroup" aria-label="${esc(ligne.titre)}" data-liste-entites>${this._choixEntitesHtml(d, ligne)}</div>
        <p class="note"><ha-icon icon="mdi:restart"></ha-icon><span>Le changement vaut dès le calcul suivant, et recharge souvent l'intégration : ses capteurs disparaissent alors quelques secondes. Jamais pendant un arrosage.</span></p>`;
      return cadre({
        icone: actuelle ? "mdi:swap-horizontal" : "mdi:power-plug-outline",
        titre: `${actuelle ? "Changer" : "Brancher"} : ${ligne.titre}`,
        corps,
        bouton: this._libelleEntree(d, actuelle),
        occupe: Boolean(d.enCours) || d.choix === actuelle,
      });
    }

    if (d.nom === "conseil_ia") {
      const telephones = (this._donnees?.notifications?.cibles || []).length > 0;
      const corps = `
        <p>L'IA lit l'état du gazon (phase, arrosages, réserve, météo, tonte) et répond. Elle ne lance aucune action. Chaque question compte auprès du fournisseur d'IA configuré.</p>
        <div class="champ"><label for="dlg-question">Question</label>
          <textarea id="dlg-question" rows="3" maxlength="1000" placeholder="Laisser vide pour obtenir un point sur la journée.">${esc(d.question || "")}</textarea>
          <div class="raccourcis questions">${QUESTIONS_IA.map((q, i) => `<button type="button" class="petit-bouton" data-dlg="question-${i}" data-question="${esc(q)}">${esc(q)}</button>`).join("")}</div></div>
        ${telephones ? `<label class="case"><input id="dlg-notifier" type="checkbox" ${d.notifier ? "checked" : ""}><span>Envoyer aussi la réponse aux appareils configurés</span></label>` : ""}
        ${d.enCours ? `<p class="note"><ha-icon icon="mdi:timer-sand"></ha-icon><span>L'IA réfléchit… Cela prend quelques secondes.</span></p>` : ""}
        ${d.erreur ? `<p class="note alerte" role="alert"><ha-icon icon="mdi:alert-circle-outline"></ha-icon><span>Ça n'a pas marché : ${esc(d.erreur)}</span></p>` : ""}
        ${d.reponse ? `<div class="reponse-ia" aria-live="polite"><small>${d.questionPosee ? `« ${esc(d.questionPosee)} »` : "Le point sur la journée"}</small>${String(d.reponse).split(/\n+/).filter((l) => l.trim()).map((l) => `<p>${esc(l)}</p>`).join("")}${
          d.envoi === "ok" ? `<small>Réponse envoyée aux appareils configurés.</small>` : d.envoi === "echec" ? `<small>La réponse n'a pu être envoyée à aucun appareil.</small>` : ""}</div>` : ""}`;
      return cadre({
        icone: "mdi:robot-outline", titre: "Demander conseil à l'IA", corps, annuler: "Fermer", occupe: d.enCours,
        bouton: d.enCours ? "Un instant…" : d.reponse ? "Demander à nouveau" : "Demander",
      });
    }

    if (d.nom === "auto" || d.nom === "coordination") {
      const cle = d.nom === "auto" ? "arrosage_automatique" : "coordination_tondeuse";
      const allume = this._valeurEntiteReelle(cle) === true;
      const textes = d.nom === "auto"
        ? { titre: `${allume ? "Couper" : "Allumer"} l'arrosage automatique`, icone: "mdi:autorenew",
          corps: allume ? "Gazon Intelligent ne lancera plus d'arrosage tout seul. Les recommandations continueront d'indiquer quand arroser." : "Gazon Intelligent pourra de nouveau lancer l'arrosage tout seul, quand le gazon en a besoin." }
        : { titre: `${allume ? "Ne plus attendre" : "Attendre"} la tondeuse`, icone: "mdi:robot-mower",
          corps: allume ? "L'arrosage ne regardera plus si la tondeuse est dehors." : "Les vannes resteront fermées tant que la tondeuse travaille ou rentre à sa base." };
      return cadre({ icone: textes.icone, titre: textes.titre, corps: `<p>${esc(textes.corps)}</p>`, bouton: allume ? "Couper" : "Allumer", genreBouton: allume ? "danger" : "" });
    }
    return "";
  }

  // Ce que le moteur fera de cette dose : les mêmes durées arrondies, et le découpage DU JOUR.
  _planZonesHtml(mm) {
    const zones = this._zonesAvecDebit();
    if (!zones.length) return `<p class="vide">Aucune zone n'a de débit réglé : rien ne peut partir.</p>`;
    const { passages, pauseS } = this._decoupageDuJour();
    const plan = planArrosage(mm, zones, passages, pauseS);
    if (!plan) return "";
    const fin = partiesLocales(new Date(Date.now() + plan.totalS * 1000), this._fuseau()).minute;
    const sansDebit = this._zones().filter((z) => !zones.some((x) => x.switch === z.switch)).map((z) => z.nom);
    return `${this._derouleHtml(plan, { depart: "tout de suite", fin: `fin vers ${heureFr(fin)}`, compact: true })}
      ${sansDebit.length ? `<p class="vide">Pas arrosée${sansDebit.length > 1 ? "s" : ""} (aucun débit réglé) : ${esc(sansDebit.join(", "))}.</p>` : ""}`;
  }

  async _validerDialogue() {
    const d = this._dialogue;
    if (!d) return;
    const f = this._fenetre;
    const val = (id) => f.querySelector(`#${id}`)?.value ?? "";
    const dateService = () => {
      const v = val("dlg-date");
      const m = v.match(/^(\d{4})-(\d{2})-(\d{2})$/);
      return m ? `${m[3]}/${m[2]}/${m[1]}` : undefined;
    };
    const entites = this._donnees.entites || {};
    if (d.nom === "conseil_ia") {
      await this._demanderConseil(d, f);
      return;
    }
    if (d.nom === "entree") {
      await this._changerEntree(d);
      return;
    }
    let appel = null;
    let message = "";
    if (d.nom === "arroser") {
      appel = ["gazon_intelligent", "start_manual_irrigation", { entity_id: entites.objectif, objectif_mm: d.mm }];
      message = `Arrosage de ${mmFr(d.mm)} lancé.`;
    } else if (d.nom === "arrose_main") {
      const mm = Number.parseFloat(val("dlg-mm"));
      if (!Number.isFinite(mm) || mm < 0 || mm > 30) {
        this._afficherToast("Sélectionner une quantité entre 0 et 30 mm.", true);
        return;
      }
      appel = ["gazon_intelligent", "declare_watering", { entity_id: entites.objectif, objectif_mm: mm, ...(dateService() ? { date_action: dateService() } : {}) }];
      message = `Arrosage de ${mmFr(mm)} noté.`;
    } else if (d.nom === "tondu") {
      const lame = Number.parseFloat(val("dlg-lame"));
      if (val("dlg-lame") !== "" && (!Number.isFinite(lame) || lame < 10 || lame > 120)) {
        this._afficherToast("La lame se règle entre 10 et 120 mm.", true);
        return;
      }
      appel = ["gazon_intelligent", "declare_mowing", {
        entity_id: entites.tonte_autorisee,
        ...(dateService() ? { date_action: dateService() } : {}),
        ...(Number.isFinite(lame) ? { hauteur_coupe_mm: lame } : {}),
      }];
      message = "Tonte notée.";
    } else if (d.nom === "produit") {
      const produits = this._a("catalogue_produits", "products_summary") || [];
      const fiche = produits.find((p) => p.id === val("dlg-produit"));
      if (!fiche) {
        this._fermerDialogue();
        return;
      }
      const note = val("dlg-note").trim();
      appel = ["gazon_intelligent", "declare_intervention", {
        entity_id: entites.prochaine_intervention, intervention: fiche.type, produit_id: fiche.id,
        ...(dateService() ? { date_action: dateService() } : {}), ...(note ? { note } : {}),
      }];
      message = `${fiche.nom || fiche.id} noté.`;
    } else if (d.nom === "annuler_application") {
      if (!(this._a("derniere_application", "application_history") || []).length) {
        this._fermerDialogue();
        return;
      }
      appel = ["gazon_intelligent", "remove_last_application", { entity_id: entites.prochaine_intervention }];
      message = "Dernière application annulée.";
    } else if (d.nom === "mode") {
      if (d.choix === this._s("mode")) {
        this._fermerDialogue();
        return;
      }
      appel = ["select", "select_option", { entity_id: entites.mode, option: d.choix }];
      message = `Le gazon passe en mode ${d.choix}.`;
    } else if (d.nom === "normal") {
      appel = ["gazon_intelligent", "reset_mode", { entity_id: entites.phase }];
      message = "Retour au mode Normal.";
    } else if (d.nom === "deverrouiller") {
      appel = ["gazon_intelligent", "clear_irrigation_safety_lock", { entity_id: entites.blocage_arrosage }];
      message = "Verrou de sécurité levé.";
    } else if (d.nom === "reserve") {
      const mm = Number.parseFloat(val("dlg-reserve"));
      if (!Number.isFinite(mm) || mm < 0 || mm > 100) {
        this._afficherToast("Sélectionner une valeur entre 0 et 100 mm.", true);
        return;
      }
      appel = ["gazon_intelligent", "recalibrate_reserve", { entity_id: entites.reserve, reserve_mm: mm, figer_la_journee: f.querySelector("#dlg-figer")?.checked !== false }];
      message = `Réserve recalée à ${mmFr(mm)}.`;
    } else if (d.nom === "fiche_produit") {
      const lu = this._lireFicheProduit(f, d);
      if (lu.erreur) {
        this._afficherToast(lu.erreur, true);
        return;
      }
      appel = ["gazon_intelligent", "register_product", { entity_id: entites.catalogue_produits, ...lu.donnees }];
      message = d.id ? `Fiche de ${lu.donnees.nom} enregistrée.` : `${lu.donnees.nom} ajouté aux produits.`;
    } else if (d.nom === "retirer_produit") {
      appel = ["gazon_intelligent", "remove_product", { entity_id: entites.catalogue_produits, product_id: d.id }];
      message = `${d.fiche.nom || d.id} retiré des produits.`;
    } else if (d.nom === "auto" || d.nom === "coordination") {
      const cle = d.nom === "auto" ? "arrosage_automatique" : "coordination_tondeuse";
      const allume = this._valeurEntiteReelle(cle) === true;
      appel = ["switch", allume ? "turn_off" : "turn_on", { entity_id: entites[cle] }];
      message = d.nom === "auto" ? `Arrosage automatique ${allume ? "coupé" : "allumé"}.` : `Attente de la tondeuse ${allume ? "coupée" : "allumée"}.`;
    }
    if (!appel) {
      this._fermerDialogue();
      return;
    }
    const bouton = f.querySelector("[data-valider]");
    if (bouton) {
      bouton.disabled = true;
      bouton.textContent = "Un instant…";
    }
    const ok = await this._service(...appel, message);
    if (ok && (d.nom === "fiche_produit" || d.nom === "retirer_produit")) await this._rechargerProduits();
    if (ok) this._fermerDialogue();
    else if (bouton) {
      bouton.disabled = false;
      this._redessinerDialogue();
    }
  }

  // La réponse de l'IA s'affiche dans la fenêtre : l'action rend son texte (`return_response`).
  async _demanderConseil(d, f) {
    if (d.enCours) return;
    if (!this._estAdmin()) {
      this._afficherToast("Seul un administrateur peut faire ça.", true);
      return;
    }
    d.question = f.querySelector("#dlg-question")?.value?.trim() ?? "";
    d.notifier = f.querySelector("#dlg-notifier")?.checked === true;
    d.enCours = true;
    d.erreur = null;
    this._redessinerDialogue();
    try {
      const retour = await this._hass.callWS({
        type: "call_service",
        domain: "gazon_intelligent",
        service: "ask_ai",
        service_data: {
          entity_id: (this._donnees.entites || {}).assistant,
          ...(d.question ? { question: d.question } : {}),
          notifier: d.notifier,
        },
        return_response: true,
      });
      if (this._dialogue !== d) return;
      const reponse = retour?.response || {};
      d.reponse = String(reponse.reponse || "").trim() || "L'IA n'a rien répondu.";
      d.questionPosee = d.question;
      // Dit DANS la fenêtre : un toast passerait sous elle, qui reste ouverte pour la lecture.
      d.envoi = d.notifier ? (Array.isArray(reponse.envoye_a) && reponse.envoye_a.length ? "ok" : "echec") : null;
    } catch (e) {
      console.error("Gazon Intelligent : échec du conseil IA", e);
      d.erreur = erreurLisible(e);
      this.dispatchEvent(new CustomEvent("haptic", { detail: "failure", bubbles: true, composed: true }));
    } finally {
      d.enCours = false;
      if (this._dialogue === d) this._redessinerDialogue();
    }
  }

  // ── Les fiches produit ──

  _ficheProduit(id) {
    return (this._donnees?.produits || []).find((p) => p.id === id) || null;
  }

  _ficheProduitHtml(d) {
    const f = d.fiche;
    const champ = (id, libelle, contenu, aide = "") => `<div class="champ"><label for="${id}">${libelle}</label>${contenu}${aide ? `<small>${aide}</small>` : ""}</div>`;
    const nombre = (id, valeur, min, max, pas, placeholder = "") => `<input id="${id}" type="number" min="${min}" max="${max}" step="${pas}" inputmode="decimal" value="${valeur ?? ""}" placeholder="${esc(placeholder)}">`;
    const options = (table, actuel, vide) => `${vide ? `<option value="">${esc(vide)}</option>` : ""}${Object.entries(table).map(([v, l]) => `<option value="${esc(v)}" ${v === actuel ? "selected" : ""}>${esc(l)}</option>`).join("")}`;
    const mois = new Set(Array.isArray(f.application_months) ? f.application_months : []);
    const phases = new Set(Array.isArray(f.phase_compatible) ? f.phase_compatible : []);
    const types = Object.fromEntries(TYPES_PRODUIT.map((x) => [x, x === "Agent Mouillant" ? "Agent mouillant" : x]));
    return `
      <p>${d.id ? "Change ce qui doit l'être : le reste de la fiche est gardé tel quel." : "Les premières questions suffisent. Le reste affine les conseils."}</p>
      ${champ("fp-nom", "Son nom", `<input id="fp-nom" type="text" value="${esc(f.nom || "")}" placeholder="Par exemple : Engrais d'automne" autocomplete="off">`,
        d.id ? `Identifiant : <code>${esc(d.id)}</code> (il ne change pas).` : "")}
      <div class="champs-deux">
        ${champ("fp-type", "Quelle sorte de produit ?", `<select id="fp-type">${options(types, f.type || "Fertilisation")}</select>`)}
        ${champ("fp-dose", "Quelle dose ?", `<input id="fp-dose" type="text" value="${esc(f.dose_conseillee || "")}" placeholder="30 g/m²">`)}
      </div>
      <label class="case"><input id="fp-arroser" type="checkbox" ${f.application_requires_watering_after ? "checked" : ""}><span>Il faut arroser après
        <small>Coché, Gazon Intelligent prévoit l'arrosage qui fait entrer le produit dans la terre.</small></span></label>
      ${champ("fp-arroser-mm", "Combien d'eau après ? (mm)", nombre("fp-arroser-mm", f.application_post_watering_mm, 0, 10, 0.1, "5"))}
      <details class="plus-de-details">
        <summary>Plus de détails</summary>
        <div class="champs-deux">
          ${champ("fp-max", "Combien de fois par an, au plus ?", nombre("fp-max", f.max_applications_per_year, 0, 3650, 1))}
          ${champ("fp-reapp", "Combien de jours avant d'en remettre ?", nombre("fp-reapp", f.reapplication_after_days, 0, 3650, 1))}
          ${champ("fp-tonte", "Combien de jours sans tondre après ?", nombre("fp-tonte", f.delai_avant_tonte_jours, 0, 3650, 1))}
          ${champ("fp-usage", "À quoi sert-il ?", `<select id="fp-usage">${options(USAGES_PRODUIT, f.usage_mode, "Usage inconnu")}</select>`)}
          ${champ("fp-tmin", "Température la plus basse (°C)", nombre("fp-tmin", f.temperature_min, -30, 60, 0.5))}
          ${champ("fp-tmax", "Température la plus haute (°C)", nombre("fp-tmax", f.temperature_max, -30, 60, 0.5))}
        </div>
        <div class="champ"><span>Quels mois ?</span>
          <div class="puces-choix">${INITIALES_MOIS.map((_, i) => `<label class="puce-choix"><input type="checkbox" data-fp-mois="${i + 1}" ${mois.has(i + 1) ? "checked" : ""}><span>${esc(MOIS_LONGS[i].slice(0, 4))}</span></label>`).join("")}</div>
          <small>Aucun mois coché : toute l'année.</small></div>
        <div class="champ"><span>Pour quel gazon ?</span>
          <div class="puces-choix">${Object.entries(PHASES_PRODUIT).map(([v, l]) => `<label class="puce-choix"><input type="checkbox" data-fp-phase="${esc(v)}" ${phases.has(v) ? "checked" : ""}><span>${esc(l)}</span></label>`).join("")}</div></div>
        <div class="champs-deux">
          ${champ("fp-app-type", "Où va-t-il ?", `<select id="fp-app-type">${options({ sol: "Sur la terre", foliaire: "Sur les feuilles" }, f.application_type, "Selon la sorte")}</select>`)}
          ${champ("fp-mode", "L'arrosage d'après se lance…", `<select id="fp-mode">${options(MODES_ARROSAGE_PRODUIT, f.application_irrigation_mode, "Selon la sorte")}</select>`)}
          ${champ("fp-delai", "Attendre avant cet arrosage (min)", nombre("fp-delai", f.application_irrigation_delay_minutes, 0, 1440, 1))}
          ${champ("fp-blocage", "Pas d'arrosage pendant (h)", nombre("fp-blocage", f.application_irrigation_block_hours, 0, 72, 1))}
        </div>
        ${champ("fp-etiquette", "Ce que dit l'étiquette", `<textarea id="fp-etiquette" rows="2">${esc(f.application_label_notes || "")}</textarea>`)}
        ${champ("fp-note", "Note", `<textarea id="fp-note" rows="3">${esc(f.note || "")}</textarea>`)}
      </details>`;
  }

  // Relit le formulaire PAR-DESSUS la fiche complète : un champ absent du formulaire reste intact.
  _lireFicheProduit(fenetre, d) {
    const val = (id) => fenetre.querySelector(`#${id}`)?.value?.trim() ?? "";
    const nom = val("fp-nom");
    if (!nom) return { erreur: "Donne un nom au produit." };
    const id = d.id || idProduit(nom);
    if (!id) return { erreur: "Ce nom ne donne pas d'identifiant : ajouter une lettre ou un chiffre." };
    if (!d.id && this._ficheProduit(id)) return { erreur: `« ${nom} » existe déjà : modifie sa fiche plutôt.` };
    const nombres = [
      ["application_post_watering_mm", "fp-arroser-mm", 0, 10, "L'eau après : entre 0 et 10 mm."],
      ["max_applications_per_year", "fp-max", 0, 3650, "Le nombre par an : entre 0 et 3 650."],
      ["reapplication_after_days", "fp-reapp", 0, 3650, "Les jours avant d'en remettre : entre 0 et 3 650."],
      ["delai_avant_tonte_jours", "fp-tonte", 0, 3650, "Les jours sans tondre : entre 0 et 3 650."],
      ["temperature_min", "fp-tmin", -30, 60, "La température : entre -30 et 60 °C."],
      ["temperature_max", "fp-tmax", -30, 60, "La température : entre -30 et 60 °C."],
      ["application_irrigation_delay_minutes", "fp-delai", 0, 1440, "L'attente : entre 0 et 1 440 minutes."],
      ["application_irrigation_block_hours", "fp-blocage", 0, 72, "La pause d'arrosage : entre 0 et 72 heures."],
    ];
    const donnees = {};
    for (const cle of CHAMPS_PRODUIT) {
      if (d.fiche[cle] !== undefined && d.fiche[cle] !== null && d.fiche[cle] !== "") donnees[cle] = d.fiche[cle];
    }
    for (const [cle, id_, min, max, erreur] of nombres) {
      const brut = val(id_);
      if (brut === "") {
        delete donnees[cle];
        continue;
      }
      const n = Number(brut.replace(",", "."));
      if (!Number.isFinite(n) || n < min || n > max) return { erreur };
      donnees[cle] = ["max_applications_per_year", "reapplication_after_days", "delai_avant_tonte_jours"].includes(cle) ? Math.round(n) : n;
    }
    if (donnees.temperature_min !== undefined && donnees.temperature_max !== undefined && donnees.temperature_min > donnees.temperature_max) {
      return { erreur: "La température la plus basse doit être sous la plus haute." };
    }
    const texte = (cle, id_) => {
      const v = val(id_);
      if (v) donnees[cle] = v;
      else delete donnees[cle];
    };
    donnees.nom = nom;
    donnees.type = val("fp-type") || "Fertilisation";
    texte("dose_conseillee", "fp-dose");
    texte("usage_mode", "fp-usage");
    texte("application_type", "fp-app-type");
    texte("application_irrigation_mode", "fp-mode");
    texte("application_label_notes", "fp-etiquette");
    texte("note", "fp-note");
    donnees.application_requires_watering_after = fenetre.querySelector("#fp-arroser")?.checked === true;
    const mois = [...fenetre.querySelectorAll("[data-fp-mois]:checked")].map((x) => Number(x.dataset.fpMois));
    if (mois.length) donnees.application_months = mois;
    else delete donnees.application_months;
    // L'ordre d'origine est gardé : une fiche relue puis enregistrée telle quelle ne change pas.
    const cochees = [...fenetre.querySelectorAll("[data-fp-phase]:checked")].map((x) => x.dataset.fpPhase);
    const avant = Array.isArray(d.fiche.phase_compatible) ? d.fiche.phase_compatible : [];
    const phases = [...avant.filter((x) => cochees.includes(x)), ...cochees.filter((x) => !avant.includes(x))];
    if (phases.length) donnees.phase_compatible = phases;
    else delete donnees.phase_compatible;
    return { donnees: { product_id: id, ...donnees } };
  }

  // Après un ajout ou un retrait : les fiches complètes, relues sans toucher aux brouillons.
  async _rechargerProduits() {
    try {
      const message = { type: WS_LIRE, entry_id: this._donnees.entry_id };
      const donnees = await this._hass.callWS(message);
      this._donnees = { ...this._donnees, produits: donnees.produits };
    } catch (e) {
      console.warn("Gazon Intelligent : fiches produit illisibles", e);
    }
    this._rendreQuandLibre();
  }

  async _service(domaine, service, donnees, message) {
    if (!this._estAdmin()) {
      this._afficherToast("Seul un administrateur peut faire ça.", true);
      return false;
    }
    try {
      // 5ᵉ argument à `false` : Home Assistant afficherait sinon SON message d'échec (générique,
      // en anglais) en plus du nôtre. Relu dans le frontend servi (20260826.7).
      await this._hass.callService(domaine, service, donnees, undefined, false);
      if (message && this.isConnected) this._afficherToast(message);
      return true;
    } catch (e) {
      console.error(`Gazon Intelligent : échec de ${domaine}.${service}`, donnees, e);
      await this._signalerEchec(e);
      return false;
    }
  }

  // Ce que faisait le message natif qu'on a coupé (même traitement que la carte 0.30.1) : le
  // texte traduit quand l'erreur porte une clé, la vibration d'échec, et l'affichage même quand
  // la page n'est plus à l'écran (l'arrêt différé du bouton « 5 min » peut échouer plus tard).
  async _signalerEchec(e) {
    let detail = "";
    try {
      if (e?.translation_domain && e?.translation_key && this._hass?.loadBackendTranslation) {
        const localize = await this._hass.loadBackendTranslation("exceptions", e.translation_domain);
        detail = localize(`component.${e.translation_domain}.exceptions.${e.translation_key}.message`, e.translation_placeholders) || "";
      }
    } catch {
      // Repli sur le message brut.
    }
    const texte = `Ça n'a pas marché : ${detail || erreurLisible(e)}`;
    const source = this.isConnected ? this : (this.ownerDocument?.querySelector("home-assistant") || this);
    const emettre = (type, contenu) => source.dispatchEvent(new CustomEvent(type, { detail: contenu, bubbles: true, composed: true }));
    emettre("haptic", "failure");
    if (this.isConnected) this._afficherToast(texte, true);
    else emettre("hass-notification", { message: texte, duration: 10000 });
  }

  // Commandes immédiates (sans fenêtre) : arrêt d'urgence, vannes, pompe. Le bouton accuse
  // réception tout de suite, puis se libère au retour de Home Assistant.
  async _commande(nom, bouton) {
    const cle = nom.startsWith("zone-") ? `zone-${bouton?.dataset.switch}` : nom;
    if (this._commandesEnCours.has(cle)) return;
    const entites = this._donnees.entites || {};
    const pompe = this._donnees.pompe;
    const id = bouton?.dataset.switch;
    this._commandesEnCours.add(cle);
    this._rendre();
    try {
      if (nom === "arreter") {
        // Un arrêt d'urgence ne demande pas « êtes-vous sûr ? ». L'intégration ferme la vanne,
        // compte l'eau déjà versée et libère le cycle.
        if (this._sessionActive()) {
          await this._service("gazon_intelligent", "stop_irrigation", { entity_id: entites.objectif, raison: "Arrêt depuis la page Gazon." }, "Arrosage arrêté.");
        } else {
          const ouvertes = this._zones().filter((z) => this._zoneActive(z)).map((z) => z.switch);
          if (ouvertes.length) await this._service("switch", "turn_off", { entity_id: ouvertes }, "Vannes fermées.");
        }
      } else if (nom === "zone-marche") {
        if (pompe) await this._service("switch", "turn_on", { entity_id: pompe });
        await this._service("switch", "turn_on", { entity_id: id }, "Vanne ouverte.");
      } else if (nom === "zone-5min") {
        await this._service("gazon_intelligent", "run_zone_for_duration", {
          entity_id: entites.objectif,
          zone_entity_id: id,
          duration_minutes: 5,
        }, "Vanne ouverte pour 5 minutes. Home Assistant la refermera automatiquement.");
      } else if (nom === "zone-arret") {
        // Une zone temporisée appartient au moteur persistant : l'arrêter par son service
        // annule aussi la reprise après redémarrage et coupe la pompe qu'il a démarrée.
        await this._service("gazon_intelligent", "stop_irrigation", {
          entity_id: entites.objectif,
          raison: "Arrêt de la zone depuis la page Gazon.",
        });
        await this._service("switch", "turn_off", { entity_id: id }, "Vanne fermée.");
      } else if (nom === "envoyer_etat") {
        await this._service("gazon_intelligent", "send_notification", { entity_id: entites.assistant }, "État du gazon envoyé aux appareils configurés.");
      } else if (nom === "pompe-marche" || nom === "pompe-arret") {
        await this._service("switch", nom === "pompe-marche" ? "turn_on" : "turn_off", { entity_id: pompe }, nom === "pompe-marche" ? "Pompe en marche." : "Pompe arrêtée.");
      }
    } finally {
      // Le retour d'état arrive juste après : on garde l'accusé de réception un court instant.
      setTimeout(() => {
        this._commandesEnCours.delete(cle);
        this._rendreQuandLibre();
      }, 1200);
    }
  }

  // ── Onglet « Entités » : toutes les liaisons externes au même endroit ──

  _entitesHtml() {
    const annulables = ["cibles", "ia"].filter((cle) => cle in this._brouillonAlertes).length
      + (this._brouillonPompe !== undefined ? 1 : 0)
      + (this._brouillonGarageTondeuse !== undefined ? 1 : 0);
    const cases = [
      [this._liaisonsMaterielHtml("arrosage"), "tout", "tout"],
      [this._liaisonsMaterielHtml("tondeuse"), "tout", "tout"],
      [this._meteoEntreesHtml(true), "tout", "tout"],
      [this._pompeReglageHtml(), "gauche", "large"],
      [this._garageTondeuseHtml(true), "droite", "etroit"],
      [this._notificationsEntitesHtml(), "tout", "tout"],
    ];
    return `<div class="intro-onglet">
        <p>${esc(ONGLET_ENTITES.phrase)} Changer une liaison ne renomme ni ne supprime l'entité Home Assistant : seule la source utilisée par ce gazon change.</p>
        <button class="bouton-texte" data-action="annuler-entites" ${annulables ? "" : "disabled"}><ha-icon icon="mdi:undo"></ha-icon>Annuler les changements en attente</button>
      </div>
      <p class="note alerte"><ha-icon icon="mdi:alert-outline"></ha-icon><span>Réglage sensible : les vannes et la tondeuse peuvent commander du matériel réel. L'intégration vérifie le type d'entité et refuse tout changement pendant un arrosage.</span></p>
      <div class="programme-reglages entites-reglages">${cases.map(([html, largeur]) =>
        `<div class="${largeur === "tout" ? "reglage-tout" : ""}">${html}</div>`).join("")}</div>`;
  }

  _liaisonsMaterielHtml(groupe) {
    const lignes = (this._donnees?.liaisons_materiel || []).filter((l) => l.groupe === groupe);
    if (!lignes.length) return "";
    const titres = {
      arrosage: ["Vannes d'arrosage", "Chaque zone doit pointer vers son propre interrupteur. Une zone sans débit reste inactive."],
      tondeuse: ["Tondeuse et ses signaux", "La tondeuse principale est prioritaire. Les signaux facultatifs complètent ses attributs quand le constructeur les publie séparément."],
    };
    const [titre, phrase] = titres[groupe];
    const corps = `<div class="lignes">${lignes.map((l) => {
        const etat = l.entity_id ? this._hass.states[l.entity_id] : null;
        const statut = !l.entity_id ? "non branchée" : !etat ? "introuvable" : valeurEtat(etat);
        return `<div class="ligne compacte" data-cle="${esc(l.cle)}">
          <div class="ligne-tete"><span class="ligne-icone"><ha-icon icon="${groupe === "arrosage" ? "mdi:valve" : "mdi:robot-mower-outline"}"></ha-icon></span>
            <div class="ligne-textes"><h4>${esc(l.titre)}</h4><p>${esc(l.apporte)} ${l.entity_id ? `<code>${esc(l.entity_id)}</code>` : `Sans elle : ${esc(minuscule(l.sans_elle))}`}</p></div>
            ${this._estAdmin() ? `<button class="petit-bouton" data-dialogue="entree" data-entree="${esc(l.cle)}"><ha-icon icon="${l.entity_id ? "mdi:swap-horizontal" : "mdi:power-plug-outline"}"></ha-icon>${l.entity_id ? "Changer" : "Brancher"}</button>` : ""}
          </div><p class="etat-bascule">État : ${esc(statut)}</p>
        </div>`;
      }).join("")}</div>`;
    return this._sectionReglageHtml({
      titre,
      phrase,
      icone: groupe === "arrosage" ? "mdi:valve" : "mdi:robot-mower-outline",
      corps,
      attributs: `data-liaisons-materiel="${esc(groupe)}"`,
    });
  }

  // ── Onglet « Installation » ──

  _installationHtml() {
    const entites = this._donnees.entites || {};
    // Une carte par groupe (arrosage, tondeuse, capteurs, notifications) : un en-tête visible
    // avant chaque paquet, plutôt qu'une suite de cartes sans repère commun.
    const parGroupe = new Map(GROUPES_INSTALLATION.map((g) => [g.cle, []]));
    for (const s of INSTALLATION) {
      const lignes = s.lignes.filter((l) => entites[l.cle] && this._entite(l.cle));
      if (!lignes.length) continue;
      parGroupe.get(s.groupe).push([this._sectionReglageHtml({
        titre: s.titre,
        phrase: s.phrase,
        icone: lignes[0]?.icone || "mdi:tune-variant",
        cles: lignes.map((l) => l.cle),
        corps: `<div class="lignes">${lignes.map((l) => this._ligneEntiteHtml(l)).join("")}</div>`,
      }), ...s.place]);
    }
    for (const c of (this._registre.choix || []).filter((c) => c.cle === "type_sol")) {
      parGroupe.get("arrosage").push([this._choixHtml(c), "droite", "etroit"]);
    }
    if (this._reglage("surface_gazon_m2")) {
      const reglagesSurface = this._sectionHtml({
        titre: "Consommation d'eau estimée",
        phrase: "La surface totale du gazon sert à convertir les arrosages en litres estimés.",
        cles: ["surface_gazon_m2"],
      });
      parGroupe.get("arrosage").push([reglagesSurface, "droite", "etroit"]);
    }
    const pilotage = (this._registre.choix || []).find((c) => c.cle === "pilotage_tondeuse");
    if (pilotage) parGroupe.get("tondeuse").push([this._choixHtml(pilotage), "tout", "tout"]);
    const creneauxDepart = (this._registre.choix || []).find((c) => c.cle === "tondeuse_creneaux_depart");
    if (creneauxDepart) parGroupe.get("tondeuse").push([this._choixHtml(creneauxDepart), "tout", "tout"]);
    const reglagesPilotage = this._sectionHtml({
      titre: "Sécurités du pilotage",
      phrase: "Ces seuils protègent les commandes automatiques de la tondeuse.",
      cles: ["tondeuse_pilotage_batterie_min", "tondeuse_pilotage_delai_commandes"],
    });
    parGroupe.get("tondeuse").push([reglagesPilotage, "milieu", "large"], [this._garageTondeuseHtml(), "droite", "etroit"]);
    parGroupe.get("notifications").push([this._alertesReglagesHtml(), "tout", "tout"]);

    const cases = [];
    for (const g of GROUPES_INSTALLATION) {
      const contenu = parGroupe.get(g.cle).filter(([html]) => String(html || "").trim());
      if (!contenu.length) continue;
      cases.push([`<div class="groupe-installation"><ha-icon icon="${g.icone}"></ha-icon><h2>${esc(g.titre)}</h2></div>`, "tout", "tout"]);
      cases.push(...contenu);
    }
    const mosaique = `<div class="programme-reglages installation-reglages">${cases.map(([html, largeur]) =>
      `<div class="${largeur === "tout" ? "reglage-tout" : ""}">${html}</div>`).join("")}</div>`;
    const annulables = Object.keys(this._brouillonEntites).length + Object.keys(this._brouillonChoix).length
      + Object.keys(this._brouillonAlertes).filter((cle) => !["cibles", "ia"].includes(cle)).length
      + Object.keys(this._brouillon).filter((cle) => this._reglage(cle)?.groupe === "installation").length;
    return `<div class="intro-onglet">
        <p>${esc(ONGLET_INSTALLATION.phrase)} Les branchements vers Home Assistant sont regroupés dans l'onglet « Entités ».</p>
        <button class="bouton-texte" data-action="annuler-installation" ${annulables ? "" : "disabled"}><ha-icon icon="mdi:undo"></ha-icon>Annuler les changements</button>
      </div>
      ${mosaique || `<div class="etat-page"><p>Aucune entité trouvée pour cette installation.</p></div>`}`;
  }

  // ── La pompe (0.94.0) : écrite dans les options de l'entrée, comme la terre ──

  _changerPompe(valeur) {
    const enregistree = this._donnees?.pompe_choix?.choisie || "";
    this._brouillonPompe = valeur === enregistree ? undefined : valeur;
  }

  _pompeReglageHtml() {
    const c = this._donnees?.pompe_choix;
    if (!c) return "";
    const lecture = !this._estAdmin();
    const change = this._brouillonPompe !== undefined;
    const choisie = change ? this._brouillonPompe : c.choisie || "";
    const interrupteurs = Array.isArray(c.interrupteurs) ? c.interrupteurs : [];
    const proposees = interrupteurs.filter((i) => i.proposee);
    const autres = interrupteurs.filter((i) => !i.proposee);
    const option = (i) => `<option value="${esc(i.entity_id)}" ${i.entity_id === choisie ? "selected" : ""}>${esc(i.nom)}</option>`;
    // Une pompe choisie puis retirée de Home Assistant reste visible : on peut la remplacer.
    const perdue = choisie && !interrupteurs.some((i) => i.entity_id === choisie)
      ? `<option value="${esc(choisie)}" selected>${esc(choisie)} (introuvable)</option>` : "";
    const etat = choisie ? this._hass.states[choisie] : null;
    const texteEtat = !choisie ? "Aucune : la page n'en montre pas."
      : !etat ? "Introuvable dans Home Assistant."
      : `En ce moment : ${etat.state === "on" ? "en marche" : etat.state === "off" ? "arrêtée" : valeurEtat(etat)}.`;
    const corps = `<div class="lignes"><div class="ligne ${change ? "change" : ""}" data-cle="pompe">
        ${change ? `<span class="a-enregistrer">à enregistrer</span>` : ""}
        <div class="ligne-tete">
          <span class="ligne-icone"><ha-icon icon="mdi:pump"></ha-icon></span>
          <div class="ligne-textes"><h4>Quel interrupteur allume la pompe ?</h4><p>${esc(texteEtat)}</p></div>
        </div>
        <div class="champ champ-pompe"><select data-role="pompe" aria-label="Interrupteur de la pompe" ${lecture ? "disabled" : ""}>
          <option value="" ${choisie ? "" : "selected"}>Aucune pompe</option>
          ${perdue}
          ${proposees.length ? `<optgroup label="Leur nom parle d'une pompe">${proposees.map(option).join("")}</optgroup>` : ""}
          ${autres.length ? `<optgroup label="Les autres interrupteurs">${autres.map(option).join("")}</optgroup>` : ""}
        </select></div>
      </div></div>`;
    return this._sectionReglageHtml({
      titre: "Pompe",
      phrase: "L'intégration ne la pilote pas : la page la montre et la commande avec les vannes.",
      icone: "mdi:pump",
      corps,
      attributs: 'data-pompe="1"',
      ouverte: change,
    });
  }

  _changerGarageTondeuse(valeur) {
    const enregistree = this._donnees?.garage_tondeuse?.choisie || "";
    this._brouillonGarageTondeuse = valeur === enregistree ? undefined : valeur;
  }

  _garageTondeuseHtml(choixSeulement = false) {
    const c = this._donnees?.garage_tondeuse;
    if (!c) return "";
    const lecture = !this._estAdmin();
    const change = this._brouillonGarageTondeuse !== undefined;
    const choisie = change ? this._brouillonGarageTondeuse : c.choisie || "";
    const volets = Array.isArray(c.volets) ? c.volets : [];
    const option = (v) => `<option value="${esc(v.entity_id)}" ${v.entity_id === choisie ? "selected" : ""}>${esc(v.nom)}</option>`;
    const perdue = choisie && !volets.some((v) => v.entity_id === choisie)
      ? `<option value="${esc(choisie)}" selected>${esc(choisie)} (introuvable)</option>` : "";
    const choix = `<div class="lignes"><div class="ligne ${change ? "change" : ""}" data-cle="garage-tondeuse">
        ${change ? `<span class="a-enregistrer">à enregistrer</span>` : ""}
        <div class="ligne-tete">
          <span class="ligne-icone"><ha-icon icon="mdi:garage"></ha-icon></span>
          <div class="ligne-textes"><h4>Quel volet protège le passage de la tondeuse ?</h4><p>Le départ attend son ouverture. Il ne se ferme qu'après une rentrée confirmée.</p></div>
        </div>
        <div class="champ champ-pompe"><select data-role="garage-tondeuse" aria-label="Volet du garage de la tondeuse" ${lecture ? "disabled" : ""}>
          <option value="" ${choisie ? "" : "selected"}>Aucun volet</option>
          ${perdue}${volets.map(option).join("")}
        </select></div>
        ${choisie ? this._etatGarageTondeuseHtml(choisie) : ""}
        <p class="note alerte"><ha-icon icon="mdi:alert-outline"></ha-icon><span>Réglage sensible : en cas d'état inconnu, la tondeuse ne démarre pas et le volet ne se ferme pas.</span></p>
      </div></div>`;
    if (choixSeulement) return this._sectionReglageHtml({
      titre: "Garage de la tondeuse",
      phrase: "Facultatif. Sans volet choisi, cette protection reste entièrement inactive.",
      icone: "mdi:garage-variant",
      corps: choix,
      attributs: 'data-garage-tondeuse="1"',
      ouverte: change,
    });
    const scenario = (titre, icone, resume, cles) => {
      const ouvert = cles.some((cle) => Object.hasOwn(this._brouillon, cle));
      return `<details class="garage-groupe" data-garage-groupe="${esc(titre)}" ${!this._narrow || ouvert ? "open" : ""}>
        <summary>
          <span class="garage-scenario-icone"><ha-icon icon="${icone}"></ha-icon></span>
          <span class="garage-scenario-texte"><b>${esc(titre)}</b><small>${esc(resume)}</small></span>
          <ha-icon class="garage-chevron" icon="mdi:chevron-down"></ha-icon>
        </summary>
        <div class="lignes">${cles.map((cle) => this._ligneHtml(this._reglage(cle))).join("")}</div>
      </details>`;
    };
    const ouvertureAuto = this._valeur("tondeuse_garage_ouvrir_avant_depart") === true;
    const retourAuto = this._valeur("tondeuse_garage_ouvrir_pour_retour") === true;
    const fermetureAuto = this._valeur("tondeuse_garage_fermer_apres_retour") === true;
    const avance = nombreFr(this._valeur("tondeuse_garage_avance_ouverture"), 3);
    const ouvertureMin = nombreFr(this._valeur("tondeuse_garage_ouverture_min"), 3);
    const fermeture = nombreFr(this._valeur("tondeuse_garage_delai_fermeture"), 3);
    const phrase = choisie
      ? `Le passage est protégé par ${volets.find((v) => v.entity_id === choisie)?.nom || choisie}. Chaque étape reste indépendante.`
      : "Aucun volet n'est branché.";
    const corps = `${choisie ? this._etatGarageTondeuseHtml(choisie) : ""}
      ${choisie ? `<div class="garage-reglages">
        ${scenario("Avant le départ", "mdi:garage-open-variant", `${ouvertureAuto ? "Ouverture automatique" : "Ouverture manuelle"} · passage à ${ouvertureMin} % · attente ${avance} min`, [
          "tondeuse_garage_ouvrir_avant_depart",
          "tondeuse_garage_ouverture_min",
          "tondeuse_garage_avance_ouverture",
        ])}
        ${scenario("Au retour", "mdi:home-import-outline", `${retourAuto ? "Ouverture automatique" : "Ouverture manuelle"} · ${fermetureAuto ? `fermeture après ${fermeture} min` : "reste ouvert"}`, [
          "tondeuse_garage_ouvrir_pour_retour",
          "tondeuse_garage_fermer_apres_retour",
          "tondeuse_garage_delai_fermeture",
        ])}
      </div>` : `<p class="note"><ha-icon icon="mdi:information-outline"></ha-icon><span>Sélectionner un volet dans Réglages → Entités pour afficher ses automatismes et ses délais.</span></p>`}`;
    return this._sectionReglageHtml({
      titre: "Garage de la tondeuse",
      phrase,
      icone: "mdi:garage-variant",
      corps,
      attributs: 'data-garage-tondeuse="1"',
      ouverte: change,
    });
  }

  _etatGarageTondeuseHtml(entityId) {
    const etat = this._hass.states[entityId];
    if (!etat) {
      return `<div class="etat-garage"><span>${esc(entityId)}</span><span class="statut retient"><ha-icon icon="mdi:help-circle-outline"></ha-icon>introuvable</span></div>`;
    }
    const brut = String(etat.state || "").toLowerCase();
    const etats = {
      open: ["ok", "mdi:garage-open-variant", "ouvert"],
      opening: ["retient", "mdi:garage-alert-variant", "ouverture en cours"],
      closed: ["retient", "mdi:garage-variant", "fermé"],
      closing: ["retient", "mdi:garage-alert-variant", "fermeture en cours"],
      unavailable: ["retient", "mdi:alert-outline", "indisponible"],
      unknown: ["retient", "mdi:alert-outline", "état inconnu"],
    };
    const [ton, icone, libelle] = etats[brut] || ["retient", "mdi:garage-alert-variant", valeurEtat(etat)];
    const nom = etat.attributes?.friendly_name || entityId;
    const position = Number(etat.attributes?.current_position);
    const libelleComplet = Number.isFinite(position) && ["open", "opening", "closing"].includes(brut)
      ? `${libelle} · ${nombreFr(position, 3)} %` : libelle;
    return `<div class="etat-garage">
      <span>${esc(nom)}</span>
      <span class="statut ${ton}"><ha-icon icon="${icone}"></ha-icon>${esc(libelleComplet)}</span>
    </div>`;
  }

  // ── Alertes et conseils (0.93.0) : écrits dans les options de l'entrée, comme la terre ──

  _alerteEnregistree(cle) {
    const n = this._donnees?.notifications || {};
    if (cle === "cibles") return (n.cibles || []).map((c) => c.entity_id).sort();
    if (cle === "alertes") return n.alertes !== false;
    if (cle === "mode") return n.mode === "veille_intelligente" ? "veille_intelligente" : "manuel";
    if (cle === "source") return n.source === "conseiller_gazon" ? "conseiller_gazon" : "integration";
    if (cle === "niveau_minimal") return ["information", "action", "critique"].includes(n.niveau_minimal) ? n.niveau_minimal : "information";
    if (cle === "heures_calmes") return {
      active: n.heures_calmes?.active === true,
      debut: Number.isInteger(n.heures_calmes?.debut) ? n.heures_calmes.debut : 22 * 60,
      fin: Number.isInteger(n.heures_calmes?.fin) ? n.heures_calmes.fin : 7 * 60,
    };
    if (cle === "categories") return {
      arrosage_graines: n.categories?.arrosage_graines !== false,
      securite_arrosage: n.categories?.securite_arrosage !== false,
      capteurs_meteo: n.categories?.capteurs_meteo !== false,
      tondeuse: n.categories?.tondeuse !== false,
    };
    return n.ia_choisie || "";
  }

  _valeurAlerte(cle) {
    return cle in this._brouillonAlertes ? this._brouillonAlertes[cle] : this._alerteEnregistree(cle);
  }

  _changerAlerte(cle, valeur) {
    const v = cle === "cibles" ? [...valeur].sort()
      : ["categories", "heures_calmes"].includes(cle) ? { ...valeur } : valeur;
    const enregistree = this._alerteEnregistree(cle);
    const identique = ["categories", "heures_calmes"].includes(cle)
      ? Object.keys(enregistree).every((categorie) => v[categorie] === enregistree[categorie])
      : egal(v, enregistree);
    if (identique) delete this._brouillonAlertes[cle];
    else this._brouillonAlertes[cle] = v;
  }

  _alertesReglagesHtml() {
    const n = this._donnees?.notifications;
    if (!n) return "";
    const lecture = !this._estAdmin();
    const change = (cle) => cle in this._brouillonAlertes;
    const marque = (cle) => (change(cle) ? `<span class="a-enregistrer">à enregistrer</span>` : "");
    const alertes = this._valeurAlerte("alertes");
    const sourceNotifications = this._valeurAlerte("source");
    const niveauMinimal = this._valeurAlerte("niveau_minimal");
    const heuresCalmes = this._valeurAlerte("heures_calmes");
    const categories = this._valeurAlerte("categories");
    const puce = (action, valeur, nom, actif) => `<button class="puce-bascule ${actif ? "active" : ""}" data-action="${action}" data-valeur="${esc(valeur)}" aria-pressed="${actif}" ${lecture ? "disabled" : ""}>${actif ? `<ha-icon icon="mdi:check"></ha-icon>` : ""}${esc(nom)}</button>`;
    const choixCategories = [
      ["arrosage_graines", "mdi:sprinkler-variant", "Arrosage et graines", "Cycle retardé, suspendu ou rattrapé."],
      ["securite_arrosage", "mdi:shield-alert-outline", "Sécurité arrosage", "Vanne non fermée et verrou de sécurité posé."],
      ["capteurs_meteo", "mdi:access-point-off", "Capteurs et météo", "Mesure absente depuis une heure, puis revenue."],
      ["tondeuse", "mdi:robot-mower-outline", "Tondeuse en erreur", "Nouvelle erreur du robot, sans répétition tant qu'elle reste identique."],
      ["activite_arrosage", "mdi:water-check-outline", "Activité arrosage", "Début et fin d'un cycle, quantité et zones exécutées."],
      ["activite_tondeuse", "mdi:robot-mower", "Activité tondeuse", "Départ, retour vers la station et rentrée confirmée."],
      ["garage_tondeuse", "mdi:garage-variant", "Garage tondeuse", "Ouverture, fermeture confirmée ou erreur de commande."],
    ];
    const choixHtml = choixCategories.map(([cle, icone, titre, aide]) => `<div class="ligne compacte">
      <div class="ligne-tete">
        <span class="ligne-icone"><ha-icon icon="${icone}"></ha-icon></span>
        <div class="ligne-textes"><h4>${titre}</h4><p>${aide}</p></div>
        <button class="bascule" role="switch" data-action="alerte-categorie" data-valeur="${cle}" aria-checked="${categories[cle] !== false}" aria-label="Recevoir : ${titre}" ${lecture ? "disabled" : ""}></button>
      </div>
    </div>`).join("");
    const corps = `<div class="lignes">
        <div class="ligne ${change("alertes") ? "change" : ""}" data-cle="alertes-actives">
          ${marque("alertes")}
          <div class="ligne-tete">
            <span class="ligne-icone"><ha-icon icon="${alertes ? "mdi:bell-ring-outline" : "mdi:bell-off-outline"}"></ha-icon></span>
            <div class="ligne-textes"><h4>Activer les notifications automatiques ?</h4><p>Interrupteur général. Chaque alerte laisse aussi une trace dans les notifications de Home Assistant.</p></div>
            <button class="bascule" role="switch" data-action="alerte-bascule" aria-checked="${alertes}" aria-label="Activer les notifications automatiques" ${lecture ? "disabled" : ""}></button>
          </div>
          <p class="etat-bascule">${alertes ? "Allumé" : "Éteint"}${change("alertes") ? " (pas encore enregistré)" : ""}</p>
        </div>
        <div class="ligne ${change("source") ? "change" : ""}" data-cle="alertes-source">
          ${marque("source")}
          <div class="ligne-tete">
            <span class="ligne-icone"><ha-icon icon="mdi:brain"></ha-icon></span>
            <div class="ligne-textes"><h4>Qui rédige les notifications ?</h4><p>L'intégration écrit un message factuel. Conseiller Gazon le personnalise avec l'IA ; si elle ne répond pas, le message factuel part quand même.</p></div>
          </div>
          <div class="puces-bascule" role="radiogroup" aria-label="Rédaction des notifications">
            ${puce("alerte-source", "integration", "Gazon Intelligent", sourceNotifications === "integration")}
            ${puce("alerte-source", "conseiller_gazon", "Conseiller Gazon", sourceNotifications === "conseiller_gazon")}
          </div>
        </div>
        <div class="ligne ${change("niveau_minimal") ? "change" : ""}" data-cle="alertes-niveau">
          ${marque("niveau_minimal")}
          <div class="ligne-tete">
            <span class="ligne-icone"><ha-icon icon="mdi:filter-variant"></ha-icon></span>
            <div class="ligne-textes"><h4>Quel niveau doit déclencher une notification ?</h4><p>Les messages filtrés restent visibles dans les notifications de Home Assistant.</p></div>
          </div>
          <div class="puces-bascule" role="radiogroup" aria-label="Niveau minimal des notifications">
            ${puce("alerte-niveau", "information", "Tout recevoir", niveauMinimal === "information")}
            ${puce("alerte-niveau", "action", "Important", niveauMinimal === "action")}
            ${puce("alerte-niveau", "critique", "Urgences seulement", niveauMinimal === "critique")}
          </div>
        </div>
        <div class="ligne ${change("heures_calmes") ? "change" : ""}" data-cle="alertes-heures-calmes">
          ${marque("heures_calmes")}
          <div class="ligne-tete">
            <span class="ligne-icone"><ha-icon icon="mdi:weather-night"></ha-icon></span>
            <div class="ligne-textes"><h4>Heures calmes</h4><p>Les alertes non critiques attendent dans Home Assistant sans alerter les appareils. Une vanne bloquée reste toujours urgente.</p></div>
            <button class="bascule" role="switch" data-action="alerte-heures-calmes" aria-checked="${heuresCalmes.active}" aria-label="Activer les heures calmes" ${lecture ? "disabled" : ""}></button>
          </div>
          <div class="heures-calmes-champs">
            <label>Début<input type="time" data-alerte-heure="debut" value="${heurePourChamp(heuresCalmes.debut)}" ${lecture || !heuresCalmes.active ? "disabled" : ""}></label>
            <span aria-hidden="true">→</span>
            <label>Fin<input type="time" data-alerte-heure="fin" value="${heurePourChamp(heuresCalmes.fin)}" ${lecture || !heuresCalmes.active ? "disabled" : ""}></label>
          </div>
        </div>
        <div class="ligne ${change("categories") ? "change" : ""}" data-cle="alertes-categories">
          ${marque("categories")}
          <div class="ligne-tete">
            <span class="ligne-icone"><ha-icon icon="mdi:bell-cog-outline"></ha-icon></span>
            <div class="ligne-textes"><h4>Quelles notifications recevoir ?</h4><p>Chaque catégorie est indépendante. Une même panne n'est envoyée qu'une fois.</p></div>
          </div>
          <div class="lignes alertes-categories">${choixHtml}</div>
        </div>
      </div>`;
    return this._sectionReglageHtml({
      titre: "Alertes et conseils",
      phrase: "Configurer les messages à recevoir. Les appareils destinataires et l'IA se choisissent dans Entités.",
      icone: "mdi:bell-cog-outline",
      cles: ["alertes", "source", "niveau_minimal", "heures_calmes", "categories"],
      corps,
      classes: "section-rangee",
      attributs: 'data-alertes="1"',
    });
  }

  _notificationsEntitesHtml() {
    const n = this._donnees?.notifications;
    if (!n) return "";
    const lecture = !this._estAdmin();
    const change = (cle) => cle in this._brouillonAlertes;
    const marque = (cle) => change(cle) ? `<span class="a-enregistrer">à enregistrer</span>` : "";
    const cibles = new Set(this._valeurAlerte("cibles"));
    const ia = this._valeurAlerte("ia");
    const telephones = [...(Array.isArray(n.telephones) ? n.telephones : [])];
    for (const cible of n.cibles || []) {
      if (!telephones.some((t) => t.entity_id === cible.entity_id)) telephones.push(cible);
    }
    const ias = [{ entity_id: "", nom: "Automatique" }, ...(Array.isArray(n.ias) ? n.ias : [])];
    const puce = (action, valeur, nom, actif) => `<button class="puce-bascule ${actif ? "active" : ""}" data-action="${action}" data-valeur="${esc(valeur)}" aria-pressed="${actif}" ${lecture ? "disabled" : ""}>${actif ? `<ha-icon icon="mdi:check"></ha-icon>` : ""}${esc(nom)}</button>`;
    const corps = `<div class="lignes">
        <div class="ligne ${change("cibles") ? "change" : ""}" data-cle="alertes-telephones">
          ${marque("cibles")}<div class="ligne-tete"><span class="ligne-icone"><ha-icon icon="mdi:cellphone-message"></ha-icon></span>
            <div class="ligne-textes"><h4>Appareils à prévenir</h4><p>Entités <code>notify.*</code> qui reçoivent les alertes et « Envoyer l'état ». Aucun : seulement dans Home Assistant.</p></div></div>
          ${telephones.length ? `<div class="puces-bascule">${telephones.map((t) => puce("alerte-telephone", t.entity_id, t.nom, cibles.has(t.entity_id))).join("")}</div>`
            : `<p class="note"><ha-icon icon="mdi:information-outline"></ha-icon><span>Aucune entité de notification disponible. Installer l'application Home Assistant sur un téléphone pour en créer une.</span></p>`}
        </div>
        <div class="ligne ${change("ia") ? "change" : ""}" data-cle="alertes-ia">
          ${marque("ia")}<div class="ligne-tete"><span class="ligne-icone"><ha-icon icon="mdi:robot-outline"></ha-icon></span>
            <div class="ligne-textes"><h4>IA du Conseiller Gazon</h4><p>Entité <code>ai_task.*</code> utilisée pour personnaliser les messages et répondre aux questions. Elle ne commande jamais les machines.</p></div></div>
          ${n.ia_disponible || ias.length > 1 ? `<div class="puces-bascule" role="radiogroup" aria-label="Quelle IA pour les conseils ?">${ias.map((x) => puce("alerte-ia", x.entity_id, x.nom, ia === x.entity_id)).join("")}</div>`
            : `<p class="note"><ha-icon icon="mdi:information-outline"></ha-icon><span>Aucune entité d'IA dans Home Assistant.</span></p>`}
        </div>
      </div>`;
    return this._sectionReglageHtml({
      titre: "Notifications et intelligence artificielle",
      phrase: "Les entités qui reçoivent ou rédigent les messages. Le contenu et les catégories restent dans Installation.",
      icone: "mdi:bell-outline",
      cles: ["cibles", "ia"],
      corps,
      classes: "section-rangee",
      attributs: 'data-entites-notifications="1"',
    });
  }

  // ── Les choix (type de sol) ──

  _valeurChoix(cle) {
    const c = (this._registre.choix || []).find((x) => x.cle === cle);
    return this._brouillonChoix[cle] ?? this._donnees?.choix?.[cle] ?? c?.defaut;
  }

  _changerChoix(cle, valeur) {
    const enregistre = this._donnees?.choix?.[cle]
      ?? (this._registre.choix || []).find((c) => c.cle === cle)?.defaut;
    if (valeur === enregistre) delete this._brouillonChoix[cle];
    else this._brouillonChoix[cle] = valeur;
  }

  // Une carte par option : on voit tout de suite ce que la terre change.
  _choixHtml(c) {
    if (c.cle === "pilotage_tondeuse") return this._pilotageTondeuseHtml(c);
    if (c.cle === "tondeuse_creneaux_depart") return this._creneauxDepartTondeuseHtml(c);
    const actuel = this._valeurChoix(c.cle);
    const enregistre = this._donnees?.choix?.[c.cle] ?? c.defaut;
    const enAttente = c.cle in this._brouillonChoix;
    const lecture = !this._estAdmin();
    const plafond = Math.max(...c.options.map((o) => o.reserve_max_mm || 0), 1);
    const options = c.options.map((o) => {
      const choisi = o.valeur === actuel;
      return `<button class="choix-sol ${choisi ? "choisi" : ""}" role="radio" aria-checked="${choisi}"
          data-action="choisir" data-choix="${esc(c.cle)}" data-valeur="${esc(o.valeur)}" ${lecture ? "disabled" : ""}>
        <span class="choix-sol-tete"><b>${esc(o.titre)}</b>${o.valeur === enregistre && !choisi ? `<small>enregistrée</small>` : ""}${choisi ? `<ha-icon icon="mdi:check-circle"></ha-icon>` : ""}</span>
        <span class="choix-sol-texte">${esc(o.aide)}</span>
        <span class="choix-sol-reserve" aria-hidden="true"><i style="width:${pourcent(o.reserve_mm, 0, plafond)}%"></i><i class="max" style="width:${pourcent(o.reserve_max_mm, 0, plafond)}%"></i></span>
        <span class="choix-sol-chiffres">garde ${esc(mmFr(o.reserve_mm))} pour le gazon · ${esc(mmFr(o.reserve_max_mm))} au plus</span>
      </button>`;
    }).join("");
    const corps = `<div class="choix-sols" role="radiogroup" aria-label="${esc(c.titre)}">${options}</div>
      <p class="note choix-sol-note"><ha-icon icon="mdi:information-outline"></ha-icon><span>${enAttente
        ? "Pas encore enregistré. Une fois enregistré, le calcul de la réserve suit la nouvelle terre dès son prochain passage."
        : "En cas de doute, prendre une poignée de terre humide : elle file entre les doigts (sableuse), reste douce (limoneuse) ou colle (argileuse)."}</span></p>`;
    return this._sectionReglageHtml({
      titre: "La terre du jardin", phrase: `${c.titre} ${c.aide}`, icone: "mdi:terrain",
      cles: [c.cle], corps, classes: enAttente ? "change" : "",
      attributs: `data-cle="${esc(c.cle)}" data-choix-carte="1"`,
    });
  }

  _creneauxDepartTondeuseHtml(c) {
    const actuel = this._valeurChoix(c.cle);
    const enregistre = this._donnees?.choix?.[c.cle] ?? c.defaut;
    const enAttente = c.cle in this._brouillonChoix;
    const lecture = !this._estAdmin();
    const icones = {
      ideal_seulement: "mdi:weather-sunny",
      ideal_acceptable: "mdi:weather-sunset",
      tout_non_bloque: "mdi:clock-outline",
    };
    const options = c.options.map((o) => {
      const choisi = o.valeur === actuel;
      return `<button class="choix-sol ${choisi ? "choisi" : ""}" role="radio" aria-checked="${choisi}"
          data-action="choisir" data-choix="${esc(c.cle)}" data-valeur="${esc(o.valeur)}" ${lecture ? "disabled" : ""}>
        <span class="choix-sol-tete"><ha-icon icon="${icones[o.valeur] || "mdi:circle-outline"}"></ha-icon><b>${esc(o.titre)}</b>${o.valeur === enregistre && !choisi ? `<small>enregistré</small>` : ""}${choisi ? `<ha-icon icon="mdi:check-circle"></ha-icon>` : ""}</span>
        <span class="choix-sol-texte">${esc(o.aide)}</span>
      </button>`;
    }).join("");
    const corps = `<div class="choix-sols" role="radiogroup" aria-label="${esc(c.titre)}">${options}</div>
      <p class="note"><ha-icon icon="mdi:shield-check-outline"></ha-icon><span>Un créneau déconseillé reste visible dans les conseils, mais ne déclenche un départ que lorsque « Tout créneau non bloqué » est sélectionné explicitement.</span></p>`;
    return this._sectionReglageHtml({
      titre: "Créneau des départs automatiques", phrase: c.aide, icone: "mdi:clock-outline",
      cles: [c.cle], corps, classes: enAttente ? "change" : "",
      attributs: `data-cle="${esc(c.cle)}" data-choix-carte="1"`,
    });
  }

  _pilotageTondeuseHtml(c) {
    const actuel = this._valeurChoix(c.cle);
    const enregistre = this._donnees?.choix?.[c.cle] ?? c.defaut;
    const enAttente = c.cle in this._brouillonChoix;
    const lecture = !this._estAdmin();
    const icones = { desactive: "mdi:power-off", observation: "mdi:eye-outline", actif: "mdi:robot-mower" };
    const options = c.options.map((o) => {
      const choisi = o.valeur === actuel;
      return `<button class="choix-sol ${choisi ? "choisi" : ""}" role="radio" aria-checked="${choisi}"
          data-action="choisir" data-choix="${esc(c.cle)}" data-valeur="${esc(o.valeur)}" ${lecture ? "disabled" : ""}>
        <span class="choix-sol-tete"><ha-icon icon="${icones[o.valeur] || "mdi:circle-outline"}"></ha-icon><b>${esc(o.titre)}</b>${o.valeur === enregistre && !choisi ? `<small>enregistré</small>` : ""}${choisi ? `<ha-icon icon="mdi:check-circle"></ha-icon>` : ""}</span>
        <span class="choix-sol-texte">${esc(o.aide)}</span>
      </button>`;
    }).join("");
    const corps = `<div class="choix-sols" role="radiogroup" aria-label="${esc(c.titre)}">${options}</div>
      <p class="note"><ha-icon icon="mdi:sync"></ha-icon><span>Après un départ, la tondeuse gère seule ses retours batterie et ses redéparts. Si Gazon Intelligent la rappelle pour une condition bloquante, il envoie une seule reprise lorsque toutes les sécurités sont de nouveau réunies.</span></p>
      <p class="note alerte"><ha-icon icon="mdi:alert-outline"></ha-icon><span>Actif doit rester éteint tant qu'un autre automatisme, notamment Node-RED, peut encore commander la tondeuse.</span></p>`;
    return this._sectionReglageHtml({
      titre: "Pilotage automatique de la tondeuse", phrase: c.aide, icone: "mdi:robot-mower",
      cles: [c.cle], corps, classes: enAttente ? "change" : "",
      attributs: `data-cle="${esc(c.cle)}" data-choix-carte="1"`,
    });
  }

  _ligneEntiteHtml(ligne) {
    const numero = /^debit_zone_(\d)$/.exec(ligne.cle)?.[1];
    const zone = numero ? (this._donnees?.zones || []).find((z) => String(z.numero) === numero && z.nom) : null;
    const l = zone ? { ...ligne, titre: `${zone.nom} (zone ${numero}) : combien de millimètres d'eau en une heure ?` } : ligne;
    const etat = this._entite(l.cle);
    const a = etat.attributes || {};
    const v = this._valeurEntite(l.cle);
    const enAttente = l.cle in this._brouillonEntites;
    const lecture = !this._estAdmin();
    const indisponible = etat.state === "unavailable" || etat.state === "unknown";
    if (l.genre === "interrupteur") {
      return `<div class="ligne ${enAttente ? "change" : ""}" data-cle="${esc(l.cle)}" data-entite="1">
        ${enAttente ? `<span class="a-enregistrer">à enregistrer</span>` : ""}
        <div class="ligne-tete">
          <span class="ligne-icone"><ha-icon icon="${esc(l.icone)}"></ha-icon></span>
          <div class="ligne-textes"><h4>${esc(l.titre)}</h4><p>${esc(l.aide)}</p></div>
          <button class="bascule" role="switch" data-action="basculer" aria-checked="${v === true}" aria-label="${esc(l.titre)}" ${lecture || indisponible ? "disabled" : ""}></button>
        </div>
        <p class="etat-bascule">${indisponible ? "Indisponible pour l'instant." : v ? "Allumé" : "Éteint"}${enAttente ? " (pas encore enregistré)" : ""}</p>
      </div>`;
    }
    const r = this._reglageEntite(l, a);
    const ligneErreur = this._erreurEntite(l.cle);
    return `<div class="ligne ${enAttente ? "change" : ""} ${ligneErreur ? "en-erreur" : ""}" data-cle="${esc(l.cle)}" data-entite="1">
      ${enAttente ? `<span class="a-enregistrer">à enregistrer</span>` : ""}
      <div class="ligne-tete">
        <span class="ligne-icone"><ha-icon icon="${esc(l.icone)}"></ha-icon></span>
        <div class="ligne-textes"><h4>${esc(l.titre)}</h4><p>${esc(l.aide)}</p></div>
        <output class="bulle bulle-haut">${indisponible || v === undefined ? "—" : esc(valeurFr(r, v))}</output>
      </div>
      <div class="reglette">
        <button class="pas-btn" data-action="moins" aria-label="Moins" ${lecture || indisponible || v <= r.minimum ? "disabled" : ""}><ha-icon icon="mdi:minus"></ha-icon></button>
        <div class="curseur-zone">
          <input type="range" min="${r.minimum}" max="${r.maximum}" step="${r.pas}" value="${v ?? r.minimum}"
            style="--rempli:${pourcent(v ?? r.minimum, r.minimum, r.maximum)}%"
            aria-label="${esc(l.titre)}" aria-valuetext="${esc(valeurFr(r, v))}" ${lecture || indisponible ? "disabled" : ""}>
        </div>
        <button class="pas-btn" data-action="plus" aria-label="Plus" ${lecture || indisponible || v >= r.maximum ? "disabled" : ""}><ha-icon icon="mdi:plus"></ha-icon></button>
        <output class="bulle bulle-bas" aria-hidden="true">${indisponible || v === undefined ? "—" : esc(valeurFr(r, v))}</output>
      </div>
      <div class="ligne-pied">
        <span>${esc(valeurFr(r, r.minimum))}</span>
        <span class="conseil">${enAttente && !lecture ? `<button data-action="annuler-entite"><ha-icon icon="mdi:undo"></ha-icon>Revenir à ${esc(valeurFr(r, this._valeurEntiteReelle(l.cle)))}</button>` : ""}</span>
        <span class="borne-max">${esc(valeurFr(r, r.maximum))}</span>
      </div>
      ${ligneErreur ? `<p class="erreur" role="alert"><ha-icon icon="mdi:alert-circle-outline"></ha-icon><span>${esc(ligneErreur)}</span></p>` : ""}
    </div>`;
  }

  _reglageEntite(l, a) {
    const unite = a.unit_of_measurement || "";
    const pas = Number(a.step) || 1;
    return {
      cle: l.cle,
      genre: l.genre === "duree" && unite === "min" ? "duree" : "nombre",
      minimum: Number.isFinite(Number(a.min)) ? Number(a.min) : 0,
      maximum: Number.isFinite(Number(a.max)) ? Number(a.max) : 100,
      pas,
      unite,
    };
  }

  _erreurEntite(cle) {
    const min = this._valeurEntite("hauteur_min_tondeuse_cm");
    const max = this._valeurEntite("hauteur_max_tondeuse_cm");
    if ((cle === "hauteur_min_tondeuse_cm" || cle === "hauteur_max_tondeuse_cm") && typeof min === "number" && typeof max === "number" && min >= max) {
      return "La hauteur la plus basse doit être plus petite que la plus haute.";
    }
    return "";
  }

  // ── Barre d'enregistrement et messages ──

  _majBarre() {
    const n = this._etat === "pret" ? this._nombreChangements() : 0;
    // Pendant l'enregistrement, la barre reste là même si les brouillons se vident un à un.
    const visible = n > 0 || this._enregistrement;
    this._barre.classList.toggle("visible", visible);
    this._barre.setAttribute("aria-hidden", String(!visible));
    if (!visible) return;
    const { erreurs } = valider(this._registre, this._toutesLesValeurs());
    const nErreurs = Object.keys(erreurs).length + (this._erreurEntite("hauteur_min_tondeuse_cm") ? 1 : 0);
    const resume = nErreurs
      ? `${nErreurs} réglage${nErreurs > 1 ? "s" : ""} à corriger<small>Consulter le message en rouge.</small>`
      : `${n} changement${n > 1 ? "s" : ""} à enregistrer<small>Rien n'est appliqué avant l'enregistrement.</small>`;
    this._barre.innerHTML = `
      <div class="resume">${this._enregistrement ? "Enregistrement…<small>Un instant.</small>" : resume}</div>
      <div class="actions">
        <button class="bouton-contour" data-action="annuler" ${this._enregistrement ? "disabled" : ""}>Annuler</button>
        ${nErreurs && !this._enregistrement
          ? `<button class="bouton-plein" data-action="voir-erreur">Voir</button>`
          : `<button class="bouton-plein" data-action="enregistrer" ${this._enregistrement ? "disabled" : ""}>Enregistrer</button>`}
      </div>`;
  }

  _afficherToast(texte, mauvais = false) {
    this._toast.className = `toast visible ${mauvais ? "mauvais" : ""}`;
    this._toast.innerHTML = `<ha-icon icon="${mauvais ? "mdi:alert-circle-outline" : "mdi:check-circle-outline"}"></ha-icon><span>${esc(texte)}</span>`;
    clearTimeout(this._minuteurToast);
    this._minuteurToast = setTimeout(() => this._toast.classList.remove("visible"), mauvais ? 6000 : 2600);
  }

  // ── Mises à jour partielles pendant un glissement ──

  _rafraichirApresChangement(cle, { depuisCurseur = false } = {}) {
    if (!depuisCurseur) {
      this._rendre();
      return;
    }
    // Le curseur tenu sous le doigt n'est JAMAIS reconstruit (le glissement s'arrêterait net) :
    // on remplace tout ce qui l'entoure dans sa ligne, puis les dessins, onglets et la barre.
    const fabriquer = (html) => {
      const t = document.createElement("template");
      t.innerHTML = html.trim();
      return t.content.firstElementChild;
    };
    const ligne = this._page.querySelector(`[data-cle="${cle}"]`);
    const reglette = ligne?.querySelector(".reglette");
    const entite = ligne?.dataset.entite === "1";
    if (ligne && reglette) {
      const neuve = fabriquer(entite ? this._ligneEntiteHtml(this._ligneInstallation(cle)) : this._ligneHtml(this._reglage(cle)));
      const avant = [];
      const apres = [];
      let passee = false;
      for (const enfant of [...neuve.children]) {
        if (enfant.classList.contains("reglette")) {
          passee = true;
          const range = reglette.querySelector('input[type="range"]');
          const neuf = enfant.querySelector('input[type="range"]');
          range.style.cssText = neuf.style.cssText;
          range.setAttribute("aria-valuetext", neuf.getAttribute("aria-valuetext") || "");
          const boutons = reglette.querySelectorAll(".pas-btn");
          enfant.querySelectorAll(".pas-btn").forEach((b, i) => { boutons[i].disabled = b.disabled; });
          const bulle = reglette.querySelector(".bulle-bas");
          const neuveBulle = enfant.querySelector(".bulle-bas");
          if (bulle && neuveBulle) bulle.textContent = neuveBulle.textContent;
        } else {
          (passee ? apres : avant).push(enfant);
        }
      }
      for (const enfant of [...ligne.children]) if (enfant !== reglette) enfant.remove();
      reglette.before(...avant);
      reglette.after(...apres);
      ligne.className = neuve.className;
    }
    if (!entite) {
      // Une contrainte croisée peut faire apparaître (ou disparaître) un message sur une autre ligne.
      for (const autre of this._page.querySelectorAll(".ligne[data-cle]:not([data-entite])")) {
        const r = this._reglage(autre.dataset.cle);
        if (autre === ligne || !r || r.genre === "table_mois") continue;
        const neuve = fabriquer(this._ligneHtml(r));
        const texte = (el) => el.querySelector(".erreur")?.textContent.trim() || "";
        if (texte(neuve) !== texte(autre)) autre.replaceWith(neuve);
      }
    }
    this._rafraichirDessins();
    const groupes = [...this._registre.groupes, ONGLET_INSTALLATION];
    for (const bouton of this._page.querySelectorAll(".onglets [data-onglet]")) {
      const g = groupes.find((x) => x.cle === bouton.dataset.onglet);
      if (g) bouton.replaceWith(fabriquer(this._ongletHtml(g, bouton.getAttribute("aria-selected") === "true")));
    }
    this._majBarre();
  }

  _rafraichirDessins() {
    for (const bloc of this._page.querySelectorAll("[data-dessin]")) bloc.innerHTML = this._dessinHtml(bloc.dataset.dessin);
  }

  _rafraichirValeursReglages() {
    if (this._vue !== "reglages" || !this._page) return;
    for (const ligne of this._page.querySelectorAll('.ligne[data-entite="1"][data-cle]')) {
      this._rafraichirLigneEntite(ligne);
    }
    this._rafraichirPompeInstallation();
    this._rafraichirEntreesMeteoInstallation();
    this._majBarre();
  }

  _rafraichirLigneEntite(ligne) {
    const cle = ligne.dataset.cle;
    const description = this._ligneInstallation(cle);
    const etat = description ? this._entite(cle) : null;
    if (!description || !etat) return;
    const indisponible = etat.state === "unavailable" || etat.state === "unknown";
    const valeur = this._valeurEntite(cle);
    const enAttente = cle in this._brouillonEntites;
    ligne.classList.toggle("change", enAttente);
    const attente = ligne.querySelector(".a-enregistrer");
    if (enAttente && !attente) ligne.insertAdjacentHTML("afterbegin", '<span class="a-enregistrer">à enregistrer</span>');
    if (!enAttente) attente?.remove();

    if (description.genre === "interrupteur") {
      const bouton = ligne.querySelector(".bascule");
      if (bouton) {
        bouton.setAttribute("aria-checked", String(valeur === true));
        bouton.disabled = !this._estAdmin() || indisponible;
      }
      const texte = ligne.querySelector(".etat-bascule");
      if (texte) texte.textContent = `${indisponible ? "Indisponible pour l'instant." : valeur ? "Allumé" : "Éteint"}${enAttente ? " (pas encore enregistré)" : ""}`;
      return;
    }

    const reglage = this._reglageEntite(description, etat.attributes || {});
    const texte = indisponible || valeur === undefined ? "—" : valeurFr(reglage, valeur);
    for (const bulle of ligne.querySelectorAll(".bulle")) bulle.textContent = texte;
    const range = ligne.querySelector('input[type="range"]');
    if (range) {
      const affichee = valeur ?? reglage.minimum;
      range.min = String(reglage.minimum);
      range.max = String(reglage.maximum);
      range.step = String(reglage.pas);
      range.value = String(affichee);
      range.style.setProperty("--rempli", `${pourcent(affichee, reglage.minimum, reglage.maximum)}%`);
      range.setAttribute("aria-valuetext", valeurFr(reglage, valeur));
      range.disabled = !this._estAdmin() || indisponible;
    }
    const [moins, plus] = ligne.querySelectorAll(".pas-btn");
    if (moins) moins.disabled = !this._estAdmin() || indisponible || valeur <= reglage.minimum;
    if (plus) plus.disabled = !this._estAdmin() || indisponible || valeur >= reglage.maximum;
    const erreur = this._erreurEntite(cle);
    ligne.classList.toggle("en-erreur", Boolean(erreur));
    const blocErreur = ligne.querySelector(".erreur");
    if (blocErreur) {
      if (erreur) blocErreur.querySelector("span").textContent = erreur;
      else blocErreur.remove();
    } else if (erreur) {
      ligne.insertAdjacentHTML("beforeend", `<p class="erreur" role="alert"><ha-icon icon="mdi:alert-circle-outline"></ha-icon><span>${esc(erreur)}</span></p>`);
    }
  }

  _rafraichirPompeInstallation() {
    const ligne = this._page.querySelector('[data-cle="pompe"] .ligne-textes p');
    const choisie = this._brouillonPompe !== undefined ? this._brouillonPompe : this._donnees?.pompe_choix?.choisie || "";
    if (!ligne) return;
    const etat = choisie ? this._hass.states[choisie] : null;
    ligne.textContent = !choisie ? "Aucune : la page n'en montre pas."
      : !etat ? "Introuvable dans Home Assistant."
      : `En ce moment : ${etat.state === "on" ? "en marche" : etat.state === "off" ? "arrêtée" : valeurEtat(etat)}.`;
  }

  _rafraichirEntreesMeteoInstallation() {
    for (const ligne of this._page.querySelectorAll("tr[data-source-meteo]")) {
      const source = this._sourceMeteo(ligne.dataset.sourceMeteo);
      if (!source) continue;
      const lecture = this._lectureSource(source);
      const deTravers = lecture.etat && source.domaine && !entreeAcceptee(source, source.entity_id, lecture.etat.attributes || {}, lecture.etat.state);
      const statuts = {
        ok: ["ok", "mdi:check-circle-outline", lecture.statut === "ok" && !source.numerique && !deTravers ? "répond" : "mesure lue"],
        absente: ["", "mdi:minus-circle-outline", "non branchée"],
        introuvable: ["retient", "mdi:help-circle-outline", "entité introuvable"],
        indisponible: ["retient", "mdi:alert-outline", "indisponible"],
        illisible: ["retient", "mdi:alert-outline", "valeur illisible"],
      };
      const [ton, icone, libelle] = deTravers ? ["retient", "mdi:alert-outline", "unité inattendue"] : statuts[lecture.statut];
      ligne.className = ton;
      const valeur = ligne.querySelector(".entree-valeur");
      if (valeur) valeur.innerHTML = lecture.etat ? `${esc(valeurEtat(lecture.etat))}<small>${esc(ilYA(lecture.etat.last_updated))}</small>` : "—";
      const statut = ligne.querySelector(".entree-statut .statut");
      if (statut) {
        statut.className = `statut ${ton}`;
        statut.innerHTML = `<ha-icon icon="${icone}"></ha-icon>${esc(libelle)}`;
        if (deTravers) statut.title = this._unitesAttendues(source);
        else statut.removeAttribute("title");
      }
    }
  }

  _ligneInstallation(cle) {
    return INSTALLATION.flatMap((s) => s.lignes).find((l) => l.cle === cle);
  }

  // ── Événements ──

  _surSaisie(e) {
    const cible = e.target;
    if (this._dialogue?.nom === "entree" && cible.id === "dlg-recherche") {
      // Seule la liste change : le champ garde le curseur, la fenêtre sa position.
      this._dialogue.recherche = cible.value;
      const liste = this._fenetre.querySelector("[data-liste-entites]");
      const ligne = this._sourceMeteo(this._dialogue.cle);
      if (liste && ligne) liste.innerHTML = this._choixEntitesHtml(this._dialogue, ligne);
      return;
    }
    if (cible.id === "recherche-reglages") {
      // Même principe : seule la liste de résultats change, le champ garde le curseur.
      this._rechercheReglages = cible.value;
      const liste = this.shadowRoot.querySelector("[data-liste-recherche]");
      if (liste) liste.innerHTML = this._rechercheResultatsHtml();
      return;
    }
    if (this._fenetre.contains(cible)) return;
    if (!cible.matches?.('input[type="range"]')) return;
    const ligne = cible.closest("[data-cle]");
    if (!ligne) return;
    const cle = ligne.dataset.cle;
    const brute = Number(cible.value);
    if (ligne.dataset.entite === "1") {
      const r = this._reglageEntite(this._ligneInstallation(cle), this._entite(cle)?.attributes || {});
      this._changerEntite(cle, caler(r, brute));
    } else {
      const r = this._reglage(cle);
      this._changer(cle, caler(r, brute));
    }
    this._rafraichirApresChangement(cle, { depuisCurseur: true });
  }

  _surChangement(e) {
    const cible = e.target;
    if (this._dialogue && this._fenetre.contains(cible)) {
      if (cible.dataset.dlg === "entite" && this._dialogue.nom === "entree") {
        this._dialogue.choix = cible.value;
        this._dialogue.erreur = null;
        this._majPiedEntree();
      } else if (cible.dataset.dlg === "mode") {
        this._dialogue.choix = cible.value;
        this._redessinerDialogue();
      } else if (cible.dataset.dlg === "produit") {
        // On garde la date et la note déjà saisies.
        const date = this._fenetre.querySelector("#dlg-date")?.value;
        const note = this._fenetre.querySelector("#dlg-note")?.value;
        this._dialogue.produit = cible.value;
        this._redessinerDialogue();
        if (date) this._fenetre.querySelector("#dlg-date").value = date;
        if (note) this._fenetre.querySelector("#dlg-note").value = note;
      }
      return;
    }
    if (cible.matches?.('select[data-role="pompe"]')) {
      this._changerPompe(cible.value);
      this._rendre();
      return;
    }
    if (cible.matches?.('select[data-role="garage-tondeuse"]')) {
      this._changerGarageTondeuse(cible.value);
      this._rendre();
      return;
    }
    if (cible.matches?.('input[data-alerte-heure]')) {
      const minute = minuteDepuisChamp(cible.value);
      if (minute === null) return;
      const heures = { ...this._valeurAlerte("heures_calmes"), [cible.dataset.alerteHeure]: minute };
      this._changerAlerte("heures_calmes", heures);
      this._rendre();
      return;
    }
    if (cible.matches?.('select[data-role="instance"]')) {
      if (this._nombreChangements()) {
        cible.value = this._donnees.entry_id;
        this._afficherToast("Enregistrer ou annuler les changements en cours avant de continuer.", true);
        return;
      }
      this._charger(cible.value);
      return;
    }
    if (cible.matches?.('input[type="range"]')) {
      // Fin du glissement (ou flèche du clavier) : un rendu complet remet tout d'aplomb.
      this._renduEnAttente = false;
      this._rendre();
    }
  }

  // Rend vrai si le clic concernait la navigation, la base de contrôle ou une fenêtre.
  _surClicAccueil(e) {
    const cible = e.target;
    if (cible === this._fenetre) {
      // Un clic sur le fond sombre ferme la fenêtre.
      this._fermerDialogue();
      return true;
    }
    if (this._fenetre.contains(cible)) {
      const bouton = cible.closest?.("button");
      if (!bouton || bouton.disabled) return true;
      if (bouton.hasAttribute("data-fermer")) this._fermerDialogue();
      else if (bouton.hasAttribute("data-valider")) this._validerDialogue();
      else if (bouton.dataset.question !== undefined && this._dialogue?.nom === "conseil_ia") {
        const zone = this._fenetre.querySelector("#dlg-question");
        if (zone) {
          zone.value = bouton.dataset.question;
          zone.focus();
        }
      } else if (bouton.dataset.dlg && this._dialogue?.nom === "arroser") {
        const d = this._dialogue;
        if (bouton.dataset.dlg === "dose-moins") d.mm = Math.max(0.5, Math.round((d.mm - 0.5) * 2) / 2);
        else if (bouton.dataset.dlg === "dose-plus") d.mm = Math.min(30, Math.round((d.mm + 0.5) * 2) / 2);
        else if (bouton.dataset.mm) d.mm = Number(bouton.dataset.mm);
        this._redessinerDialogue();
      }
      return true;
    }
    const vue = cible.closest?.("[data-vue]");
    if (vue) {
      this._choisirVue(vue.dataset.vue);
      return true;
    }
    const onglet = cible.closest?.("[data-onglet-accueil]");
    if (onglet) {
      this._ongletAccueil = onglet.dataset.ongletAccueil;
      this._rendre();
      this._page.scrollTo({ top: 0 });
      if (this._ongletAccueil === "arrosage") this._chargerHistorique();
      return true;
    }
    const dialogue = cible.closest?.("[data-dialogue]");
    if (dialogue) {
      if (!dialogue.disabled) {
        this._ouvrirDialogue(dialogue.dataset.dialogue, {
          produit: dialogue.dataset.produit,
          entree: dialogue.dataset.entree,
          mode: dialogue.dataset.mode,
        });
      }
      return true;
    }
    const commande = cible.closest?.("[data-commande]");
    if (commande) {
      if (!commande.disabled) this._commande(commande.dataset.commande, commande);
      return true;
    }
    const note = cible.closest?.("[data-bascule-note]");
    if (note) {
      // Dépliage local, sans rendu : un rendu replierait les autres notes.
      note.classList.toggle("ouverte");
      return true;
    }
    if (cible.closest?.('[data-action-locale="historique-tout"]')) {
      this._historiqueTout = !this._historiqueTout;
      this._rendre();
      return true;
    }
    return false;
  }

  _changerEntite(cle, valeur) {
    if (egal(valeur, this._valeurEntiteReelle(cle))) delete this._brouillonEntites[cle];
    else this._brouillonEntites[cle] = valeur;
  }

  _surClic(e) {
    if (this._surClicAccueil(e)) return;
    const modeReglage = e.target.closest?.("[data-mode-reglage]");
    if (modeReglage) {
      this._modeReglage = modeReglage.dataset.modeReglage;
      this._rendre();
      return;
    }
    const onglet = e.target.closest?.("[data-onglet]");
    if (onglet) {
      this._onglet = onglet.dataset.onglet;
      this._moisChoisi = {};
      this._rendre();
      this.shadowRoot.querySelector(".page")?.scrollTo({ top: 0 });
      return;
    }
    const mois = e.target.closest?.("[data-mois]");
    const tableau = mois?.closest("[data-cle]")?.dataset.cle;
    if (mois && tableau) {
      this._moisChoisi = { ...this._moisChoisi, [tableau]: Number(mois.dataset.mois) };
      this._rendre();
      return;
    }
    const bouton = e.target.closest?.("[data-action]");
    if (!bouton || bouton.disabled) return;
    const action = bouton.dataset.action;
    const ligne = bouton.closest("[data-cle]");
    const cle = ligne?.dataset.cle;
    switch (action) {
      case "menu":
        this.dispatchEvent(new CustomEvent("hass-toggle-menu", { bubbles: true, composed: true }));
        return;
      case "recharger":
        this._charger(this._donnees?.entry_id);
        return;
      case "aller-reglage":
        this._allerAuReglage(cle, bouton.dataset.cibleOnglet);
        return;
      case "moins":
      case "plus":
        this._pas(ligne, action === "plus" ? 1 : -1);
        return;
      case "revenir":
        this._changer(cle, copie(this._defaut(cle)));
        this._rendre();
        return;
      case "mois-moins":
      case "mois-plus":
      case "mois-revenir":
        this._pasMois(action, cle);
        return;
      case "tout-revenir":
        const groupesARestaurer = String(bouton.dataset.groupes || bouton.dataset.groupe || "")
          .split(",").filter(Boolean);
        for (const r of this._registre.reglages) {
          if (groupesARestaurer.includes(r.groupe)) this._changer(r.cle, copie(r.defaut));
        }
        this._rendre();
        this._afficherToast("Valeurs conseillées restaurées. Utiliser « Enregistrer » pour les conserver.");
        return;
      case "profil-gazon": {
        const profil = PROFILS_GAZON.find((p) => p.cle === bouton.dataset.profil);
        if (!profil) return;
        for (const [cleProfil, valeur] of Object.entries(profil.valeurs)) {
          if (this._reglage(cleProfil)) this._changer(cleProfil, copie(valeur));
        }
        for (const [cleProfil, valeur] of Object.entries(profil.choix || {})) {
          if ((this._registre.choix || []).some((c) => c.cle === cleProfil)) this._changerChoix(cleProfil, valeur);
        }
        this._rendre();
        this._afficherToast(`Profil « ${profil.titre} » préparé. Utiliser « Enregistrer » pour l'appliquer.`);
        return;
      }
      case "profil-pluie":
        this._changer("arrosage_sensibilite_pluie", Number(bouton.dataset.valeur));
        this._rendre();
        return;
      case "mode-revenir": {
        const section = (DISPOSITION.modes || []).find((s) => s.mode === this._modeVisible());
        for (const cleMode of section?.cles || []) {
          const r = this._reglage(cleMode);
          if (r) this._changer(cleMode, copie(r.defaut));
        }
        this._rendre();
        this._afficherToast("Valeurs conseillées restaurées pour ce mode. Utiliser « Enregistrer » pour les conserver.");
        return;
      }
      case "basculer":
        this._changerEntite(cle, !(this._valeurEntite(cle) === true));
        this._rendre();
        return;
      case "basculer-reglage":
        this._changer(cle, !(this._valeur(cle) === true));
        this._rendre();
        return;
      case "annuler-entite":
        delete this._brouillonEntites[cle];
        this._rendre();
        return;
      case "choisir": {
        const cleChoix = bouton.dataset.choix;
        const valeur = bouton.dataset.valeur;
        this._changerChoix(cleChoix, valeur);
        this._rendre();
        return;
      }
      case "alerte-bascule":
        this._changerAlerte("alertes", !this._valeurAlerte("alertes"));
        this._rendre();
        return;
      case "alerte-categorie": {
        const categories = { ...this._valeurAlerte("categories") };
        const categorie = bouton.dataset.valeur;
        categories[categorie] = categories[categorie] === false;
        this._changerAlerte("categories", categories);
        this._rendre();
        return;
      }
      case "alerte-source":
        this._changerAlerte("source", bouton.dataset.valeur || "integration");
        this._rendre();
        return;
      case "alerte-niveau":
        this._changerAlerte("niveau_minimal", bouton.dataset.valeur || "information");
        this._rendre();
        return;
      case "alerte-heures-calmes": {
        const heures = { ...this._valeurAlerte("heures_calmes") };
        heures.active = !heures.active;
        this._changerAlerte("heures_calmes", heures);
        this._rendre();
        return;
      }
      case "alerte-telephone": {
        const choisis = new Set(this._valeurAlerte("cibles"));
        if (choisis.has(bouton.dataset.valeur)) choisis.delete(bouton.dataset.valeur);
        else choisis.add(bouton.dataset.valeur);
        this._changerAlerte("cibles", [...choisis]);
        this._rendre();
        return;
      }
      case "alerte-ia":
        this._changerAlerte("ia", bouton.dataset.valeur || "");
        this._rendre();
        return;
      case "annuler-entites":
        delete this._brouillonAlertes.cibles;
        delete this._brouillonAlertes.ia;
        this._brouillonPompe = undefined;
        this._brouillonGarageTondeuse = undefined;
        this._rendre();
        return;
      case "annuler-installation":
        this._brouillonEntites = {};
        this._brouillonChoix = {};
        for (const cleAlerte of Object.keys(this._brouillonAlertes)) {
          if (!["cibles", "ia"].includes(cleAlerte)) delete this._brouillonAlertes[cleAlerte];
        }
        for (const cleReglage of Object.keys(this._brouillon)) {
          if (this._reglage(cleReglage)?.groupe === "installation") delete this._brouillon[cleReglage];
        }
        this._rendre();
        return;
      case "annuler":
        this._brouillon = {};
        this._brouillonEntites = {};
        this._brouillonChoix = {};
        this._brouillonAlertes = {};
        this._brouillonPompe = undefined;
        this._brouillonGarageTondeuse = undefined;
        this._rendre();
        this._afficherToast("Changements annulés.");
        return;
      case "voir-erreur":
        this._allerALErreur();
        return;
      case "enregistrer":
        this._enregistrer();
        return;
      default:
    }
  }

  _pas(ligne, sens) {
    const cle = ligne.dataset.cle;
    if (ligne.dataset.entite === "1") {
      const r = this._reglageEntite(this._ligneInstallation(cle), this._entite(cle)?.attributes || {});
      const v = this._valeurEntite(cle) ?? r.minimum;
      this._changerEntite(cle, caler(r, v + sens * r.pas));
    } else {
      const r = this._reglage(cle);
      this._changer(cle, caler(r, this._valeur(cle) + sens * r.pas));
    }
    this._rendre();
  }

  _pasMois(action, cle) {
    const r = this._reglage(cle);
    if (!r || r.genre !== "table_mois") return;
    const i = this._moisChoisi[r.cle] ?? (this._contexte().maintenant.mois - 1);
    const valeurs = [...this._valeur(r.cle)];
    if (action === "mois-revenir") valeurs[i] = r.defaut[i];
    else valeurs[i] = caler(r, valeurs[i] + (action === "mois-plus" ? r.pas : -r.pas));
    this._moisChoisi = { ...this._moisChoisi, [r.cle]: i };
    this._changer(r.cle, valeurs);
    this._rendre();
  }

  _allerALErreur() {
    const { erreurs } = valider(this._registre, this._toutesLesValeurs());
    const cle = Object.keys(erreurs)[0];
    if (cle) {
      const groupe = this._reglage(cle)?.groupe;
      if (groupe && groupe !== this._onglet) {
        this._onglet = groupe;
        this._rendre();
      }
    } else if (this._erreurEntite("hauteur_min_tondeuse_cm") && this._onglet !== ONGLET_INSTALLATION.cle) {
      this._onglet = ONGLET_INSTALLATION.cle;
      this._rendre();
    }
    const cible = this.shadowRoot.querySelector(".ligne.en-erreur");
    cible?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  async _enregistrer() {
    if (this._enregistrement || !this._nombreChangements()) return;
    const { erreurs } = valider(this._registre, this._toutesLesValeurs());
    if (Object.keys(erreurs).length || this._erreurEntite("hauteur_min_tondeuse_cm")) {
      this._allerALErreur();
      return;
    }
    this._enregistrement = true;
    this._rendre();
    let echec = null;
    try {
      const alertes = Object.keys(this._brouillonAlertes).length ? { ...this._brouillonAlertes } : null;
      const pompe = this._brouillonPompe;
      const garageTondeuse = this._brouillonGarageTondeuse;
      if (Object.keys(this._brouillon).length || Object.keys(this._brouillonChoix).length || alertes || pompe !== undefined || garageTondeuse !== undefined) {
        const reponse = await this._hass.callWS({
          type: WS_ECRIRE,
          entry_id: this._donnees.entry_id,
          valeurs: this._brouillon,
          choix: this._brouillonChoix,
          ...(alertes ? { notifications: alertes } : {}),
          ...(pompe !== undefined ? { pompe: pompe || null } : {}),
          ...(garageTondeuse !== undefined ? { garage_tondeuse: garageTondeuse || null } : {}),
        });
        if (reponse?.ok === false) {
          const premiere = Object.entries(reponse.erreurs || {})[0];
          // Le message des alertes se suffit ; celui d'un réglage suit son titre.
          const titre = premiere && !["notifications", "pompe", "garage_tondeuse"].includes(premiere[0]) ? `${this._reglage(premiere[0])?.titre || premiere[0]} ` : "";
          throw new Error(premiere ? `${titre}${premiere[1]}` : "valeurs refusées");
        }
        this._donnees = {
          ...this._donnees,
          valeurs: reponse.valeurs,
          choix: reponse.choix ?? this._donnees.choix,
          notifications: reponse.notifications ?? this._donnees.notifications,
          ...(reponse.pompe_choix ? { pompe: reponse.pompe ?? null, pompe_choix: reponse.pompe_choix } : {}),
          ...(reponse.garage_tondeuse ? { garage_tondeuse: reponse.garage_tondeuse } : {}),
        };
        this._brouillon = {};
        this._brouillonChoix = {};
        this._brouillonAlertes = {};
        this._brouillonPompe = undefined;
        this._brouillonGarageTondeuse = undefined;
      }
      const cles = Object.keys(this._brouillonEntites).sort((a, b) => {
        const rang = (x) => (ORDRE_ECRITURE.includes(x) ? ORDRE_ECRITURE.indexOf(x) : ORDRE_ECRITURE.length);
        return rang(a) - rang(b);
      });
      for (const cle of cles) {
        const valeur = this._brouillonEntites[cle];
        const entityId = this._donnees.entites[cle];
        if (entityId.startsWith("switch.")) {
          await this._hass.callService("switch", valeur ? "turn_on" : "turn_off", { entity_id: entityId }, undefined, false);
        } else {
          await this._hass.callService("number", "set_value", { entity_id: entityId, value: valeur }, undefined, false);
        }
        this._attenteEntites[cle] = { valeur, depuis: Date.now() };
        delete this._brouillonEntites[cle];
      }
    } catch (e) {
      echec = erreurLisible(e);
    }
    this._enregistrement = false;
    this._aChange();
    this._rendre();
    if (echec) this._afficherToast(`Pas enregistré : ${echec}`, true);
    else this._afficherToast("C'est enregistré.");
  }
}

if (!customElements.get("gazon-intelligent-panel")) {
  customElements.define("gazon-intelligent-panel", GazonIntelligentPanel);
}
