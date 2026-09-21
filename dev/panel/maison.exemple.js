// Maison d'EXEMPLE pour l'aperçu local de la page « Gazon » : des valeurs inventées, cohérentes.
// Pour voir ta vraie maison, crée `maison.local.js` (ignoré par git) sur le même modèle.
// Les horaires du soleil trahissent une position : ne les publie jamais.

const MODES = ["Normal", "Semis", "Sursemis", "Traitement", "Fertilisation", "Biostimulant", "Agent Mouillant", "Scarification", "Hivernage"];

const nombre = (state, min, max, step, unite, nom, icone) => ({
  state: String(state),
  attributes: { min, max, step, mode: "slider", unit_of_measurement: unite, friendly_name: nom, icon: icone },
});
const interrupteur = (state, nom) => ({ state, attributes: { friendly_name: nom } });
const volet = (state, nom) => ({ state, attributes: { friendly_name: nom, device_class: "garage" } });
const capteur = (state, attributes = {}) => ({ state: String(state), attributes });

const P = "gazon_intelligent";

// Voyants de santé des entrées : ce que l'intégration publie dans `sensor_health`.
const SANTE = {
  temperature_utilisee_c: 21.4, humidite_utilisee_pct: 54, vent_utilise_kmh: 6.8,
  temperature_valid: true, humidity_valid: true, wind_valid: true, wind_measured: true, pluie_valid: true, etp_valid: true,
  weather_profile_available: true, eto_hourly_available: true, eto_radiation_measured: true, eto_pressure_measured: false,
  pluie_actuelle_active: false, pluie_mesuree_active: false, pluie_cumul_jour_mm: 0, pluie_mesuree_minutes_depuis_hausse: 2890,
  etp_ecoulee_mm: 1.9, etp_jour_estime_mm: 3.4,
};
const mesure = (state, unite, nom, classe, classeEtat = "measurement") => ({
  state: String(state),
  attributes: { unit_of_measurement: unite, friendly_name: nom, state_class: classeEtat, ...(classe ? { device_class: classe } : {}) },
});

