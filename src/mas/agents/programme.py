"""Programme DSPy multi-agents optimisé par GEPA.

    pages anonymisées
        │
        ▼
    [Extracteur] ⇄ [Contrôleur déterministe]   boucle de correction (feedback)
        │
        ▼
    [Catégoriseur]  (par lots de libellés uniques)
        │
        ▼
    [Détecteur de récurrences]  (Python, déterministe)
        │
        ▼
    [Classeur]  obligatoire / abonnement_optionnel / courant_variable

Les trois prédicteurs (extracteur, categoriseur, classeur) sont ceux que GEPA optimise.
"""

from __future__ import annotations

import logging
import re
import time
from collections import Counter
from datetime import date

import dspy
from dspy.utils.exceptions import LMError

from ..suivi import duree_lisible

log = logging.getLogger("mas")
# Avancement étape par étape : affiché par `mas analyser`, muet pendant l'optimisation GEPA
progression = logging.getLogger("mas.progression")

from ..config import ConfigLLM, ConfigRecurrence
from ..modeles import Classement, GroupeRecurrent, Transaction, TransactionCategorisee
from ..recurrence import detecter_recurrences
from .signatures import CategoriserLibelles, ClasserRecurrences, ExtraireTransactions

MONTANT = re.compile(r"(?<![\d,.])-?\d{1,3}(?:[  .]\d{3})*,\d{2}(?![\d])")
# Mots entiers uniquement : "TOTALENERGIES" est une vraie opération, pas un total.
LIGNE_IGNOREE = re.compile(
    r"\b(?:SOLDE|TOTAL|TOTAUX|REPORT|ANCIEN|NOUVEAU|CUMUL)\b", re.IGNORECASE
)
PERIODE = re.compile(r"du\s+(\d{2}/\d{2}/\d{4})\s+au\s+(\d{2}/\d{2}/\d{4})", re.IGNORECASE)

NATURE_PAR_DEFAUT = {
    "logement": "obligatoire", "energie": "obligatoire", "telecom": "obligatoire",
    "assurance": "obligatoire", "impots_taxes": "obligatoire", "credit": "obligatoire",
    "sante": "obligatoire", "frais_bancaires": "obligatoire", "transport": "obligatoire",
    "abonnement": "abonnement_optionnel", "loisirs": "abonnement_optionnel",
}


def configurer_lm(config: ConfigLLM) -> dspy.LM:
    lm = dspy.LM(config.modele, temperature=config.temperature, max_tokens=config.max_tokens)
    dspy.configure(lm=lm)
    return lm


def montant_fr(texte: str) -> float:
    return float(re.sub(r"[  .]", "", texte).replace(",", "."))


def montants_de_la_page(page: str) -> Counter:
    montants = Counter()
    for ligne in page.splitlines():
        if LIGNE_IGNOREE.search(ligne):
            continue
        for m in MONTANT.finditer(ligne):
            montants[round(abs(montant_fr(m.group())), 2)] += 1
    return montants


def cle_libelle(libelle: str) -> str:
    """Pour retrouver un libellé que l'IA a recopié avec d'autres espaces ou une autre casse."""
    return " ".join(libelle.split()).casefold()


def trouver_periode(pages: list[str]) -> str:
    for p in pages:
        if m := PERIODE.search(p):
            return f"du {m.group(1)} au {m.group(2)}"
    return "inconnue"


def controler_extraction(page: str, transactions: list[Transaction]) -> str:
    """Contrôleur : compare les montants extraits à ceux présents sur la page.

    Renvoie un retour en langage naturel (vide si tout est cohérent), réinjecté
    dans l'extracteur à la tentative suivante.
    """
    attendus = montants_de_la_page(page)
    extraits = Counter(round(abs(t.montant), 2) for t in transactions)
    problemes = []
    if manquants := attendus - extraits:
        problemes.append(
            "Montants présents sur la page mais absents de ton extraction : "
            + ", ".join(f"{m:.2f}" for m in sorted(manquants.elements()))
        )
    if inventes := extraits - attendus:
        problemes.append(
            "Montants extraits qui n'existent pas sur la page (ou sont des soldes) : "
            + ", ".join(f"{m:.2f}" for m in sorted(inventes.elements()))
        )
    dates_invalides = []
    for t in transactions:
        try:
            date.fromisoformat(t.date)
        except ValueError:
            dates_invalides.append(t.date)
    if dates_invalides:
        problemes.append("Dates invalides (format attendu AAAA-MM-JJ) : " + ", ".join(dates_invalides))
    return " ".join(problemes)


