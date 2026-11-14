"""Agent de synthèse + construction du rapport budgétaire.

Tous les chiffres sont calculés en Python ; le LLM ne rédige que le commentaire.
"""

from __future__ import annotations

import re
from collections import defaultdict

import dspy

from ..modeles import Classement, GroupeRecurrent, TransactionCategorisee
from ..aujourdhui import aujourdhui_markdown, budget_aujourdhui
from ..conseils import pistes_economie, pistes_markdown
from ..page import epargne_proche_phrase
from ..recurrence import cle_beneficiaire, cle_libelle
from .signatures import RedigerSynthese

TITRES = {
    "obligatoire": "Dépenses obligatoires",
    "abonnement_optionnel": "Abonnements optionnels",
    "courant_variable": "Dépenses courantes régulières",
}
# Argent qui ne fait que changer de compte : montré à part, jamais compté comme une dépense
TRANSFERTS = {
    "epargne": "Épargne (tes livrets, LDD…)",
    "entre_tes_comptes": "Entre tes comptes (débité sur un relevé, crédité sur un autre)",
    "tes_comptes": "Tes autres comptes déclarés",
    "a_ton_nom": "Comptes à ton nom (à confirmer)",
    "proches": "Virements avec des proches (mis à part)",
    "epargne_proche": "Épargne d'un proche gardée sur ton compte (reçue, puis rendue)",
    "exceptionnel": "Achat exceptionnel et son financement (hors moyenne mensuelle)",
}


def _eur(x: float) -> str:
    return f"{x:,.2f} €".replace(",", " ").replace(".", ",")


def mois_lisible(n: float) -> str:
    return str(int(n)) if float(n).is_integer() else f"{n:.1f}".replace(".", ",")


def solder_proches(transactions: list[TransactionCategorisee]) -> tuple[dict[str, float], dict[str, float]]:
    """Virements avec des proches, personne par personne et dans l'ordre des dates.

    L'argent qui revient après un virement (remboursement) annule ce virement au lieu de compter
    comme un revenu ; seul ce qui dépasse la somme envoyée est un revenu. À l'inverse, rendre à un
    proche l'argent qu'il t'avait avancé n'est pas une dépense. Renvoie les totaux et la dépense
    nette de chaque mois (négative le mois d'un remboursement).
    """
    soldes: dict[str, float] = defaultdict(float)   # > 0 : la personne te doit ; < 0 : tu lui dois
    totaux = {"envoye": 0.0, "recu": 0.0, "rembourse": 0.0, "depense": 0.0, "revenu": 0.0}
    par_mois: dict[str, float] = defaultdict(float)
    proches = [t for t in transactions if t.categorie == "virement_personnel"]
    for t in sorted(proches, key=lambda t: t.date):
        personne, mois = cle_beneficiaire(t.libelle), t.date[:7]
        if t.montant < 0:
            montant = -t.montant
            rendu = min(montant, max(0.0, -soldes[personne]))     # tu rends une avance
            totaux["envoye"] += montant
            totaux["rembourse"] += rendu
            totaux["revenu"] -= rendu
            totaux["depense"] += montant - rendu
            par_mois[mois] += montant - rendu
            soldes[personne] += montant
        else:
            montant = t.montant
            rembourse = min(montant, max(0.0, soldes[personne]))  # on te rend ce que tu avais envoyé
            totaux["recu"] += montant
            totaux["rembourse"] += rembourse
            totaux["depense"] -= rembourse
            totaux["revenu"] += montant - rembourse
            par_mois[mois] -= rembourse
            soldes[personne] -= montant
    return totaux, par_mois


NATURES_PROCHES = {
    "recus": "Reçus seulement",
    "allers_retours": "Allers-retours (avances, remboursements)",
    "regulier": "Régulier (presque tous les mois)",
    "ponctuel": "Ponctuel (un ou deux virements)",
    "occasionnel": "Occasionnel",
}


