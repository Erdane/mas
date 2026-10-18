# Ce que Mas range dans chaque catégorie

Pour chaque opération de tes relevés, l'IA choisit une catégorie à partir du libellé anonymisé,
par exemple `PRLV SEPA DGFIP IMPOT` ou `VIR INST A [PERSONNE_2] WEEKEND`. Elle reçoit, pour chaque
catégorie, la définition citée ci-dessous mot pour mot, plus les règles de la fin de cette page.
Les calculs (moyennes, mois par mois, remboursements déduits) sont faits ensuite par Mas, sur ton
ordinateur.

Trois choses à garder en tête :

- **Les noms sont masqués.** L'IA voit `[PERSONNE_2]`, jamais le nom de la personne : elle décide
  d'après les autres mots du libellé.
- **Un remboursement va dans la catégorie de la dépense remboursée.** Un remboursement de
  l'Assurance maladie va dans Santé, un avoir de magasin dans Shopping : il est déduit de la
  catégorie au lieu de gonfler tes revenus.
- **L'argent qui change seulement de compte n'est rangé nulle part.** Quand Mas lit directement le
  tableau de ton relevé, il met à part les virements vers tes livrets et tes autres comptes : ils
  ne passent pas par l'IA et ne comptent pas comme des dépenses (voir « Ce qui compte comme
  dépense » dans le [README](../README.md#ce-qui-compte-comme-dépense)).

## Logement

> Définition donnée à l'IA : loyer, mensualité de crédit immobilier, charges de copropriété,
> frais d'agence

**N'y va pas :**

- l'électricité, le gaz, l'eau : Énergie ;
- la box internet : Télécom ;
- l'assurance habitation : Assurances ;
- la taxe foncière : Impôts et taxes ;
- les meubles, l'électroménager, le bricolage : Shopping.

**Loyer versé à un particulier :** le nom de ton propriétaire est masqué. L'IA range le virement
dans Logement quand le libellé indique un loyer (`VIR PERMANENT [PERSONNE_1] LOYER`). Sinon, Mas le
repère à sa régularité, après l'IA : des virements vers la même personne presque tous les mois (au
moins 3 mois, et 6 sur 10 des mois couverts), d'un montant stable (écart de moins de 10 %) et d'au
moins 300 € par mois. Ils passent alors dans Logement et le rapport le signale (« Loyer probable »).

C'est une déduction : une pension ou une somme fixe versée chaque mois à un proche y ressemble. Dans
la section `analyse` de `config.yaml`, `loyers_sans_libelle: non` coupe cette détection et
`loyer_montant_min` change le seuil de 300 €.

## Virements à des proches

> Définition donnée à l'IA : virements vers ou depuis des particuliers ([PERSONNE_n], un prénom),
> y compris par Lydia, Wero, Paylib ou PayPal entre particuliers

**N'y va pas :**

- un virement dont le libellé indique un loyer : Logement ; un salaire : Revenus ;
- les virements vers tes livrets ou tes propres comptes : mis à part, hors dépenses ;
- un paiement à un commerçant passé par PayPal : la catégorie du commerçant.

**Comment c'est compté :** personne par personne (le même pseudonyme `[PERSONNE_n]` d'un mois à
l'autre) et dans l'ordre des dates.

- **Un remboursement annule le virement qu'il rembourse.** Tu envoies 60 € à quelqu'un, il t'en
  renvoie 80 plus tard : 60 € sont un remboursement, ni dépense ni revenu ; les 20 € en plus
  comptent comme un revenu.
- **Rendre une avance n'est pas une dépense.** Un proche t'envoie 100 €, tu les lui rends le mois
  suivant : ni revenu, ni dépense.
- **Le reste** : l'argent envoyé sans retour compte dans tes dépenses, l'argent reçu sans envoi
  préalable dans tes revenus.

Le rapport donne le détail : envoyé, reçu, dont remboursements, puis ce qui reste en dépense et en
revenu. Dans le tableau mois par mois, un remboursement vient en déduction le mois où il arrive.

Pour sortir ces virements du budget, mets `virements_a_des_proches: a_part` dans la section
`analyse` de `config.yaml` : ils sont alors montrés à part, ni en dépenses ni en revenus.

**À savoir :** comme les noms sont masqués, un virement à une nounou ou à un artisan arrive ici
aussi. Un loyer régulier, lui, est repéré et compté dans Logement (voir plus haut).

## Autres

> Définition donnée à l'IA : ce qui ne correspond à aucune catégorie (chèque sans précision, don,
> école ou garde d'enfants, vétérinaire…) ou dont le libellé ne permet pas de décider

Concrètement :

- **un chèque :** le relevé ne dit pas à qui il a été fait ;
- **un don, l'école, la garde d'enfants, le vétérinaire :** aucune catégorie ne leur correspond ;
- **un libellé trop vague :** un simple code, un paiement PayPal sans nom de marchand.

