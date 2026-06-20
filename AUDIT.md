# Audit complet — intégration `gazon_intelligent`

> Audit du 2026-06-19. 38 fichiers Python (~28 000 lignes), recoupé par 8 agents +
> analyse déterministe (ruff full, vulture, graphe d'imports, cross-ref def↔usage
> sur tout le dépôt : `custom_components/`, `tests/`, `services.yaml`, `strings.json`,
> `translations/`). But : repartir propre — supprimer le code mort, lister bugs et vestiges.

## 1. État général

- **Architecture saine** : aucun module orphelin, aucune dépendance cyclique. Chaque
  fichier est atteint depuis un point d'entrée (HA platforms, `__init__`, config_flow,
  diagnostics) ou importé.
- **Garde-fous CI volontairement minimalistes** (à connaître) :
  - `ruff.toml` ne sélectionne que `E9,F63,F7,F82` → **les imports/variables inutilisés
    (F401/F841) ne sont PAS détectés par la CI**. D'où l'accumulation ci-dessous.
  - `mypy.ini` ne couvre que 4 fichiers (`config_flow`, `entity_ids`, `entity_migration`,
    `migration`). Le reste n'est pas typé-vérifié.

## 2. Code mort SUPPRIMÉ (sûr : 0 usage prod + 0 usage test, vérifié repo-wide)

### Imports inutilisés
| Fichier | Ligne | Symbole |
|---|---|---|
| coordinator.py | 56-60 | `WATERING_STAGE_ENRACINEMENT/GERMINATION/LEVEE/NORMAL`, `WATERING_STRATEGY_ADULT_DEEP` |
| decision_models.py | 7 / 6 | `typing.Literal`, `datetime` (après retrait classes Mad) |
| decision_risk.py | 6 | `logging` |
| decision_watering.py | 16-17 | `WATERING_STAGE_ENRACINEMENT/GERMINATION` |
| guidance.py | 3 / 17-18 | `dataclasses.field`, `WATERING_STAGE_ENRACINEMENT/GERMINATION` |
| sensor.py | 23 | `compute_fungal_risk as _sensor_compute_fungal_risk` |

### Variables locales mortes (assignées, jamais relues)
| Fichier | Lignes |
|---|---|
| assistant.py | 346 `blocked_statuses` |
| decision_mowing.py | 543 `pluie_24h`, 858/884 `reason_hint`, 927 `application_reasons`, 947 `forecast_reasons`, 1398 `stress_level`, 1468 `mowing_window_blocked`, 1571 `next_mowing_reason_hint` |
| decision_watering.py | 1261/1273 `arrosage_recommande`, 1424 `score_tonte`, 1426 `tonte_ok`, 1430 `arrosage_recent`, 1508 `application_post_watering_ready_at` |
| guidance.py | 1364 `opt_end`, 2209 `besoin_court`/`besoin_tendance`, 2224 `rosee` |
| sensor.py | 398 `post_status` |

### Fonctions / méthodes mortes
| Fichier | Ligne | Symbole |
|---|---|---|
| decision_watering.py | 284 | `_passage_spacing_text` (doublon de `_watering_style_text`) |
| decision_watering.py | 396 | `_watering_amount_text` |
| guidance.py | 890 | `_season_label` |
| shared_state.py | 34 | `_defined_config_value` |
| watering_policy.py | 491 | `_normalize_dose_band` |
| coordinator.py | 816 | `_check_sensor_stuck` (+ attribut `_sensor_history`) — détection « capteur figé » jamais branchée |

### Classes / constantes / propriétés mortes
| Fichier | Ligne | Symbole |
|---|---|---|
| decision_models.py | 283/309/376 | `MadInputs`, `MadPolicyPayload`, `MadHysteresisState` (+`as_payload`) — feature MAD jamais câblée |
| decision_models.py | 78 | `MAD_BAND_VALUES` (dans aucune map `_POSSIBLE_VALUES_BY_KEY`) |
| const.py | 152 | `IRRIGATION_REASON_KINDS` (tuple agrégateur) |
| entity_base.py | 56 | `_PUBLIC_MOWING_FACADE_KEYS` (constante orpheline) |
| guidance.py | 43/60/61 | `SEMIS_DAYTIME_ACCEPTABLE_END_HOUR`, `NORMAL_WEEKLY_GUARDRAIL_MM_MIN/MAX` |
| coordinator.py | ~1088 | clé `"mad_dynamic_enabled": True` (posée, jamais lue) |

## 3. Vestiges / features inachevées — À ARBITRER (non supprimé sans ton feu vert)

