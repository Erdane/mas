"""Les bulletins de paie anonymisés avant toute lecture, comme les relevés.

Le texte de chaque page passe par l'anonymiseur de mas (le même coffre que tes relevés : un pseudonyme vaut
partout la même personne) ; chaque mot touché par une détection prend le pseudonyme, sans bouger de place, pour que
la lecture des colonnes reste possible. Puis le vérificateur cherche ce qui resterait en clair (ton identité
déclarée, un numéro de sécurité sociale, un IBAN, un e-mail, un téléphone) : il relance l'anonymisation avec ce qu'il
a trouvé, et bloque la lecture si une fuite reste.

Le vocabulaire des bulletins (« PRIME », « COTISATION », « FRAIS »…) est mis en liste blanche : spaCy le prend
parfois pour un nom, et un libellé masqué ne dirait plus ce qu'il paie. Sur une ligne de paie (une ligne qui porte un
montant), les noms et lieux que spaCy devine sont ignorés : « PRIME D'ASSIDUITE » n'est pas une personne. Ton
identité déclarée et les numéros (sécurité sociale, IBAN, téléphone, e-mail) restent masqués partout ; l'en-tête, où
sont ton nom et ton adresse, l'est entièrement.
"""
from __future__ import annotations

import re

from ..anonymisation.moteur import Anonymiseur
from ..verification import Fuite, Verificateur

MOTS_PAIE = [
    "REMUNERATION", "BRUTE", "BRUT", "SALAIRE", "BASE", "TRAITEMENT", "APPOINTEMENTS", "PRIME", "PRIMES", "INDEMNITE",
    "INDEMNITES", "INDEM", "IND", "GRATIFICATION", "ANCIENNETE", "ENGAGT", "ENGAGEMENT", "FIXE", "VARIABLE", "PERF",
    "CONTRACT", "COTISATION", "COTISATIONS", "COTIS", "CONTRIBUTION", "CONTRIBUTIONS", "CSG", "CRDS", "RETRAITE",
    "VIEILLESSE", "VIEILLESS", "MALADIE", "MAL", "PREVOYANCE", "MUTUELLE", "SOLIDARITE", "CHOMAGE", "INVALIDITE",
    "INVAL", "NET", "SOCIAL", "IMPOSABLE", "FRAIS", "TRANSPORT", "TRANS", "MENS", "TELETRAVAIL", "REPAS", "PEAGE",
    "SEJOUR", "STAGE", "MISSION", "RECEPTION", "EQUIPEMENT", "ABSENCE", "ABS", "CONGES", "RAPPEL", "REGUL", "MOIS",
    "ANTER", "EXER", "EXERCICE", "TOTAL", "MONTANT", "PAS", "TAUX", "FORFAIT", "JOURS", "HEURES", "PERIODE",
    "EMPLOYEUR", "SALARIE", "PATRONAL", "SALARIAL", "ALLEGEMENT", "DEFISCALISEES", "PRELEVEMENT", "SOURCE", "IMPOT",
    "REVENU", "CET", "EPARGNE", "INTERESSEMENT", "PARTICIPATION", "EXCEPTIONNEL", "EXCEPTIONNELLE", "TELEPHONIE",
    "DED", "NDED", "FISC", "DEDUCTIBLE", "COMP", "COMPL", "SUP", "SPE", "AGS", "FIN", "ANNEE", "PLEIN", "REEL",
    "AUTRES", "DUES", "VIREMENT", "PAYER", "AVANT", "REMB", "CUMUL", "CUMULS", "CONTRAT", "EMPLOI", "COEFFICIENT",
    "ISOLE", "C.S.M", "CSM", "SECU", "SS", "NP", "PL", "PAT", "AT", "CG", "PF", "INV", "DEC", "TX", "NN", "PERSO", "MT",
]


def anonymiseurs(config, coffre) -> tuple[Anonymiseur, Verificateur]:
    """L'anonymiseur des bulletins (liste blanche élargie au vocabulaire de la paie) et son vérificateur. Le
    vérificateur cherche ton identité déclarée et les numéros (sécurité sociale, IBAN…), pas les autres valeurs du
    coffre : des mots courants y figurent (« frais »…) et masqueraient les libellés."""
    termes = config.identite.termes()
    reglages = config.anonymisation.model_copy(update={"liste_blanche": [*config.anonymisation.liste_blanche, *MOTS_PAIE]})
    return Anonymiseur(reglages, coffre, termes), Verificateur(config.verification, termes)


