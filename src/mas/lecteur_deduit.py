"""Lecture directe d'un relevé de mise en page inconnue : les colonnes se déduisent des opérations elles-mêmes.

Quand le relevé n'a pas d'en-tête « Date … Débit … Crédit » exploitable (voir releve.py), on cherche :

1. les lignes d'opérations : elles commencent par une date (« 05.09 », « 05/09/26 », « 05/09/2026 »,
   « 5 sept. 2026 »), toujours à la même position, et se terminent par un ou deux montants ;
2. les colonnes de montants : les bords droits des montants (alignés à droite) se regroupent en une,
   deux ou trois positions ;
3. plusieurs lectures possibles de ces colonnes (les hypothèses ci-dessous), essayées dans l'ordre.

Une lecture n'est retenue que si elle tombe juste au centime : soldes imprimés (solde de début +
crédits − débits = solde de fin), totaux imprimés, ou solde affiché après chaque opération. Une mauvaise
hypothèse ne passe donc jamais : si aucune ne tombe juste, le relevé part à l'IA, et la raison est donnée
(« raison »), pour l'utilisateur et pour `mas structure`.

Limites : un seul compte par relevé (un livret imprimé à la suite fait échouer le contrôle, donc l'IA prend
le relais) ; un relevé scanné n'a pas de positions fiables.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date

from .releve import MOIS, Compte, Operation, ReleveStructure, _cellule, _date_reference, _lignes, _simple, resoudre_date

DATE_COMPLETE = re.compile(r"(\d{2})[./-](\d{2})[./-](\d{4})")
DATE_AN_COURT = re.compile(r"(\d{2})[./-](\d{2})[./-](\d{2})")
DATE_COURTE = re.compile(r"\d{2}[./]\d{2}")
JOUR = re.compile(r"\d{1,2}")
JOUR_MOIS = re.compile(r"(\d{1,2})([^\W\d_]{3,}\.?)")      # « 21sept. » : jour et mois collés par le PDF
ANNEE = re.compile(r"\d{4}")
NUMERIQUE = re.compile(r"[−+-]?[\d.,  ]*\d[\d.,  ]*[−-]?")
SIGNE_SEUL = {"-", "+", "−"}
MONTANT_SIGNE = re.compile(r"([−+-])?\s?(\d{1,3}(?:[ .  ]\d{3})*,\d{2})\s?([−-])?")
DEVISES = {"€", "eur", "euro", "euros"}
ECART_COLONNES = 20       # points entre les bords droits de deux colonnes
TOLERANCE_COLONNE = 12    # un montant appartient à la colonne dont le bord droit est à moins de 12 points
ADJACENT = 6              # deux mots à moins de 6 points font partie du même montant (« 1 » « 234,56 »)


@dataclass
class Montant:
    valeur: float          # toujours positive
    signe: int | None      # -1, +1, ou None si aucun signe n'est imprimé
    x0: float
    x1: float

    @property
    def signee(self) -> float:
        return -self.valeur if self.signe == -1 else self.valeur


def _mois(texte: str) -> int | None:
    abrege = _simple(texte).rstrip(".")
    if len(abrege) < 3:
        return None
    candidats = {numero for nom, numero in MOIS.items() if nom.startswith(abrege)}
    return candidats.pop() if len(candidats) == 1 else None


def date_en_tete(ligne: list[dict], reference: date | None) -> tuple[date | None, int, str] | None:
    """Date au début de la ligne : (date, nombre de mots qu'elle occupe, texte), ou None si la ligne ne
    commence pas par une date. La date vaut None si elle n'a pas d'année et que celle du relevé est inconnue."""
    t = ligne[0]["text"]
    for motif, siecle in ((DATE_COMPLETE, 0), (DATE_AN_COURT, 2000)):
        if m := motif.fullmatch(t):
            try:
                return date(siecle + int(m.group(3)), int(m.group(2)), int(m.group(1))), 1, t
            except ValueError:
                return None
    if DATE_COURTE.fullmatch(t):
        return resoudre_date(t, reference), 1, t
    jour, mois, nb = None, None, 0
    if JOUR.fullmatch(t) and len(ligne) > 1 and (mois := _mois(ligne[1]["text"])):
        jour, nb = int(t), 2
    elif (m := JOUR_MOIS.fullmatch(t)) and (mois := _mois(m.group(2))):
        jour, nb = int(m.group(1)), 1
    if jour is None:
        return None
    annee_mot = len(ligne) > nb and ANNEE.fullmatch(ligne[nb]["text"])
    texte = " ".join(w["text"] for w in ligne[:nb + 1 if annee_mot else nb])
    try:
        if annee_mot:
            return date(int(ligne[nb]["text"]), mois, jour), nb + 1, texte
        return resoudre_date(f"{jour:02d}.{mois:02d}", reference), nb, texte
    except ValueError:
        return None


def _est_une_date(texte: str) -> bool:
    return bool(DATE_COMPLETE.fullmatch(texte) or DATE_AN_COURT.fullmatch(texte) or DATE_COURTE.fullmatch(texte))


def montants_finaux(ligne: list[dict]) -> list[Montant]:
    """Montants qui terminent la ligne, de gauche à droite (devise ignorée). La lecture s'arrête au premier
    mot qui n'est pas un montant : un montant cité dans le libellé (« 12,50 USD ») n'est pas pris."""
    groupes: list[list[dict]] = []
    separe = False
    for w in reversed(ligne):
        t = w["text"]
        if _simple(t) in DEVISES:
            separe = True               # « 481,10 € » : la devise suit un montant, et le sépare du précédent
            continue
        numerique = (NUMERIQUE.fullmatch(t) or t in SIGNE_SEUL) and not _est_une_date(t)
        if not numerique:
            break
        if groupes and not separe and groupes[-1][0]["x0"] - w["x1"] < ADJACENT:
            groupes[-1].insert(0, w)
        else:
            groupes.append([w])
        separe = False
    montants = []
    for g in reversed(groupes):
        m = MONTANT_SIGNE.fullmatch(" ".join(w["text"] for w in g))
        if not m:
            if montants:        # un mot numérique qui n'est pas un montant interrompt la fin de ligne
                montants = []
            continue
        signe = -1 if (m.group(1) in ("-", "−") or m.group(3)) else 1 if m.group(1) == "+" else None
        valeur = float(re.sub(r"[ .  ]", "", m.group(2)).replace(",", "."))
        montants.append(Montant(valeur, signe, g[0]["x0"], g[-1]["x1"]))
    return montants


def _colonnes(bords: list[float]) -> list[float]:
    """Bords droits des colonnes : regroupe les bords des montants séparés de moins de ECART_COLONNES."""
    groupes: list[list[float]] = []
    for b in sorted(bords):
        if groupes and b - groupes[-1][-1] < ECART_COLONNES:
            groupes[-1].append(b)
        else:
            groupes.append([b])
    return [max(g) for g in groupes]


def _colonne(m: Montant, colonnes: list[float]) -> int | None:
    proche = min(range(len(colonnes)), key=lambda k: abs(colonnes[k] - m.x1))
    return proche if abs(colonnes[proche] - m.x1) <= TOLERANCE_COLONNE else None


@dataclass
class Ligne:
    page: int
    mots: list[dict]
    date: date | None = None
    date_texte: str = ""
    libelle: str = ""
    valeur: str = ""
    montants: tuple[Montant, ...] = ()


# Hypothèses : rôle de chaque colonne, de gauche à droite.
#   debit / credit : montant sans signe dans sa colonne ; signe : montant signé (sans signe = crédit) ;
#   solde : solde affiché après chaque opération.
HYPOTHESES = {
    1: [("signe",)],
    2: [("debit", "credit"), ("credit", "debit"), ("signe", "solde")],
    3: [("debit", "credit", "solde"), ("credit", "debit", "solde")],
}
DESCRIPTIONS = {
    ("signe",): "une colonne de montants signés",
    ("debit", "credit"): "deux colonnes, débit puis crédit",
    ("credit", "debit"): "deux colonnes, crédit puis débit",
    ("signe", "solde"): "montants signés, solde après chaque opération",
    ("debit", "credit", "solde"): "débit, crédit, solde après chaque opération",
    ("credit", "debit", "solde"): "crédit, débit, solde après chaque opération",
}


class LecteurDeduit:
    def __init__(self) -> None:
        self.lignes: list[tuple[int, list[dict]]] = []
        self.raison = ""
        self.ocr = False

    def ajouter_page(self, page, index: int) -> None:
        self.lignes += [(index, l) for l in _lignes(page) if l]

    # ── repérage ─────────────────────────────────────────────────────────────
    def _reference(self) -> date | None:
        return _date_reference("\n".join(" ".join(w["text"] for w in l) for _, l in self.lignes))

    def _operations(self, reference: date | None) -> tuple[list[Ligne], float] | None:
        brutes = []
        for page, mots in self.lignes:
            d = date_en_tete(mots, reference)
            montants = montants_finaux(mots)
            if d is None or not montants:
                continue
            reste = mots[d[1]:]
            dates = [w for w in reste if _est_une_date(w["text"]) and w["x1"] <= montants[0].x0]
            brutes.append((page, mots, d, montants, reste, dates[-1] if dates else None))
        if not brutes:
            return None
        # Date de valeur : la dernière date avant les montants, si elle forme une colonne (une ligne sur deux
        # au moins). Sinon, une date citée dans le libellé (« CARTE 01/09 … ») le couperait.
        positions = Counter(round(dv["x0"]) for *_, dv in brutes if dv)
        x_valeur = None
        if positions:
            x, n = positions.most_common(1)[0]
            x_valeur = x if n >= len(brutes) / 2 else None
        candidates = []
        for page, mots, (quand, _, texte), montants, reste, dv in brutes:
            valeur = dv if dv is not None and x_valeur is not None and abs(dv["x0"] - x_valeur) <= 6 else None
            fin_libelle = valeur["x0"] if valeur else montants[0].x0
            libelle = " ".join(w["text"] for w in reste if w["x1"] <= fin_libelle and w is not valeur).strip()
            if "solde" in _simple(libelle).replace(" ", ""):
                continue                        # « 07.04 Solde précédent 1 000,00 » : un solde, pas une opération
            candidates.append(Ligne(page, mots, quand, texte, libelle, valeur["text"] if valeur else "", tuple(montants)))
        if not candidates:
            return None
        x_date = Counter(round(l.mots[0]["x0"]) for l in candidates).most_common(1)[0][0]
        return [l for l in candidates if abs(l.mots[0]["x0"] - x_date) <= 4], x_date

    # ── lecture ──────────────────────────────────────────────────────────────
    def resultat(self) -> ReleveStructure | None:
        if not self.lignes:
            self.raison = "relevé scanné (image) : pas de texte positionné" if self.ocr else "aucun texte dans le PDF"
            return None
        reference = self._reference()
        trouve = self._operations(reference)
        if trouve is None:
            self.raison = ("relevé scanné (image) : positions trop approximatives" if self.ocr
                           else "aucune ligne qui commence par une date et finit par un montant")
            return None
        operations, x_date = trouve
        if any(l.date is None for l in operations):
            self.raison = "dates sans année, et date du relevé introuvable pour la compléter"
            return None
        colonnes = _colonnes([m.x1 for l in operations for m in l.montants])
        hypotheses = HYPOTHESES.get(len(colonnes))
        if not hypotheses:
            self.raison = f"{len(colonnes)} colonnes de montants : mise en page non reconnue"
            return None
        raisons = []
        for roles in hypotheses:
            releve, raison = self._lire(operations, x_date, colonnes, roles)
            if releve is not None:
                releve.lecture = f"colonnes déduites ({DESCRIPTIONS[roles]})"
                return releve
            raisons.append(raison)
        self.raison = (next((r for r in raisons if r.startswith("aucun solde")), None)
                       or (raisons[0] if len(set(raisons)) == 1 else "aucune lecture des colonnes ne tombe juste au centime"))
        return None

    def _lire(self, operations: list[Ligne], x_date: float, colonnes: list[float],
              roles: tuple[str, ...]) -> tuple[ReleveStructure | None, str]:
        avec_solde = "solde" in roles

        def lire_montants(montants: tuple[Montant, ...]) -> tuple[float | None, float | None] | None:
            """(mouvement signé, solde affiché) d'une ligne selon les rôles, ou None si elle ne colle pas."""
            mouvement = solde = None
            for m in montants:
                k = _colonne(m, colonnes)
                if k is None:
                    return None
                role = roles[k]
                if role == "solde":
                    solde = m.signee
                elif mouvement is not None:
                    return None                 # deux mouvements sur la même ligne
                elif role == "signe":
                    mouvement = m.signee
                else:
                    if m.signe == -1:
                        return None             # un signe dans une colonne débit / crédit : autre mise en page
                    mouvement = -m.valeur if role == "debit" else m.valeur
            if mouvement is None or (avec_solde and solde is None):
                return None
            return mouvement, solde

        compte = Compte("compte principal")
        releve = ReleveStructure(comptes=[compte])
        rendus: dict[int, list[str]] = {}
        index_ops = {id(l.mots): l for l in operations}
        soldes_avant: list[tuple[date | None, float]] = []
        soldes_affiches: list[float] = []
        derniere: Operation | None = None
        bas, page_derniere = 0.0, -1
        for page, mots in self.lignes:
            rendu = rendus.setdefault(page, [])
            texte = " ".join(w["text"] for w in mots)
            simple = _simple(texte).replace(" ", "")
            ligne = index_ops.get(id(mots))
            if ligne is not None:
                lu = lire_montants(ligne.montants)
                if lu is None:
                    return None, f"montants hors des colonnes ({DESCRIPTIONS[roles]})"
                mouvement, solde = lu
                debit, credit = (-mouvement, None) if mouvement < 0 else (None, mouvement)
                derniere = Operation(ligne.date, ligne.libelle, debit, credit, ligne.date_texte, ligne.valeur)
                compte.operations.append(derniere)
                if solde is not None:
                    soldes_affiches.append(solde)
                rendu.append("| " + " | ".join([ligne.date_texte, _cellule(ligne.libelle),
                                                f"{debit:.2f}".replace(".", ",") if debit is not None else "",
                                                f"{credit:.2f}".replace(".", ",") if credit is not None else "",
                                                ligne.valeur]) + " |")
                bas, page_derniere = max(w["bottom"] for w in mots), page
                continue
            montants = montants_finaux(mots)
            if "solde" in simple and montants:
                m = montants[-1]
                k = _colonne(m, colonnes)
                role = roles[k] if k is not None else "solde"
                valeur = -m.valeur if (role == "debit" or m.signe == -1 or "debiteur" in simple) else m.valeur
                trouvee = DATE_COMPLETE.search(texte) or DATE_AN_COURT.search(texte)
                quand = date_en_tete([{"text": trouvee.group()}], None)[0] if trouvee else None
                if compte.operations:
                    compte.solde_fin = (quand, valeur)
                else:
                    soldes_avant.append((quand, valeur))
                derniere = None
                rendu.append(texte)
                continue
            hauteur = max(8.0, max(w["bottom"] - w["top"] for w in mots))
            if (derniere is not None and page == page_derniere and not montants
                    and not re.search(r"total|solde|report", simple) and mots[0]["x0"] > x_date + 20
                    and min(w["top"] for w in mots) - bas < 2.2 * hauteur):
                derniere.libelle = f"{derniere.libelle} {texte}".strip()      # libellé sur plusieurs lignes
                rendu[-1] = re.sub(r"^\| ([^|]*) \| ([^|]*) \|",
                                   lambda g: f"| {g.group(1)} | {g.group(2)} {_cellule(texte)} |", rendu[-1], count=1)
                bas = max(w["bottom"] for w in mots)
                continue
            if "total" in simple and len(montants) >= 2 and not avec_solde:
                lus = [(roles[k], m.valeur) for m in montants[-2:] if (k := _colonne(m, colonnes)) is not None]
                if {r for r, _ in lus} == {"debit", "credit"}:
                    compte.totaux = (dict(lus)["debit"], dict(lus)["credit"])
            derniere = None
            rendu.append(texte)

        if soldes_avant:
            compte.solde_debut = soldes_avant[0]
            if compte.solde_fin is None and len(soldes_avant) > 1:
                compte.solde_fin = soldes_avant[-1]          # encadré « ancien / nouveau solde » en haut du relevé
        if avec_solde:
            # Solde après chaque opération : chaque ligne se vérifie avec la précédente
            ops = compte.operations
            for k in range(1, len(ops)):
                if abs(soldes_affiches[k - 1] + ops[k].montant - soldes_affiches[k]) >= 0.005:
                    return None, "le solde affiché après chaque opération ne suit pas les montants"
            compte.solde_debut = compte.solde_debut or (ops[0].date, round(soldes_affiches[0] - ops[0].montant, 2))
            compte.solde_fin = (ops[-1].date, soldes_affiches[-1])
            compte.totaux = None
        elif compte.solde_debut and compte.solde_fin:
            compte.totaux = None                              # les soldes suffisent, et ne dépendent pas des pages
        if compte.solde_debut and compte.solde_fin and compte.solde_debut[0] and compte.solde_fin[0]:
            compte.periodes = [(compte.solde_debut[0], compte.solde_fin[0])]
        ok, detail = compte.controle()
        if ok is None:
            return None, "aucun solde ni total imprimé pour vérifier la lecture"
        if not ok:
            return None, f"contrôle faux en lisant {DESCRIPTIONS[roles]} ({detail})"
        releve.pages_rendues = {i: "\n".join(["| Date | Libellé | Débit | Crédit | Valeur |", *r]) for i, r in rendus.items()}
        return releve, ""
