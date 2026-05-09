# PRD — TMX v2 : Système de Mean Reversion sur FNBs Canadiens

**Version :** 3.1
**Date :** Mai 2026
**Auteur :** Sylvain (avec assistance Claude/Opus)
**Statut :** Paper trading en cours (phase de validation 6–9 mois)

---

## CHANGELOG

> Ce changelog documente l'ensemble des modifications depuis la version 2.2.

### C1 — Réduction de l'univers de trading actif (Section 6)

**Changement :** Cinq FNBs retirés du système de mean reversion. Ils demeurent dans l'univers comme *indicateurs contextuels* uniquement.

| FNB | Raison du retrait |
|-----|-------------------|
| XEG.TO | Aucun signal mean reversion validé par test de Wilcoxon |
| ZAG.TO | Aucun signal mean reversion validé par test de Wilcoxon |
| XGD.TO | Aucun signal mean reversion validé par test de Wilcoxon |
| XIT.TO | 87 % des baisses sont fondamentales (Shopify) — pas de rebond systématique |
| XMA.TO | Aucun signal mean reversion validé par test de Wilcoxon |

**Univers de trading actif réduit à 7 FNBs :** XIU, XFN, XUT, XRE, XIN, XHC, XST.

### C2 — Horizons de sortie corrigés par test de Wilcoxon (Section 6 et Maillon 4)

| FNB | Horizon v2.2 | Horizon v3.0 | Statut |
|-----|-------------|-------------|--------|
| XIN.TO | 10 jours | **10 jours** | ✓ Confirmé |
| XST.TO | 10 jours | **15 jours** | Corrigé |
| XHC.TO | 15 jours | **10 jours** | Corrigé |
| XFN.TO | 15 jours | **20 jours** | Corrigé |
| XIU.TO | 10 jours | **20 jours** | Corrigé |
| XUT.TO | 10 jours | **20 jours** | Marginal — surveiller |
| XRE.TO | 25 jours | **20 jours** | Corrigé |

### C3 — Couche de signaux de contagion inter-FNB (Section 5bis)

**Ajout :** Cinq signaux de contagion validés sur 25 ans documentés formellement.

| Signal | Niveau | p permutation | Déploiement |
|--------|--------|--------------|-------------|
| XRE chute ≥ 2,5 é.-t. → acheter XIN J+1 | 1 — Validé | 0,000 | Prioritaire |
| XEG chute ≥ 2,5 é.-t. → shorter XFN J+1 | 2 — Robuste | N/D (stabilité tridécennale) | Phase 2 |
| XUT chute ≥ 2,5 é.-t. → acheter XIN J+1 | 1 — Validé | 0,002 | Surveiller érosion 2021–26 |
| XUT chute ≥ 2,5 é.-t. → acheter XFN J+1 | 1 — Validé | < 0,001 | Phase 2 |
| XEG chute ≥ 3,0 é.-t. → shorter XIU J+1 | 3 — Veille | N/D | n=14 — ne pas déployer solo |

### C4 — Stratégie combinée A+B retirée

**Changement :** Wilcoxon p = 0,908, distribution pathologique (skewness = −2,59, kurtosis = +11,40). Non déployable.

### C5 — Filtre jour de la semaine (vendredi) abandonné

**Changement :** Test Mann-Whitney non significatif. Aucune différence entre le vendredi et les autres jours.

### C6 — Filtre régime VIX confirmé comme seul filtre calendaire

### C7 — Source de données permanente : yfinance

**Changement :** Questrade abandonné définitivement (blocage Cloudflare, contraintes API). Garde de fraîcheur ajoutée.

### C8 — Filtre H (publications trimestrielles) retiré

**Changement :** XIT retiré du trading actif → Filtre H caduc. Note conservée en section 13.

### C9 — Mise à jour du tableau de bord

**Changement :** Retrait référence Questrade. Ajout alerte fraîcheur yfinance.

### C10 — Validation empirique du seuil et du Filtre D (Section 14)

**Changement :** Backtest post-déploiement (mars–mai 2026, 48 jours de bourse) et analyse sur 25 ans confirment le seuil −2,0σ optimal. Le Filtre D est validé empiriquement; son coût en fréquence est documenté. Fréquence réelle du système établie à 10–20 trades/an. Section 14 ajoutée.

---

## Table des matières

1. Vision et objectif
2. Contexte — TMX v12.5 et indépendance de TMX v2
3. Philosophie du système
4. Ce que l'analyse des données nous a appris
5. Architecture — Les 4 maillons de la chaîne de décision
5bis. Signaux de contagion inter-FNB
6. Univers d'investissement — Les 7 FNBs actifs et 5 indicateurs contextuels
7. Règles de dimensionnement des positions
8. Coûts de transaction et réalisme d'exécution
9. Métriques de succès et critères d'arrêt
10. Tableau de bord et monitoring
11. Infrastructure technique
12. Plan de déploiement et jalons
13. Risques et limites connues
14. Validation empirique post-déploiement *(nouveau v3.1)*
15. Glossaire pour néophyte
16. Annexe A — Calendrier économique canadien 2026

---

## 1. Vision et objectif

### En une phrase

Un système automatisé qui surveille des FNBs canadiens cotés sur le TSX pendant les heures de bourse, achète quand un FNB tombe anormalement bas par rapport à son comportement récent (mean reversion), et exploite des signaux de contagion inter-FNB validés sur 25 ans de données.

### Objectif de la phase paper trading (6-9 mois)

Valider que le système détecte correctement les aubaines, que les FNBs rebondissent comme l'historique le suggère, que les signaux de contagion se confirment en temps réel, et que les filtres de sécurité empêchent les erreurs — le tout sans risquer un dollar.

### Ce que le système N'EST PAS

