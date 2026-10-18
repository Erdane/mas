"""Agent de synthèse + construction du rapport budgétaire.

Tous les chiffres sont calculés en Python ; le LLM ne rédige que le commentaire.
"""

from __future__ import annotations

from collections import defaultdict

import dspy

from ..modeles import Classement, GroupeRecurrent, TransactionCategorisee
from .signatures import RedigerSynthese

TITRES = {
    "obligatoire": "Dépenses obligatoires",
    "abonnement_optionnel": "Abonnements optionnels",
    "courant_variable": "Dépenses courantes régulières",
}
# Argent qui ne fait que changer de compte : montré à part, jamais compté comme une dépense
TRANSFERTS = {
    "epargne": "Épargne (tes livrets, LDD…)",
    "tes_comptes": "Tes autres comptes déclarés",
    "a_ton_nom": "Comptes à ton nom (à confirmer)",
    "proches": "Virements avec des proches (mis à part)",
}


def _eur(x: float) -> str:
    return f"{x:,.2f} €".replace(",", " ").replace(".", ",")


def mois_lisible(n: float) -> str:
    return str(int(n)) if float(n).is_integer() else f"{n:.1f}".replace(".", ",")


def calculer_budget(
    transactions: list[TransactionCategorisee],
    groupes: list[GroupeRecurrent],
    classements: list[Classement],
    transferts: list[dict] | None = None,
    nb_mois: float | None = None,
    periode: str | None = None,
    proches_a_part: bool = False,
    couverture: dict[str, float] | None = None,
) -> dict:
    """Moyennes mensuelles.

    - `nb_mois` / `periode` : d'après les dates des relevés quand on les connaît (sinon, les mois
      présents dans les opérations) ;
    - `transferts` : mouvements entre tes propres comptes, exclus des dépenses et des revenus ;
    - les remboursements (crédits d'une catégorie de dépense) viennent en déduction de la catégorie ;
    - l'argent reçu de particuliers compte dans les revenus ;
    - `couverture` (mois -> part des jours couverts par les relevés) signale les mois incomplets.
    """
    mois = sorted({t.date[:7] for t in transactions}) or ["?"]
    n = nb_mois or len(mois)
    nature = {c.cle: c.nature for c in classements}

    par_nature: dict[str, list[GroupeRecurrent]] = defaultdict(list)
    for g in groupes:
        par_nature[nature.get(g.cle, "courant_variable")].append(g)

    debits: dict[str, float] = defaultdict(float)
    credits: dict[str, float] = defaultdict(float)
    for t in transactions:
        if t.montant < 0:
            debits[t.categorie] += -t.montant
        else:
            credits[t.categorie] += t.montant

    flux: dict[str, dict[str, float]] = defaultdict(lambda: {"sortis": 0.0, "rentres": 0.0})
    for tr in transferts or []:
        flux[tr["type"]]["sortis" if tr["montant"] < 0 else "rentres"] += abs(tr["montant"])
    # Épargne repérée par l'IA (relevés sans tableau reconnu) : mise de côté, pas une dépense
    flux["epargne"]["sortis"] += debits.pop("epargne", 0.0)
    flux["epargne"]["rentres"] += credits.pop("epargne", 0.0)
    if proches_a_part:
        flux["proches"]["sortis"] += debits.pop("virement_personnel", 0.0)
        flux["proches"]["rentres"] += credits.pop("virement_personnel", 0.0)

    revenus = credits.pop("revenu", 0.0) - debits.pop("revenu", 0.0) + credits.pop("virement_personnel", 0.0)
    depenses_cat: dict[str, float] = {}
    for categorie in set(debits) | set(credits):
        net = debits.get(categorie, 0.0) - credits.get(categorie, 0.0)
        if net > 0:
            depenses_cat[categorie] = net
        elif net < 0:
            revenus += -net                 # remboursements plus élevés que les dépenses du mois

    # Répartition mois par mois, avec les mêmes règles (remboursements déduits, transferts exclus)
    par_mois_cat: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for t in transactions:
        categorie = t.categorie
        if categorie in ("revenu", "epargne") or (proches_a_part and categorie == "virement_personnel"):
            continue
        if categorie == "virement_personnel" and t.montant > 0:
            continue                        # argent reçu d'un proche : un revenu, pas une dépense négative
        par_mois_cat[categorie][t.date[:7]] += -t.montant
    # mois des relevés (couverture) et mois des opérations : aucune opération ne sort du tableau
    liste_mois = sorted(set(couverture) | {t.date[:7] for t in transactions}) if couverture else mois
    ordre = [c for c, _ in sorted(depenses_cat.items(), key=lambda x: -x[1])]
    par_mois = {
        "mois": liste_mois,
        "partiels": [m for m in liste_mois if couverture and couverture.get(m, 0.0) < 0.75],
        "lignes": [{"categorie": c, "montants": [round(par_mois_cat[c].get(m, 0.0), 2) for m in liste_mois]}
                   for c in ordre],
    }
    par_mois["totaux"] = [round(sum(l["montants"][i] for l in par_mois["lignes"]), 2)
                          for i in range(len(liste_mois))]

    total_oblig = sum(g.montant_mensuel for g in par_nature["obligatoire"])
    return {
        "par_mois": par_mois,
        "nb_mois": n,
        "periode": periode or f"{mois[0]} → {mois[-1]}",
        "revenus_mensuels": revenus / n,
        "depenses_mensuelles": sum(depenses_cat.values()) / n,
        "par_categorie": {k: v / n for k, v in sorted(depenses_cat.items(), key=lambda x: -x[1])},
        "par_nature": par_nature,
        "total_obligatoire": total_oblig,
        "total_optionnel": sum(g.montant_mensuel for g in par_nature["abonnement_optionnel"]),
        "reste_apres_obligatoire": revenus / n - total_oblig,
        "transferts": {k: {"sortis": v["sortis"] / n, "rentres": v["rentres"] / n}
                       for k, v in flux.items() if v["sortis"] or v["rentres"]},
    }


