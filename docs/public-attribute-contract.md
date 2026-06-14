# Contrat Public Des Attributs

Ce document fige le **contrat public cible** de l'intégration `Gazon Intelligent` sans modifier le comportement runtime actuel.

Objectifs:

- clarifier quelles entités portent les attributs canoniques
- distinguer les alias legacy conservés pour compatibilité
- préparer une migration progressive sans casser la carte Lovelace, les automatisations, les scripts ni l'historique Home Assistant

Principes:

- une entité publique a un **rôle principal**
- les attributs canoniques doivent rester sur l'entité la plus logique
- aucun attribut public existant n'est supprimé tant qu'une migration compatible n'a pas été menée
- un alias legacy peut rester exposé si son usage exact n'est pas totalement maîtrisé

## Statuts de contrat

- **Canonique**: attribut à conserver durablement
- **Legacy**: alias maintenu pour compatibilité
- **Dépréciation future**: candidat à retrait ultérieur après migration documentée

## Entités publiques principales

### `binary_sensor.*_tonte_autorisee`

Rôle canonique:

- exprimer l'autorisation métier de tonte
- exposer la possibilité d'action immédiate à partir du gazon, de la machine et des blocages actifs

Attributs canoniques:

- `phase_active`
- `tonte_statut`
- `risque_gazon`
- `hauteur_tonte_recommandee_cm`
- `hauteur_tonte_min_cm`
- `hauteur_tonte_max_cm`
- `mowing_frequency_target_per_week`
- `mowing_frequency_label`
- `mowing_window_state`
- `mowing_window_label`
- `mowing_window_reason`
- `mowing_daily_session_limit`
- `mowing_daily_session_policy`
- `next_mowing_date`
- `next_mowing_display`
- `gazon_permet_tonte`
- `machine_permet_tonte`
- `mowing_blocked`
- `action_possible`
- `mowing_block_reason_code`
- `mowing_block_reason_label`
- `mowing_machine_unavailable_label`

Alias legacy conservés:

- `raison_blocage_code`
- `raison_blocage_tonte`
- `mowing_block_reason`

### `sensor.*_prochaine_tonte`

Rôle canonique:

- exposer la prochaine échéance tonte côté UI
- fournir la date métier et, si connue, la date/heure exécutable

Attributs canoniques:

- `source_entity`
- `target_date`
- `target_display`
- `target_datetime`
- `target_datetime_display`
- `action_possible`
- `tonte_statut`
- `block_reason`
- `machine_unavailable_detail`
- `machine_unavailable_label`
- `daily_session_limit`
- `daily_session_policy`
- `reason`
- `summary`

Notes:

- `target_date` est une **date métier**
- `target_datetime` n'est renseigné que lorsqu'une vraie heure planifiable est disponible

### `sensor.*_etat_de_tonte`

Rôle canonique:

- façade tondeuse + état tonte
- support principal des vues machine de la carte Lovelace

Attributs canoniques:

- `tondeuse_source_entity`
- `tondeuse_nom`
- `tondeuse_statut`
- `tondeuse_statut_libelle`
- `tondeuse_connectee`
- `tondeuse_prete`
- `tondeuse_raison`
- `tondeuse_en_charge`
- `tondeuse_pluie`
- `tondeuse_erreur`
- `tondeuse_erreur_libelle`
- `tondeuse_batterie`
- `tondeuse_prochain_depart`
- `tondeuse_prochain_depart_display`
- `tondeuse_hauteur_coupe_mm`
- `mower_coordination_enabled`
- `mower_coordination_ready`
- `mower_presence_state`
- `mower_presence_label`
- `mower_operation_state`
- `mower_operation_label`
- `mower_is_docked`
- `mower_is_outside`
- `mower_is_safe_for_watering`
- `mower_reason_code`
- `mower_reason_label`
- `mowing_blocked_by_watering`
- `mowing_block_reason_code`
- `mowing_block_reason_label`
- `mowing_cooldown_remaining_minutes`
- `mowing_post_application_active`
- `gazon_permet_tonte`
- `machine_permet_tonte`
- `action_possible`

