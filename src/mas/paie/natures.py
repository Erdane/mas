"""La nature de chaque ligne de paie, d'après son libellé : salaire de base, prime du mois, 13e mois, variable…

Les libellés changent d'un employeur à l'autre : les règles ci-dessous lisent les mots les plus courants des
bulletins français. Un libellé que mas range mal se corrige dans config.yaml (`paie.natures`) : un mot du libellé,
puis sa nature.
"""
from __future__ import annotations

import re
import unicodedata

NATURES = {
    "base": "Salaire de base",
    "mensuelle": "Primes et indemnités du mois",
    "treizieme": "13e mois",
    "rappel": "Rappels",
    "variable": "Part variable",
    "interessement": "Intéressement",
    "exceptionnelle": "Primes exceptionnelles",
    "frais": "Frais remboursés",
    "cet": "Épargne temps (CET)",
    "absence": "Absences",
    "stage": "Gratification de stage",
    "autre": "Autres lignes",
}
# Ce qui revient chaque année quoi qu'il arrive, et ce qui dépend des résultats
FIXE = ("base", "mensuelle", "treizieme", "rappel", "cet", "absence")
VARIABLE = ("variable", "interessement", "exceptionnelle")

ANTERIEUR = r"(MOIS|EXER|EXERCICE)\s+ANTER|RAPPEL|REGUL"
REGLES = [
    ("cet", r"\bCET\b|EPARGNE TEMPS"),
    ("absence", r"\bABS\b|ABSENCE|MALADIE|CARENCE"),
    ("frais", r"TELETRAV|TRANSPORT|\bTRANS\b|PEAGE|SEJOUR|MISSION|EQUIPEMENT|VELO|FERM REST|REPAS|KILOMETR|NAVIGO|FRAIS"),
    ("stage", r"GRATIFICATION DE STAGE|\bSTAGIAIRE|\bSTAGE\b"),
    ("treizieme", r"GRATIFICATION|FIN D.?ANNEE|13E? ?MOIS|TREIZIEME"),
    ("variable", r"PERF|VARIABLE|BONUS|OBJECTIF"),
    ("interessement", r"INTERESS|\bINTE|PARTICIPATION"),
    ("exceptionnelle", r"EXCEP|\bPPV\b|PARTAGE DE LA VALEUR|PEPA"),
    ("rappel", rf"(REMUNERATION BRUTE|SALAIRE DE BASE|TRAITEMENT|PRIME).*({ANTERIEUR})"),
    ("base", r"REMUNERATION BRUTE|SALAIRE DE BASE|TRAITEMENT DE BASE|APPOINTEMENT"),
    ("mensuelle", r"PRIME|\bIND\b|INDEM|ANCIENNETE|BYOD|ASTREINTE|HEURES SUP"),
]


def normaliser(libelle: str) -> str:
    sans_accents = unicodedata.normalize("NFKD", libelle).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sans_accents).strip().upper()


def nature_de(libelle: str, corrections: dict[str, str] | None = None) -> str:
    """`corrections` : {mot du libellé: nature} venues de config.yaml, comparées sans accents ni casse ; la plus
    longue qui convient l'emporte."""
    cle = normaliser(libelle)
    for mot, nature in sorted((corrections or {}).items(), key=lambda x: -len(x[0])):
        if normaliser(mot) and normaliser(mot) in cle:
            return nature if nature in NATURES else "autre"
    for nature, motif in REGLES:
        if re.search(motif, cle):
            return nature
    return "autre"