**Et aussi :** les libellés que l'IA a oubliés dans sa réponse, ou ceux d'un lot qui a échoué,
tombent dans Autres. Mas l'indique pendant l'analyse (« libellé(s) sans réponse de l'IA »).

## Loisirs

> Définition donnée à l'IA : sorties et culture (cinéma, concerts, musées, livres, jeux), sport
> hors abonnement, vacances (hébergement, activités, parcs de loisirs), jeux d'argent

**N'y va pas :**

- les billets de train, d'avion ou de car, même pour les vacances : Transport ;
- les restaurants et les bars : Restauration ;
- la salle de sport ou le streaming payés chaque mois : Abonnements ;
- le matériel de sport et les vêtements : Shopping.

**À savoir :** Amazon va dans Shopping (achats en ligne). Une enseigne qui vend de tout, comme la
Fnac, est rangée d'après ce que l'IA devine du libellé : Shopping ou Loisirs.

## Retraits d'espèces

> Définition donnée à l'IA : retraits d'espèces au distributeur (DAB, GAB) ou au guichet, dépôts
> d'espèces

**Comment c'est compté :** tout le retrait compte comme une dépense, le mois où tu retires l'argent,
car Mas ne sait pas à quoi ont servi les billets. Un dépôt d'espèces vient en déduction.

## Transport

> Définition donnée à l'IA : carburant, recharge électrique, péages, parking, transports en commun,
> billets de train, d'avion ou de car, taxis et VTC, location de véhicule, entretien et réparation
> du véhicule

**N'y va pas :**

- l'assurance auto : Assurances ;
- le crédit auto : Crédits ;
- les amendes : Impôts et taxes ;
- l'hébergement des vacances : Loisirs.

## Impôts et taxes

> Définition donnée à l'IA : impôt sur le revenu, taxe foncière, taxe d'habitation, cotisations
> URSSAF d'indépendant, amendes, timbres fiscaux

Un remboursement d'impôt vient en déduction.

**À savoir :** avec le prélèvement à la source, l'impôt sur ton salaire est retenu par ton
employeur. Il n'apparaît pas sur ton relevé, et le salaire que tu reçois est déjà net d'impôt. Tu ne
verras ici que ce que tu paies directement : solde d'impôt, acomptes sur d'autres revenus, taxe
foncière, amendes…

## Crédits

> Définition donnée à l'IA : remboursement d'un prêt autre qu'immobilier : crédit à la
> consommation, crédit auto, crédit renouvelable, prêt étudiant, paiement en plusieurs fois

**N'y va pas :**

- la mensualité de ton crédit immobilier : Logement ;
- l'assurance emprunteur prélevée à part : Assurances.

**À savoir :** un crédit qui revient chaque mois apparaît en général aussi dans « À payer quoi qu'il
arrive », avec tes autres dépenses récurrentes obligatoires.

## Les autres catégories

| Catégorie | Définition donnée à l'IA |
|---|---|
| Énergie | électricité, gaz, eau, fioul, bois de chauffage |
| Télécom | box internet, forfait mobile, téléphone fixe |
| Assurances | assurances habitation, auto, moto, emprunteur, mutuelle santé, prévoyance |
| Alimentation | courses : supermarché, épicerie, boulangerie, marché, boucherie, primeur |
| Restauration | restaurants, fast-foods, cafés et bars, cantine, livraison de repas |
| Abonnements | abonnements résiliables : streaming, musique, logiciels, applications, stockage en ligne, presse, salle de sport |
| Santé | pharmacie, médecin, dentiste, opticien, kiné, hôpital, laboratoire |
| Épargne | versements vers ou retraits depuis un livret, une assurance-vie, un PEA, un PEL, l'épargne salariale (mis à part : ce n'est pas une dépense) |
| Shopping | vêtements, beauté et coiffeur, high-tech, maison (meubles, électroménager, bricolage, décoration, jardin), achats en ligne non alimentaires |
| Frais bancaires | cotisation de carte, tenue de compte, agios, commissions, frais de rejet, frais sur les paiements à l'étranger |
| Revenus | salaire, primes, retraite, allocations (CAF, France Travail), indemnités, aides, revenus d'une activité |

## Les règles données à l'IA

- Un virement vers ou depuis `[PERSONNE_n]` va dans Virements à des proches, sauf si le libellé
  indique un loyer (Logement) ou un salaire (Revenus).
- Un remboursement venant d'un commerçant ou d'un organisme (Assurance maladie, mutuelle, impôts…)
  va dans la catégorie de la dépense remboursée, pas dans Revenus.
- Un paiement passé par un intermédiaire (PayPal, SumUp…) va dans la catégorie du marchand quand le
  libellé l'indique.
- Les billets de train, d'avion ou de car vont dans Transport, même pour des vacances.
- Autres seulement si aucune catégorie ne convient ou si le libellé ne permet pas de décider.

## Modifier une définition

Les définitions sont dans `src/mas/modeles.py` (`DEFINITIONS_CATEGORIES`) et les règles dans
`src/mas/agents/signatures.py`. Ce que tu y changes est appliqué à l'analyse suivante. Mets aussi
cette page à jour pour qu'elle reste fidèle à ce que reçoit l'IA.