def _texte(page: dict) -> tuple[str, list[tuple[int, int, int, int]]]:
    """Le texte de la page (une ligne par ligne de mots) et la place de chaque mot : (ligne, mot, début, fin)."""
    morceaux, places, curseur = [], [], 0
    for i, ligne in enumerate(page["lignes"]):
        for j, mot in enumerate(ligne):
            if j:
                morceaux.append(" ")
                curseur += 1
            places.append((i, j, curseur, curseur + len(mot["text"])))
            morceaux.append(mot["text"])
            curseur += len(mot["text"])
        morceaux.append("\n")
        curseur += 1
    return "".join(morceaux), places


def _appliquer(page: dict, texte: str, places, detections, coffre) -> dict:
    pseudos = [(d.debut, d.fin, coffre.pseudonyme(d.entite, texte[d.debut:d.fin])) for d in detections]
    lignes = [[dict(m) for m in ligne] for ligne in page["lignes"]]
    for i, j, debut, fin in places:
        touchees = [(a, b, p) for a, b, p in pseudos if a < fin and b > debut]
        if not touchees:
            continue
        neuf, curseur = "", debut
        for a, b, p in sorted(touchees):
            if a > curseur:
                neuf += texte[curseur:a]
            if a >= debut:                      # la détection commence dans ce mot : il porte le pseudonyme
                neuf += p
            curseur = max(curseur, min(b, fin))
        neuf += texte[curseur:fin]
        lignes[i][j]["text"] = neuf.strip()
    return {**page, "lignes": [[m for m in ligne if m["text"]] for ligne in lignes if any(m["text"] for m in ligne)]}


class FuiteDansUnBulletin(RuntimeError):
    def __init__(self, fichier: str, fuites: list[Fuite]):
        self.fuites = fuites
        super().__init__(f"Lecture bloquée : des données personnelles restent visibles dans {fichier} après "
                         "anonymisation :\n" + "\n".join(f"  - {f}" for f in fuites))


DEVINES = {"PERSON", "FR_LIEU", "LOCATION", "ORGANIZATION", "NRP"}      # ce que spaCy devine, par opposition aux motifs
MONTANT = re.compile(r"(?<![\d,])\d{1,3}(?:\d{3})*,\d{2}(?![\d,])")


def _sur_une_ligne_de_paie(texte: str, d) -> bool:
    debut = texte.rfind("\n", 0, d.debut) + 1
    fin = texte.find("\n", d.fin)
    ligne = texte[debut:fin if fin >= 0 else len(texte)]
    return "\n" not in texte[d.debut:d.fin] and bool(MONTANT.search(ligne))


def _retenues(texte: str, detections: list) -> list:
    return [d for d in detections
            if not (d.source == "presidio" and d.entite in DEVINES and _sur_une_ligne_de_paie(texte, d))]


def anonymiser_pages(pages: list[dict], anonymiseur: Anonymiseur, verificateur: Verificateur, fichier: str = "",
                     iterations: int = 3) -> tuple[list[dict], int]:
    """(les pages anonymisées, le nombre de remplacements). Lève FuiteDansUnBulletin si une fuite résiste."""
    resultat, total = [], 0
    for page in pages:
        texte, places = _texte(page)
        supplementaires: dict[str, str] = {}
        for _ in range(iterations + 1):
            detections = _retenues(texte, anonymiseur.detecter(texte, list(supplementaires.items())))
            neuve = _appliquer(page, texte, places, detections, anonymiseur.coffre)
            fuites = verificateur.verifier(_texte(neuve)[0])
            if not fuites:
                break
            for f in fuites:
                supplementaires[f.valeur] = f.entite if f.entite != "DONNEE_PERSO" else "PERSON"
        else:
            raise FuiteDansUnBulletin(fichier, fuites)
        resultat.append(neuve)
        total += len(detections)
    return resultat, total


def anonymiser_libelle(libelle: str, anonymiseur: Anonymiseur) -> str:
    """Un libellé du classeur (en-tête de colonne), anonymisé de la même façon."""
    return anonymiseur.anonymiser(libelle).texte
