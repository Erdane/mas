# mas

> Anciennement *masque*. Au carnaval antillais, « faire mas », c'est se déguiser pour cacher son
> identité : c'est ce que fait l'outil avec tes données.

Anonymise tes PDF **sur ton PC**, puis fait analyser la version anonyme par des
agents LLM optimisés avec **DSPy + GEPA**. Premier cas d'usage : à partir de
relevés bancaires, retrouver les dépenses récurrentes et obligatoires pour
construire un budget.

```
 PDF / ZIP
    │
    ▼
 ┌──────────────────────── LOCAL (rien ne sort) ─────────────────────────┐
 │ Lecture          tableau relu ligne par ligne (date, libellé, débit,   │
 │                  crédit) ; comptes séparés ; contrôle au centime avec  │
 │                  les totaux de la banque ; sinon l'IA ; OCR optionnel  │
 │ Anonymisation    Presidio + spaCy FR + regex FR (IBAN, RIB, NIR,       │
 │                  tél., adresses, noms dans les virements) + GLiNER     │
 │                  optionnel + tes données déclarées dans config.yaml    │
 │ Pseudonymisation « Jean Dupont » → [PERSONNE_1], partout et d'un mois  │
 │                  sur l'autre ; table chiffrée dans ~/.mas/             │
 │ Vérificateur     regex + clés de contrôle + recherche des valeurs      │
 │                  connues ; boucle jusqu'à 0 fuite, sinon ENVOI BLOQUÉ  │
 └────────────────────────────────────────────────────────────────────────┘
    │ texte pseudonymisé uniquement
    ▼
 ┌──────────────────────── AGENTS (LLM cloud) ───────────────────────────┐
 │ Extracteur ⇄ Contrôleur   le contrôleur (Python) compare les montants │
 │                           extraits à ceux de la page et renvoie ses   │
 │                           remarques à l'extracteur (2 corrections max)│
 │ Catégoriseur              logement, énergie, abonnement…              │
 │ Détecteur de récurrences  Python déterministe (périodicité, montants) │
 │ Classeur                  obligatoire / optionnel / courant variable  │
 │ Synthétiseur              commentaire ; chiffres calculés en Python   │
 └────────────────────────────────────────────────────────────────────────┘
    │
    ▼
 Rapport dé-pseudonymisé EN LOCAL (rapports/rapport_<date>.md + .html) + version anonyme
```

## Sommaire