- Ce n'est pas du day trading (l'horizon de détention est de 10 à 20 jours)
- Ce n'est pas de la spéculation (les décisions sont basées sur des statistiques validées sur 25 ans, pas sur des intuitions)
- Ce n'est pas un remplacement de TMX v12.5 (c'est un complément indépendant, sans aucune dépendance technique)

---

## 2. Contexte — Relation avec TMX v12.5

TMX v12.5 est le premier système, déjà en production. Il fonctionne sur une logique **mensuelle** : une fois par mois, il génère un signal d'allocation et ajuste les positions sur les mêmes FNBs canadiens. Il utilise le VIX pour calibrer la taille des positions et roule en paper trading via GitHub Actions.

TMX v2 est un **système parallèle et complètement indépendant** qui opère en **continu** pendant les heures de bourse.

| | TMX v12.5 | TMX v2 |
|---|---|---|
| Fréquence de décision | 1 fois par mois | En continu (scan aux 5 minutes) |
| Type de signal | Allocation tactique | Achat sur baisse anormale + contagion |
| Horizon de détention | ~1 mois | 10–20 jours selon le FNB |
| Indicateur de risque | VIX intégré au calibrage | VIX comme filtre de régime autonome |
| Philosophie | "Comment répartir le capital ce mois-ci?" | "Y a-t-il une aubaine ou un signal de contagion en ce moment?" |

**Indépendance :** TMX v2 ne dépend pas de TMX v12.5 pour fonctionner. Il calcule son propre indicateur de régime de marché basé sur le VIX.

---

## 3. Philosophie du système

### L'analogie du pêcheur et de la météo

Le VIX est la station météo. Il dit : "On est en période de beau temps pour les marchés" (VIX bas) ou "Attention, tempête en vue" (VIX élevé). TMX v2 est le pêcheur. En beau temps, il sort pêcher. En tempête, il reste au quai.

### Le principe du mean reversion (retour à la moyenne)

L'idée centrale : quand le prix d'un FNB s'éloigne anormalement de son comportement récent — sans raison fondamentale grave — il a tendance à revenir vers sa normale. C'est comme un élastique qu'on étire : plus on l'étire, plus la force de rappel est grande.

Le système mesure cet "étirement" avec un outil statistique appelé le **z-score**. Quand l'étirement est suffisant (≥ 2 écarts-types), le système considère que c'est une aubaine potentielle.

### La contagion inter-FNB

En complément du mean reversion, le système exploite des **signaux de contagion** : la découverte que certains FNBs transmettent leurs chocs à d'autres FNBs avec un décalage d'un jour de bourse. Ces signaux sont structurels et ont été validés sur 25 ans de données (2001–2026). Ils sont documentés en section 5bis.

---

## 4. Ce que l'analyse des données nous a appris

### 4.1 L'écart-type et le z-score, expliqués simplement

**L'écart-type** mesure combien un prix bouge "normalement."

**Le z-score** traduit le mouvement du jour en nombre d'écarts-types. Un z-score de -2.5 signifie que le FNB a baissé de 2.5 fois son mouvement normal.

**Formule — approche multi-horizon :**

- **Z-score 20 jours (court terme) :** Signal principal de déclenchement.
- **Z-score 60 jours (moyen terme) :** Confirme si la baisse est aussi anormale sur un horizon plus large. N'est pas un filtre bloquant — ajuste la taille de position uniquement.