- **API héritée de décision** : `decision.py` `compute_decision` (+`_build_legacy_context`,
  `_build_legacy_runtime_bundles`), `build_decision_snapshot`, et les wrappers
  `compute_phase_active/dominant_phase/subphase/recent_watering_mm/advanced_context/
  water_balance/objectif_mm/memory/etp/action_guidance`. **Non branchés en prod** (la prod
  passe par `build_decision_result`), mais **couverts par ~45 tests**. Les supprimer =
  supprimer aussi leurs tests. → décision produit.
- **Garde-fous oubliés (champs dataclass jamais lus)** dans `watering_policy.py` :
  `WateringRange.max_extreme_mm` + condition `allow_extreme_only_if_hydrophobic` (agent
  mouillant), `WateringExecution.avoid_if_heavy_rain`, `avoid_deep_watering`,
  `DosePolicyBand.season_label`, `WateringRange.optimal_mm` (test-only). → soit câbler, soit retirer.
- **`_evaluate_light_weather_guard`** (watering_policy.py:619) = copie **identique** de
  `_evaluate_weather_guard` → le « light » (Biostimulant) bloque exactement comme la
  Fertilisation. Différenciation prévue mais non implémentée.
- **Module dose dynamique** (`resolve_dose_policy`, `DoseInputs`, `DosePolicyPayload`,
  bands) : dormant (`dynamic_enabled` toujours faux en prod). Vivant via tests uniquement.
- **Constantes test-only** : `APPLICATION_IRRIGATION_MODES`, `APPLICATION_IRRIGATION_MODE_ALIASES`
  (const.py) — utilisées seulement par `test_const.py`.

## 4. Bugs & incohérences

### Vrais défauts fonctionnels — CORRIGÉS
1. ✅ **`assistant.py`** : lisait `snapshot.get("reason_decision")` — clé **inexistante**
   (vraie clé `raison_decision`), toujours None. Les 4 sites étaient des chaînes `or` →
   **lignes mortes retirées** (neutre : l'assistant utilisait déjà `conseil_principal`, le bon
   texte pour cette façade simple).
2. ✅ **`intervention_recommendation.py:1416`** : comparait `best_type == "Agent Mouillant"`
   (brut) → **normalisé** via `_normalize_text` comme le scoring → robuste à la casse stockée.
3. ✅ **`binary_sensor.py`** : défaut `auto_irrigation_enabled` divergent (absent→True vs
   présent-None→False) → **inconnu (absent OU None) traité uniformément comme activé** (ce
   capteur « post-application autorisé » est permissif par défaut ; confirmé par les tests).
4. ✅ **`intervention_recommendation.py:325`** : `reserve_hydrique_sol_mm or bilan_hydrique_mm`
   ignorait une réserve sol réelle de **0 mm** → **check explicite `is None`** (+ 3 tests neufs
   `test_intervention_recommendation.py`).

### Faux positif levé
5. ❌ **`guidance.py:398-400`** (germination) : **PAS un bug** — `phases.py:40` définit bien
   le label `"Germination"` capitalisé, donc `sous_phase in {"Germination","Levée"}` matche.

