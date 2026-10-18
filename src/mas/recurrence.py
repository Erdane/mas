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