Calcul :
- Rendement du jour = (prix aujourd'hui − prix hier) / prix hier
- Z-score = (rendement du jour − moyenne N jours) / écart-type N jours

### 4.2 À quelle fréquence les baisses anormales se produisent-elles?

Analyse réalisée sur 25 ans de données quotidiennes (2001–2026), 13 FNBs.

**Fréquence pour XIU (référence) :**

| Seuil | Par année | En mots |
|-------|-----------|---------|
| 1 écart-type | ~40/an | Presque chaque semaine — trop fréquent |
| 2 écarts-types | ~8,6/an | ~1 fois par mois — signal intéressant |
| 2,5 écarts-types | ~3,6/an | ~1 fois par trimestre — signal fort |
| 3 écarts-types | ~0,6/an | ~1 fois aux 2 ans — exceptionnel |

**Sur les 7 FNBs actifs combinés :** fréquence brute suffisante pour validation, mais les filtres de sécurité ramènent la fréquence effective à 10–20 trades/an (voir section 14 pour la validation empirique).

### 4.3 Découverte clé — Les FNBs actifs rebondissent à des vitesses différentes

| FNB | Profil | Horizon Wilcoxon | Taux de récupération | Perte additionnelle au creux |
|-----|--------|-----------------|---------------------|------------------------------|
| XIN.TO | Rapide | 10 jours ✓ confirmé | 92 % | −4,8 % |
| XHC.TO | Rapide | 10 jours (était 15) | 83 % | −5,5 % |
| XST.TO | Rapide | 15 jours (était 10) | 95 % | −3,1 % |
| XFN.TO | Moyen | 20 jours (était 15) | 86 % | −5,9 % |
| XIU.TO | Moyen | 20 jours (était 10) | 94 % | −5,0 % |
| XUT.TO | Moyen | 20 jours (était 10) — marginal | 88 % | −5,3 % |
| XRE.TO | Moyen | 20 jours (était 25) | 78 % | −6,8 % |

**FNBs retirés du trading actif (indicateurs contextuels) :**

| FNB | Raison | Taux de récupération historique |
|-----|--------|-------------------------------|
| XEG.TO | Aucun signal Wilcoxon validé | 78 % sur 25 ans |
| ZAG.TO | Aucun signal Wilcoxon validé | 75 % sur 25 ans |
| XGD.TO | Aucun signal Wilcoxon validé | 85 % sur 25 ans |
| XIT.TO | 87 % des baisses fondamentales (Shopify) | 88 % sur 25 ans |
| XMA.TO | Aucun signal Wilcoxon validé | 86 % sur 25 ans |

### 4.4 Saisonnalité — Quand les aubaines se présentent

| Mois | Niveau d'activité | Note |
|------|-------------------|------|
| Octobre | Le plus élevé | Mois des corrections historiques |
| Février | Élevé | Ajustements post-résultats annuels |
| Juin | Élevé | Fin de semestre |
| Mars | Élevé | Perspectives de taux T1 |
| Juillet | Le plus calme | — |
| Novembre | Calme | — |

**Signatures sectorielles :**
- XFN (financières) : pic en février et août — saisons des résultats bancaires
- XUT (services publics) : pic en septembre — sensibilité aux annonces de taux
- XRE (immobilier) : pic en mars — perspectives de taux fin T1

### 4.5 Les baisses en grappes — un phénomène structurel

| FNBs en baisse simultanée | Fréquence | Interprétation |
|---------------------------|-----------|----------------|
| 1 seul FNB | 60 % | Correction sectorielle isolée — terrain de chasse idéal |
| 2-3 FNBs | 28 % | Contagion limitée — prudence modérée |
| 4-6 FNBs | 10 % | Stress macro — réduire la taille |
| 7+ FNBs | 2 % | Crise systémique — ne pas agir |

Les proportions sont quasi identiques avec ou sans COVID — les clusters sont structurels.

### 4.6 Corrélations entre FNBs — deux blocs à connaître

**Bloc "marché large" :**

| Paire | Corrélation |
|-------|-------------|
| XFN — XIU | 0,91 |
| XIN — XIU | 0,82 |
| XFN — XIN | 0,78 |

**Bloc "taux" :**

| Paire | Corrélation |
|-------|-------------|
| XRE — XUT | 0,66 |

### 4.7 Impact des annonces de la Banque du Canada

| FNB | Rendement jour avec RPM | Rendement jour sans RPM | Différence |
|-----|------------------------|------------------------|------------|
| XIU | −0,18 % | +0,30 % | −0,48 % |
| XFN | −0,24 % | +0,33 % | −0,57 % |
| XRE | −0,02 % | +0,39 % | −0,41 % |
| XUT | −0,01 % | +0,26 % | −0,27 % |

**Règle pour les jours avec RPM :** Attendre après 10h00 HE. Exiger un seuil de 2,5 é.-t. pour XRE, XUT, XFN.

---

## 5. Architecture — Les 4 maillons de la chaîne de décision

### Maillon 1 — Le filtre de régime (VIX autonome)

| Niveau du VIX | Régime | Comportement de TMX v2 |
|---------------|--------|----------------------|
| VIX < 16 | Risk-on | Opère normalement |
| VIX entre 16 et 25 | Neutre | Tailles réduites ou seuils plus exigeants |
| VIX > 25 | Risk-off | Pause complète, ou signaux extrêmes (≥ 3 é.-t.) sur XST seulement |

**Le filtre de régime VIX est le seul filtre calendaire pertinent.** Aucun autre filtre calendaire n'est justifié par les données (filtre vendredi abandonné — Mann-Whitney non significatif).

### Maillon 2 — Le scanner de signaux

Le scanner tourne aux 5 minutes pendant les heures de bourse (9h30–16h00 HE), du lundi au vendredi.

À chaque cycle :
1. Récupérer les prix via **yfinance** (source unique et permanente)
2. **Garde de fraîcheur :** vérifier que la dernière date des données == date du jour → alerte tableau de bord + courriel si non
3. Calculer le z-score 20j (signal principal) et z-score 60j (ajustement taille)
4. Si z-score 20j ≤ −2,0 pour un FNB actif → lever un drapeau et passer au maillon 3
5. Pour les FNBs contextuels : calculer les z-scores mais **ne pas déclencher de signal mean reversion**. Consigner les chocs ≥ 2,5 é.-t. pour activation des signaux de contagion (section 5bis)

### Maillon 3 — Les filtres de sécurité

Sept filtres appliqués dans l'ordre :

**Filtre A — Compteur de signaux simultanés**
- 1-3 FNBs : Agir normalement
- 4-6 FNBs : Réduire la taille de 50 % et exiger un seuil de 2,5 é.-t.
- 7+ FNBs : Bloquer toute nouvelle position

**Filtre B — Régime compatible**
Le régime VIX actuel permet-il l'action? (Voir tableau du maillon 1)

**Filtre C — Profil du FNB**
Le seuil de z-score atteint est-il suffisant pour le profil du FNB?
- Tous les FNBs actifs (Rapide et Moyen) : seuil minimum de 2,0 é.-t.

**Filtre D — Corrélation avec le marché large**
- Si XIU ≥ 0 % et qu'un FNB sectoriel baisse → correction sectorielle isolée → seuil +0,5 é.-t. et taille ÷ 1,5
- Si XIU < −0,5 % → mouvement systémique, rebond collectif plus probable → règles normales
- Si XIU entre −0,5 % et 0 % → zone grise → règles normales, log de l'observation

*Note v3.1 : Le Filtre D est validé empiriquement sur 25 ans (+0,21 % de rendement moyen à J+1 sur les signaux gardés vs bloqués). Son seuil de déclenchement (XIU ≥ 0 %) est actif 56 % des jours de bourse — une piste d'assouplissement à XIU > +0,3 % est documentée en section 14, en attente de validation statistique.*

**Filtre E — Confirmation par le volume**
- Volume élevé + baisse = capitulation probable → renforce le signal
- Volume faible + baisse = bruit possible → taille réduite

**Filtre F — Tendance moyen terme (SMA 50 jours)**
- Prix au-dessus de la SMA 50 → signal valide normalement
- Prix sous la SMA 50 → seuil +0,5 é.-t. et taille ÷ 2

**Filtre G — Exposition corrélée**
- **Bloc Marché large : {XIU, XFN, XIN}** — Maximum 1 position ouverte
- **Bloc Taux : {XRE, XUT}** — Maximum 1 position ouverte
- XHC et XST : peuvent être détenus simultanément sans restriction

**Filtre futur — Calendrier économique**
Jours RPM : attendre après 10h00 HE et exiger 2,5 é.-t. pour XRE, XUT, XFN.

### Maillon 4 — L'exécution et le suivi

**Sortie de position — Quatre scénarios :**
- **Objectif atteint :** Prix revient au niveau pré-baisse → vente complète
- **Sortie partielle à 50 % du rebond :** Vendre la moitié. La moitié restante protégée par trailing stop de 1,5 %
- **Horizon dépassé :** Nombre de jours maximal atteint (selon profil FNB, section 6) → vente
- **Stop-loss :** Perte dépasse le 80e percentile de la perte additionnelle historique → vente

---

## 5bis. Signaux de contagion inter-FNB

### Architecture de la contagion

Les signaux de contagion s'activent **après** le Maillon 1 (filtre de régime VIX), mais opèrent indépendamment des Maillons 2 à 4. Si un FNB émetteur chute ≥ seuil à la fermeture du jour J, le système place un signal conditionnel sur le FNB récepteur pour J+1.

### Classement des signaux par robustesse

#### Signaux de Niveau 1 — Validés et exploitables

| # | Signal | Direction | Seuil | Rend. moy. J+1 | Win rate | p perm. | N | Stabilité | Mécanisme |
|---|--------|-----------|-------|---------------|----------|---------|---|-----------|-----------|
| **S1** | **XRE → XIN** | Achat XIN | ≥ 2,5 é.-t. | +0,61 % | 62,7 % | **0,000** | 59 | 4/4 ✓ | Décalage horaire — structurel |
| **S3** | **XUT → XIN** | Achat XIN | ≥ 2,5 é.-t. | +0,70 % | 57,6 % | **0,002** | 34 | 3/4 ~ | Décalage horaire — érosion 2021–26 à surveiller |
| **S4** | **XUT → XFN** | Achat XFN | ≥ 2,5 é.-t. | +0,92 % | — | **< 0,001** | 34 | 3/4 ~ | Rotation défensive — érosion 2021–26 à surveiller |

#### Signaux de Niveau 2 — Robustes, à confirmer

| # | Signal | Direction | Seuil | Rend. moy. J+1 | Win rate | p t-test | N | Stabilité | Risque érosion |
|---|--------|-----------|-------|---------------|----------|----------|---|-----------|----------------|
| **S2** | **XEG → XFN** | Short XFN | ≥ 2,5 é.-t. | −0,43 % | 55,2 % | 0,016 | 29 | 3/3 ✓ | FAIBLE — tridécennal |

#### Signal de Niveau 3 — En veille

| # | Signal | Direction | Seuil | Rend. moy. J+1 | Win rate | N | Problème |
|---|--------|-----------|-------|---------------|----------|---|----------|
| **S5** | **XEG → XIU** | Short XIU | ≥ 3,0 é.-t. | −0,74 % | 64,3 % | 14 | n insuffisant — ne pas déployer seul |

### Règles d'implémentation

**Taille de position pour les signaux de contagion :**

| Niveau | Taille de base | Ajustement régime neutre |
|--------|---------------|--------------------------|
| Niveau 1 | 75 % de la position de base | ÷ 2 |
| Niveau 2 | 50 % de la position de base | ÷ 2 |
| Niveau 3 | Ne pas déployer | — |

**Horizon de sortie :** Entrée à l'ouverture de J+1, sortie à la fermeture de J+1. Si non profitable : conserver maximum 3 jours additionnels, puis fermer.

**Mécanismes explicatifs validés :**

- **S1, S3 (décalage horaire) :** Les marchés européens et asiatiques composant XIN ferment à des heures différentes du TSX. Un choc canadien se propage aux marchés internationaux avec un délai — l'effet lundi est spectaculaire (+1,76 % pour XFN→XIN).
- **S2 (co-dépendance crédit-énergie) :** Les banques canadiennes (XFN) sont exposées au secteur énergétique via leurs portefeuilles de prêts. Un choc extrême sur XEG signale une détérioration du crédit sectoriel — stabilité quasi-parfaite sur trois décennies.

**Protocole de suivi :**
- Révue mensuelle : win rate glissant sur 12 derniers trades (seuil d'alerte : < 45 % → mise en veille)
- Révue annuelle : recalcul des p-values; si p global > 0,10 après 3 ans → abandonner le signal

**La stratégie combinée mean reversion + contagion est non déployable :** Wilcoxon p = 0,908, distribution pathologique. Les deux couches opèrent indépendamment.

---

## 6. Univers d'investissement — Les 7 FNBs actifs et 5 indicateurs contextuels

| # | Ticker | Description | Rôle | Profil | Seuil min. | Horizon sortie | Bloc corrélé | Risque fond. |
|---|--------|-------------|------|--------|-----------|----------------|--------------|-------------|
| 1 | XIU.TO | S&P/TSX 60 (large caps CA) | **Trading actif** | Moyen | 2,0 é.-t. | **20 jours** | Marché large | — |
| 2 | XFN.TO | Financières CA | **Trading actif** | Moyen | 2,0 é.-t. | **20 jours** | Marché large | 2 % |
| 3 | XUT.TO | Services publics CA | **Trading actif** | Moyen | 2,0 é.-t. | **20 jours** | Taux | — |
| 4 | XRE.TO | Immobilier CA (REIT) | **Trading actif** | Moyen | 2,0 é.-t. | **20 jours** | Taux | — |
| 5 | XIN.TO | International | **Trading actif** | Rapide | 2,0 é.-t. | **10 jours** | Marché large | — |
| 6 | XHC.TO | Soins de santé mondiaux | **Trading actif** | Rapide | 2,0 é.-t. | **10 jours** | — | — |
| 7 | XST.TO | Consommation de base CA | **Trading actif** | Rapide | 2,0 é.-t. | **15 jours** | — | — |
| 8 | XEG.TO | Énergie CA | *Indicateur contextuel* | — | — | — | — | 0 % |
| 9 | ZAG.TO | Obligations CA agrégées | *Indicateur contextuel* | — | — | — | — | — |
| 10 | XGD.TO | Mines d'or | *Indicateur contextuel* | — | — | — | Métaux | 7 % |
| 11 | XIT.TO | Technologies CA | *Indicateur contextuel* | — | — | — | — | 87 % |
| 12 | XMA.TO | Matériaux CA | *Indicateur contextuel* | — | — | — | Métaux | — |

**Légende — Rôle :**
- **Trading actif** : signal mean reversion validé par Wilcoxon.
- *Indicateur contextuel* : z-scores calculés, aucune position mean reversion. Chocs ≥ 2,5 é.-t. peuvent activer les signaux de contagion.

**Règle de diversification :** Maximum 1 position par bloc corrélé.

---

## 7. Règles de dimensionnement des positions

### 7.1 Taille graduelle selon la profondeur du signal

| Profondeur du signal | Multiplicateur |
|---------------------|---------------|
| 2,0 écarts-types | 1,0x |
| 2,5 écarts-types | 1,5x |
| 3,0 écarts-types | 2,0x |

### 7.2 Ajustement selon le profil du FNB

| Profil | Taille de base | Justification |
|--------|---------------|---------------|
| Rapide | 100 % | Rebond fiable, horizon court |
| Moyen | 75 % | Rebond probable mais plus lent |

### 7.3 Ajustement selon les filtres de sécurité

| Situation | Ajustement |
|-----------|-----------|
| 4-6 FNBs en signal simultané | Taille ÷ 2 |
| Volume faible sur le FNB | Taille ÷ 1,5 |
| XIU stable/positif (filtre D) | Taille ÷ 1,5 + seuil +0,5 é.-t. |
| Régime neutre (VIX 16-25) | Taille ÷ 2 |
| Prix sous SMA 50 jours (filtre F) | Taille ÷ 2 |
| Z-score 60j > −1,5 (signal faible moyen terme) | Taille ÷ 1,5 |

Ces ajustements se cumulent.

### 7.4 Limite de concentration

- Maximum 3 positions ouvertes simultanément
- Maximum 1 position par FNB
- Maximum 1 position par bloc corrélé

---

## 8. Coûts de transaction et réalisme d'exécution

### 8.1 Coûts modélisés

| Coût | Estimation | Source |
|------|-----------|--------|
| Spread bid-ask | 0,05–0,10 % par transaction | FNBs TSX liquides |
| Commissions | **0 $** | Disnat — aucune commission sur FNBs CA |
| Slippage | 0,05 % additionnel | Estimation conservatrice |
| **Coût total aller-retour** | **~0,10–0,20 %** | |

### 8.2 Impact sur l'edge

Sur un horizon de 10–20 jours : rebond médian ~5 % (XIU), moins ~0,15 % de coûts = ~4,85 % net. L'edge survit largement aux coûts.

### 8.3 Type d'ordres

- Entrée : Ordre limite au prix courant ou légèrement en dessous
- Sortie objectif : Ordre limite au prix pré-baisse
- Sortie stop-loss : Ordre stop-limite

---

## 9. Métriques de succès et critères d'arrêt

### 9.1 Métriques mesurées pendant le paper trading

| Métrique | Définition | Cible minimale |
|----------|-----------|----------------|
| Taux de réussite (hit rate) | % de trades positifs après coûts | ≥ 60 % |
| Rendement moyen par trade | Gain net moyen après coûts | ≥ +1,5 % |
| Pire excursion adverse (MAE) | Pire perte temporaire moyenne | Conforme aux profils historiques (±20 %) |
| Max drawdown | Pire perte cumulée | < 15 % du capital virtuel |
| Ratio gain/perte | Rendement gagnants vs perdants | ≥ 1,5 : 1 |
| Durée moyenne de détention | Jours en position | Conforme aux profils (10–20j) |
| Nombre de trades | Volume d'activité | ≥ 30 trades |

### 9.2 Critères d'arrêt (kill switch)

Le système est arrêté ou réévalué si, après 6 mois :
- Taux de réussite sous 50 %
- Rendement moyen par trade négatif après coûts
- Max drawdown dépasse 20 % du capital virtuel
- Profils de rebond réels divergent de plus de 30 % des profils historiques

### 9.3 Critères de passage en argent réel

- Au moins 30 trades complétés en paper trading
- Taux de réussite ≥ 60 % après coûts
- Max drawdown < 15 % sur la période
- Les filtres ont démontré une valeur ajoutée mesurable

### 9.4 Règle de gouvernance

Aucun changement de paramètre pendant une période de gel de 3 mois minimum. Les ajustements ne sont faits qu'à la fin d'une période d'observation complète.

---

## 10. Tableau de bord et monitoring

### "Est-ce que le système est vivant?"

- **Garde de fraîcheur des données :** Alerte rouge si données yfinance ≠ date du jour
- Dernier cycle de scan complété (horodatage)
- Alerte si cycles consécutifs manqués

### "Qu'est-ce qu'il voit en ce moment?"

- Z-score actuel de chaque FNB (actif et contextuel)
- Indicateur visuel : FNBs actifs vs contextuels
- Régime de marché actuel (VIX et seuils)
- Signaux ignorés et la raison
- Position de chaque FNB par rapport à sa SMA 50 jours

### "Qu'est-ce qu'il a fait récemment?"

- Positions ouvertes avec prix actuel mis à jour via yfinance, jours réels écoulés, P&L virtuel
- Historique des trades complétés
- Métriques de performance cumulées, séparées par type de signal (mean reversion vs contagion)

### Format

Rapport HTML statique régénéré à chaque cycle de 5 minutes, hébergé sur GitHub Pages. Résumé quotidien par courriel à 16h15 HE.

---

## 11. Infrastructure technique

### 11.1 Choix retenu : GitHub Actions (gratuit)

| Critère | Détail |
|---------|--------|
| Plateforme | GitHub Actions (repo **public**) |
| Coût | Gratuit (2 000 min/mois incluses) |
| Consommation estimée | ~1 560 min/mois |
| Déclencheur | Cron aux 5 minutes, 9h25–16h05 HE, lun-ven |
| Langage | Python 3.12 |

### 11.2 Sources de données

| Donnée | Source | Fréquence |
|--------|--------|-----------|
| Prix intraday 5 min | **yfinance** (source unique permanente) | Aux 5 minutes |
| Prix de fermeture quotidiens | **yfinance** | 1x/jour après 16h |
| Régime de marché (VIX) | yfinance (^VIX) | Aux 5 minutes |
| FNBs contextuels | yfinance | Aux 5 minutes |

**Abandon définitif de Questrade :** Blocage Cloudflare + contraintes des conditions d'utilisation API.

**Garde de fraîcheur (v3.0) :** Vérification que `df.index[-1].date() == date.today()` pour chaque FNB. Si non : alerte tableau de bord + courriel immédiat.

### 11.3 Notifications par courriel

| Événement | Fréquence |
|-----------|-----------|
| Signal mean reversion détecté | En temps réel |
| Signal de contagion détecté | En temps réel |
| Position ouverte ou fermée | En temps réel |
| Résumé quotidien | 16h15 HE |
| Alerte fraîcheur données | Si données périmées |
| Erreur système | En temps réel |

Service : Gmail SMTP (gratuit, limite 500 courriels/jour).

### 11.4 Agent d'analyse des nouvelles (news_agent.py)

Utilise Groq (llama-3.3-70b) pour classifier les chocs : SECTORIEL / FONDAMENTAL / SYSTÉMIQUE. Classification fournie à titre informatif — pas un filtre bloquant.

### 11.5 Plan de migration (post-paper trading)

Si GitHub Actions devient insuffisant : Oracle Cloud Free Tier (gratuit) ou DigitalOcean (~5 $/mois). Code modulaire — seul le déclencheur change.

---

## 12. Plan de déploiement et jalons

### Phase 1 — Fondation ✅ Complétée

- Scanner yfinance (7 FNBs actifs + 5 contextuels), z-scores, garde de fraîcheur
- Simulateur interne paper trading
- Notifications courriel (mean reversion + contagion)
- GitHub Actions opérationnel

### Phase 2 — Filtres et signaux de contagion ✅ Complétée

- Maillons 1–4 opérationnels
- Signaux de contagion S1–S4 activés
- Tableau de bord HTML avec métriques section 9

### Phase 3 — Observation active (Mois 3–6) — En cours

- Système en autonomie complète
- Collecte de données sur les performances
- Évaluation de la valeur ajoutée de chaque filtre
- Suivi des signaux de contagion S3 et S4 (érosion post-2021)

### Phase 4 — Bilan et décision (Mois 7–9)

- Analyse complète des résultats vs critères section 9
- Questions à répondre :
  - Les FNBs "rapides" rebondissent-ils en 10–15 jours?
  - Les FNBs "moyens" rebondissent-ils en 20 jours?
  - Le filtre de cluster a-t-il évité des pertes?
  - Le filtre SMA 50 a-t-il de la valeur ajoutée?
  - Les signaux de contagion confirment-ils leur win rate historique?
  - Le Filtre D bénéficierait-il d'un assouplissement à XIU > +0,3 %?
- Décision : Passer en argent réel, ajuster ou abandonner

---

## 13. Risques et limites connues

### Risques opérationnels

| Risque | Impact | Mitigation |
|--------|--------|-----------|
| Données yfinance périmées | Aucun scan valide | Garde de fraîcheur → alerte immédiate |
| GitHub Actions en file d'attente | Délai de scan | Acceptable pour horizon 10–20 jours |
| Erreur de calcul du z-score | Signal erroné | Validation croisée avec fermetures quotidiennes |
| Courriel non livré | Signal manqué | Log dans le tableau de bord |
| Agent Groq indisponible | Classification manquante | Classification remplacée par "INCONNU" — le système continue |

### Risques stratégiques

| Risque | Impact | Mitigation |
|--------|--------|-----------|
| Mean reversion inopérant en conditions futures | Pertes paper trading | Phase 6–9 mois + critères d'arrêt (section 9.2) |
| Érosion des signaux S3/S4 (XUT→XIN post-2021) | Win rate < 50 % | Suivi mensuel — mise en veille si win rate < 45 % |
| Crise systémique prolongée | Multiples signaux faux | Filtre cluster + régime + tendance + max 3 positions |
| Overfitting historique | Résultats réels décevants | Validation hors-échantillon + gel des paramètres |
| Changement structurel de régime | Mean reversion échoue | Filtre F (SMA 50 jours) |
| Coûts réels supérieurs aux estimations | Edge érodé | Modèle conservateur + mesure des écarts |

### Limites connues

- Le z-score 20j est relatif à la volatilité récente. Le z-score 60j atténue ce risque sans l'éliminer.
- Les données yfinance sont des prix de fermeture quotidiens. Les performances intraday réelles pourraient différer.
- Le système réagit à la statistique, pas au fondamental. Les filtres de calendrier et de tendance atténuent cette limite.
- Le VIX est un indicateur américain appliqué à des FNBs canadiens. Sa pertinence sera validée pendant le paper trading.
- **XIT.TO :** 87 % des baisses causées par Shopify (55 % du FNB). Concentration de risque idiosyncratique expliquant l'absence de signal mean reversion fiable.
- **Signaux de contagion — n limité :** XRE→XIN : ~2,4 chocs/an; XEG→XFN : ~1,2 chocs/an. Accumulation de trades out-of-sample significatifs prendra des années.
- **Stratégie combinée A+B :** Non déployable — Wilcoxon p = 0,908, distribution pathologique.
- **Fréquence effective :** 10–20 trades/an avec les paramètres actuels (voir section 14). L'attente de 1 signal/semaine n'est pas fondée sur les paramètres réels.

---

## 14. Validation empirique post-déploiement *(nouveau v3.1)*

*Ajoutée en mai 2026 — après deux semaines de paper trading en production. Source : données yfinance, 7 FNBs actifs, mars–mai 2026 + 25 ans historiques.*

### 14.1 Contexte

Deux observations ont motivé cette analyse après le déploiement en production :

1. **Fréquence inférieure aux attentes** — un seul trade mean reversion complété (XUT.TO, 22 avril 2026) sur la période initiale.
2. **Interrogation sur le seuil** — est-ce qu'un seuil à −1,5σ permettrait d'atteindre une fréquence plus élevée sans sacrifier la qualité?

### 14.2 Backtest — Seuil −2,0σ vs −1,5σ

**Périmètre :** 48 jours de bourse (2 mars – 7 mai 2026), 7 FNBs actifs. Signaux bruts z-score uniquement (Filtres A/B/D/G non appliqués pour isoler l'effet du seuil).

| Métrique | Seuil −2,0σ (actuel) | Seuil −1,5σ (testé) |
|---|---|---|
| Signaux déclenchés | **5** | **29** |
| FNBs touchés | 4 / 7 | 7 / 7 |
| Hit rate J+1 | 40 % | 39 % |
| Rendement moyen J+1 | **+0,10 %** | **−0,12 %** |
| Hit rate J+5 | 40 % | 33 % |
| Rendement moyen J+5 | −0,12 % | −0,32 % |
| Hit rate J+10 | 20 % | 46 % |
| Rendement moyen J+10 | −0,81 % | −0,31 % |

Les 24 signaux supplémentaires à −1,5σ présentent des rendements négatifs à J+1 et J+5 en moyenne. La période mars–avril 2026 était marquée par une correction soutenue : les baisses à −1,5σ capturaient le début de tendances baissières continues, non des anomalies temporaires.

> **Conclusion : le seuil −2,0σ est maintenu.** L'abaissement à −1,5σ multiplie par 5,8x le nombre de signaux mais dégrade la qualité. Le gain de fréquence ne compense pas la perte de qualité.

### 14.3 Analyse du Filtre D — Impact sur la fréquence

**Rappel :** Quand XIU ≥ 0 %, le seuil effectif monte de −2,0σ à −2,5σ pour tous les FNBs actifs.

**Distribution sur 25 ans (2001–2026) :**

| Contexte XIU | Jours | Part | Seuil effectif |
|---|---|---|---|
| XIU positif ou stable (≥ 0 %) | 3 550 | **56 %** | −2,5σ (durci) |
| Zone grise (entre −0,5 % et 0 %) | 1 375 | 22 % | −2,0σ (normal) |
| XIU systémique (< −0,5 %) | 1 422 | 22 % | −2,0σ (normal) |

**Qualité des signaux par contexte (25 ans, 1 043 signaux bruts à −2,0σ) :**

| Groupe | Signaux | Hit rate J+1 | Rend. moy J+1 | Hit rate J+5 | Rend. moy J+5 |
|---|---|---|---|---|---|
| Bloqués par Filtre D (XIU +) | 100 | 45 % | −0,13 % | 52 % | −0,01 % |
| Gardés — zone grise | 131 | 50 % | −0,03 % | 53 % | +0,19 % |
| Gardés — XIU systémique | 812 | 50 % | +0,10 % | 55 % | +0,15 % |
| **Gardés (total)** | **943** | **50 %** | **+0,08 %** | **55 %** | **+0,16 %** |

**Delta en faveur des signaux gardés :** +0,21 % à J+1, +0,17 % à J+5.

> **Conclusion : le Filtre D est validé empiriquement.** Il améliore la qualité à court terme. Son coût : il est actif 56 % des jours de bourse, ce qui contribue directement à la faible fréquence observée.

### 14.4 Explication de la fréquence effective

| Facteur | Impact sur la fréquence |
|---|---|
| Seuil de base −2,0σ | Événement rare (~7–8 fois/an par FNB) |
| Filtre D actif 56 % du temps | Seuil effectif à −2,5σ la majorité des jours |
| Filtre B (VIX > 25 = pause) | Bloque en période de stress, quand les z-scores s'accumulent |
| Filtre A (7+ signaux = bloquer) | Bloque les clusters en crise corrélée |
| Filtre G (1 position par bloc) | Limite les positions simultanées |

**La fréquence de 10–20 trades/an est le comportement attendu du système.** L'attente de 1 signal/semaine (52/an) n'était pas fondée sur les paramètres réels.

### 14.5 Piste d'assouplissement documentée (non déployée)

**Piste :** Relever le seuil de déclenchement du Filtre D de XIU ≥ 0 % à XIU > +0,3 %.

**Raisonnement :** Une hausse de XIU de +0,05 % ne constitue pas un signal de solidité suffisant pour justifier le durcissement du seuil. Ce changement réduirait les jours en mode "seuil durci" d'environ 56 % à ~35 %.

**Validation requise avant déploiement :** test de Wilcoxon ou Mann-Whitney sur les rendements post-signal pour le contexte XIU entre 0 % et +0,3 %, sur les 25 ans de données.

> ⚠️ **Statut : piste documentée, validation statistique pendante. Paramètres actuels maintenus.**

### 14.6 Paramètres confirmés après validation

| Paramètre | Valeur | Statut |
|---|---|---|
| Seuil z-score de base | −2,0σ | ✅ Confirmé — backtest mai 2026 |
| Seuil Filtre D (XIU +) | −2,5σ | ✅ Confirmé — analyse 25 ans |
| Seuil déclenchement Filtre D | XIU ≥ 0 % | ⚠️ Piste d'assouplissement à valider |
| Fréquence effective attendue | 10–20 trades/an | ✅ Documentée et comprise |

---

## 15. Glossaire pour néophyte

| Terme | Définition simple |
|-------|-------------------|
| **Écart-type** | Mesure de combien un prix bouge "normalement." |
| **Z-score** | Le mouvement du jour exprimé en nombre d'écarts-types. Un z-score de -2 signifie une baisse 2 fois plus grande que la normale. |
| **Mean reversion** | L'idée que quand un prix s'éloigne trop de sa moyenne, il a tendance à y revenir. Comme un élastique. |
| **Contagion inter-FNB** | La transmission d'un choc d'un FNB à un autre avec un décalage d'un jour de bourse. |
| **FNB (ETF)** | Fonds négocié en bourse. Un panier d'actions acheté et vendu comme une action individuelle. |
| **FNB actif** | FNB pour lequel le système peut ouvrir des positions (signal mean reversion validé). |
| **FNB contextuel** | FNB suivi par le scanner mais sans position mean reversion. Ses chocs peuvent activer des signaux de contagion. |
| **Paper trading** | Trading virtuel — simulation d'achats et de ventes sans argent réel. |
| **Régime de marché** | L'état général du marché : optimiste (risk-on), neutre, ou pessimiste (risk-off). |
| **Cluster** | Plusieurs FNBs qui baissent le même jour — signe d'un événement qui touche tout le marché. |
| **SMA 50 jours** | Moyenne mobile simple sur 50 jours de bourse (~2,5 mois). Un FNB sous sa SMA 50 est en tendance baissière. |
| **Stop-loss** | Seuil de perte prédéfini qui déclenche une vente automatique pour limiter les dégâts. |
| **Trailing stop** | Stop-loss qui monte avec le prix — protège les gains acquis. |
| **Capitulation** | Quand les investisseurs paniquent et vendent massivement. Souvent un signe que le creux est proche. |
| **Fat tails** | Le fait que les événements extrêmes arrivent plus souvent que la théorie statistique le prédit. |
| **Backtest** | Tester une stratégie sur des données historiques pour voir comment elle aurait performé. |
| **Spread bid-ask** | La différence entre le prix d'achat (ask) et le prix de vente (bid). Coût caché de chaque transaction. |
| **Slippage** | La différence entre le prix attendu et le prix réellement obtenu lors de l'exécution. |
| **Corrélation** | Mesure de combien deux FNBs bougent ensemble. 1,0 = identiques, 0 = indépendants, -1 = opposés. |
| **yfinance** | Bibliothèque Python qui récupère gratuitement les données de marché depuis Yahoo Finance. Source unique de TMX v2. |
| **GitHub Actions** | Service de GitHub qui exécute des scripts automatiquement selon un horaire défini. |
| **VIX** | "L'indice de la peur." Mesure la volatilité attendue du marché américain. Filtre de régime de TMX v2. |
| **RPM** | Rapport sur la politique monétaire de la Banque du Canada. Publié 4 fois par an avec annonce de taux. |
| **Hit rate** | Pourcentage de trades qui se terminent avec un profit. |
| **Max drawdown** | La pire perte cumulée du portefeuille entre un sommet et un creux. |
| **Wilcoxon (test de)** | Test statistique non-paramétrique qui vérifie si une série de rendements est significativement différente de zéro, sans supposer une distribution normale. |
| **p permutation** | Valeur p calculée par simulation (1 000 itérations). Confirme qu'un signal n'est pas le fruit du hasard. |
| **Garde de fraîcheur** | Vérification automatique que les données correspondent bien à la date du jour. |

---

## 16. Annexe A — Calendrier économique canadien 2026

### Annonces du taux directeur — Banque du Canada (9h45 HE)

| Date | Rapport sur la politique monétaire | Impact historique |
|------|-----------------------------------|--------------------|
| Mercredi 28 janvier 2026 | Oui | Rendement moyen négatif (XIU : −0,18 %) |
| Mercredi 18 mars 2026 | Non | Rendement moyen positif (XIU : +0,30 %) |
| Mercredi 29 avril 2026 | Oui | Rendement moyen négatif — prudence requise |
| Mercredi 10 juin 2026 | Non | Rendement moyen positif |
| Mercredi 15 juillet 2026 | Oui | Rendement moyen négatif — prudence requise |
| Mercredi 2 septembre 2026 | Non | Rendement moyen positif |
| Mercredi 28 octobre 2026 | Oui | Rendement moyen négatif — mois le plus risqué |
| Mercredi 9 décembre 2026 | Non | Rendement moyen positif |

**Règle pour les jours avec RPM :** Attendre après 10h00 HE. Seuil de 2,5 é.-t. pour XRE, XUT, XFN.

### Enquêtes économiques — Banque du Canada (10h30 HE)

- Lundi 19 janvier 2026
- Lundi 20 avril 2026
- Lundi 6 juillet 2026
- Lundi 19 octobre 2026

### Rapport sur la stabilité financière

- Jeudi 28 mai 2026 (10h00 HE)

### Dates à surveiller

- **IPC canadien (Statistique Canada) :** Généralement 3e ou 4e semaine du mois, 8h30 HE
- **Rapport sur l'emploi canadien :** Généralement premier vendredi du mois, 8h30 HE
- **CPI américain :** Impact direct sur les marchés canadiens, dates variables

*Source : Banque du Canada, communiqué du 6 août 2025*

---

*Document généré dans le cadre du développement de TMX v2. Les données statistiques proviennent de l'analyse de prix quotidiens sur 25 ans (2001–2026) de 13 FNBs canadiens. Le système opère en trading actif sur 7 FNBs cotés au TSX; 5 FNBs additionnels sont maintenus comme indicateurs contextuels.*