Alias legacy conservés:

- `tondeuse_erreur_code`
- `mower_error`
- `mower_activity_code`

### `sensor.*_hauteur_de_tonte_conseillee`

Rôle canonique:

- porter la recommandation de hauteur de coupe et son contexte immédiat

Attributs canoniques:

- `hauteur_tonte_min_cm`
- `hauteur_tonte_max_cm`
- `tonte_statut`
- `phase_active`
- `mowing_frequency_target_per_week`
- `mowing_frequency_label`
- `mowing_window_state`
- `mowing_window_label`
- `mowing_window_reason`
- `tondeuse_statut`
- `tondeuse_statut_libelle`
- `tondeuse_batterie`
- `tondeuse_hauteur_coupe_mm`
- `mowing_blocked`
- `mowing_block_reason_code`
- `mowing_block_reason_label`
- `mowing_cooldown_remaining_minutes`

### `sensor.*_reserve_actuelle`

Rôle canonique:

- porter la réserve hydrique utile et ses métriques dérivées

Attributs canoniques:

- `reserve_utile_mm`
- `reserve_stock_mm`
- `reserve_stock_max_mm`
- `reserve_surplus_mm`
- `reserve_fill_ratio`
- `reserve_available_ratio`
- `reserve_minimale_mm`
- `depletion_mm`
- `depletion_ratio`
- `hydric_state`

Alias legacy conservés:

- `reserve_utile_max_mm`
- `reserve_utile_actuelle_mm`
- `reserve_totale_sol_mm`
- `reserve_totale_sol_max_mm`
- `surplus_hydrique_mm`

### `sensor.*_etat_hydrique`

Rôle canonique:

- exposer une synthèse hydrique lisible

Attributs canoniques:

- `reserve_actuelle_mm`
- `reserve_stock_mm`
- `reserve_stock_max_mm`
- `reserve_surplus_mm`
- `reserve_fill_ratio`
- `reserve_available_ratio`
- `reserve_minimale_mm`
- `depletion_mm`
- `depletion_ratio`
- `hydric_state`

Alias legacy conservés:

- `reserve_utile_max_mm`
- `reserve_utile_actuelle_mm`
- `reserve_totale_sol_mm`
- `reserve_totale_sol_max_mm`
- `surplus_hydrique_mm`

### `sensor.*_objectif_d_arrosage`

Rôle canonique:

- exposer le contexte de calcul d'arrosage
- concentrer les métriques agronomiques utilisées pour la décision

Attributs canoniques:

- `phase_active`
- `phase_dominante`
- `sous_phase`
- `bilan_hydrique_mm`
- `bilan_hydrique_journalier_mm`
- `deficit_3j`
- `deficit_7j`
- `pluie_demain`
- `forecast_pluie_j2`
- `forecast_pluie_3j`
- `forecast_probabilite_max_3j`
- `temperature`
- `forecast_temperature_today`
- `etp`
- `et0_mm`
- `kc_gazon`
- `etc_mm`
- `reserve_utile_mm`
- `reserve_actuelle_mm`
- `reserve_stock_mm`
- `reserve_stock_max_mm`
- `reserve_surplus_mm`
- `reserve_fill_ratio`
- `reserve_available_ratio`
- `reserve_minimale_mm`
- `depletion_mm`
- `depletion_ratio`
- `depletion_allowed_mm`
- `mad_ratio`
- `hydric_state`
- `hydric_balance_level`
- `hydric_strategy`

Alias legacy conservés:

- `reserve_utile_max_mm`
- `reserve_utile_actuelle_mm`
- `reserve_totale_sol_mm`
- `reserve_totale_sol_max_mm`
- `surplus_hydrique_mm`
- `reserve_hydrique_sol_mm`

### `sensor.*_sous_phase`

Rôle canonique:

- exposer la sous-phase active et sa progression

Attributs canoniques:

- `phase_dominante`
- `phase_dominante_source`
- `sous_phase_detail`
- `sous_phase_age_days`
- `sous_phase_progression`
- `possible_values`

### `sensor.*_phase_dominante`

Rôle canonique:

- exposer la phase globale et son origine

Attributs canoniques:

- `phase_dominante_source`
- `type_sol`
- `pluie_demain_source`
- `possible_values`

### `sensor.*_risque_gazon`

Rôle canonique:

- exposer le niveau de risque/stress synthétique

Attributs canoniques:

- aucun attribut enrichi obligatoire au-delà de l'état principal

### `sensor.*_prochain_arrosage`

Rôle canonique:

- exposer la prochaine échéance arrosage publique

Attributs canoniques:

- `target_date`
- `target_display`
- `target_datetime`
- `optimal_target_datetime`
- `target_window`
- `target_window_label`
- `next_action`
- `summary`
- `objective_mm`
- `type_arrosage`
- `watering_cause`
- `block_reason`
- `block_reason_label`
- `confidence_score`
- `confidence_reasons`
- `watering_window_display`
- `optimal_window_display`

### `sensor.*_conseil_principal`

Rôle canonique:

- fournir une synthèse façade lisible pour les tableaux de bord et notifications

Attributs canoniques:

- `action_recommandee`
- `action_a_eviter`
- `niveau_action`
- `niveau_action_hydrique`
- `fenetre_optimale`
- `risque_gazon`
- `objectif_mm`
- `type_arrosage`
- `watering_cause`
- `summary`

### `sensor.*_assistant`

Rôle canonique:

- façade canonique runtime transversale

Attributs canoniques:

- `action`
- `moment`
- `quantity_mm`
- `status`
- `reason`
- `next_action_date`
- `next_action_display`
- `gazon_permet_tonte`
- `machine_permet_tonte`
- `mowing_blocked`
- `action_possible`

## Sémantique tonte

Les attributs de tonte ne sont pas interchangeables.

### `tonte_statut`

Statut métier du gazon.

Exemples:

- `autorisee`
- `interdite`
- `a_surveiller`

Il répond à la question:

- **le gazon permet-il la tonte selon les règles métier ?**

### `gazon_permet_tonte`

Booléen métier gazon.

Il répond à la question:

- **côté agronomie et règles du gazon, la tonte est-elle permise ?**

### `machine_permet_tonte`

Booléen machine.

Il répond à la question:

- **la tondeuse est-elle disponible pour accepter une nouvelle action ?**

### `mowing_blocked`

Booléen de blocage contextuel actif.

Il couvre les blocages opérationnels ou transverses:

- délai post-arrosage
- post-produit
- fenêtre nuit
- indisponibilité machine
- autres contraintes runtime

### `action_possible`

Booléen final d'exécutabilité.

Il répond à la question:

- **l'action de tonte peut-elle être lancée maintenant ?**

En pratique:

- `gazon_permet_tonte = true`
- `machine_permet_tonte = false`
- `action_possible = false`

reste un cas cohérent:

- le gazon autorise la tonte
- mais la machine ne peut pas lancer une nouvelle action

### `block_reason`

Code compact de la raison bloquante publique.

Sur `sensor.*_prochaine_tonte`, c'est la raison publique la plus simple à consommer.

Sur les entités tonte plus riches, les couples suivants restent plus détaillés:

- `mowing_block_reason_code`
- `mowing_block_reason_label`

## Différence entre `reason` et `summary`

### `reason`

Détail explicatif principal.

Il doit répondre à:

- **pourquoi agit-on ou attend-on ?**

Exemple:

- `Robot déjà en tonte: attendre la fin du cycle en cours.`

### `summary`

Synthèse courte orientée affichage.

Il doit répondre à:

- **que faut-il retenir ou afficher rapidement ?**

Exemples:

- `Tonte possible après le délai post-arrosage`
- `Tonte à reconsidérer le 21/05/2026`

État actuel assumé:

- `summary` peut être identique à `reason`
- cette redondance est volontairement tolérée pour compatibilité
- une future divergence entre les deux devra être introduite comme évolution explicite de contrat

## Alias hydriques

Ces alias sont conservés pour compatibilité historique et pour des dashboards existants.

| Alias legacy | Canonique |
|---|---|
| `reserve_utile_actuelle_mm` | `reserve_actuelle_mm` |
| `reserve_utile_max_mm` | `reserve_utile_mm` |
| `reserve_totale_sol_mm` | `reserve_stock_mm` |
| `reserve_totale_sol_max_mm` | `reserve_stock_max_mm` |
| `surplus_hydrique_mm` | `reserve_surplus_mm` |
| `reserve_hydrique_sol_mm` | contexte ancien, proche de `bilan_hydrique_mm` ou lecture hydrique legacy selon l'entité |

Règle cible:

- les nouvelles intégrations, cartes ou automatisations devraient lire les attributs canoniques
- les alias restent exposés tant qu'une migration utilisateur explicite n'a pas été menée

## Alias legacy conservés pour compatibilité

### Tonte et blocage

- `raison_blocage_code`
  - canonique proche: `mowing_block_reason_code` ou `block_reason`
  - raison: compatibilité FR/historique
- `raison_blocage_tonte`
  - canonique proche: `mowing_block_reason_label` ou `reason`
  - raison: compatibilité FR/historique
- `mowing_block_reason`
  - canonique: `mowing_block_reason_code`
  - raison: ancien doublon de code de blocage

### Tondeuse

- `tondeuse_erreur_code`
  - canonique: `tondeuse_erreur`
  - raison: compatibilité carte
- `mower_error`
  - canonique: `tondeuse_erreur`
  - raison: alias neutre côté UI/API
- `mower_activity_code`
  - canonique: `mower_operation_state`
  - raison: compatibilité carte

### Hydrique

- `reserve_utile_actuelle_mm`
  - canonique: `reserve_actuelle_mm`
- `reserve_utile_max_mm`
  - canonique: `reserve_utile_mm`
- `reserve_totale_sol_mm`
  - canonique: `reserve_stock_mm`
- `reserve_totale_sol_max_mm`
  - canonique: `reserve_stock_max_mm`
- `surplus_hydrique_mm`
  - canonique: `reserve_surplus_mm`
- `reserve_hydrique_sol_mm`
  - canonique proche: attribut legacy hydrique, à documenter au cas par cas selon l'entité

## Candidats à dépréciation future

Ces attributs ne doivent **pas** être supprimés maintenant, mais sont de bons candidats à une dépréciation progressive:

- `mowing_block_reason`
- `reserve_utile_actuelle_mm`
- `reserve_utile_max_mm`
- `reserve_totale_sol_mm`
- `reserve_totale_sol_max_mm`
- `surplus_hydrique_mm`
- `reserve_hydrique_sol_mm`

Les couples suivants peuvent aussi être visés plus tard, **uniquement** après migration documentée:

- `raison_blocage_code`
- `raison_blocage_tonte`

## Stratégie de migration progressive

### Phase 1

- documenter le contrat canonique
- garder tous les alias legacy
- ne rien casser

### Phase 2

- faire lire en priorité les attributs canoniques par la carte et les exemples officiels
- conserver les alias en miroir
- documenter les alias comme "legacy"

### Phase 3

- annoncer la dépréciation dans les notes de version
- auditer la carte, les docs, les exemples et les automatisations de référence
- ne supprimer que dans une version ultérieure avec migration explicitement annoncée

## Règle de compatibilité

Tant qu'un attribut public est:

- utilisé par la carte Lovelace
- utilisé par une automatisation/script de référence
- ou d'usage utilisateur inconnu

il doit être considéré comme **à conserver**, sauf migration préparée et documentée.
