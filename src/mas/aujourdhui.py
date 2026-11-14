"""Ton budget aujourd'hui : les charges fixes à leur montant actuel, le reste en moyenne des derniers mois.

La moyenne de toute la période décrit le passé, et dilue ce qui vient de changer : une mensualité de prêt
commencée il y a quatre mois n'y pèse presque rien, un abonnement arrêté y compte encore. Ici :

- une charge fixe mensuelle (ou plus fréquente) toujours payée compte pour son dernier montant (la moyenne des
  derniers mois si son montant varie) ; arrêtée, elle ne compte plus ;
- une charge plus espacée (trimestrielle, annuelle…) ou un impôt compte pour ce qui a été payé sur les douze
  derniers mois, ramené au mois ;
- une dépense courante mais régulière, au même montant chaque mois (une mensualité que mas n'a pas su reconnaître
  comme un crédit, par exemple), compte elle aussi pour son dernier montant, dans les dépenses courantes ;
- le reste des dépenses courantes et les revenus sont la moyenne des douze derniers mois complets.

Calcul local, sans IA. Le budget n'est montré que s'il s'écarte vraiment de la moyenne (`a_montrer`).
"""

from __future__ import annotations

import statistics
from calendar import monthrange
from collections import defaultdict
from datetime import date

from .modeles import GroupeRecurrent, TransactionCategorisee
from .recurrence import PERIODES, cle_beneficiaire, cle_libelle

FENETRE_MOIS = 12
MOIS_MIN = 3
FREQUENTES = ("hebdomadaire", "mensuelle")
ETALEES = {"impots_taxes"}           # payées par mensualités sur une partie de l'année : comptées sur 12 mois
ECART_MIN_EUR, ECART_MIN_PART = 50.0, 0.03
CHANGEMENT_MIN_EUR = 5.0


def _jour(s: str) -> date | None:
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _fin_du_mois(aaaa_mm: str) -> date:
    annee, mois = int(aaaa_mm[:4]), int(aaaa_mm[5:7])
    return date(annee, mois, monthrange(annee, mois)[1])


def _paiements(g: GroupeRecurrent, debits: dict[str, list[TransactionCategorisee]]) -> list[tuple[date, float]]:
    """Ce que le groupe a coûté à chacune de ses dates (même clé de libellé, ou même bénéficiaire)."""
    benef = cle_beneficiaire(g.libelle)
    paiements = []
    for d in sorted(set(g.dates)):
        jour = _jour(d)
        montant = sum(-t.montant for t in debits.get(d[:10], [])
                      if cle_libelle(t.libelle) == g.cle or cle_beneficiaire(t.libelle) == benef)
        if jour and montant > 0:
            paiements.append((jour, montant))
    return paiements


def _actuel(g: GroupeRecurrent, paiements: list[tuple[date, float]], debut: date, fin: date,
            nb_mois: int, premiere: date) -> tuple[float, str, str | None]:
    """(montant mensuel d'aujourd'hui, ce qui a changé, depuis/jusqu'à quand). Changé : « nouvelle »,
    « arretee », « modifiee » ou "" ; pour une charge espacée, rien n'est dit. `premiere` : première opération
    des relevés (une charge déjà là au début n'est pas « nouvelle »)."""
    if not paiements:
        return 0.0, "", None
    periode = PERIODES.get(g.periodicite, PERIODES["mensuelle"])
    if g.periodicite not in FREQUENTES or g.categorie in ETALEES:
        # Ce qui a été payé sur les douze derniers mois (un peu plus pour une annuelle, payée à date près),
        # ramené au mois. Payée une seule fois : son montant net des remboursements (reperer_annuels).
        if g.occurrences == 1:
            paiements = [(paiements[-1][0], g.montant_moyen)]
        recul = max(nb_mois * PERIODES["mensuelle"], periode * 1.08)
        recents = [m for j, m in paiements if (fin - j).days < recul]
        return sum(recents) / max(nb_mois, periode / PERIODES["mensuelle"]), "", None
    dernier = paiements[-1][0]
    if (fin - dernier).days > periode + max(15.0, 0.25 * periode):
        return 0.0, "arretee", dernier.isoformat()[:7]
    recents = [m for j, m in paiements if j >= debut] or [paiements[-1][1]]
    montant = statistics.mean(recents) if g.montant_variable else paiements[-1][1]
    mensuel = montant * PERIODES["mensuelle"] / periode
    if paiements[0][0] >= debut and (paiements[0][0] - premiere).days > periode + 15:
        return mensuel, "nouvelle", paiements[0][0].isoformat()[:7]
    if not g.montant_variable and abs(mensuel - g.montant_mensuel) >= max(10.0, 0.03 * g.montant_mensuel):
        return mensuel, "modifiee", None
    return mensuel, "", None


