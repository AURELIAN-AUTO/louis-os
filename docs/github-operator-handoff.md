# Passation du pilote GitHub

Initialisée le 15 septembre 2026. Point de reprise :
https://github.com/liubaining-louis/louis-os/issues/473.
Lire aussi les commentaires récents de cette issue, qui consignent les preuves
d'intégration et les actions effectuées après ce document.

## Mandat actif

Piloter Louis OS depuis la conversation et exécuter la relance monétisation avec
le mode sans VM. Le mode connecté agit pendant les conversations actives. Les
paquets du runtime dégradé attendent ce pilote ; ils ne sont pas envoyés par Actions.

## Acquis vérifiés avant cette bascule

- Diagnostic de facturation GCP corrigé et intégré : PR #472.
- Runtime sans VM intégré : PR #474. Cycles 35004511904 et 35004512120 réussis.
- Dernier état lu : 15 septembre à 18:00 UTC, cycle 2, 30 missions inspectées,
  aucune qualifiée, aucune nouvelle soumission ni réception de paiement vérifiée.
- Connexion GitHub Louis OS opérationnelle pour branches, commits, PR et fusion.
  Cela ne prouve pas l'accès à chaque dépôt externe.
- MoltJobs, TaskForce, AgentPact et wallet Earn restent indisponibles depuis le
  runtime sans VM lorsque leurs credentials sont uniquement sur la VM.

## Priorité suivante

1. Vérifier l'intégration et le premier cycle du mode pilote connecté dans #473,
   puis lire le briefing actualisé et réconcilier toute intention présente.
2. Traiter un paquet qualifié s'il existe ; sinon poursuivre la recherche de
   missions courtes et la revue des voies déjà engagées, sans inventer de revenu.
3. Manic : notification officielle annonçant 10 USD de gains individuels, paiement
   non vérifié ; la dotation de campagne de 1 000 USDC n'est pas le gain individuel.
4. Ne relancer les voies VM qu'après résolution de facturation et preuve de santé.
   BountyBook 19a16071 reste en pause en attendant la résolution oracle documentée.

Pour la prochaine passation, inscrire la tâche traitée, le SHA/PR/run, les preuves
obtenues, ce qui reste incertain et la prochaine action. Ne jamais marquer une
fusion, une livraison ou un paiement comme terminé avant sa vérification.

## Mandat renouvelé le 18 octobre 2026

Le propriétaire demande des ajustements continus pour rentabiliser Louis OS.
La tâche ChatGPT existante « Rentabiliser Louis OS » a été réactivée avec un
cycle borné toutes les six heures, sans modifier la fréquence des workflows.
Chaque reprise doit vérifier les accès et les preuves actuelles ; ce calendrier
ne garantit ni l'accès aux plateformes ni un travail ChatGPT permanent.

Priorités concrètes, dans cet ordre :

1. Rendre les erreurs de rapprochement visibles. Les cinq discussions RustChain
   renvoient HTTP 404 au contrôle du 18 octobre, alors que le job reste vert.
   Le correctif doit conserver une santé horodatée indépendamment du revenu,
   distinguer solde fraîchement lu et cache, préserver les reçus historiques,
   signaler l'échec après persistance et éviter les commits/commentaires répétés
   lorsque rien de significatif ne change. Vérifier la CI puis un run réel.
2. Relier une sélection du routeur au dossier et au pilote d'exécution. Le
   18 octobre, sept opportunités sont à préparer mais aucun paquet n'est
   disponible dans le briefing. La comparaison CI/CD à 7 USDC est sélectionnée
   depuis au moins le 11 octobre. Ne pas prétendre que ce raccordement est fait.
3. Appliquer réellement les pivots et réconcilier les travaux déjà soumis.
   Mesurer missions distinctes, livraisons, reçus, acceptations, paiements,
   coûts connus/inconnus et temps bloqué. Les scans et commits ne sont pas
   des résultats économiques ; aucun revenu ni rentabilité n'est garanti.

