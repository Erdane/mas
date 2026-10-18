"""Métrique avec retour textuel pour GEPA.

GEPA ne se contente pas d'un score : il lit le retour (« feedback ») pour
comprendre POURQUOI une sortie est mauvaise, puis réécrit les instructions du
prédicteur concerné. Chaque prédicteur reçoit donc un retour ciblé :

- extracteur  : opérations manquées, inventées, erreurs de signe ou de date
- categoriseur: libellés mal classés (prédit / attendu)
- classeur    : récurrences mal qualifiées (obligatoire / optionnel / variable)
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

import dspy

from ..anonymisation.coffre import sans_accents

POIDS = {"extraction": 0.35, "categorisation": 0.25, "recurrence": 0.20, "nature": 0.20}
MAX_EXEMPLES = 8


def _f1(vp: int, fp: int, fn: int) -> float:
    if vp == 0:
        return 0.0 if fp or fn else 1.0
    p, r = vp / (vp + fp), vp / (vp + fn)
    return 2 * p * r / (p + r)


def _norm(texte: str) -> str:
    return re.sub(r"\s+", "", sans_accents(texte)).lower()


def _champ(objet, nom):
    return objet[nom] if isinstance(objet, dict) else getattr(objet, nom)


@dataclass
class Evaluation:
    scores: dict[str, float] = field(default_factory=dict)
    retours: dict[str, list[str]] = field(default_factory=dict)
    fuite: list[str] = field(default_factory=list)

    @property
    def score(self) -> float:
        if self.fuite:
            return 0.0
        return round(sum(POIDS[k] * self.scores.get(k, 0.0) for k in POIDS), 4)

    def retour(self, composant: str | None = None) -> str:
        entete = (
            f"Score global {self.score:.2f} — extraction {self.scores['extraction']:.2f}, "
            f"catégorisation {self.scores['categorisation']:.2f}, "
            f"récurrences {self.scores['recurrence']:.2f}, nature {self.scores['nature']:.2f}."
        )
        lignes = [entete]
        if self.fuite:
            lignes.append(
                "ÉCHEC CRITIQUE : des données personnelles apparaissent en clair dans la "
                "sortie : " + ", ".join(self.fuite) + ". Recopie les jetons [XXX_n] sans les deviner."
            )
        cles = [composant] if composant else list(self.retours)
        for c in cles:
            lignes += self.retours.get(c, [])
        if len(lignes) == 1:
            lignes.append("Aucune erreur sur ce composant pour cet exemple.")
        return "\n".join(lignes)


def evaluer_prediction(gold, pred) -> Evaluation:
    ev = Evaluation(retours={"extraction": [], "categorisation": [], "nature": []})

    # --- 1. Extraction : appariement par (date, |montant|) ---------------------
    gold_tx = list(gold.transactions)
    pred_tx = list(pred.transactions or [])
    index_gold: dict[tuple, list[dict]] = {}
    for g in gold_tx:
        index_gold.setdefault((g["date"], round(abs(g["montant"]), 2)), []).append(g)
    paires, inventees = [], []
    for p in pred_tx:
        cle = (_champ(p, "date"), round(abs(_champ(p, "montant")), 2))
        if index_gold.get(cle):
            paires.append((index_gold[cle].pop(), p))
        else:
            inventees.append(p)
    manquees = [g for liste in index_gold.values() for g in liste]
    ev.scores["extraction"] = _f1(len(paires), len(inventees), len(manquees))

    r = ev.retours["extraction"]
    if manquees:
        r.append(f"{len(manquees)} opération(s) manquée(s), par ex. : " + "; ".join(
            f"{g['date']} « {g['libelle']} » {g['montant']:+.2f}" for g in manquees[:MAX_EXEMPLES]
        ))
    if inventees:
        r.append(f"{len(inventees)} opération(s) sans correspondance (montant ou date faux, "
                 "ou solde pris pour une opération), par ex. : " + "; ".join(
            f"{_champ(p, 'date')} « {_champ(p, 'libelle')} » {_champ(p, 'montant'):+.2f}"
            for p in inventees[:MAX_EXEMPLES]
        ))
    signes = [(g, p) for g, p in paires if (g["montant"] > 0) != (_champ(p, "montant") > 0)]
    if signes:
        r.append(f"{len(signes)} erreur(s) de signe débit/crédit, par ex. : " + "; ".join(
            f"« {g['libelle']} » attendu {g['montant']:+.2f}, obtenu {_champ(p, 'montant'):+.2f}"
            for g, p in signes[:MAX_EXEMPLES]
        ))
        ev.scores["extraction"] *= 1 - len(signes) / max(1, len(paires))

    # --- 2. Catégorisation (sur les opérations appariées) ----------------------
    erreurs = [(g, p) for g, p in paires if _champ(p, "categorie") != g["categorie"]]
    ev.scores["categorisation"] = 1 - len(erreurs) / len(paires) if paires else 0.0
    vues = set()
    for g, p in erreurs:
        cle = (_champ(p, "categorie"), g["categorie"], " ".join(g["libelle"].split()[:3]))
        if cle in vues:
            continue
        vues.add(cle)
        ev.retours["categorisation"].append(
            f"« {_champ(p, 'libelle')} » classé {_champ(p, 'categorie')}, attendu {g['categorie']}."
        )
        if len(vues) >= MAX_EXEMPLES:
            break

    # --- 3. Récurrences (détection déterministe en aval de l'extraction) -------
    motifs = {r_["motif"]: r_ for r_ in gold.recurrents}
    trouves: dict[str, object] = {}
    faux = []
    for groupe in pred.recurrents or []:
        lib = sans_accents(_champ(groupe, "libelle")).upper()
        motif = next((m for m in motifs if sans_accents(m).upper() in lib), None)
        if motif and motif not in trouves:
            trouves[motif] = groupe
        elif not motif:
            faux.append(groupe)
    rates = [m for m in motifs if m not in trouves]
    ev.scores["recurrence"] = _f1(len(trouves), len(faux), len(rates))
    if rates:
        # Une récurrence ratée vient presque toujours de l'extraction (date ou montant faux)
        ev.retours["extraction"].append(
            "Dépenses récurrentes non détectées (vérifie que chaque occurrence mensuelle "
            "est extraite avec sa date exacte et son libellé recopié) : "
            + ", ".join(f"{m} (~{motifs[m]['montant_mensuel']:.2f} €/mois)" for m in rates)
        )

    # --- 4. Nature des récurrences ---------------------------------------------
    natures = {c.cle: c.nature for c in (pred.classements or [])}
    bons = 0
    for motif, groupe in trouves.items():
        attendu = motifs[motif]["nature"]
        obtenu = natures.get(_champ(groupe, "cle"), "absent")
        if obtenu == attendu:
            bons += 1
        else:
            ev.retours["nature"].append(
                f"« {_champ(groupe, 'libelle')} » (catégorie {_champ(groupe, 'categorie')}) "
                f"classé {obtenu}, attendu {attendu}."
            )
    ev.scores["nature"] = bons / len(trouves) if trouves else 0.0

    # --- 5. Confidentialité : aucune donnée personnelle ne doit ressortir ------
    sortie = _norm(" ".join(_champ(p, "libelle") for p in pred_tx))
    ev.fuite = [pii for pii in gold.pii if len(pii) >= 4 and _norm(pii) in sortie]
    return ev


COMPOSANTS = {"extracteur": "extraction", "categoriseur": "categorisation", "classeur": "nature"}


def metrique_gepa(gold, pred, trace=None, pred_name=None, pred_trace=None, *args, **kwargs):
    ev = evaluer_prediction(gold, pred)
    composant = None
    if pred_name:
        composant = next((v for k, v in COMPOSANTS.items() if k in pred_name), None)
    return dspy.Prediction(score=ev.score, feedback=ev.retour(composant))


def metrique_score(gold, pred, trace=None) -> float:
    return evaluer_prediction(gold, pred).score