def _reguliere(g: GroupeRecurrent) -> bool:
    """Une dépense courante qui se comporte comme une charge : chaque mois (ou plus souvent), au même montant.
    Pas les virements à des proches : calculer_budget les compte déjà nets de leurs remboursements."""
    return g.periodicite in FREQUENTES and not g.montant_variable and g.categorie != "virement_personnel"


def budget_aujourdhui(transactions: list[TransactionCategorisee], obligatoires: list[GroupeRecurrent],
                      optionnels: list[GroupeRecurrent], par_mois: dict,
                      courants: list[GroupeRecurrent] = (), fenetre_mois: int = FENETRE_MOIS) -> dict | None:
    """`par_mois` : le tableau mois par mois de `calculer_budget` (mois, partiels, lignes, totaux, revenus) ;
    `courants` : les groupes récurrents classés en dépenses courantes. None s'il y a moins de trois mois complets."""
    mois = par_mois.get("mois") or []
    partiels = set(par_mois.get("partiels") or [])
    complets = [m for m in mois if m not in partiels and len(m) == 7 and m[4] == "-"]
    fenetre = complets[-fenetre_mois:]
    if len(fenetre) < MOIS_MIN:
        return None
    debut = date(int(fenetre[0][:4]), int(fenetre[0][5:7]), 1)
    # L'activité se juge jusqu'à la dernière opération connue (un mois incomplet à la fin compte)
    jours = [j for t in transactions if (j := _jour(t.date))]
    fin = max([_fin_du_mois(fenetre[-1]), *jours])
    premiere = min(jours, default=debut)

    debits: dict[str, list[TransactionCategorisee]] = defaultdict(list)
    for t in transactions:
        if t.montant < 0:
            debits[t.date[:10]].append(t)

    comptees = {l["categorie"] for l in par_mois.get("lignes") or []}
    fixes_du_mois: dict[str, float] = defaultdict(float)     # dépenses régulières, mois par mois
    totaux = {"obligatoire": 0.0, "abonnement_optionnel": 0.0, "courant_variable": 0.0}
    changements = []
    for nature, groupes in (("obligatoire", obligatoires), ("abonnement_optionnel", optionnels),
                            ("courant_variable", [g for g in courants if _reguliere(g)])):
        for g in groupes:
            paiements = _paiements(g, debits)
            if g.categorie in comptees:
                for j, m in paiements:
                    fixes_du_mois[j.isoformat()[:7]] += m
            mensuel, sorte, quand = _actuel(g, paiements, debut, fin, len(fenetre), premiere)
            totaux[nature] += mensuel
            # Listé s'il pèse au moins 5 € par mois (compté dans tous les cas)
            if sorte and (sorte == "modifiee" or max(mensuel, g.montant_mensuel) >= CHANGEMENT_MIN_EUR):
                changements.append({
                    "nature": nature, "libelle": g.libelle, "sorte": sorte, "quand": quand,
                    "montant": round(mensuel if sorte != "arretee" else g.montant_mensuel, 2),
                    "avant": round(g.montant_mensuel, 2) if sorte == "modifiee" else None,
                })

    rang = {m: i for i, m in enumerate(mois)}
    tot_mois = par_mois.get("totaux") or []
    rev_mois = par_mois.get("revenus") or []
    courantes = statistics.mean(max(0.0, (tot_mois[rang[m]] if rang[m] < len(tot_mois) else 0.0) - fixes_du_mois[m])
                                for m in fenetre) + totaux["courant_variable"]
    revenus = statistics.mean(rev_mois[rang[m]] if rang[m] < len(rev_mois) else 0.0 for m in fenetre)
    depenses = totaux["obligatoire"] + totaux["abonnement_optionnel"] + courantes
    changements.sort(key=lambda c: -abs(c["montant"] - (c["avant"] or 0)))
    return {
        "fenetre": {"debut": fenetre[0], "fin": fenetre[-1], "nb_mois": len(fenetre)},
        "revenus": round(revenus, 2),
        "depenses": round(depenses, 2),
        "obligatoire": round(totaux["obligatoire"], 2),
        "optionnel": round(totaux["abonnement_optionnel"], 2),
        "courantes": round(courantes, 2),
        "changements": changements[:8],
    }