1. [Installation](#installation)
2. [Configuration](#configuration)
3. [Analyser tes relevés, pas à pas](#analyser-tes-relevés-pas-à-pas)
4. [Comment mas lit tes relevés](#comment-mas-lit-tes-relevés) et [ce qui compte comme dépense](#ce-qui-compte-comme-dépense)
5. [Tes fiches de paie](#tes-fiches-de-paie)
6. [Les deux boucles de mas](#les-deux-boucles-de-mas)
7. [Essayer sans tes données](#essayer-sans-tes-données)
8. [Publier le code sans tes données](#publier-le-code-sans-tes-données)
9. [Commandes](#commandes)
10. [Optimisation avec GEPA](#optimisation-avec-gepa)
11. [Tests](#tests-sans-clé-api)
12. [Structure](#structure)
13. [Ta banque n'est pas reconnue ?](#ta-banque-nest-pas-reconnue-)
14. [Limites](#limites)
15. [Licence](#licence)

## Installation

Il faut Python 3.10 ou plus récent (Linux, macOS ou WSL sous Windows).

```bash
git clone https://github.com/<ton-compte>/mas.git && cd mas
python3 -m venv .venv && source .venv/bin/activate   # ou : uv venv
pip install -e ".[dev]"                              # ou : uv pip install -e ".[dev]"
mas init
```

`mas init` prépare le dossier sans rien écraser :

- `config.yaml` (copie de `config.example.yaml`) : renseigne ta section `identite` et choisis le
  modèle dans `llm` ;
- `.env` (copie de `.env.example`) : colle ta clé d'API ;
- `releves/` pour tes PDF et `rapports/` pour les résultats, deux dossiers ignorés par git ;
- le modèle français de spaCy, téléchargé s'il manque.

Options : `pip install -e ".[gliner]"` (2e détecteur de noms, plus lent),
`".[ocr]"` + `sudo apt install tesseract-ocr tesseract-ocr-fra` (PDF scannés).

## Configuration

**Lance toujours `mas` depuis son dossier.** `config.yaml` et `.env` sont lus dans le dossier
courant. Sans `config.yaml`, `mas analyser` et `mas anonymiser` s'arrêtent et te proposent
`mas init`, plutôt que de traiter tes relevés sans tes données déclarées. Pour une configuration
rangée ailleurs : `mas analyser … -c chemin/config.yaml`.

### `.env` : la clé d'API

Il est lu automatiquement à chaque commande. Une variable déjà définie dans le terminal reste
prioritaire. Il est ignoré par git, comme `config.yaml`.

### `config.yaml` : les réglages

| Section | Rôle |
|---|---|
| `llm` | modèle d'analyse, au format LiteLLM `fournisseur/modele`. `anthropic/claude-haiku-4-5-20251001` est économique (1 $ / 5 $ par million de tokens en entrée / sortie) ; `anthropic/claude-sonnet-5-5` est plus fin et coûte le double (2 $ / 10 $) ; `anthropic/claude-opus-5-5` est le plus fin des trois et coûte quatre fois Haiku (4 $ / 20 $). Pour Sonnet et Opus 5.5 : **`temperature: null` et `max_tokens: 16000`**, car ils refusent la température et leur réflexion avant de répondre compte dans `max_tokens` |
| `analyse` | ce qui compte comme dépense : virements vers un bénéficiaire à ton nom (`virements_a_ton_nom`), tes comptes dans d'autres banques (`comptes_personnels`), virements à des proches (`virements_a_des_proches`), loyers payés sans le mot « loyer » (`loyers_sans_libelle`, `loyer_montant_min`), achats exceptionnels (`achat_exceptionnel_min`), argent reçu de proches (`recus_de_proches`), épargne qu'un proche garde sur ton compte (`epargne_de_proches`), catégories que tu imposes (`categories`) ; voir [Ce qui compte comme dépense](#ce-qui-compte-comme-dépense) |
| `identite` | tes données qui ne doivent jamais sortir : noms (toutes les variantes écrites sur tes relevés), adresses, IBAN, numéros de compte, téléphones, e-mails, et `autres` (n° client, n° de contrat, proches à qui tu fais des virements…) |
| `anonymisation` | modèle spaCy, types d'entités masquées, `liste_blanche` des marchands à ne pas masquer |
| `verification` | nombre maximal de boucles anonymisation → vérification (voir [Les deux boucles de mas](#les-deux-boucles-de-mas)), vérificateur LLM local optionnel (Ollama) |
| `coffre` | emplacement de la table chiffrée des pseudonymes |
| `recurrence` | seuils de détection des dépenses récurrentes |
| `optimisation` | GEPA : modèle de réflexion (`temperature_reflexion: null` pour Opus 5.5), taille des jeux, dossiers |

## Analyser tes relevés, pas à pas

**1. Se placer dans le dossier**

```bash
cd mas                        # le dossier du dépôt
source .venv/bin/activate
```

**2. Récupérer les relevés**

Télécharge tes relevés en PDF depuis ton espace bancaire : au moins **3 mois**, idéalement 6 à 12.
C'est la répétition qui révèle une dépense récurrente, et 12 mois font apparaître les dépenses
trimestrielles ou annuelles. Range-les dans `releves/` : ce dossier est ignoré par git.

**3. Déclarer tes données dans `config.yaml`**

```yaml
identite:
  noms: ["Prénom NOM", "NOM PRENOM", "M NOM"]
  adresses: ["12 rue ..."]
  ibans: ["FR76 ..."]
  numeros_compte: ["..."]
  telephones: ["06..."]
  emails: ["...@..."]
  autres: ["n° client", "noms des proches à qui tu fais des virements"]
```

Elles sont masquées en plus de la détection automatique, puis recherchées une dernière fois par le
vérificateur avant tout envoi.

**4. Mettre la clé d'API dans `.env`** (voir [Installation](#installation)).

**5. Anonymiser et relire, sans rien envoyer**

```bash
mas anonymiser releves/ --sortie sortie_anonyme/
```

Ouvre les `.txt` produits et vérifie :

- **Tes données sont masquées :** cherche ton nom, ton IBAN et ta rue avec Ctrl+F. S'il reste
  quelque chose, ajoute-le à `identite.autres` et relance.
- **Les marchands sont lisibles :** EDF, Netflix… Un marchand masqué à tort (par exemple
  `[PERSONNE_2]`) s'ajoute à `anonymisation.liste_blanche`.
- **Les opérations sont lues :** dates, libellés et montants doivent être là. Une page vide
  signifie un PDF scanné, voir [Limites](#limites).

**6. Lancer l'analyse**

```bash
mas analyser releves/
```

mas anonymise à nouveau puis vérifie (voir [Les deux boucles de mas](#les-deux-boucles-de-mas)) :

- **S'il reste une donnée personnelle**, l'envoi est **bloqué** et mas dit laquelle.
- **Sinon**, il affiche le tableau « Tes relevés » (pour chacun : lu directement et contrôlé au centime,
  ou lu par l'IA et pourquoi), un extrait de ce qui partira, puis demande confirmation en disant ce qui
  part : les libellés et montants des opérations lues directement, et les pages entières des relevés
  non reconnus. `--oui` saute cette question.

Pendant l'analyse, chaque étape s'affiche :

```
[1/5] Lecture directe des tableaux (sans IA) : 363 opération(s) sur le compte principal,
      50 mouvement(s) entre tes comptes mis à part
  Totaux imprimés par la banque : 6/6 relevé(s) concordant(s)
[2/5] Catégorisation : 214 libellé(s) distinct(s) en 6 lot(s)
[3/5] Dépenses récurrentes (calcul local, sans IA) : 9 trouvée(s)
[4/5] Classement obligatoire / optionnel de 9 dépense(s)…
[5/5] Rédaction de la synthèse…
```

Si le tableau d'un relevé n'est pas reconnu, l'étape 1 passe par l'IA, page par page
(« [1/5] Extraction des opérations par l'IA »), voir [Comment mas lit tes relevés](#comment-mas-lit-tes-relevés).

À la fin, un **résumé du traitement** donne la durée de l'anonymisation et de l'analyse, le nombre
d'appels à l'IA, les tokens consommés et le **coût estimé**. Seuls les appels réellement facturés
sont comptés : si tu relances la même analyse, les réponses déjà calculées sont reprises du cache
de DSPy, gratuitement. Si l'IA est injoignable (clé invalide, crédit épuisé, modèle inconnu),
l'analyse s'arrête tout de suite avec l'erreur au lieu de produire un rapport vide.

**Sans IA : `mas analyser releves/ --no-ai`**

Rien n'est envoyé, rien n'est facturé, aucune confirmation n'est demandée. La lecture des relevés,
les récurrences et tous les chiffres viennent du même code. Ce qui change :

- les catégories viennent de mots-clés ([`sans_ia.py`](src/mas/sans_ia.py)). Un commerçant inconnu
  reste dans « Autres », et une épargne non reconnue compte comme une dépense. Le rapport dit quelle
  part des dépenses reste à classer et liste les commerçants qui pèsent le plus :
  `analyse.categories` permet de les classer ;
- le classement obligatoire / optionnel suit la catégorie ;
- le commentaire se limite à des constats calculés, sans conseils ;
- un relevé dont la mise en page n'est pas reconnue est écarté et signalé : seule l'IA sait le lire.

**7. Lire le résultat**

| Fichier | Contenu |
|---|---|
| `rapports/rapport_2026-11-01_1430.html` | **la page du rapport**, avec tes vrais noms remis en local ; elle s'ouvre à la fin de l'analyse (`--no-open` pour l'éviter) |
| `rapports/rapport_2026-11-01_1430_anonyme.html` | la même page, telle que l'IA l'a vue (pseudonymes) |
| `rapports/rapport_2026-11-01_1430_detail.html` / `…_anonyme_detail.html` | le détail de tes dépenses : chaque catégorie, puis chaque mois, avec toutes ses opérations |
| `rapports/rapport_2026-11-01_1430.md` / `…_anonyme.md` | les mêmes informations en texte |
| `rapports/rapport_2026-11-01_1430.json` | les données de la page, avec les pseudonymes (pour `mas exporter`) |

Chaque analyse écrit ses fichiers sous un nouveau nom, à sa date et à son heure : les précédentes restent
dans `rapports/`, que git ignore. Une analyse sans IA ajoute `_no-ai` au nom.

La page du rapport montre :

- **ton mois moyen :** une barre représente tes revenus ; les parties colorées sont tes dépenses
  (obligatoires, abonnements optionnels, courantes), la partie vide est ce qu'il te reste, avec ce
  montant en grand. C'est la moyenne de toute la période, écrite sous la barre ;
- **ton budget aujourd'hui :** la même barre pour les mois qui viennent, si rien ne change. Tes dépenses
  régulières (charges fixes, abonnements, mensualités) y comptent pour leur montant actuel : une
  mensualité commencée il y a quatre mois y pèse en entier, un abonnement arrêté n'y est plus ; une
  charge espacée (annuelle, impôt en plusieurs fois) pour ce qui a été payé sur douze mois. Le reste,
  et les revenus, en moyenne des douze derniers mois complets. Ce qui a changé est listé dessous. Elle
  n'apparaît que si elle s'écarte de la moyenne (50 € et 3 % au moins), et « Où économiser » mesure
  alors le manque d'après elle ;
- **ce que dit l'analyse :** le constat et les pistes d'économies rédigés par l'IA ;
- **où va ton argent :** tes dépenses mensuelles par catégorie, avec le tableau des montants exacts.
  Touche une catégorie : la page de détail s'ouvre sur elle, tous ses mois dépliés, chaque opération
  avec sa date et son montant ;
- **revenus et dépenses, mois par mois :** ce qu'il reste de tes revenus une fois tes dépenses payées,
  une barre par mois (sous zéro, tu as dépensé plus que tes revenus), et la moyenne en pointillé. Les
  mois incomplets sont laissés de côté ;
- **mois par mois :** chaque catégorie de dépenses, mois après mois, avec la moyenne et le total de
  chaque mois ; plus la case est colorée, plus la dépense est élevée. Touche une case pour voir les
  opérations de ce mois-là. Un mois que tes relevés ne couvrent qu'en partie est marqué « incomplet » :
  ses montants sont forcément plus bas ;
- **tes dépenses récurrentes :** à payer quoi qu'il arrive, abonnements que tu peux arrêter,
  dépenses courantes qui reviennent, avec le coût par mois et par an.

Survole une barre (ou atteins-la au clavier) pour voir son montant, sa part et son coût annuel.
Dans la version anonyme, les pseudonymes apparaissent comme de petits masques ; dans la version
personnelle, les vraies valeurs remises en local sont soulignées en pointillé.

La page est autonome : styles et script intégrés, aucune ressource externe (l'ouvrir n'envoie
rien), thème clair ou sombre selon Windows, imprimable. Elle s'ouvre toute seule à la fin de
l'analyse ; pour la rouvrir depuis WSL dans le navigateur Windows :

```bash
explorer.exe "$(wslpath -w rapports/rapport_2026-11-01_1430.html)"
```

`mas coffre` affiche la table des pseudonymes et de leurs vraies valeurs, en local.

## Comment mas lit tes relevés

**Peu importe ta banque :** mas lit un relevé d'après sa mise en page, pas d'après le nom de la banque, et
vérifie sa lecture au centime avec les soldes ou les totaux imprimés. Avant tout envoi, `mas analyser`
affiche pour chaque relevé comment il est lu et le résultat de ce contrôle ; le rapport reprend ce tableau
(« Comment tes relevés ont été lus »).

| Ordre | Lecture | Quand | Vérification |
|---|---|---|---|
| 1 | **directe, d'après l'en-tête** (`releve.py`) | l'en-tête « Date … Débit … Crédit » donne la position des colonnes (la BRED, beaucoup de banques) | totaux ou soldes imprimés |
| 2 | **directe, colonnes déduites** (`lecteur_deduit.py`) | pas d'en-tête exploitable, mais des lignes qui commencent par une date et finissent par un montant | retenue seulement si elle tombe juste au centime |
| 3 | **par l'IA**, page par page | aucune des deux, ou contrôle faux ; la raison s'affiche | aucune vérification au centime possible |

**Colonnes déduites.** Les montants sont alignés à droite : leurs bords droits se regroupent en une, deux ou
trois colonnes. mas essaie les lectures possibles et garde la seule qui tombe juste au centime, si bien
qu'une mauvaise hypothèse ne passe jamais :

| Mise en page | Exemple de ligne | Vérifiée par |
|---|---|---|
| deux colonnes, débit puis crédit (ou l'inverse) | `05/09/2026  CARTE BOULANGERIE  05/09/2026  12,40` | solde de début + crédits − débits = solde de fin |
| une colonne de montants signés | `04/09/26  VIREMENT RECU  +1 900,00` | idem |
| débit, crédit, solde après chaque opération | `03.09  ABONNEMENT  10,99  489,01` | chaque ligne avec la précédente |
| montant signé, solde après chaque opération | `5 sept. 2026  Carte Librairie  -18,90 €  481,10 €` | idem |

Les dates peuvent être courtes (« 05.09 », l'année vient de la période du relevé), complètes
(« 05/09/2026 », « 05/09/26 ») ou en lettres (« 5 sept. 2026 »). Un libellé sur plusieurs lignes est recollé,
une date citée dans le libellé (« CARTE 01/09 … ») y reste, et les mots collés par le PDF (« SOLDEAU »,
« 21sept. ») sont reconnus.

**Ce que garantit la lecture directe :**

- **elle ne dépend pas du dessin du tableau :** certains relevés (la BRED, par exemple) sont lus par
  l'extraction de tableaux classique comme une seule ligne fourre-tout, où plus aucun montant n'est
  rattaché à son libellé ;
- **elle est contrôlée au centime,** et un écart est signalé en tête du rapport ;
- **elle donne la bonne période :** le nombre de mois vient des soldes de début et de fin, arrondi au
  demi-mois ;
- **elle sépare les comptes d'un même relevé** (lecture d'après l'en-tête) : seul le compte courant est
  analysé, les livrets imprimés à la suite (LDD, Livret A…) servent à reconnaître ton épargne. Les colonnes
  déduites lisent un seul compte par relevé : un livret imprimé à la suite fait échouer le contrôle, et
  l'IA prend le relais.

**Extraction par l'IA**, page par page, avec la boucle de correction décrite plus bas : seulement pour les
relevés que ni l'une ni l'autre lecture ne reconnaît.

### Ce qui compte comme dépense

L'argent qui change seulement de compte n'est **pas** une dépense. Il est montré à part, sous la
barre des revenus (« Pas compté dans tes dépenses ») et dans le rapport texte :

| Mouvement | Comment il est repéré | Réglage |
|---|---|---|
| vers / depuis tes livrets | un virement du compte courant et un mouvement d'un livret figurant sur un des relevés, de même montant, en sens inverse, à 4 jours près | automatique |
| entre tes comptes de deux banques | un virement débité sur un relevé et le même montant crédité sur un autre, à 5 jours près (week-end, jour férié) ; les deux relevés couvrent ensemble l'une de ces dates (pas deux mois successifs d'un même compte), et les deux libellés ne nomment pas deux personnes différentes. Ton nom, même écrit autrement d'une banque à l'autre, compte pour toi, et les paires où les deux libellés portent ton nom passent en premier | automatique, si tu donnes les relevés des deux comptes |
| vers tes autres comptes | le libellé mentionne un compte que tu as déclaré (IBAN, code BIC, banque, ou ton nom tel qu'il apparaît : « J DUPONT ») | `analyse.comptes_personnels` |
| vers un compte à ton nom | le bénéficiaire porte le nom déclaré dans `identite.noms` | `analyse.virements_a_ton_nom` |
| avec des proches | catégorie « virements à des proches » | `analyse.virements_a_des_proches` |
| épargne d'un proche gardée sur ton compte | il t'envoie de l'argent, tu le lui rends plus tard : son pseudonyme, ou tous les mots de son nom, dans le libellé. La page dit ce que tu as reçu, rendu, et ce qui est encore chez toi | `analyse.epargne_de_proches` |
| achat exceptionnel et son prêt | des paiements à un même bénéficiaire en 7 jours qui font au moins 3 000 € (prélèvements exceptés), et un prêt débloqué ; les mensualités du prêt, elles, comptent chaque mois | `analyse.achat_exceptionnel_min` |

Le repérage « à ton nom » est une **déduction**, pas une certitude : un homonyme, un proche qui
porte ton nom ou un compte joint donnent le même résultat. Ces virements sont mis à part par
défaut ; mets `virements_a_ton_nom: depense` pour les compter comme des dépenses, ou déclare tes
vrais comptes dans `comptes_personnels` pour ne plus dépendre du nom. Les virements à des proches
comptent comme des dépenses, sauf avec `virements_a_des_proches: a_part`. Le rapport les détaille
personne par personne (envoyé, reçu, compté en dépense, plus gros virement, chaque opération) : si
l'un d'eux va en fait vers un compte à toi, ajoute ce qui le désigne dans `comptes_personnels`.

Le reste du calcul :

- **remboursements :** un remboursement par carte vient en déduction des dépenses de sa catégorie ;
- **revenus :** salaire et revenus. L'argent reçu de particuliers annule d'abord ce que tu leur
  avais envoyé (voir [docs/categories.md](docs/categories.md#virements-à-des-proches)) ; ce qui
  dépasse est montré à part, pas compté comme un revenu, sauf avec `analyse.recus_de_proches: revenu` ;
- **loyer :** un virement avec « loyer » dans le libellé reste un loyer, même si ton nom y figure
  en référence ;
- **dépenses récurrentes :** les références, numéros de magasin et dates collées sont retirés des
  libellés avant de les regrouper ; un même montant payé presque tous les mois compte comme mensuel
  même si la date varie, et une assurance, un abonnement ou une taxe payés une seule fois sur au
  moins six mois de relevés comptent comme une dépense annuelle, ramenée au mois ;
- **à vérifier :** le rapport liste ce que mas n'a pas pu classer avec certitude (achats
  exceptionnels, prêt, commerçants inconnus ou au nom masqué de 100 € ou plus, virements de 500 € ou
  plus à des particuliers). Ce que tu sais d'un commerçant se note dans `analyse.categories`
  (« GARAGE MARTIN: transport ») : son vrai nom marche aussi, il est comparé en local ;
- **loyer sans libellé :** des virements mensuels d'un montant stable vers une même personne
  (300 € ou plus) sont comptés dans le logement et signalés comme « loyer probable »
  (`analyse.loyers_sans_libelle`, `analyse.loyer_montant_min`) ;
- **moyennes :** chaque montant est divisé par le nombre de mois couverts par les relevés ;
- **catégories :** ce que l'IA range dans chaque catégorie (logement, crédits, virements à des
  proches, autres…) est expliqué dans [docs/categories.md](docs/categories.md) ;
- **mois par mois :** les mêmes règles, appliquées à chaque mois. Un mois couvert à moins de 75 %
  par tes relevés (par exemple du 1er au 5) est marqué incomplet ; la somme des mois, divisée par le
  nombre de mois couverts, redonne les moyennes (au centime près).

## Tes fiches de paie

Dépose tes bulletins de paie PDF dans `fiches_de_paie/` (le dossier `paie.dossier` de `config.yaml`, ignoré par
git), puis :

```bash
mas payslips                 # tes bulletins, croisés avec ton dernier rapport de budget
mas payslips --alone         # la page des bulletins seule
```

`mas analyser` le fait aussi tout seul quand le dossier contient des bulletins. Un rapport a alors trois pages,
reliées par un menu commun :

| Page | Ce qu'elle montre |
|---|---|
| `rapport_X.html` : **Ton budget** | la page de toujours (dépenses, catégories, récurrences, où économiser…) |
| `rapport_X_paie.html` : **Tes fiches de paie** | ton pouvoir d'achat (indice des prix de l'INSEE), le calendrier de tes primes, le net d'un mois sans prime, ce que prennent cotisations et impôt (et les changements de taux), chaque augmentation et son rappel, les règles de ta paie vérifiées mois par mois (primes en pourcentage du salaire de base, 13e mois), ce que ton employeur t'a annoncé, les mois qui viennent, ton compte épargne temps |
| `rapport_X_croise.html` : **Salaire et budget** | ce que ton salaire laisse après tes dépenses mois par mois, mois ordinaires contre mois de prime, le net de chaque bulletin contre le virement reçu, salaire et dépenses d'une année sur l'autre (sur les mêmes mois), les douze mois qui viennent |

**Anonymisés avant d'être lus.** Chaque bulletin passe par le même anonymiseur que tes relevés, avec le même coffre :
le texte est lu mot par mot avec sa position, chaque mot repéré prend son pseudonyme sans bouger de place, puis le
vérificateur cherche ce qui resterait (ton identité déclarée, un numéro de sécurité sociale, un IBAN…) et bloque la
lecture si une fuite résiste. Sur une ligne de paie, les noms que spaCy devinerait dans un libellé (« PRIME
D'ASSIDUITE ») sont ignorés ; ton identité déclarée et les numéros restent masqués partout. Rien n'est envoyé à l'IA :
tout se calcule sur ton PC, et seul l'indice des prix est téléchargé (le même pour tout le monde).

**Lecture.** Le bulletin est un tableau : base, taux, retenue, gain, part employeur. Le texte seul ne dit pas dans
quelle colonne tombe un montant : mas lit la position de chaque mot, et calibre les colonnes sur le bulletin lui-même
(le salaire de base dans les gains, le total des cotisations dans les retenues, la ligne d'impôt). À défaut,
`paie.colonnes` les règle. Un libellé mal rangé se corrige dans `paie.natures` (un mot du libellé, puis sa nature).

**Un classeur en complément.** `paie.classeur` : un classeur Excel avec une feuille « Brut AAAA » (une colonne par
ligne de paie, puis « Cotisations ») et une feuille « Net AAAA » (net avant et après impôt) par année. Il sert pour les
mois sans PDF ; là où les deux existent, le PDF fait foi et mas signale ce que le classeur dit autrement (un signe
inversé, une ligne oubliée) et ce que ses formules calculent de travers.

**Ce qu'on t'a annoncé.** `paie.annonces` : une augmentation, un salaire de base, une prime, une rémunération annuelle
(modèle dans `config.example.yaml`). mas les compare aux bulletins ; une hausse annoncée en janvier mais versée en
avril avec trois mois de rappel est conforme.

## Les deux boucles de mas

mas répète deux étapes jusqu'à obtenir un résultat satisfaisant. Elles n'ont ni le même rôle ni
le même coût :

| Boucle | Rôle | Où | Coût | Réglage |
|---|---|---|---|---|
| Anonymisation ⇄ vérification | ne rien envoyer de personnel | sur ton PC | gratuit | `verification.iterations_max` dans `config.yaml` (3) |
| Extracteur ⇄ contrôleur | extraire des opérations justes, quand le tableau n'est pas reconnu | avec l'IA | un appel à l'IA par correction | `tentatives_max` dans `agents/programme.py` (2) |

### 1. Anonymisation ⇄ vérification : le filet de sécurité

```
anonymiser toutes les pages
        ↓
vérifier toutes les pages ──── aucune fuite ──→ envoi possible
        │ fuite(s) trouvée(s)
        ↓
ajouter les valeurs trouvées à la liste à masquer,
ré-anonymiser les pages concernées depuis le texte d'origine
        ↓
recommencer (3 corrections au maximum) ──── encore des fuites ──→ ENVOI BLOQUÉ
```

- **Deux contrôleurs indépendants :** le vérificateur ne fonctionne pas comme l'anonymiseur. Il
  utilise des motifs, les clés de contrôle des IBAN, cartes et numéros de sécurité sociale, et
  cherche mot pour mot les valeurs déjà pseudonymisées ailleurs. Les deux ne ratent donc pas les
  mêmes choses.
- **Pourquoi recommencer :** ton nom peut être reconnu en page 1 mais raté par spaCy dans un
  libellé de virement en page 4. Le vérificateur le retrouve, mas ré-anonymise cette page, puis
  revérifie **tous** les documents : une valeur découverte dans le troisième fichier doit aussi
  être masquée si elle apparaît dans le premier.
- **Ton nom sous toutes ses formes :** les noms de `identite.noms` sont cherchés dans les deux
  ordres, **collés** aux mots voisins quand la banque compacte le libellé (« VIRINSTJEANDUPONT »,
  pour un nom d'au moins deux mots et huit lettres), et **mot par mot** quand un seul apparaît
  (« Virement automatique DUPONT », pour les mots de cinq lettres ou plus, en mot entier).
- **Les autres personnes, même en minuscules ou collées :** dans un virement, les mots qui suivent la
  référence (« émis 1a2b3c4 jean dupont ») sont pris pour le nom de l'autre partie, sauf les
  organismes et motifs connus (EDF, CAF, loyer, remboursement…) ; un nom collé par Boursorama
  (« VIRSEPAJeanDupont »), une civilité (« m », « mlle », « dr ») et un prénom connu (près de
  17 000, toutes langues) sont masqués aussi, comme un commerçant qui porte un prénom. Le lieu d'un
  retrait d'espèces (ville, agence) devient un `[LIEU_n]`. Les villes dans les noms de commerçants
  (« PRIMARK LYON ») restent visibles.
- **En pratique :** la boucle s'arrête dès qu'une vérification ne trouve plus rien, en général
  juste après le premier passage. Sur le relevé de démonstration, il n'y a eu aucune itération
  supplémentaire.

Le message « Itération 1 : N fuite(s) corrigée(s) » signifie que le filet a servi. Pour que le
premier passage attrape ces valeurs directement, ajoute-les à `identite` dans `config.yaml`
(`mas anonymiser` permet de les repérer). Augmenter `iterations_max` ne sert à rien : si l'envoi
est bloqué, la solution est de déclarer la donnée.

### 2. Extracteur ⇄ contrôleur : la qualité de l'extraction

Cette boucle ne sert que pour les relevés dont le tableau n'est pas reconnu (sinon, les opérations
sont lues directement, sans IA). Pendant l'analyse, page par page :

1. l'IA extrait les opérations de la page ;
2. un contrôle en Python compare les montants extraits avec ceux imprimés sur la page ;
3. en cas d'écart (opération oubliée, signe inversé…) ou de réponse mal formée, il renvoie ses
   remarques à l'IA, qui recommence : **2 corrections au maximum par page**, et mas garde la
   meilleure tentative ;
4. les pages encore incohérentes sont signalées : « N page(s) avec des incohérences d'extraction
   non résolues : vérifie le rapport ».

Contrairement à la première boucle, **chaque correction est un appel à l'IA de plus, donc
payant**.

## Essayer sans tes données

Le générateur produit un relevé fictif de 3 à 6 mois, avec sa vérité terrain en JSON (opérations,
dépenses récurrentes, données personnelles) :

```bash
mas generer --n 1 --sortie donnees/demo
mas anonymiser donnees/demo/releve_0000.pdf --sortie donnees/demo/anonyme
mas analyser donnees/demo/releve_0000.pdf --sortie donnees/demo/rapport.md
```

Premier essai (octobre 2026, Claude Haiku 4.5, relevé de 4 mois) : aucune donnée personnelle en
clair, 7 dépenses récurrentes sur 7 retrouvées, 6 catégories sur 7 justes.

## Publier le code sans tes données

Le dépôt ne contient que le code, la documentation et les tests. Tout le reste est ignoré par git
(voir `.gitignore`) :

| Ignoré | Pourquoi |
|---|---|
| `config.yaml`, `.env` | ton identité déclarée, tes clés d'API |
| `releves/`, `rapports/`, `sortie_anonyme/` | tes relevés et tout ce que mas en tire |
| `donnees/`, `artefacts/` | relevés de démonstration, journaux d'optimisation |
| `*.pdf`, `*.csv`, `*.ofx`, `*.xlsx`, `*.png`… | relevés, exports bancaires et captures, où qu'ils soient |

Un `.gitignore` ne voit pas le **contenu** des fichiers : ton nom recopié dans un test, par
exemple. `mas check-repo` passe en revue les fichiers que git publierait et y cherche tes
données déclarées dans `config.yaml`, les valeurs de ton coffre (celles de plusieurs mots et les
numéros) et tes clés d'API. Il affiche le fichier, la ligne et le type de donnée, jamais la valeur.

Pour qu'il tourne avant chaque commit, active le crochet fourni, une fois par clone :

```bash
git config core.hooksPath .githooks
```

Un commit qui contient une de tes données est alors refusé. En cas de fausse alerte (un nom
inventé pour un test qui se trouve aussi dans ton coffre), change le nom dans le test ;
`git commit --no-verify` passe outre, à réserver aux cas que tu as vérifiés.

## Commandes

| Commande | Rôle | Options utiles |
|---|---|---|
| `mas init` | prépare le dossier : `config.yaml`, `.env`, `releves/`, `rapports/`, modèle spaCy (n'écrase rien) | `-c` |
| `mas anonymiser ENTRÉE` | anonymise seulement, rien n'est envoyé | `--sortie DOSSIER` |
| `mas analyser ENTRÉE` | anonymise, vérifie, analyse, écrit un rapport daté dans `rapports/` et l'ouvre | `--no-ai`, `--no-open`, `--sortie FICHIER.md`, `--oui` |
| `mas exporter RAPPORT.md` | régénère les pages HTML d'un rapport existant, sans rappeler l'IA (à partir de `rapport.json` ; sans lui, simple mise en page du Markdown) | `-c` |
| `mas payslips` | tes fiches de paie (`fiches_de_paie/`, et un classeur en complément), anonymisées puis lues sans IA : leur page, et celle qui les croise avec ton dernier rapport de budget | `--budget RAPPORT.json`, `--alone`, `--refresh-prices`, `--no-open` |
| `mas coffre` | table pseudonymes → vraies valeurs (local) | |
| `mas generer` | relevés synthétiques (PDF + vérité JSON) | `--n`, `--sortie`, `--graine` |
| `mas optimiser` | optimise les agents avec GEPA | `--regenerer` |
| `mas evaluer` | score du programme courant | |
| `mas check-repo` | cherche tes données et tes fichiers personnels dans ce que git publierait | `--staged` |
| `mas structure ENTRÉE` | décrit la mise en page des relevés que mas ne lit pas directement (intitulés de colonnes génériques, positions, types date / montant / texte), sans aucune donnée : de quoi apprendre une nouvelle banque à mas | `--tous` |

`ENTRÉE` est un PDF, un ZIP de PDF ou un dossier. Toutes les commandes qui lisent la
configuration acceptent `-c chemin/config.yaml`.

## Optimisation avec GEPA

```bash
mas generer --n 5 --sortie donnees/apercu   # voir à quoi ressemblent les relevés de test
mas optimiser                               # génère 36 relevés, optimise, sauvegarde
mas evaluer                                 # score du programme courant
```

L'optimisation n'utilise **que des relevés synthétiques** (Faker) dont on connaît
la vérité : transactions, catégories, récurrences et données personnelles. Ils
passent par le vrai pipeline d'anonymisation, donc les agents apprennent sur des
textes identiques à ceux de production, sans tes données.

La métrique (`src/mas/optimisation/metrique.py`) note quatre axes et renvoie
à GEPA un retour ciblé sur le prédicteur qu'il est en train d'améliorer :

| Prédicteur   | Score             | Exemple de retour |
|--------------|-------------------|-------------------|
| extracteur   | F1 des opérations | « 3 opérations manquées : 2026-03-08 PRLV SEPA EDF… −90,79 » ; erreurs de signe ; récurrences ratées |
| categoriseur | précision         | « « CB UBER EATS 12/03 » classé alimentation, attendu restauration » |
| classeur     | précision         | « « PRLV SEPA BASIC FIT » classé obligatoire, attendu abonnement_optionnel » |
| (global)     | 0 si fuite        | toute donnée personnelle en clair dans la sortie annule le score |

Le programme optimisé est sauvegardé dans `artefacts/programme_optimise.json`
et chargé automatiquement par `mas analyser`. Les instructions réécrites
sont lisibles dans `artefacts/instructions_optimisees.json`.

Coût : avec `auto: light`, compte quelques centaines d'appels au modèle
d'analyse et quelques dizaines au modèle de réflexion. Commence avec
`n_train: 12`, `n_val: 6` pour un premier essai. Avec Claude Opus 5.5 comme modèle
de réflexion, mets `temperature_reflexion: null`.

## Tests (sans clé API)

```bash
pytest
```

Les tests utilisent un faux LLM déterministe (`tests/faux_llm.py`) pour exécuter
tout le pipeline, la boucle extracteur ⇄ contrôleur et une compilation GEPA. Ils
couvrent aussi la lecture directe des tableaux (relevé factice au format BRED : comptes,
totaux, libellés sur deux lignes, livrets, virements entre comptes), le calcul du budget et sa
répartition mois par mois,
l'anonymisation (dates et noms de livrets non masqués), la vérification du dépôt avant publication,
`mas init`, la page HTML (versions anonyme et personnelle, déficit,
injection de HTML), la lecture du `.env`, l'affichage unique des messages répétés, l'avancement de
l'analyse, le calcul des tokens et du coût, et l'analyse sans IA (aucun appel au modèle, rapport daté,
ouverture du navigateur).

## Structure

```
src/mas/
  config.py             lecture de config.yaml en objets typés
  modeles.py            structures de données, définitions des catégories envoyées à l'IA
  ingestion.py          PDF/ZIP -> texte page par page, tableaux | col | col |
  releve.py             lecture d'après l'en-tête Date / Débit / Crédit, comptes, soldes et totaux
  lecteur_deduit.py     lecture sans en-tête : colonnes déduites, hypothèses vérifiées au centime
  structure.py          mas structure : squelette d'un relevé, sans aucune donnée
  anonymisation/
    reconnaisseurs.py   regex FR + GLiNER
    validateurs.py      Luhn, IBAN mod 97, clé RIB, clé NIR
    moteur.py           Presidio + résolution des chevauchements + pseudonymisation
    coffre.py           table de correspondance chiffrée (Fernet)
  verification.py       vérificateur de fuites indépendant (+ LLM local optionnel)
  depot.py              mas check-repo : aucune donnée personnelle dans le dépôt git
  agents/
    signatures.py       instructions de départ des agents (réécrites par GEPA)
    programme.py        programme DSPy + contrôleur
    synthese.py         calcul du budget + rapport
  recurrence.py         détection déterministe des récurrences
  synthetique.py        générateur de relevés + vérité terrain
  optimisation/         jeux de données, métrique avec feedback, boucle GEPA
  orchestrateur.py      enchaîne tout, bloque l'envoi en cas de fuite
  page.py               page HTML du rapport (barre des revenus, catégories, écart revenus/dépenses, mois par
                        mois, récurrences) et sa page de détail par catégorie et par mois
  navigation.py         le menu commun aux pages d'un rapport (budget, fiches de paie, salaire et budget)
  paie/                 tes fiches de paie, sans IA
    pdf.py              lecture d'un bulletin d'après la position des mots, colonnes calibrées sur le bulletin
    anonymisation.py    anonymisation mot par mot, sans bouger les positions, puis vérification
    excel.py            classeur « Brut AAAA » / « Net AAAA », et ses formules qui calculent de travers
    natures.py          la nature de chaque ligne (salaire de base, prime du mois, 13e mois, variable, frais…)
    analyses.py         augmentations, règles de paie, 13e mois, calendrier, impôts, pouvoir d'achat, CET
    controles.py        classeur contre bulletins ; lignes qui ne retombent pas sur le net
    annonces.py         ce que l'employeur a annoncé, contre les bulletins
    prevision.py        les mois qui viennent
    inflation.py        l'indice des prix de l'INSEE (gardé une semaine dans ~/.mas/ipc.json)
    page.py, croise.py  la page des bulletins ; celle qui les croise avec le budget
    rapprochement.py    le net de chaque bulletin contre le virement reçu
    export.py, sortie.py  les données en JSON ; l'écriture et le lien des pages
  export.py             mise en page simple d'un rapport Markdown (anciens rapports)
  suivi.py              durées, tokens et coût estimé d'une analyse
  sans_ia.py            mas analyser --no-ai : catégories par mots-clés, constats calculés
  cli.py                commandes mas ..., chargement du .env
tests/                  faux LLM, relevés factices (BRED, Boursorama, une famille de mise en page
                        chacun), lecture, budget, catégories,
                        anonymisation, pipeline, page, export, journal, suivi
docs/categories.md      ce que l'IA range dans chaque catégorie
.githooks/pre-commit    lance mas check-repo avant chaque commit
.github/ISSUE_TEMPLATE/ ticket « Banque non reconnue » (sortie de mas structure)
config.example.yaml     modèle de config.yaml ; .env.example : modèle de .env (copiés par mas init)
```

## Ta banque n'est pas reconnue ?

Tu le vois avant l'envoi : dans le tableau « Tes relevés », la colonne Lecture indique « par l'IA : mise en
page non reconnue (raison) ». L'analyse fonctionne quand même, mais l'IA lit ces pages : c'est payant, et
aucune vérification au centime n'est possible. Pour que ta banque soit lue directement, pour toi et pour
les suivants :

1. **Décris la mise en page, sans aucune donnée :**
   ```bash
   mas structure releves/
   ```
   Seuls apparaissent des intitulés de colonnes pris dans une liste fixe de mots génériques (date, libellé,
   débit…), des positions et des types (`DATE_LONGUE`, `MONTANT`, `TEXTE`) : jamais tes libellés, tes montants,
   ton nom ou tes numéros. La sortie reste dans ton terminal ; relis-la avant de la partager.
2. **Ouvre un ticket « Banque non reconnue »** sur GitHub (modèle prévu) avec le nom de la banque, cette
   sortie et la raison affichée.
3. **La mise en page est reproduite** dans un relevé factice (`tests/releves_factices.py`), le lecteur est
   adapté, et ta banque est lue directement pour tout le monde.

| Raison affichée | Ce qu'elle veut dire | À essayer |
|---|---|---|
| aucun solde ni total imprimé pour vérifier la lecture | mas ne lit pas directement ce qu'il ne peut pas vérifier | le relevé mensuel officiel de ta banque (avec soldes), plutôt qu'un export d'historique |
| relevé scanné (image) | pas de texte positionné dans le PDF | le PDF téléchargé depuis ton espace bancaire, pas un scan |
| contrôle faux en lisant … | aucune lecture des colonnes ne retombe sur les soldes | souvent plusieurs comptes dans le même relevé : signale-le (étape 2) |
| N colonnes de montants | une mise en page encore inconnue | signale-la (étape 2) |
| aucune ligne qui commence par une date et finit par un montant | la date ou le montant sont ailleurs sur la ligne | signale-la (étape 2) |
| dates sans année, et date du relevé introuvable | les opérations n'ont que « 05.09 », sans période lisible | signale-la (étape 2) |

**Vérifie aussi l'anonymisation** sur un vrai relevé avec `mas anonymiser` : tes données doivent être
masquées, et seulement elles (marchands masqués à tort : `anonymisation.liste_blanche` ; données oubliées :
`identite.autres`).

## Limites

- **Anonymisation imparfaite :** l'anonymisation automatique n'est jamais parfaite. Relis la
  sortie de `mas anonymiser` sur tes premiers relevés.
- **Ville des achats visible :** dans « CB CARREFOUR LYON », la ville reste lisible. C'est un
  choix pour garder les marchands lisibles. Ajoute ta ville dans `identite.autres` si tu veux la
  masquer.
- **PDF scannés :** sans l'option OCR, une page scannée sort **vide, sans message d'erreur**. Si
  `mas anonymiser` produit des pages vides, installe `".[ocr]"` et tesseract (voir
  [Installation](#installation)).
- **Catégories à vérifier :** les catégories sont choisies par l'IA et peuvent se tromper. Les
  montants et les totaux, eux, sont calculés en Python.
- **Tableaux non reconnus :** un relevé sans en-tête « Date … Débit … Crédit » (une seule colonne
  « Montant » signée, par exemple) passe par l'extraction par l'IA, moins fiable et sans contrôle
  au centime.
- **« À ton nom » est une déduction :** un virement vers quelqu'un qui porte ton nom est mis à part
  comme un mouvement entre tes comptes. Vérifie-le dans le rapport, et déclare tes vrais comptes
  dans `analyse.comptes_personnels`.
- **Épargne dans une autre banque :** un virement vers un livret qui ne figure pas sur le même
  relevé n'est reconnu que s'il est à ton nom ou si ce compte est déclaré.
- **Clé du coffre :** garde `~/.mas/cle.key`, ou la variable `MAS_CLE_COFFRE`. Sans elle, la table
  des pseudonymes ne peut plus être déchiffrée.
- **Matériel :** pas de GPU nécessaire. spaCy et Presidio tournent sur CPU ; GLiNER et le
  vérificateur LLM local (Ollama) sont optionnels.

## Licence

[MIT](LICENSE) : tu peux utiliser, copier, modifier et redistribuer ce code, y compris dans un
projet commercial, à condition de garder la mention de copyright et la licence. Le logiciel est
fourni sans garantie.
