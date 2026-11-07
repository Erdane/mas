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
    t = re.sub(r"^(CARTE|AVOIR|RETRAITDAB)\s?\d{2}/\d{2}/\d{2}", r"\1 ", t)   # « CARTE02/05/26NETFLIX » (Boursorama)
    t = re.sub(r"\s?\d?CB\*\d+", " ", t)                       # « 2CB*1234 » : la carte, pas le commerçant
    t = re.sub(r"\b\d{1,2}[/.\-]\d{1,2}(?:[/.\-]\d{2,4})?\b", " ", t)  # dates
    t = re.sub(r"\b(?=[0-9A-F]*\d[0-9A-F]*\d)[0-9A-F]{6,}\b", " ", t)  # identifiants (« E81AEFC »)
    t = re.sub(r"\b([A-Z]{3,})\d+\b", r"\1", t)                # numéro de magasin : « LIDL3604 »
    t = re.sub(r"\b\w*\d{3,}\w*\b|\bX{3,}\b", " ", t)          # références numériques, n° de carte masqué
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
        montants = [abs(t.montant) for t, _ in elements]
        moyenne = statistics.mean(montants)
        conformes = sum(abs(i - p) / p <= config.tolerance_intervalle for i in intervalles)
        # Un loyer payé à date variable (le 1er, puis le 5, puis le 15) reste mensuel : même montant
        # presque tous les mois, un ou deux paiements par mois au plus
        mois_payes = {(d.year, d.month) for d in jours}
        mensuel_a_date_variable = (
            nom == "mensuelle" and len(mois_payes) >= 0.6 * len(mois) and len(jours) <= 1.5 * len(mois_payes)
            and statistics.pstdev(montants) / moyenne <= config.tolerance_montant / 2
        )
        if conformes / len(intervalles) < 0.7 and not mensuel_a_date_variable:
            continue  # courses, restaurants... : fréquents mais irréguliers

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


ANNUELLES = {"assurance", "abonnement", "impots_taxes"}


def reperer_annuels(
    transactions: list[TransactionCategorisee], groupes: list[GroupeRecurrent], montant_min: float = 50.0
) -> list[GroupeRecurrent]:
    """Dépense payée une fois par an (assurance auto, abonnement annuel, taxe foncière) : une seule fois
    sur au moins six mois de relevés, d'au moins montant_min € remboursements déduits. Ramenée au mois
    comme si elle revenait l'an prochain ; detecter_recurrences ne la voit pas (trois paiements au moins)."""
    if len({t.date[:7] for t in transactions if _date(t.date)}) < 6:
        return []
    deja = {g.cle for g in groupes}
    par_cle: dict[str, list[TransactionCategorisee]] = defaultdict(list)
    for t in transactions:
        if t.categorie in ANNUELLES and _date(t.date):
            par_cle[cle_libelle(t.libelle)].append(t)
    resultats = []
    for cle, liste in par_cle.items():
        debits = [t for t in liste if t.montant < 0]
        net = -sum(t.montant for t in liste)
        if cle in deja or len(debits) != 1 or net < montant_min:
            continue
        resultats.append(GroupeRecurrent(
            cle=cle, libelle=debits[0].libelle, categorie=debits[0].categorie, periodicite="annuelle",
            occurrences=1, montant_moyen=round(net, 2), montant_mensuel=round(net / 12, 2),
            montant_variable=False, dates=[debits[0].date],
        ))
    return resultats


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
