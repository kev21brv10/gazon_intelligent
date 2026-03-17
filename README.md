# Gazon Intelligent

Intégration Home Assistant pour gérer les modes gazon :

- Normal
- Sursemis
- Traitement
- Fertilisation
- Biostimulant
- Agent Mouillant
- Scarification
- Hivernage

## Fonctionnalités

- Configuration UI
- Sélection des entités
- Calcul automatique de l'objectif d'arrosage
- Autorisation tonte / arrosage automatique
- Gestion des phases gazon

## Entités créées

- Mode gazon
- Objectif d'arrosage
- Jours restants de la phase
- Tonte autorisée
- Arrosage automatique autorisé
- Bouton retour au mode normal

## Installation simple

1. Copier `custom_components/gazon_intelligent` dans le dossier `custom_components` de Home Assistant (ou installer via HACS si tu publies le repo).
2. Redémarrer Home Assistant.
3. Dans *Paramètres → Appareils et services → Ajouter une intégration*, choisir **Gazon Intelligent**.

## Configuration (ce qui est demandé)

- Zone 1 (obligatoire) + Zones 2 à 5 (optionnelles) : ce sont tes `switch` d’électrovannes.
- Tondeuse (optionnel).
- Capteur pluie 24h (obligatoire), pluie demain / température / ETP (optionnels).
- Débit par zone (mm/min) : combien de millimètres d’eau la zone apporte en 1 minute. Si tu ne sais pas, laisse 1.0 (tu affineras plus tard).

## Entités créées

- Sélecteur de mode gazon (Normal, Sursemis, Traitement, Fertilisation, Biostimulant, Agent Mouillant, Scarification, Hivernage).
- Capteur `Objectif d'arrosage` (mm).
- Capteur `Jours restants de la phase`.
- Binaire `Tonte autorisée`.
- Binaire `Arrosage automatique autorisé`.
- Bouton `Repasser en mode normal`.

Toutes les entités sont rattachées à un appareil « Gazon Intelligent » pour permettre le renommage persistant.

## Services

- `gazon_intelligent.set_mode` (`mode` parmi la liste ci-dessus).
- `gazon_intelligent.set_date_action` (`date_action` au format `AAAA-MM-JJ`).
- `gazon_intelligent.reset_mode` (revient en Normal).
- `gazon_intelligent.start_manual_irrigation` (`objectif_mm` float, 0‑30).
- `gazon_intelligent.start_auto_irrigation` (objectif optionnel, utilise l'objectif calculé si omis). Lance chaque zone en séquence en convertissant l'objectif mm en durée selon le débit renseigné.

## Événement

`gazon_intelligent_manual_irrigation_requested` émis lors de `start_manual_irrigation` avec `objectif_mm`, `mode`, `date_action`.

### Exemple d'automatisation pour déclencher une scène d'arrosage

```yaml
alias: Arrosage manuel gazon
mode: single
trigger:
  - platform: event
    event_type: gazon_intelligent_manual_irrigation_requested
action:
  - service: gazon_intelligent.start_auto_irrigation
    data: {}

# Variante : imposer 2 mm d'eau
#  - service: gazon_intelligent.start_auto_irrigation
#    data:
#      objectif_mm: 2
```