def proches_par_personne(transactions: list[TransactionCategorisee]) -> list[dict]:
    """Virements avec des proches, personne par personne (pseudonyme, sinon premier mot du libellé),
    sur toute la période : ce que chacun ajoute aux dépenses, son plus gros virement et chaque
    opération. De quoi voir qui pèse dans le total et repérer ce qui n'est pas un proche (un compte
    à toi, un loyer…). Du plus gros poids dans les dépenses au plus petit."""
    par_personne: dict[str, list[TransactionCategorisee]] = defaultdict(list)
    for t in transactions:
        if t.categorie == "virement_personnel":
            par_personne[cle_beneficiaire(t.libelle)].append(t)
    nb_mois = len({t.date[:7] for t in transactions}) or 1
    detail = []
    for personne, liste in par_personne.items():
        totaux, _ = solder_proches(liste)       # mêmes règles que le total : remboursements déduits
        envois = [t for t in liste if t.montant < 0]
        mois_envois = {t.date[:7] for t in envois}
        if not envois:
            nature = "recus"
        elif totaux["recu"] >= 0.5 * totaux["envoye"]:
            nature = "allers_retours"
        elif len(mois_envois) >= 3 and len(mois_envois) >= 0.6 * nb_mois:
            nature = "regulier"
        else:
            nature = "ponctuel" if len(envois) <= 2 else "occasionnel"
        plus_gros = min(envois, key=lambda t: t.montant) if envois else None
        detail.append({
            "personne": personne,
            "virements": len(liste),
            **{k: round(totaux[k], 2) for k in ("envoye", "recu", "depense", "revenu")},
            "nature": nature,
            "plus_gros": {"date": plus_gros.date, "montant": round(-plus_gros.montant, 2)} if plus_gros else None,
            "operations": [{"date": t.date, "libelle": t.libelle, "montant": round(t.montant, 2)}
                           for t in sorted(liste, key=lambda t: t.date)],
        })
    return sorted(detail, key=lambda p: (-p["depense"], -p["envoye"]))


SEUIL_A_VERIFIER = 100.0


def a_verifier(transactions: list[TransactionCategorisee], transferts: list[dict] | None = None,
               seuil: float = SEUIL_A_VERIFIER) -> list[dict]:
    """Ce que mas n'a pas pu classer avec certitude et qui pèse dans le budget : à confirmer par toi
    (analyse.categories, analyse.comptes_personnels). Les plus gros montants d'abord, 20 au plus."""
    lignes = []
    for t in transferts or []:
        if t["type"] == "exceptionnel":
            raison = ("Prêt débloqué : pas compté comme un revenu." if t["montant"] > 0 else
                      "Achat exceptionnel, mis à part de la moyenne : vérifie que c'en est bien un.")
            lignes.append({"date": t["date"], "libelle": t["libelle"], "montant": round(t["montant"], 2),
                           "categorie": None, "raison": raison})
    for t in transactions:
        if abs(t.montant) < seuil:
            continue
        if t.categorie == "autre":
            raison = "Commerçant inconnu : donne sa catégorie dans analyse.categories."
        elif re.search(r"(?i)^\s*carte\s+\d+\s+\[PERSONNE_\d+\]", t.libelle):   # le commerçant lui-même
            raison = "Commerçant au nom masqué : si sa catégorie est fausse, corrige-la dans analyse.categories."
        elif t.categorie == "virement_personnel" and t.montant <= -500:
            raison = ("Gros virement à un particulier : un achat, un loyer, un de tes comptes "
                      "(analyse.comptes_personnels) ?")
        else:
            continue
        lignes.append({"date": t.date, "libelle": t.libelle, "montant": round(t.montant, 2),
                       "categorie": t.categorie, "raison": raison})
    return sorted(lignes, key=lambda l: -abs(l["montant"]))[:20]


def nom_proche(personne: str) -> str:
    """Pseudonyme entre crochets (remplacé par le vrai nom dans la version personnelle)."""
    return f"[{personne}]" if re.fullmatch(r"PERSONNE_\d+", personne) else personne