def resume_markdown(budget: dict, classements: list[Classement]) -> str:
    justif = {c.cle: c.justification for c in classements}
    l = [
        f"**Période analysée :** {budget['periode']} ({mois_lisible(budget['nb_mois'])} mois)",
        "",
        "| Indicateur (moyenne mensuelle) | Montant |",
        "|---|---:|",
        f"| Revenus | {_eur(budget['revenus_mensuels'])} |",
        f"| Dépenses totales | {_eur(budget['depenses_mensuelles'])} |",
        f"| Dépenses obligatoires récurrentes | {_eur(budget['total_obligatoire'])} |",
        f"| Abonnements optionnels | {_eur(budget['total_optionnel'])} |",
        f"| Reste après dépenses obligatoires | {_eur(budget['reste_apres_obligatoire'])} |",
    ]
    if budget.get("transferts"):
        l += ["", "### Hors dépenses : argent déplacé entre tes comptes (moyenne mensuelle)", "",
              "Ces mouvements ne sont comptés ni dans les dépenses ni dans les revenus.", "",
              "| Vers / depuis | Sorti | Rentré |", "|---|---:|---:|"]
        for cle, v in budget["transferts"].items():
            l.append(f"| {TRANSFERTS.get(cle, cle)} | {_eur(v['sortis'])} | {_eur(v['rentres'])} |")
    for nature, titre in TITRES.items():
        groupes = budget["par_nature"].get(nature, [])
        if not groupes:
            continue
        l += ["", f"### {titre}", "", "| Poste | Catégorie | Périodicité | Par mois | Remarque |",
              "|---|---|---|---:|---|"]
        for g in groupes:
            variable = " (montant variable)" if g.montant_variable else ""
            l.append(
                f"| {g.libelle} | {g.categorie} | {g.periodicite} ({g.occurrences}×) | "
                f"{_eur(g.montant_mensuel)}{variable} | {justif.get(g.cle, '')} |"
            )
    l += ["", "### Dépenses par catégorie (moyenne mensuelle)", "", "| Catégorie | Montant |", "|---|---:|"]
    l += [f"| {k} | {_eur(v)} |" for k, v in budget["par_categorie"].items()]
    par_mois = budget.get("par_mois") or {}
    if par_mois.get("lignes") and len(par_mois["mois"]) > 1:
        partiels = set(par_mois["partiels"])
        entetes = [m + ("*" if m in partiels else "") for m in par_mois["mois"]]
        l += ["", "### Dépenses par mois et par catégorie", "",
              "| Catégorie | " + " | ".join(entetes) + " | Moyenne |",
              "|---|" + "---:|" * (len(entetes) + 1)]
        for ligne in par_mois["lignes"]:
            l.append(f"| {ligne['categorie']} | " + " | ".join(_eur(x) for x in ligne["montants"])
                     + f" | {_eur(budget['par_categorie'].get(ligne['categorie'], 0.0))} |")
        l.append("| **Total** | " + " | ".join(f"**{_eur(x)}**" for x in par_mois["totaux"])
                 + f" | **{_eur(budget['depenses_mensuelles'])}** |")
        if partiels:
            l += ["", "\\* mois incomplet : les relevés ne couvrent qu'une partie du mois."]
    return "\n".join(l)


class Synthetiseur(dspy.Module):
    def __init__(self):
        super().__init__()
        self.rediger = dspy.Predict(RedigerSynthese)

    def forward(self, transactions, recurrents, classements, transferts=None, nb_mois=None,
                periode=None, proches_a_part=False, couverture=None) -> dspy.Prediction:
        budget = calculer_budget(transactions, recurrents, classements, transferts, nb_mois, periode,
                                 proches_a_part, couverture)
        resume = resume_markdown(budget, classements)
        try:
            commentaire = self.rediger(resume_chiffre=resume).synthese
        except Exception as e:
            commentaire = f"_Synthèse indisponible ({e})._"
        rapport = f"# Analyse budgétaire\n\n{commentaire}\n\n## Chiffres détaillés\n\n{resume}\n"
        return dspy.Prediction(rapport=rapport, budget=budget, commentaire=commentaire)
