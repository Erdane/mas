"""Détection déterministe des dépenses récurrentes (pas de LLM : fiable et gratuit)."""

from __future__ import annotations

import re
import statistics
from collections import defaultdict
from datetime import date

from .anonymisation.coffre import sans_accents
from .config import ConfigRecurrence
from .modeles import GroupeRecurrent, TransactionCategorisee

PERIODES = {
    "hebdomadaire": 7.0,
    "mensuelle": 30.44,
    "bimestrielle": 60.9,
    "trimestrielle": 91.3,
    "semestrielle": 182.6,
    "annuelle": 365.25,
}

BRUIT = re.compile(
    r"\b(?:PRLV|PRELEVEMENT|PRELEV|SEPA|EUROPEEN|VIR|VIREMENT|INST|INSTANTANE|RECU|EMIS|"
    r"PERMANENT|CB|CARTE|PAIEMENT|PAIE|ACHAT|FACTURE|FACT|DU|LE|DE|A|POUR|REF|RUM|ICS|"
    r"MANDAT|ECHEANCE|X\d+)\b"
)


def cle_libelle(libelle: str, nb_mots: int = 3) -> str:
    """Normalise un libellé pour regrouper les occurrences d'une même dépense."""
    t = sans_accents(libelle).upper()
    t = re.sub(r"\[(?!PERSONNE_)[A-Z]+_\d+\]", " ", t)        # jetons non-personne
    t = re.sub(r"\[(PERSONNE_\d+)\]", r" \1 ", t)               # garde le bénéficiaire
    t = re.sub(r"\b\d{1,2}[/.\-]\d{1,2}(?:[/.\-]\d{2,4})?\b", " ", t)  # dates
    t = re.sub(r"\b\w*\d{3,}\w*\b", " ", t)                    # références numériques
    t = re.sub(r"[^A-Z0-9_ ]", " ", t)
    t = BRUIT.sub(" ", t)
    mots = [m for m in t.split() if len(m) > 1 or m.isdigit()]
    return " ".join(mots[:nb_mots]) or sans_accents(libelle).upper().strip()


def _date(s: str) -> date | None:
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def detecter_recurrences(
    transactions: list[TransactionCategorisee], config: ConfigRecurrence | None = None
) -> list[GroupeRecurrent]:
    config = config or ConfigRecurrence()
    datees = [(t, _date(t.date)) for t in transactions if t.montant < 0 and _date(t.date)]
    if not datees:
        return []
    mois = {(d.year, d.month) for _, d in datees}
    occ_min = max(2, min(config.occurrences_min, len(mois)))

    groupes: dict[str, list[tuple[TransactionCategorisee, date]]] = defaultdict(list)
    for t, d in datees:
        groupes[cle_libelle(t.libelle)].append((t, d))

    resultats = []
    for cle, elements in groupes.items():
        elements.sort(key=lambda x: x[1])
        jours = sorted({d for _, d in elements})
        if len(jours) < occ_min:
            continue
        intervalles = [(b - a).days for a, b in zip(jours, jours[1:])]
        mediane = statistics.median(intervalles)
        periode = next(
            (
                (nom, p)
                for nom, p in PERIODES.items()
                if abs(mediane - p) / p <= config.tolerance_intervalle
            ),
            None,
        )
        if not periode:
            continue
        nom, p = periode
        conformes = sum(abs(i - p) / p <= config.tolerance_intervalle for i in intervalles)
        if conformes / len(intervalles) < 0.7:
            continue  # courses, restaurants... : fréquents mais irréguliers

        montants = [abs(t.montant) for t, _ in elements]
        moyenne = statistics.mean(montants)
        variable = (
            len(montants) > 1 and statistics.pstdev(montants) / moyenne > config.tolerance_montant / 2
        )
        categories = [t.categorie for t, _ in elements]
        resultats.append(
            GroupeRecurrent(
                cle=cle,
                libelle=elements[-1][0].libelle,
                categorie=max(set(categories), key=categories.count),
                periodicite=nom,
                occurrences=len(elements),
                montant_moyen=round(moyenne, 2),
                montant_mensuel=round(moyenne * PERIODES["mensuelle"] / p, 2),
                montant_variable=variable,
                dates=[d.isoformat() for d in jours],
            )
        )
    return sorted(resultats, key=lambda g: -g.montant_mensuel)


def cle_beneficiaire(libelle: str) -> str:
    """Personne concernée par un virement : son pseudonyme, sinon le premier mot significatif."""
    jeton = re.search(r"\[(PERSONNE_\d+)\]", libelle)
    return jeton.group(1) if jeton else cle_libelle(libelle, nb_mots=1)


def reperer_loyers(
    transactions: list[TransactionCategorisee], montant_min: float = 300.0, ecart_max: float = 0.1
) -> tuple[list[TransactionCategorisee], list[dict]]:
    """Loyer payé par virement sans le mot « loyer » : des virements vers une même personne, presque
    tous les mois, d'un montant stable et élevé. Ils passent de « virement_personnel » à « logement ».
    C'est une déduction (une pension versée chaque mois y ressemble) : elle est signalée dans le rapport."""
    mois_couverts = {t.date[:7] for t in transactions if _date(t.date)}
    par_personne: dict[str, list[TransactionCategorisee]] = defaultdict(list)
    for t in transactions:
        if t.categorie == "virement_personnel" and t.montant < 0 and _date(t.date):
            par_personne[cle_beneficiaire(t.libelle)].append(t)

    loyers, retenus = [], set()
    for personne, liste in par_personne.items():
        par_mois: dict[str, float] = defaultdict(float)
        for t in liste:
            par_mois[t.date[:7]] += -t.montant
        montants = list(par_mois.values())
        if len(montants) < 3 or len(montants) < 0.6 * len(mois_couverts):
            continue
        moyenne = statistics.mean(montants)
        if moyenne < montant_min or statistics.pstdev(montants) / moyenne > ecart_max:
            continue
        retenus.add(personne)
        loyers.append({"beneficiaire": personne, "montant_mensuel": round(moyenne, 2), "mois": len(montants)})
    if not retenus:
        return transactions, []
    return [
        t.model_copy(update={"categorie": "logement"})
        if t.categorie == "virement_personnel" and t.montant < 0 and cle_beneficiaire(t.libelle) in retenus
        else t
        for t in transactions
    ], loyers