Migration locale reportée par le propriétaire : mini Lenovo d'environ 2016,
Pentium, 16 Go de RAM, SSD, actuellement Windows ; Linux envisagé. Ne pas
supposer ce PC installé ou accessible. Ne pas réactiver la facturation GCP.
Les API d'IA éventuelles restent des coûts distincts. Charbon exclu de Louis OS.

### Première amélioration intégrée et vérifiée — 18 octobre 2026

- PR #481 fusionnée : https://github.com/liubaining-louis/louis-os/pull/481 ;
  commit `bfeb4001a4d023c1b4375986bc86b7782ded923f`.
- CI `39139588292` réussie au SHA de PR
  `e0f2f356483593ff026afdcf4988b738721f5eae`, Python 3.11 et 3.12 ;
  826 tests, dont 16 tests ciblés de rapprochement/probe. La suite complète
  locale n'est pas une preuve : le contrôle automatique l'a bloquée sur un
  ancien test contactant les métadonnées cloud. Ne pas contourner ce blocage.
- Run réel `39139750902` : tests, persistance et artifact réussis ; le contrôle
  final échoue maintenant explicitement pour les cinq HTTP 404. C'est la
  détection attendue du défaut fournisseur, pas une régression des tests.
- `results/external_outcome_health.json` à 15:16:48 UTC : état `degraded`,
  1 source sur 6 lue avec succès ; wallet RTC lu fraîchement, aucun cache.
  Aucune transition économique détectée, aucun nouveau revenu affirmé.
- Artifact `external-outcome-probe-39139750902-1` disponible dans ce run.
  Les états de santé ne génèrent un commit qu'à une transition significative.

Prochaine intervention : priorité 2 ci-dessus, raccorder sélection, dossier
et exécution pour une seule mission admissible et actuellement revalidée ;
examiner la cause des 404 en parallèle sans réinterpréter l'historique en
paiements nouveaux. Reprendre les PR ouvertes avant de créer un doublon.

### Livrable sélectionné préparé — PR #482, 18 octobre 2026

- `main` épinglé à `5aa32a87ebf4ccc03ec2a1f5210f45b13ce2f3b6` ; aucun
  `AGENTS.md` présent. Politiques de production et runtime dégradé inchangés.
- Mission BountyBook `d47a42b6-8203-4bc7-8bbf-c22ef912c232` relue sur l'API
  officielle à 17:08 UTC : ouverte, non réclamée, récompense annoncée 7 USDC.
- PR #482 : https://github.com/liubaining-louis/louis-os/pull/482 ; SHA courant
  `c27d3b05307eee9b214a72ee7321b6659ac178a3` avant cette passation.
- Livrable `cicd_comparison.json` complet et manifeste ajoutés ; SHA-256 du
  livrable `5da3d4b0eb34b560b04dfc6005a55dde5a4cf1d72a9b438a631a6b69b649be8c`.
  L'enregistrement exact relie le candidat canonique au pilote sans promouvoir
  une autre mission ni contourner les garde-fous.
- 52 tests ciblés réussis. La découverte locale complète a exécuté 809 tests
  mais reste non probante : neuf imports échouent faute de dépendances optionnelles
  (`google`, `eth_account`) et un ancien test heartbeat VM échoue. La CI GitHub au
  SHA exact reste donc obligatoire avant fusion.
- Coût connu : 0 EUR. Coûts d'accès plateforme et de paiement : inconnus.
  Soumission, acceptation et paiement vérifiés : 0.

Prochaine action : attendre la CI de #482, corriger tout échec sur la même PR,
puis fusionner seulement si tous les contrôles requis sont verts. Après fusion,
vérifier le cycle Universal market et le routeur ; l'action humaine minimale
sera alors la revue des conditions BountyBook et l'autorisation d'utiliser une
identité BountyBook légitime existante, sans création/financement de wallet.