class AnalyseReleve(dspy.Module):
    def __init__(
        self,
        config_recurrence: ConfigRecurrence | None = None,
        tentatives_max: int = 2,
        taille_lot: int = 40,
    ):
        super().__init__()
        self.extracteur = dspy.ChainOfThought(ExtraireTransactions)
        self.categoriseur = dspy.Predict(CategoriserLibelles)
        self.classeur = dspy.ChainOfThought(ClasserRecurrences)
        self.config_recurrence = config_recurrence or ConfigRecurrence()
        self.tentatives_max = tentatives_max
        self.taille_lot = taille_lot

    # --- agent 1 : extraction avec boucle de correction ----------------------
    def extraire(self, pages: list[str]) -> tuple[list[Transaction], list[str]]:
        periode_globale = trouver_periode(pages)
        toutes, retours_finaux = [], []
        debut, nb_corrections, n = time.perf_counter(), 0, len(pages)
        for numero, page in enumerate(pages, 1):
            if not MONTANT.search(page):
                progression.info("  Page %d/%d : aucun montant, ignorée", numero, n)
                continue
            progression.info("  Page %d/%d : extraction des opérations…", numero, n)
            periode = trouver_periode([page])
            if periode == "inconnue":
                periode = periode_globale
            retour, meilleures, meilleur_nb_pb = "", [], None
            for tentative in range(self.tentatives_max + 1):
                try:
                    res = self.extracteur(page=page, periode=periode, retour_controleur=retour)
                    transactions = list(res.transactions or [])
                except LMError:
                    # Clé invalide, crédit épuisé, modèle inconnu, réseau… : réessayer ne servirait
                    # à rien et produirait un rapport vide, on arrête l'analyse avec l'erreur.
                    raise
                except Exception as e:  # sortie mal formée : on la signale et on réessaie
                    transactions, retour = [], f"Ta réponse précédente était invalide : {e}"
                    motif = f"réponse mal formée ({type(e).__name__})"
                else:
                    retour = controler_extraction(page, transactions)
                    nb_pb = len(retour)
                    if meilleur_nb_pb is None or nb_pb < meilleur_nb_pb:
                        meilleures, meilleur_nb_pb = transactions, nb_pb
                    if not retour:
                        break
                    motif = "montants différents de ceux de la page"
                if tentative < self.tentatives_max:
                    nb_corrections += 1
                    progression.info("  Page %d/%d : %s, correction %d/%d…",
                                     numero, n, motif, tentative + 1, self.tentatives_max)
            toutes.extend(meilleures)
            if retour:
                retours_finaux.append(retour)
                progression.info("  Page %d/%d : écarts non résolus, signalés dans le rapport", numero, n)
        corrections = f", {nb_corrections} correction(s)" if nb_corrections else ""
        progression.info("  → %d opération(s) extraite(s) en %s%s",
                         len(toutes), duree_lisible(time.perf_counter() - debut), corrections)
        return toutes, retours_finaux

    # --- agent 2 : catégorisation par lots ----------------------------------
    def categoriser(self, transactions: list[Transaction]) -> list[TransactionCategorisee]:
        libelles = list(dict.fromkeys(t.libelle for t in transactions))
        categories: dict[str, str] = {}
        nb_lots = -(-len(libelles) // self.taille_lot)
        progression.info("[2/5] Catégorisation : %d libellé(s) distinct(s) en %d lot(s)", len(libelles), nb_lots)
        for i in range(0, len(libelles), self.taille_lot):
            lot = libelles[i:i + self.taille_lot]
            progression.info("  Lot %d/%d…", i // self.taille_lot + 1, nb_lots)
            try:
                for item in self.categoriseur(libelles=lot).categories:
                    categories[cle_libelle(item.libelle)] = item.categorie
            except Exception as e:  # catégorie "autre" par défaut ; la métrique le signalera
                log.warning("Catégorisation d'un lot impossible (%s) : catégorie « autre »", e)
        oublies = sum(1 for l in libelles if cle_libelle(l) not in categories)
        if oublies:
            progression.info("  %d libellé(s) sans réponse de l'IA : classé(s) dans « autre »", oublies)
        return [
            TransactionCategorisee(**t.model_dump(), categorie=categories.get(cle_libelle(t.libelle), "autre"))
            for t in transactions
        ]

    # --- agent 4 : classement des récurrences --------------------------------
    def classer(self, groupes: list[GroupeRecurrent]) -> list[Classement]:
        if not groupes:
            return []
        try:
            classements = {c.cle: c for c in self.classeur(groupes=groupes).classements}
        except Exception as e:
            log.warning("Classement des récurrences impossible (%s) : règles par défaut", e)
            classements = {}
        return [
            classements.get(g.cle)
            or Classement(
                cle=g.cle,
                nature=NATURE_PAR_DEFAUT.get(g.categorie, "courant_variable"),
                justification="Classement par défaut d'après la catégorie.",
            )
            for g in groupes
        ]

    def forward(self, pages: list[str]) -> dspy.Prediction:
        if dspy.settings.lm is None:
            raise RuntimeError("Aucun modèle d'IA configuré pour l'analyse (dspy.settings.lm est vide).")
        progression.info("[1/5] Extraction des opérations : %d page(s)", len(pages))
        transactions, alertes = self.extraire(pages)
        return self.analyser_transactions(transactions, alertes)

    def analyser_transactions(self, transactions: list[Transaction], alertes=()) -> dspy.Prediction:
        """Étapes 2 à 4 sur des opérations déjà extraites (par l'IA ou lues dans le tableau)."""
        alertes = list(alertes)
        categorisees = self.categoriser(transactions)
        # agent 3 : déterministe
        groupes = detecter_recurrences(categorisees, self.config_recurrence)
        progression.info("[3/5] Dépenses récurrentes (calcul local, sans IA) : %d trouvée(s)", len(groupes))
        if groupes:
            progression.info("[4/5] Classement obligatoire / optionnel de %d dépense(s)…", len(groupes))
        else:
            progression.info("[4/5] Classement : aucune dépense récurrente à classer")
        classements = self.classer(groupes)
        return dspy.Prediction(
            transactions=categorisees,
            recurrents=groupes,
            classements=classements,
            alertes_extraction=alertes,
        )