export default {
  titre: "Gazon Intelligent",
  sous_titre: "Pelouse d'exemple",
  fuseau: "Europe/Paris",
  releve: "valeurs d'exemple",
  meteo: "weather.maison",
  pompe: null,
  // Les options de l'entrée que la page sait changer.
  choix: {
    type_sol: "limoneux",
    pilotage_tondeuse: "desactive",
    tondeuse_creneaux_depart: "ideal_seulement",
  },
  garage_tondeuse: { choisie: "cover.garage_tondeuse", volets: [{ entity_id: "cover.garage_tondeuse", nom: "Garage tondeuse" }] },
  zones: [
    { numero: 1, nom: "Devant", switch: "switch.vanne_1", etat: null },
    { numero: 2, nom: "Derrière", switch: "switch.vanne_2", etat: null },
  ],
  liaisons_materiel: {
    zone_1: "switch.vanne_1",
    zone_2: "switch.vanne_2",
    entite_tondeuse: "lawn_mower.robot",
    capteur_tondeuse_batterie: "sensor.robot_batterie",
    capteur_tondeuse_hauteur_coupe: "number.robot_hauteur_coupe",
  },
  entites: {
    assistant: `sensor.${P}_assistant`,
    arrosage_en_cours: `sensor.${P}_arrosage_en_cours`,
    prochain_arrosage: `sensor.${P}_prochain_arrosage`,
    blocage_arrosage: `sensor.${P}_arrosage_auto_blocage`,
    prochaine_tonte: `sensor.${P}_prochaine_tonte`,
    tonte_autorisee: `binary_sensor.${P}_tonte_autorisee`,
    phase: `sensor.${P}_phase_dominante`,
    risque: `sensor.${P}_risque_gazon`,
    reserve: `sensor.${P}_reserve_actuelle`,
    etat_hydrique: `sensor.${P}_etat_hydrique`,
    hauteur_tonte: `sensor.${P}_hauteur_de_tonte_conseillee`,
    hauteur_gazon_estimee: `sensor.${P}_hauteur_gazon_estimee`,
    tonte_etat: `sensor.${P}_etat_de_tonte`,
    catalogue_produits: `sensor.${P}_catalogue_produits`,
    derniere_application: `sensor.${P}_derniere_application`,
    prochaine_intervention: `sensor.${P}_prochaine_intervention`,
    dernier_arrosage: `sensor.${P}_dernier_arrosage_detecte`,
    objectif: `sensor.${P}_objectif_d_arrosage`,
    plan_arrosage: `sensor.${P}_plan_d_arrosage`,
    fenetre_optimale: `sensor.${P}_fenetre_optimale`,
    et0: `sensor.${P}_et0`,
    eto_horaire: `sensor.${P}_eto_horaire`,
    etc: `sensor.${P}_etc`,
    mode: `select.${P}_mode_du_gazon`,
    debit_zone_1: `number.${P}_debit_zone_1`,
    debit_zone_2: `number.${P}_debit_zone_2`,
    debit_zone_3: `number.${P}_debit_zone_3`,
    debit_zone_4: `number.${P}_debit_zone_4`,
    debit_zone_5: `number.${P}_debit_zone_5`,
    hauteur_coupe_tondeuse: `number.${P}_hauteur_coupe_tondeuse`,
    hauteur_min_tondeuse_cm: `number.${P}_hauteur_min_tondeuse`,
    hauteur_max_tondeuse_cm: `number.${P}_hauteur_max_tondeuse`,
    delai_reprise_tonte_apres_arrosage: `number.${P}_delai_reprise_tonte_apres_arrosage`,
    seuil_declaration_tonte: `number.${P}_seuil_declaration_tonte`,
    arrosage_automatique: `switch.${P}_arrosage_automatique_autorise`,
    rafraichissement_soir: `switch.${P}_rafraichissement_soir`,
    coordination_tondeuse: `switch.${P}_coordination_tondeuse`,
    declaration_tonte_auto: `switch.${P}_declaration_tonte_auto`,
  },
  // Les entrées branchées dans les options de l'intégration : rôle → entité.
  branchements: {
    entite_meteo: "weather.maison",
    capteur_temperature: "sensor.jardin_temperature",
    capteur_humidite: "sensor.jardin_humidite",
    capteur_vent: "sensor.jardin_vent",
    capteur_rayonnement: "sensor.jardin_rayonnement",
    capteur_pluie_cumul: "sensor.jardin_pluie",
    capteur_pluie_24h: "sensor.pluie_du_jour",
  },
  // Les appareils de ces entrées, avec toutes leurs mesures. Ni le point de rosée ni l'humidité
  // du feuillage ne sont branchés : seule la seconde peut tenir « Rosée sur l'herbe ».
  appareils: [
    {
      id: "station", nom: "Station du jardin", fabricant: "Exemple", modele: "Station météo", station_personnelle: true,
      entites: [
        "sensor.jardin_temperature", "sensor.jardin_humidite", "sensor.jardin_pression", "sensor.jardin_vent", "sensor.jardin_rafales",
        "sensor.jardin_direction_vent", "sensor.jardin_rayonnement", "sensor.jardin_pluie", "sensor.jardin_point_de_rosee",
        "sensor.jardin_uv", "sensor.jardin_batterie", "binary_sensor.jardin_pluie_en_cours",
        "sensor.jardin_humidite_foliaire",
      ],
    },
  ],
  // Ouvertures de vannes : [début, fin] en ISO.
  historique: {
    "switch.vanne_1": [["2026-06-01T05:10:00+02:00", "2026-06-01T05:40:00+02:00"]],
    "switch.vanne_2": [["2026-06-01T05:40:00+02:00", "2026-06-01T06:10:00+02:00"]],
  },
  prevision: { templow: 12, temperature: 24, precipitation: 0 },
  // Les fiches produit complètes (la page les reçoit de l'intégration pour pouvoir les modifier).
  produits: [
    {
      id: "engrais", nom: "Engrais d'exemple", type: "Fertilisation", dose_conseillee: "30 g/m²", usage_mode: "entretien",
      max_applications_per_year: 3, reapplication_after_days: 60, delai_avant_tonte_jours: 2, phase_compatible: ["Entretien", "Croissance"],
      application_months: [3, 4, 5, 6, 7, 8, 9, 10], application_months_label: "Mars à Octobre", temperature_min: 5, temperature_max: 30,
      application_type: "sol", application_requires_watering_after: true, application_post_watering_mm: 5,
      application_irrigation_block_hours: 0, application_irrigation_delay_minutes: 0, application_irrigation_mode: "auto",
      note: "Un engrais d'exemple.",
    },
    {
      id: "mouillant", nom: "Mouillant d'exemple", type: "Agent Mouillant", dose_conseillee: "1 ml/m²", usage_mode: "preventif",
      max_applications_per_year: 6, reapplication_after_days: 28, application_type: "foliaire",
      application_requires_watering_after: true, application_post_watering_mm: 5, application_irrigation_block_hours: 0,
      application_irrigation_delay_minutes: 0, application_irrigation_mode: "auto",
    },
  ],
  // Arrosages de demain matin, calculés par le moteur (build_watering_plan puis
  // plan_morning_departure, lever à 6 h 00) pour les scénarios de l'aperçu.
  scenarios: {
    prevu: {
      mm: 6, depart: "04:45", fin: "05:45",
      plan: {
        objective_mm: 6, zone_count: 2, total_duration_min: 60, duration_human: "60 min", fractionation: false,
        passages: 1, pause_between_passages_minutes: 0, pause_between_passages_s: 0, plan_type: "multi_zone",
        summary: "2 zones • 6.0 mm sur la surface • 60 min",
        zones: [
          { zone: "switch.vanne_1", entity_id: "switch.vanne_1", rate_mm_h: 12, duration_seconds: 1800, duration_s: 1800, duration_min: 30, mm: 6 },
          { zone: "switch.vanne_2", entity_id: "switch.vanne_2", rate_mm_h: 12, duration_seconds: 1800, duration_s: 1800, duration_min: 30, mm: 6 },
        ],
      },
    },
    gros: {
      mm: 12, depart: "03:45", fin: "06:10",
      plan: {
        objective_mm: 12, zone_count: 2, total_duration_min: 120, duration_human: "120 min", fractionation: true,
        passages: 2, pause_between_passages_minutes: 25, pause_between_passages_s: 1500, plan_type: "multi_zone",
        summary: "2 zones • 12.0 mm sur la surface • 120 min",
        zones: [
          { zone: "switch.vanne_1", entity_id: "switch.vanne_1", rate_mm_h: 12, duration_seconds: 3600, duration_s: 3600, duration_min: 60, mm: 12 },
          { zone: "switch.vanne_2", entity_id: "switch.vanne_2", rate_mm_h: 12, duration_seconds: 3600, duration_s: 3600, duration_min: 60, mm: 12 },
        ],
      },
    },
  },
  etats: {
    "sun.sun": capteur("above_horizon", { next_rising: "2026-06-01T04:00:00+00:00", next_setting: "2026-06-01T19:00:00+00:00" }),
    "weather.maison": capteur("sunny", { temperature: 21.5, temperature_unit: "°C", humidity: 55, wind_speed: 9, wind_speed_unit: "km/h", uv_index: 5.1, dew_point: 11 }),
    "switch.vanne_1": interrupteur("off", "Vanne devant"),
    "switch.vanne_2": interrupteur("off", "Vanne derrière"),
    "switch.pompe_jardin": interrupteur("off", "Pompe du jardin"),
    "switch.eclairage_terrasse": interrupteur("off", "Éclairage terrasse"),
    "sensor.jardin_temperature": mesure(21.4, "°C", "Station du jardin Température", "temperature"),
    "sensor.jardin_humidite": mesure(54, "%", "Station du jardin Humidité", "humidity"),
    "sensor.jardin_pression": mesure(1013.2, "hPa", "Station du jardin Pression", "atmospheric_pressure"),
    "sensor.jardin_vent": mesure(6.8, "km/h", "Station du jardin Vent", "wind_speed"),
    "sensor.jardin_rafales": mesure(11.2, "km/h", "Station du jardin Rafales", "wind_speed"),
    "sensor.jardin_direction_vent": mesure(250, "°", "Station du jardin Direction du vent"),
    "sensor.jardin_rayonnement": mesure(512, "W/m²", "Station du jardin Rayonnement", "irradiance"),
    "sensor.jardin_pluie": mesure(41.6, "mm", "Station du jardin Pluie cumulée", "precipitation", "total_increasing"),
    "sensor.jardin_humidite_foliaire": mesure(0, "%", "Station du jardin Humidité foliaire", "moisture"),
    "sensor.jardin_point_de_rosee": mesure(11.8, "°C", "Station du jardin Point de rosée", "temperature"),
    "sensor.jardin_uv": mesure(5, "", "Station du jardin UV"),
    "sensor.jardin_batterie": mesure(87, "%", "Station du jardin Batterie", "battery"),
    "binary_sensor.jardin_pluie_en_cours": { state: "off", attributes: { device_class: "moisture", friendly_name: "Station du jardin Pluie en cours" } },
    "sensor.pluie_du_jour": mesure(0.0, "mm", "Pluie du jour (voisin)", "precipitation", "total_increasing"),
    [`sensor.${P}_et0`]: capteur("3.4", {
      unit_of_measurement: "mm", et0_source: "fallback_pm_location", temperature: 21.4, forecast_temperature_today: 24, temperature_reference_hydrique: 22.5,
    }),
    [`sensor.${P}_eto_horaire`]: capteur("0.32", {
      unit_of_measurement: "mm/h", radiation_source: "capteur", radiation_wm2: 512, pressure_source: "fallback", wind_kmh: 6.8,
      methode: "FAO-56 Penman-Monteith horaire (Eq. 53)",
    }),
    [`sensor.${P}_etc`]: capteur("2.7", { unit_of_measurement: "mm", et0_mm: 3.4, kc_gazon: 0.8 }),
    [`select.${P}_mode_du_gazon`]: capteur("Normal", { options: MODES }),
    [`sensor.${P}_assistant`]: capteur("aucune_action", {
      action: "aucune_action", moment: "attendre", quantity_mm: 0, status: "no_need", reason: "conditions optimales",
      survie_canicule_active: false, gazon_permet_tonte: true, machine_permet_tonte: true,
    }),
    [`sensor.${P}_arrosage_en_cours`]: capteur("0.0", { active: false, progress_percent: 0, remaining_session_seconds: 0, active_zones: [], total_mm_applied: 0, detail: "Aucune session active" }),
    [`sensor.${P}_prochain_arrosage`]: capteur("Non requis", {
      objective_mm: 0, summary: "Aucun arrosage nécessaire pour le moment", watering_window_display: "03:45–10:00",
      jours_avant_arrosage_estime: 2, date_prochain_arrosage_estime: "2026-06-03",
    }),
    [`sensor.${P}_arrosage_auto_blocage`]: capteur("Aucun besoin", {
      bloque: false, code: "no_objective", safety_lock_actif: false,
      pourquoi: "La réserve ne demande pas d'eau.", comment_debloquer: "Aucune action requise.",
    }),
    [`sensor.${P}_prochaine_tonte`]: capteur("01/06/2026", { target_date: "2026-06-01", tonte_statut: "autorisee", summary: "Tonte possible" }),
    [`binary_sensor.${P}_tonte_autorisee`]: capteur("on", {
      tonte_statut: "autorisee", gazon_permet_tonte: true, machine_permet_tonte: true,
      mowing_window_state: "ideal", mowing_window_label: "Fenêtre idéale", mowing_window_reason: "Fenêtre idéale du matin.",
      mowing_frequency_label: "4 à 6 / semaine", derniere_tonte_date: "2026-05-29",
      tondeuse_nom: "Tondeuse", tondeuse_statut_libelle: "À la station", tondeuse_batterie: 90,
    }),
    [`sensor.${P}_phase_dominante`]: capteur("Normal", { pluie_demain_source: "meteo_forecast" }),
    [`sensor.${P}_risque_gazon`]: capteur("faible", {
      risque_gazon_raisons: ["aucun facteur de risque"], fungal_risk_level: "low", fungal_risk_reasons: ["temps sec"],
      sensor_health: SANTE,
    }),
    [`sensor.${P}_reserve_actuelle`]: capteur("9.0", {
      reserve_utile_mm: 12, reserve_stock_mm: 9, reserve_available_ratio: 0.75, reserve_minimale_mm: 6, depletion_mm: 3,
      arrosage_recent_7j: 12, arrosage_applique_7j: 12, pluie_efficace: 0, et0_mm: 3.4,
      sensor_health: SANTE,
    }),
    [`sensor.${P}_etat_hydrique`]: capteur("confort", { reserve_actuelle_mm: 9, reserve_available_ratio: 0.75, reserve_minimale_mm: 6, depletion_mm: 3 }),
    [`sensor.${P}_hauteur_de_tonte_conseillee`]: capteur("4.5", {
      hauteur_tonte_min_cm: 3, hauteur_tonte_max_cm: 8, hauteur_tonte_motif: "Juin : base 4,5 cm.", tondeuse_hauteur_coupe_mm: 45,
    }),
    [`sensor.${P}_hauteur_gazon_estimee`]: capteur("5.1", { gazon_pousse_jour_cm: 0.25, tondeuse_hauteur_coupe_mm: 45 }),
    [`sensor.${P}_etat_de_tonte`]: capteur("autorisee", {
      tondeuse_hauteur_coupe_mm: 45, mower_job_progress_pct: 0, mower_job_completion_state: "en_pause",
      mower_auto_declaration_state: "travail_en_pause", mower_auto_declaration_threshold_minutes: 90,
      mower_mowing_minutes_today: 0, mower_pass_count_today: 0, mower_full_pass_minutes_median: 80,
      mower_control_mode: "desactive", mower_control_state: "desactive",
      mower_control_reason: "Pilotage automatique désactivé.", mower_control_pending_action: null,
    }),
    [`sensor.${P}_objectif_d_arrosage`]: capteur("0.0", { et0_mm: 3.4, pluie_demain: 0, besoin_mm: 0, reserve_minimale_mm: 6 }),
    [`sensor.${P}_fenetre_optimale`]: capteur("attendre", { weekly_guardrail_mm_min: 20, weekly_guardrail_mm_max: 26, heat_stress_level: "normal" }),
    // Sans dose, le capteur « Cycle calculé » publie un plan vide… mais garde le découpage du jour.
    [`sensor.${P}_plan_d_arrosage`]: capteur("0.0", {
      objective_mm: 0, zones: [], zone_count: 0, total_duration_min: 0, duration_human: "0 min", fractionation: false,
      passages: 1, pause_between_passages_minutes: 0, pause_between_passages_s: 0,
      source: "no_plan", reason: "objective_non_positive", plan_type: "no_plan", summary: "Aucun cycle calculé",
    }),
    [`sensor.${P}_catalogue_produits`]: capteur("2", {
      products_summary: [
        { id: "engrais", nom: "Engrais d'exemple", type: "Fertilisation", dose_conseillee: "30 g/m²", max_applications_per_year: 3, application_months_label: "Mars à Octobre" },
        { id: "mouillant", nom: "Mouillant d'exemple", type: "Agent Mouillant", dose_conseillee: "1 ml/m²", max_applications_per_year: 6 },
      ],
    }),
    [`sensor.${P}_derniere_application`]: capteur("Engrais d'exemple", {
      application_history: [
        { libelle: "Engrais d'exemple", produit_id: "engrais", type: "Fertilisation", date_action: "2026-04-10", dose: "30 g/m²", note: "Exemple de note." },
      ],
    }),
    [`sensor.${P}_prochaine_intervention`]: capteur("preparation", {
      product_name: "Mouillant d'exemple", score: 40, hint: "Pertinence limitée dans le contexte actuel.",
      application_constraints: [{ label: "Mois compatibles", met: true, blocking: false }],
    }),
    [`sensor.${P}_dernier_arrosage_detecte`]: capteur("6.0", {
      last_watering_when: "01/06/2026 à 05:10", zone_count: 2,
      derniers_arrosages: [{
        date: "2026-06-01", started_at: "2026-06-01T03:10:00+00:00", recorded_at: "2026-06-01T04:10:00+00:00",
        source: "auto_irrigation", watering_cause: "hydrique", total_mm: 6, zone_count: 2,
        zones: [
          { entity_id: "switch.vanne_1", duration_min: 30, mm: 6 },
          { entity_id: "switch.vanne_2", duration_min: 30, mm: 6 },
        ],
      }],
    }),
    [`number.${P}_debit_zone_1`]: nombre(12, 0, 200, 1, "mm/h", "Débit zone 1", "mdi:sprinkler"),
    [`number.${P}_debit_zone_2`]: nombre(12, 0, 200, 1, "mm/h", "Débit zone 2", "mdi:sprinkler"),
    [`number.${P}_debit_zone_3`]: nombre(0, 0, 200, 1, "mm/h", "Débit zone 3", "mdi:sprinkler"),
    [`number.${P}_debit_zone_4`]: nombre(0, 0, 200, 1, "mm/h", "Débit zone 4", "mdi:sprinkler"),
    [`number.${P}_debit_zone_5`]: nombre(0, 0, 200, 1, "mm/h", "Débit zone 5", "mdi:sprinkler"),
    [`number.${P}_hauteur_coupe_tondeuse`]: nombre(45, 30, 80, 5, "mm", "Hauteur de coupe tondeuse", "mdi:content-cut"),
    [`number.${P}_hauteur_min_tondeuse`]: nombre(3.0, 0.5, 15, 0.5, "cm", "Hauteur min tondeuse"),
    [`number.${P}_hauteur_max_tondeuse`]: nombre(8.0, 0.5, 15, 0.5, "cm", "Hauteur max tondeuse"),
    [`number.${P}_delai_reprise_tonte_apres_arrosage`]: nombre(180, 0, 1440, 5, "min", "Délai reprise tonte après arrosage", "mdi:timer-sand"),
    [`number.${P}_seuil_declaration_tonte`]: nombre(90, 5, 720, 5, "min", "Seuil de déclaration de tonte", "mdi:timer-check-outline"),
    [`switch.${P}_arrosage_automatique_autorise`]: interrupteur("on", "Arrosage automatique autorisé"),
    [`switch.${P}_rafraichissement_soir`]: interrupteur("off", "Rafraîchissement du soir"),
    [`switch.${P}_coordination_tondeuse`]: interrupteur("on", "Coordination tondeuse"),
    [`switch.${P}_declaration_tonte_auto`]: interrupteur("on", "Déclaration auto de la tonte"),
    "cover.garage_tondeuse": volet("closed", "Garage tondeuse"),
    "lawn_mower.robot": capteur("docked", { friendly_name: "Tondeuse du jardin" }),
    "sensor.robot_batterie": mesure(96, "%", "Batterie tondeuse", "battery"),
    "number.robot_hauteur_coupe": nombre(45, 30, 80, 5, "mm", "Hauteur de coupe du robot", "mdi:content-cut"),
  },
};
