"""Lecture structurée des relevés bancaires, d'après la position des mots dans le PDF.

Certaines banques (la BRED, par exemple) dessinent le tableau des opérations de telle façon que
l'extraction de tableaux de pdfplumber renvoie toute une page en UNE ligne : toutes les dates dans
une cellule, tous les libellés dans une autre, tous les montants dans une troisième. Impossible
ensuite de savoir quel montant va avec quel libellé.

Ici, on repère l'en-tête du tableau (« Date … Débit … Crédit »), on en déduit la position des
colonnes, puis on reconstruit chaque opération ligne par ligne : date, libellé (sur une ou
plusieurs lignes), débit, crédit, date de valeur. On sépare aussi les comptes d'un même relevé
(compte courant, puis livrets) et on relève les soldes et totaux imprimés par la banque, qui
permettent de contrôler la lecture au centime près.

Si aucun en-tête n'est reconnu, rien n'est renvoyé : l'extraction se fait alors par l'IA.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta

MONTANT = re.compile(r"\d{1,3}(?:[ .  ]\d{3})*,\d{2}")
DATE_COURTE = re.compile(r"(\d{2})[./](\d{2})")
DATE_VALEUR = re.compile(r"\d{2}[./]\d{2}[./]\d{2,4}")
MOIS = {"janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7, "aout": 8,
        "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12}

SOLDE_DEBUT = re.compile(r"^(solde precedent|ancien solde|solde initial|solde reporte|report)\b")
SOLDE_FIN = re.compile(r"^(nouveau solde|solde final|solde en votre faveur|solde crediteur au|solde debiteur au)\b")
SOLDE_AU = re.compile(r"^solde au\b")
TOTAL = re.compile(r"^(total des mouvements|total des operations|totaux|total)\b")
TOTAL_IGNORE = re.compile(r"^(sous[- ]?total|total des frais|total frais)")
FIN_DE_TABLEAU = re.compile(r"(information prealable|frais constates|detail des frais|vos frais)")
# Soldes écrits hors tableau : « Ancien solde au 01/09/2026 : 2 658,68 EUR »
SOLDE_PARAGRAPHE = re.compile(
    r"(ancien|nouveau) solde au (\d{2})/(\d{2})/(\d{4})\s*:\s*(-?\s?\d{1,3}(?:[ .  ]\d{3})*,\d{2})")
REFERENCE_AU = re.compile(r"\bau (\d{2})/(\d{2})/(\d{4})")
# Titre d'un autre compte du même relevé (sinon, une ligne isolée n'ouvre pas de nouveau compte)
TITRE_COMPTE = re.compile(r"\b(livret|ldds?|lep|pel|cel|pea|epargne|compte|plan|codevi|csl|assurance)\b")
REFERENCE_LETTRES = re.compile(r"\b(\d{1,2}) (" + "|".join(MOIS) + r") (\d{4})\b")


def _simple(texte: str) -> str:
    texte = unicodedata.normalize("NFKD", texte.lower())
    return "".join(c for c in texte if not unicodedata.combining(c)).strip()


def montant_fr(texte: str) -> float:
    return float(re.sub(r"[ .  ]", "", texte).replace(",", "."))


def resoudre_date(jj_mm: str, reference: date | None) -> date | None:
    """« 05.05 » -> date complète : l'année la plus proche de la date du relevé, sans dépasser
    cette date de plus de 45 jours (une opération de décembre sur un relevé de janvier)."""
    m = DATE_COURTE.fullmatch(jj_mm)
    if not m or reference is None:
        return None
    jour, mois = int(m.group(1)), int(m.group(2))
    candidats = []
    for annee in (reference.year - 1, reference.year, reference.year + 1):
        try:
            candidats.append(date(annee, mois, jour))
        except ValueError:
            pass
    candidats = [c for c in candidats if c <= reference + timedelta(days=45)]
    return min(candidats, key=lambda c: abs((c - reference).days)) if candidats else None


@dataclass
class Operation:
    date: date | None
    libelle: str
    debit: float | None = None
    credit: float | None = None
    date_texte: str = ""
    valeur: str = ""

    @property
    def montant(self) -> float:
        return (self.credit or 0.0) - (self.debit or 0.0)


@dataclass
class Compte:
    nom: str
    operations: list[Operation] = field(default_factory=list)
    solde_debut: tuple[date | None, float] | None = None
    solde_fin: tuple[date | None, float] | None = None
    totaux: tuple[float, float] | None = None          # (débits, crédits) imprimés par la banque
    periodes: list[tuple[date, date]] = field(default_factory=list)

    @property
    def ferme(self) -> bool:
        return self.solde_fin is not None

    def controle(self) -> tuple[bool | None, str]:
        """Vérifie la lecture : totaux imprimés, sinon soldes début + crédits − débits = fin."""
        debits = round(sum(o.debit or 0 for o in self.operations), 2)
        credits = round(sum(o.credit or 0 for o in self.operations), 2)
        if self.totaux is not None:
            ok = abs(debits - self.totaux[0]) < 0.01 and abs(credits - self.totaux[1]) < 0.01
            return ok, (f"opérations lues {debits:.2f} € au débit et {credits:.2f} € au crédit, "
                        f"total imprimé {self.totaux[0]:.2f} € et {self.totaux[1]:.2f} €")
        if self.solde_debut is not None and self.solde_fin is not None:
            attendu = round(self.solde_debut[1] + credits - debits, 2)
            ok = abs(attendu - self.solde_fin[1]) < 0.01
            return ok, f"solde calculé {attendu:.2f} €, solde imprimé {self.solde_fin[1]:.2f} €"
        return None, "pas de total ni de solde imprimé pour contrôler"


@dataclass
class ReleveStructure:
    comptes: list[Compte] = field(default_factory=list)
    pages_rendues: dict[int, str] = field(default_factory=dict)   # index de page -> texte reconstruit

    @property
    def principal(self) -> Compte | None:
        return self.comptes[0] if self.comptes else None

    def periodes(self) -> list[tuple[date, date]]:
        """Périodes couvertes par le compte principal (pour compter les mois)."""
        p = self.principal
        if p is None:
            return []
        if p.periodes:
            return p.periodes
        if p.solde_debut and p.solde_fin and p.solde_debut[0] and p.solde_fin[0]:
            return [(p.solde_debut[0], p.solde_fin[0])]
        return []


# ---------------------------------------------------------------- géométrie

def _lignes(page) -> list[list[dict]]:
    mots = sorted(page.extract_words(keep_blank_chars=False), key=lambda w: (w["top"], w["x0"]))
    groupes: list[list[dict]] = []
    for w in mots:
        if groupes and abs(groupes[-1][0]["top"] - w["top"]) <= 3:
            groupes[-1].append(w)
        else:
            groupes.append([w])
    return [sorted(g, key=lambda w: w["x0"]) for g in groupes]


def _entete(ligne: list[dict]) -> dict | None:
    """Repère « Date … Débit … Crédit » (et Valeur, Libellé… s'ils existent)."""
    trouves: dict[str, dict] = {}
    for w in ligne:
        s = _simple(w["text"])
        if s.startswith("date") and "date" not in trouves:
            trouves["date"] = w
        elif s.startswith("debit"):
            trouves["debit"] = w
        elif s.startswith("credit"):
            trouves["credit"] = w
        elif s.startswith("valeur"):
            trouves["valeur"] = w
    if {"date", "debit", "credit"} <= trouves.keys() and trouves["debit"]["x0"] < trouves["credit"]["x0"]:
        return trouves
    return None


def _date_reference(texte: str) -> date | None:
    """Date du relevé, pour retrouver l'année des dates « jj.mm »."""
    trouves = list(REFERENCE_AU.finditer(texte))
    if trouves:
        jj, mm, aaaa = trouves[-1].groups()
        try:
            return date(int(aaaa), int(mm), int(jj))
        except ValueError:
            pass
    m = REFERENCE_LETTRES.search(_simple(texte))
    if m:
        try:
            return date(int(m.group(3)), MOIS[m.group(2)], int(m.group(1)))
        except ValueError:
            pass
    return None


def _cellule(texte: str) -> str:
    return texte.replace("|", "/").strip()


# ---------------------------------------------------------------- lecture

class LecteurReleve:
    """Lit un relevé page par page (appelé depuis l'ingestion, une page en mémoire à la fois)."""

    def __init__(self) -> None:
        self.releve = ReleveStructure()
        self.reference: date | None = None
        self.titre_en_attente: str | None = None

    # -- comptes
    def _compte(self) -> Compte:
        if not self.releve.comptes:
            self.releve.comptes.append(Compte("compte principal"))
        return self.releve.comptes[-1]

    def _solde_debut(self, quand: date | None, valeur: float, dans_tableau: bool) -> None:
        compte = self._compte()
        if compte.ferme and dans_tableau and self.titre_en_attente:
            # Après le « Nouveau solde » du compte courant : un livret, avec son titre juste avant
            compte = Compte(self.titre_en_attente)
            self.releve.comptes.append(compte)
        elif compte.ferme:
            compte.solde_fin = None                 # nouvelle période du même compte
        if compte.solde_debut is None:
            compte.solde_debut = (quand, valeur)
        if quand:
            compte.periodes.append((quand, quand))
        self.titre_en_attente = None

    def _solde_fin(self, quand: date | None, valeur: float) -> None:
        compte = self._compte()
        compte.solde_fin = (quand, valeur)
        if quand and compte.periodes and compte.periodes[-1][0] == compte.periodes[-1][1]:
            compte.periodes[-1] = (compte.periodes[-1][0], quand)

    # -- page
    def lire_page(self, page, index: int) -> str | None:
        """Lit une page. Renvoie son texte reconstruit, ou None si elle n'a pas de tableau reconnu."""
        lignes = _lignes(page)
        texte_page = "\n".join(" ".join(w["text"] for w in l) for l in lignes)
        self.reference = _date_reference(texte_page) or self.reference
        entete = None
        rendu: list[str] = []
        derniere_op: Operation | None = None
        bas_precedent = 0.0
        a_un_tableau = False

        for ligne in lignes:
            texte = " ".join(w["text"] for w in ligne)
            simple = _simple(texte)
            h = _entete(ligne)
            if h:
                entete, a_un_tableau, derniere_op = h, True, None
                avec_valeur = "valeur" in h
                rendu.append("| Date | Libellé | Débit | Crédit |" + (" Valeur |" if avec_valeur else ""))
                continue
            if m := SOLDE_PARAGRAPHE.search(simple):
                # Solde écrit hors tableau (relevés de test, certaines banques)
                quand = date(int(m.group(4)), int(m.group(3)), int(m.group(2)))
                valeur = montant_fr(m.group(5).replace(" ", "").replace("-", "")) * (-1 if "-" in m.group(5) else 1)
                if m.group(1) == "ancien":
                    self._solde_debut(quand, valeur, dans_tableau=False)
                else:
                    self._solde_fin(quand, valeur)
                rendu.append(texte)
                continue
            if entete is None:
                rendu.append(texte)
                continue
            if FIN_DE_TABLEAU.search(simple):
                entete, derniere_op = None, None
                rendu.append(texte)
                continue

            dx0 = entete["date"]["x0"]
            debut_debit = entete["debit"]["x0"] - 12
            cx0 = entete["credit"]["x0"]
            vx = entete.get("valeur")
            date_txt, valeur_txt = "", ""
            libelle, debit_mots, credit_mots = [], [], []
            for w in ligne:
                t = w["text"]
                if not date_txt and not libelle and DATE_COURTE.fullmatch(t) and abs(w["x0"] - dx0) < 14:
                    date_txt = t
                elif vx is not None and abs(w["x0"] - vx["x0"]) < 24 and DATE_VALEUR.fullmatch(t):
                    valeur_txt = t
                elif re.fullmatch(r"[\d.,  -]+", t) and w["x1"] > debut_debit:
                    (debit_mots if w["x1"] <= cx0 + 1 else credit_mots).append(t)
                else:
                    libelle.append(t)
            lib = " ".join(libelle).strip()
            m_debit = MONTANT.search(" ".join(debit_mots))
            m_credit = MONTANT.search(" ".join(credit_mots))
            debit = montant_fr(m_debit.group()) if m_debit else None
            credit = montant_fr(m_credit.group()) if m_credit else None
            lib_simple = _simple(lib)
            hauteur = max(w["bottom"] for w in ligne) - min(w["top"] for w in ligne)
            proche = derniere_op is not None and min(w["top"] for w in ligne) - bas_precedent < 2.2 * max(hauteur, 8)
            quand = resoudre_date(date_txt, self.reference) if date_txt else None

            def ligne_rendue() -> str:
                cellules = [date_txt, _cellule(lib), m_debit.group() if m_debit else "",
                            m_credit.group() if m_credit else ""]
                if "valeur" in entete:
                    cellules.append(valeur_txt)
                return "| " + " | ".join(cellules) + " |"

            if SOLDE_DEBUT.match(lib_simple) or (SOLDE_AU.match(lib_simple) and not self._compte().operations):
                self._solde_debut(quand, (credit or 0.0) - (debit or 0.0), dans_tableau=True)
                rendu.append(ligne_rendue())
                derniere_op = None
            elif SOLDE_FIN.match(lib_simple) or SOLDE_AU.match(lib_simple):
                self._solde_fin(quand, (credit or 0.0) - (debit or 0.0))
                rendu.append(ligne_rendue())
                derniere_op = None
            elif TOTAL_IGNORE.match(lib_simple):
                rendu.append(ligne_rendue())
                derniere_op = None
            elif TOTAL.match(lib_simple) and not date_txt:
                if debit is not None or credit is not None:
                    self._compte().totaux = (debit or 0.0, credit or 0.0)
                rendu.append(ligne_rendue())
                derniere_op = None
            elif date_txt and (debit is not None or credit is not None or lib):
                op = Operation(quand, lib, debit, credit, date_txt, valeur_txt)
                compte = self._compte()
                if compte.ferme and not self.titre_en_attente:
                    compte.solde_fin = None         # opérations après un solde : même compte, suite
                compte.operations.append(op)
                derniere_op = op
                rendu.append(ligne_rendue())
            elif proche and lib and debit is None and credit is None:
                derniere_op.libelle = f"{derniere_op.libelle} {lib}".strip()   # libellé sur 2 lignes
                if rendu:
                    rendu[-1] = re.sub(r"^\| ([^|]*) \| ([^|]*) \|",
                                       lambda m: f"| {m.group(1)} | {m.group(2)} {_cellule(lib)} |", rendu[-1], count=1)
            elif proche and derniere_op.debit is None and derniere_op.credit is None and (debit or credit):
                derniere_op.debit, derniere_op.credit = debit, credit
            elif lib and debit is None and credit is None and self._compte().ferme and TITRE_COMPTE.search(lib_simple):
                self.titre_en_attente = lib            # titre du compte suivant (LDD, livret…)
                rendu.append(f"| {_cellule(lib)} |  |  |  |")
            else:
                rendu.append(texte)
            if derniere_op is not None:
                bas_precedent = max(w["bottom"] for w in ligne)

        if not a_un_tableau:
            return None
        self.releve.pages_rendues[index] = "\n".join(rendu)
        return self.releve.pages_rendues[index]

    def resultat(self) -> ReleveStructure | None:
        principal = self.releve.principal
        if principal is None or not principal.operations:
            return None
        return self.releve