def calculer_budget(
    transactions: list[TransactionCategorisee],
    groupes: list[GroupeRecurrent],
    classements: list[Classement],
    transferts: list[dict] | None = None,
    nb_mois: float | None = None,
    periode: str | None = None,
    proches_a_part: bool = False,
    couverture: dict[str, float] | None = None,
    loyers: list[dict] | None = None,
    recus_de_proches: str = "a_part",
) -> dict:
    """Moyennes mensuelles.

    - `nb_mois` / `periode` : d'après les dates des relevés quand on les connaît (sinon, les mois
      présents dans les opérations) ;
    - `transferts` : mouvements entre tes propres comptes, exclus des dépenses et des revenus ;
    - les remboursements (crédits d'une catégorie de dépense) viennent en déduction de la catégorie ;
    - virements avec des proches : un remboursement annule le virement qu'il rembourse ; l'excédent
      reçu n'est compté comme un revenu qu'avec recus_de_proches="revenu" (voir `solder_proches`) ;
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

    proches, proches_par_mois = solder_proches(transactions)
    if not proches_a_part and (debits.get("virement_personnel") or credits.get("virement_personnel")):
        debits["virement_personnel"] = proches["depense"]
        credits.pop("virement_personnel", None)
    # L'argent reçu de proches en plus de ce que tu leur envoies n'est un revenu que si tu le dis
    # (analyse.recus_de_proches: revenu) : une aide ponctuelle ne se reproduit pas chaque mois
    en_revenu = not proches_a_part and recus_de_proches == "revenu"
    revenus = credits.pop("revenu", 0.0) - debits.pop("revenu", 0.0) + (proches["revenu"] if en_revenu else 0.0)
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
        if categorie == "virement_personnel":
            continue                        # compté plus bas, remboursements déduits
        par_mois_cat[categorie][t.date[:7]] += -t.montant
    if not proches_a_part:
        for mois_, montant in proches_par_mois.items():
            par_mois_cat["virement_personnel"][mois_] += montant
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
    # Dans chaque case, la part des dépenses récurrentes « à payer quoi qu'il arrive » (pour la page)
    obligatoires = par_nature.get("obligatoire", [])
    cles = {g.cle for g in obligatoires}
    paiements = {(cle_beneficiaire(g.libelle), d) for g in obligatoires for d in g.dates}
    oblig_mois: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for t in transactions:
        if t.montant < 0 and (cle_libelle(t.libelle) in cles or (cle_beneficiaire(t.libelle), t.date) in paiements):
            oblig_mois[t.categorie][t.date[:7]] += -t.montant
    for ligne in par_mois["lignes"]:
        ligne["obligatoire"] = [round(min(oblig_mois[ligne["categorie"]].get(m, 0.0), max(x, 0.0)), 2)
                                for m, x in zip(liste_mois, ligne["montants"])]
    # Ce qui a vraiment été payé en charges fixes et en abonnements, en moyenne sur la période : pour la frise
    # du mois moyen (total_obligatoire, lui, compte chaque charge comme si elle avait couru toute la période)
    optionnels = par_nature.get("abonnement_optionnel", [])
    cles_opt = {g.cle for g in optionnels}
    paiements_opt = {(cle_beneficiaire(g.libelle), d) for g in optionnels for d in g.dates}
    opt_mois: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for t in transactions:
        if t.montant < 0 and (cle_libelle(t.libelle) in cles_opt or (cle_beneficiaire(t.libelle), t.date) in paiements_opt):
            opt_mois[t.categorie][t.date[:7]] += -t.montant
    oblig_paye = sum(sum(l["obligatoire"]) for l in par_mois["lignes"])
    opt_paye = sum(min(opt_mois[l["categorie"]].get(m, 0.0), max(x - o, 0.0))
                   for l in par_mois["lignes"] for m, x, o in zip(liste_mois, l["montants"], l["obligatoire"]))
    # Revenus de chaque mois, pour l'écart revenus − dépenses de la page (jamais envoyés à l'IA)
    revenus_mois: dict[str, float] = defaultdict(float)
    for t in transactions:
        if t.categorie == "revenu":
            revenus_mois[t.date[:7]] += t.montant
    par_mois["revenus"] = [round(revenus_mois.get(m, 0.0), 2) for m in liste_mois]

    total_oblig = sum(g.montant_mensuel for g in par_nature["obligatoire"])
    par_categorie = {k: v / n for k, v in sorted(depenses_cat.items(), key=lambda x: -x[1])}
    total_optionnel = sum(g.montant_mensuel for g in par_nature["abonnement_optionnel"])
    return {
        "par_mois": par_mois,
        "nb_mois": n,
        "periode": periode or f"{mois[0]} → {mois[-1]}",
        "revenus_mensuels": revenus / n,
        "depenses_mensuelles": sum(depenses_cat.values()) / n,
        "par_categorie": par_categorie,
        "par_nature": par_nature,
        "total_obligatoire": total_oblig,
        "total_optionnel": total_optionnel,
        "obligatoire_moyen": oblig_paye / n,
        "optionnel_moyen": opt_paye / n,
        "reste_apres_obligatoire": revenus / n - total_oblig,
        "transferts": {k: {"sortis": v["sortis"] / n, "rentres": v["rentres"] / n}
                       for k, v in flux.items() if v["sortis"] or v["rentres"]},
        "proches": ({k: v / n for k, v in proches.items()}
                    if not proches_a_part and (proches["envoye"] or proches["recu"]) else None),
        "proches_detail": proches_par_personne(transactions),
        "recus_proches_en_revenu": en_revenu,
        "a_verifier": a_verifier(transactions, transferts),
        "loyers": loyers or [],
        # Où économiser sur les dépenses variables : chaque poste comparé à tes propres mois
        "pistes": pistes_economie(par_mois, revenus / n, par_categorie, total_optionnel),
        # Les charges fixes à leur montant actuel, le reste sur les douze derniers mois (aujourdhui.py)
        "aujourdhui": budget_aujourdhui(transactions, par_nature.get("obligatoire", []),
                                        par_nature.get("abonnement_optionnel", []), par_mois,
                                        par_nature.get("courant_variable", [])),
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
        if "epargne_proche" in budget["transferts"]:
            l += ["", epargne_proche_phrase(budget["transferts"]["epargne_proche"], budget["nb_mois"], _eur)]
    if budget.get("proches"):
        p = budget["proches"]
        l += ["", "### Virements avec des proches (moyenne mensuelle)", "",
              "Un remboursement annule le virement qu'il rembourse : seul l'excédent reçu est un revenu.", "",
              "| Envoyé | Reçu | Dont remboursements | Compté en dépense | "
              + ("Compté en revenu |" if budget.get("recus_proches_en_revenu") else "Reçu en plus (pas un revenu) |"),
              "|---:|---:|---:|---:|---:|",
              f"| {_eur(p['envoye'])} | {_eur(p['recu'])} | {_eur(p['rembourse'])} | {_eur(p['depense'])} | {_eur(p['revenu'])} |"]
    if budget.get("proches_detail"):
        compte = budget.get("proches") is not None      # sinon : mis à part, rien en dépense
        l += ["", f"#### Par personne (total sur {mois_lisible(budget['nb_mois'])} mois)", "",
              "| Personne | Virements | Envoyé | Reçu | Compté en dépense | Plus gros virement | Type |",
              "|---|---:|---:|---:|---:|---:|---|"]
        for d in budget["proches_detail"][:10]:
            gros = f"{_eur(d['plus_gros']['montant'])} le {d['plus_gros']['date']}" if d["plus_gros"] else "—"
            l.append(f"| {nom_proche(d['personne'])} | {d['virements']} | {_eur(d['envoye'])} | {_eur(d['recu'])} | "
                     f"{_eur(d['depense']) if compte else '—'} | {gros} | {NATURES_PROCHES[d['nature']]} |")
        if len(budget["proches_detail"]) > 10:
            reste = budget["proches_detail"][10:]
            l.append(f"| {len(reste)} autres personnes | {sum(d['virements'] for d in reste)} | "
                     f"{_eur(sum(d['envoye'] for d in reste))} | {_eur(sum(d['recu'] for d in reste))} | "
                     f"{_eur(sum(d['depense'] for d in reste)) if compte else '—'} | | |")
    l += aujourdhui_markdown(budget.get("aujourdhui"), budget["depenses_mensuelles"], _eur)
    l += pistes_markdown(budget.get("pistes"), _eur)
    if budget.get("a_verifier"):
        l += ["", "### À vérifier", "", "Opérations que mas n'a pas pu classer avec certitude.", "",
              "| Date | Libellé | Montant | Pourquoi |", "|---|---|---:|---|"]
        l += [f"| {v['date']} | {v['libelle']} | {_eur(v['montant'])} | {v['raison']} |" for v in budget["a_verifier"][:10]]
    for loyer in budget.get("loyers", []):
        l += ["", f"**Loyer probable :** {_eur(loyer['montant_mensuel'])} par mois versés à [{loyer['beneficiaire']}] "
                  f"pendant {loyer['mois']} mois, comptés dans le logement (déduction : même montant chaque mois)."]
    for nature, titre in TITRES.items():
        groupes = budget["par_nature"].get(nature, [])
        if not groupes:
            continue
        l += ["", f"### {titre}", "", "| Poste | Catégorie | Périodicité | Par mois | Remarque |",
              "|---|---|---|---:|---|"]
        for g in groupes:
            variable = " (montant variable)" if g.montant_variable else ""
            if g.periodicite != "mensuelle":
                variable += f" (ramené au mois : {_eur(g.montant_moyen)} payés à chaque fois)"
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

    def commenter(self, budget: dict, resume: str) -> str:
        try:
            return self.rediger(resume_chiffre=resume).synthese
        except Exception as e:
            return f"_Synthèse indisponible ({e})._"

    def forward(self, transactions, recurrents, classements, transferts=None, nb_mois=None,
                periode=None, proches_a_part=False, couverture=None, loyers=None,
                recus_de_proches="a_part") -> dspy.Prediction:
        budget = calculer_budget(transactions, recurrents, classements, transferts, nb_mois, periode,
                                 proches_a_part, couverture, loyers, recus_de_proches)
        resume = resume_markdown(budget, classements)
        commentaire = self.commenter(budget, resume)
        rapport = f"# Analyse budgétaire\n\n{commentaire}\n\n## Chiffres détaillés\n\n{resume}\n"
        return dspy.Prediction(rapport=rapport, budget=budget, commentaire=commentaire)