### Restants — à arbitrer côté métier (pas corrigé sans ton avis)
6. **`gazon_brain.py:660-664`** : `record_watering` écrase `total_mm` réel par l'objectif
   quand `objectif_mm` est fourni (lié à l'historique du double-comptage 0.13.2 — à confirmer).
7. **`decision_watering.py:1328`** : resolver sursemis peut produire `moment="soir"` là où les
   autres forcent `maintenant`/`attendre` — probablement involontaire.
8. **`mower_coordination.py:169-176`** : bloc qui réécrit `reason_code/label` déjà produits à
   l'identique par `_reliability` (duplication sans effet — cosmétique).
9. **`intervention_recommendation.py`** : bloc « best is None » quasi inatteignable, doublon du
   « catalogue vide » (cosmétique).

### Dette de cohérence (cosmétique, sans impact décisionnel)
- Tables de labels dupliquées et **divergées** entre `sensor.py` et `binary_sensor.py`
  (`_block_reason_display_label`, `_fallback_machine_unavailable_label_from_attrs`) → un même
  `block_reason` peut s'afficher joli côté sensor et brut côté binary_sensor.
- `seasonal_profile.py` mois 9 : `season:"summer"` vs `season_phase:"reprise_automnale"` (libellé).
- `scores.py:379-388` : recalcul de `today` inerte (paramètre legacy neutralisé).
- `memory.py:847-850` : branche `if next_date < today` = no-op (retour identique).
- `decision_models.py:155-158` : `normalize_watering_contract` réassigne la même valeur (no-op).

## 4quater. Décisions agronomiques tranchées (après recherche + vérif code)

- **Garde « light » Biostimulant** → **FUSIONNÉ** avec celui de la Fertilisation (suppression du
  doublon `_evaluate_light_weather_guard` + constante + dispatch). Cheminement honnête : la
  recherche web suggérait d'abord de *différencier* (biostimulant plus tolérant à la pluie), MAIS
  la lecture du code a montré que « bloquer » signifie *« ne pas arroser l'incorporation, la pluie
  s'en charge »* (guidance.py:1556 → `mm_final=0`). Or le biostimulant s'incorpore très bien avec
  la pluie → « laisser la pluie le faire » est correct pour lui aussi. Différencier aurait forcé un
  arrosage **inutile**. Donc on assume : même garde pour les deux. Comportement inchangé, doublon supprimé.
- **Garde-fous oubliés `watering_policy`** → **RETIRÉS** (`avoid_if_heavy_rain` redondant avec le
  weather_guard ; `avoid_deep_watering` déjà respecté par la dose 3-7 mm ≈ 1/4" reco fabricant ;
  `max_extreme_mm`/`allow_extreme_only_if_hydrophobic` non détectable sans capteur d'hydrophobie, et
  le H2Pro corrige lui-même l'hydrophobie d'après ICL). Champs morts retirés, dose 5-12 mm conservée.

## 4ter. Vérification des « restants » (chacun re-vérifié) — verdicts

- **API héritée (`compute_decision`/`build_decision_snapshot`/wrappers `compute_*`)** → **GARDÉE**.
  Vérifié : ce sont des points d'entrée **testés** (`decision.build_decision_snapshot` 41×,
  `compute_action_guidance` 11×, etc. — 90+ références de test). Les retirer détruirait la
  couverture. (L'agent les avait crus morts : son grep ratait le préfixe `decision.`.)
- **#3 `gazon_brain.record_watering` écrase `total_mm`** → **NON-bug**. Voulu : lame surfacique
  canonique (objectif uniforme) pour créditer la réserve sans double-comptage (commits 0.13.2 / 0.10.2).
- **#4 sursemis `moment="soir"`** → **NON-bug**. `_profile_for_sursemis` n'émet jamais `"soir"`
  (uniquement attendre/ce_matin/maintenant/apres_pluie) ; l'entrée « soir » est gardée et inatteignable en sursemis.
- **#8 `mower_coordination.py:169-176`** → **GARDÉ** (pas un no-op). `_reliability` a un early-return
  `if not enabled: return True, "disabled"` → quand la coordination est désactivée ET la tondeuse tond,
  le bloc remplace bien « disabled » par « mower_mowing » (effet réel sur le libellé).
- **Garde-fous oubliés (`watering_policy`)** → **GARDÉS** (intent agronomique, champs inertes mais
  documentent une règle à câbler ; référentiel sensible — ne pas supprimer sans raison agro).
- **Tables de libellés `block_reason` dupliquées/divergentes** → **CORRIGÉ**. Centralisées dans
  `const.BLOCK_REASON_DISPLAY_LABELS` (source unique) ; binary_sensor récupère les 4 libellés
  qui lui manquaient (`application_foliaire`, `temperature_trop_basse_germination`,
  `semis_cycle_daily_target_reached`, `semis_cycle_pending`). Plus de divergence possible.
  (`_fallback_machine_unavailable_label_from_attrs` reste légèrement divergente — fonction à
  logique, laissée telle quelle, divergence mineure.)

## 4bis. Faux positif rattrapé en cours de route (leçon)

Les propriétés `DecisionResult.mode` / `.objectif_mm` / `.mm_a_appliquer` semblaient mortes
(0 accès `.objectif_mm` en grep) mais sont **atteintes dynamiquement** : `_decision_value(key)`
fait `getattr(result, key)` (entity_base.py:106). Les supprimer a cassé 8 tests → **rétablies**.
→ Tout attribut/propriété de `DecisionResult` portant le nom d'une clé de snapshot est vivant
par getattr, même sans accès `.nom` littéral. (Les classes/constantes module-level, elles, ne
sont pas concernées.)

## 5. Faux positifs — NE PAS toucher (hooks dynamiques HA)
Méthodes/propriétés appelées par le framework, jamais « en dur » : `async_setup_entry`,
`async_press`, `async_set_native_value`, `async_select_option`, `async_step_*`, `native_value`,
`is_on`, `extra_state_attributes`, `_attr_*`, `CONFIG_SCHEMA`, `GazonIntelligentConfigFlow`,
`async_get_config_entry_diagnostics`, `async_setup`/`async_unload_entry`/`async_migrate_entry`.
Toutes les classes d'entités (`sensor.py`, `binary_sensor.py`, `number/select/switch/button`)
sont instanciées dans leur `async_setup_entry` → vivantes.