def a_montrer(aujourdhui: dict | None, depenses_moyennes: float) -> bool:
    """Seulement s'il dit autre chose que la moyenne : au moins 50 € et 3 % d'écart sur les dépenses."""
    if not aujourdhui:
        return False
    ecart = abs(aujourdhui["depenses"] - depenses_moyennes)
    return ecart >= ECART_MIN_EUR and ecart >= ECART_MIN_PART * max(depenses_moyennes, 1.0)


def mois_lisible(aaaa_mm: str | None) -> str:
    noms = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
            "novembre", "décembre")
    try:
        return f"{noms[int(aaaa_mm[5:7]) - 1]} {aaaa_mm[:4]}"
    except (TypeError, ValueError, IndexError):
        return ""


def aujourdhui_markdown(aujourdhui: dict | None, depenses_moyennes: float, eur) -> list[str]:
    """Le même budget dans le texte du rapport (et dans ce que lit l'IA pour sa synthèse)."""
    if not a_montrer(aujourdhui, depenses_moyennes):
        return []
    a, f = aujourdhui, aujourdhui["fenetre"]
    l = ["", f"### Ton budget aujourd'hui (dépenses régulières à leur montant actuel, le reste de {mois_lisible(f['debut'])} "
         f"à {mois_lisible(f['fin'])})", "",
         "La moyenne de toute la période décrit le passé ; ce budget-ci décrit les mois qui viennent, si rien ne change.", "",
         "| Indicateur (par mois) | Montant |", "|---|---:|",
         f"| Revenus | {eur(a['revenus'])} |",
         f"| Charges fixes actuelles | {eur(a['obligatoire'])} |",
         f"| Abonnements optionnels actuels | {eur(a['optionnel'])} |",
         f"| Dépenses courantes | {eur(a['courantes'])} |",
         f"| Dépenses totales | {eur(a['depenses'])} |",
         f"| Reste (négatif : manque) | {eur(a['revenus'] - a['depenses'])} |"]
    if a.get("changements"):
        l += ["", "Ce qui a changé :"]
        l += [f"- {phrase_changement(c, eur)}" for c in a["changements"]]
    return l


def phrase_changement(c: dict, eur, libelle: str | None = None) -> str:
    nom = libelle if libelle is not None else c["libelle"]
    if c["sorte"] == "nouvelle":
        return f"nouvelle depuis {mois_lisible(c['quand'])} : {nom}, {eur(c['montant'])} par mois"
    if c["sorte"] == "arretee":
        return f"arrêtée (dernier paiement en {mois_lisible(c['quand'])}) : {nom}, {eur(c['montant'])} par mois"
    return f"montant changé : {nom}, {eur(c['avant'])} → {eur(c['montant'])} par mois"
