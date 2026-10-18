"""Orchestrateur : enchaîne les agents locaux (anonymisation, vérification) et
les agents LLM (analyse, synthèse). Aucun texte ne part vers le LLM tant que
le vérificateur n'a pas validé toutes les pages."""

from __future__ import annotations

import logging
import re
import unicodedata
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import dspy

from .agents import AnalyseReleve, Synthetiseur, configurer_lm
from .anonymisation import Anonymiseur, Coffre
from .anonymisation.reconnaisseurs import MOTS_NON_NOMS, valeur_plausible
from .config import Config
from .ingestion import Document, iter_documents
from .modeles import Transaction
from .verification import Fuite, Verificateur

log = logging.getLogger("mas")
progression = logging.getLogger("mas.progression")


class FuiteBloquante(RuntimeError):
    def __init__(self, fuites: list[Fuite]):
        self.fuites = fuites
        super().__init__(
            "Envoi bloqué : des données personnelles restent visibles après "
            "anonymisation :\n" + "\n".join(f"  - {f}" for f in fuites)
        )


@dataclass
class OperationAnonyme:
    """Opération lue directement dans le tableau du relevé, libellé déjà anonymisé."""
    date: str                       # AAAA-MM-JJ
    libelle: str
    montant: float                  # négatif : débit
    compte: int                     # 0 : compte principal ; 1, 2… : livrets du même relevé
    a_ton_nom: bool = False         # virement dont le bénéficiaire porte un nom déclaré (identite)
    compte_declare: bool = False    # correspond à un compte listé dans analyse.comptes_personnels


@dataclass
class DocumentAnonymise:
    nom: str
    pages: list[str]
    originales: list[str] = field(repr=False, default_factory=list)
    nb_remplacements: int = 0
    operations: list[OperationAnonyme] | None = None    # None : pas de tableau reconnu (extraction IA)
    periodes: list[tuple[date, date]] = field(default_factory=list)
    controles: list[tuple[bool | None, str]] = field(default_factory=list)   # un par compte


def _simple(texte: str) -> str:
    texte = unicodedata.normalize("NFKD", texte.lower())
    return "".join(c for c in texte if not unicodedata.combining(c))


def _mots(texte: str) -> set[str]:
    return {m for m in re.findall(r"[a-z]+", _simple(texte)) if len(m) > 1 and m not in {"mr", "mme", "mlle"}}


class Orchestrateur:
    def __init__(self, config: Config, coffre: Coffre | None = None):
        self.config = config
        self.coffre = coffre if coffre is not None else Coffre(config.coffre.chemin)
        termes = config.identite.termes()
        self.anonymiseur = Anonymiseur(config.anonymisation, self.coffre, termes)
        self.verificateur = Verificateur(config.verification, termes)
        self.liste_blanche = {m.upper() for m in config.anonymisation.liste_blanche}
        self.mots_communs = self.liste_blanche | {m.upper() for m in MOTS_NON_NOMS}
        self.noms_declares = [m for m in (_mots(n) for n in config.identite.noms) if len(m) >= 2]
        self.comptes_declares = [re.sub(r"\s", "", _simple(c)) for c in config.analyse.comptes_personnels if c.strip()]

    # --- étapes locales ------------------------------------------------------
    def _valeurs_coffre(self) -> list[str]:
        return [v for v in self.coffre.valeurs_reelles()
                if v.upper() not in self.liste_blanche and valeur_plausible(v, self.mots_communs)]

    def _a_ton_nom(self, libelle_brut: str) -> bool:
        """Virement vers (ou depuis) quelqu'un qui porte un nom déclaré dans identite.noms.
        Repéré en local sur le libellé en clair, avant anonymisation. C'est une déduction :
        un homonyme ou un compte joint donnerait le même résultat."""
        if "vir" not in _simple(libelle_brut):
            return False
        mots = _mots(libelle_brut)
        return any(nom <= mots for nom in self.noms_declares)

    def _compte_declare(self, libelle_brut: str) -> bool:
        compact = re.sub(r"\s", "", _simple(libelle_brut))
        return any(c in compact for c in self.comptes_declares)

    def anonymiser(self, documents: list[Document]) -> list[DocumentAnonymise]:
        resultats = []
        for doc in documents:
            originales = [p.texte for p in doc.pages]
            res = [self.anonymiseur.anonymiser(t) for t in originales]
            resultats.append(
                DocumentAnonymise(doc.nom, [r.texte for r in res], originales, sum(r.nb for r in res))
            )

        # Boucle anonymisation -> vérification. La vérification est faite après
        # avoir traité TOUS les documents : une valeur détectée dans le fichier 3
        # doit aussi être masquée si elle apparaît en clair dans le fichier 1.
        supplementaires: dict[str, str] = {}
        for iteration in range(self.config.verification.iterations_max + 1):
            fuites = []
            valeurs = self._valeurs_coffre()
            for d in resultats:
                for i, texte in enumerate(d.pages):
                    fuites_page = self.verificateur.verifier(texte, valeurs)
                    if fuites_page:
                        fuites += fuites_page
                        for f in fuites_page:
                            supplementaires[f.valeur] = (
                                f.entite if f.entite != "DONNEE_PERSO" else "PERSON"
                            )
                        d.pages[i] = self.anonymiseur.anonymiser(
                            d.originales[i], list(supplementaires.items())
                        ).texte
            if not fuites:
                break
            log.info("Itération %d : %d fuite(s) corrigée(s)", iteration + 1, len(fuites))
        else:
            restantes = [
                f for d in resultats for t in d.pages
                for f in self.verificateur.verifier(t, self._valeurs_coffre())
            ]
            if restantes:
                raise FuiteBloquante(restantes)

        for doc, resultat in zip(documents, resultats):
            if doc.structure is not None:
                self._anonymiser_operations(doc, resultat, supplementaires)

        self.coffre.sauvegarder()
        return resultats

    def _anonymiser_operations(self, doc: Document, resultat: DocumentAnonymise,
                               supplementaires: dict[str, str]) -> None:
        """Opérations lues dans le tableau : libellés anonymisés un par un, puis vérifiés."""
        termes = list(supplementaires.items())
        operations = []
        for k, compte in enumerate(doc.structure.comptes):
            for o in compte.operations:
                if o.date is None:
                    continue
                libelle = self.anonymiseur.anonymiser(o.libelle, termes).texte
                fuites = self.verificateur.verifier(libelle, self._valeurs_coffre())
                if fuites:
                    extra = termes + [(f.valeur, f.entite if f.entite != "DONNEE_PERSO" else "PERSON") for f in fuites]
                    libelle = self.anonymiseur.anonymiser(o.libelle, extra).texte
                    restantes = self.verificateur.verifier(libelle, self._valeurs_coffre())
                    if restantes:
                        raise FuiteBloquante(restantes)
                operations.append(OperationAnonyme(
                    o.date.isoformat(), libelle, round(o.montant, 2), k,
                    a_ton_nom=self._a_ton_nom(o.libelle), compte_declare=self._compte_declare(o.libelle),
                ))
        resultat.operations = operations
        resultat.periodes = doc.structure.periodes()
        resultat.controles = [c.controle() for c in doc.structure.comptes]

    def charger_documents(self, entree: str | Path) -> list[DocumentAnonymise]:
        return self.anonymiser(list(iter_documents(entree)))

    # --- tri des opérations lues dans les tableaux ---------------------------
    def separer_transferts(self, documents: list[DocumentAnonymise]) -> tuple[list[Transaction], list[dict], list[str]]:
        """Compte principal seulement. Met à part l'argent qui ne fait que changer de compte :
        virements vers/depuis les livrets du même relevé (même montant, sens inverse, à 4 jours
        près), vers des comptes déclarés, et vers un bénéficiaire à ton nom (si configuré)."""
        principales = [o for d in documents for o in d.operations or [] if o.compte == 0]
        livrets = [o for d in documents for o in d.operations or [] if o.compte > 0]
        a_ton_nom_transfert = self.config.analyse.virements_a_ton_nom == "transfert"
        transactions, transferts = [], []
        for o in principales:
            type_ = None
            if "vir" in o.libelle.lower():
                pendant = next((e for e in livrets if abs(e.montant + o.montant) < 0.01
                                and abs((date.fromisoformat(e.date) - date.fromisoformat(o.date)).days) <= 4), None)
                if pendant is not None:
                    livrets.remove(pendant)
                    type_ = "epargne"
            if type_ is None and o.compte_declare:
                type_ = "tes_comptes"
            if type_ is None and o.a_ton_nom and a_ton_nom_transfert:
                type_ = "a_ton_nom"
            if type_:
                transferts.append({"type": type_, "date": o.date, "libelle": o.libelle, "montant": o.montant})
            else:
                transactions.append(Transaction(date=o.date, libelle=o.libelle, montant=o.montant))
        alertes = []
        for i, d in enumerate(documents, 1):
            for k, (ok, detail) in enumerate(d.controles):
                if ok is False:
                    nom = "compte principal" if k == 0 else f"autre compte n°{k}"
                    alertes.append(f"Relevé {i}, {nom} : {detail}.")
        return transactions, transferts, alertes

    @staticmethod
    def periode_couverte(documents: list[DocumentAnonymise]) -> tuple[float | None, str | None]:
        """Nombre de mois d'après les dates des relevés (solde précédent -> nouveau solde),
        arrondi au demi-mois ; plus fiable que les dates d'opérations."""
        periodes = [p for d in documents for p in d.periodes if p[0] and p[1] and p[1] > p[0]]
        if not periodes:
            return None, None
        jours = sum((fin - debut).days for debut, fin in periodes)
        mois = max(0.5, round(jours / 30.44 * 2) / 2)
        debut = min(p[0] for p in periodes)
        fin = max(p[1] for p in periodes)
        return mois, f"{debut:%Y-%m} → {fin:%Y-%m}"

    @staticmethod
    def couverture_mois(documents: list[DocumentAnonymise]) -> dict[str, float] | None:
        """Pour chaque mois de la période : part des jours couverts par les relevés (1.0 = complet).
        Un relevé du 5 au 5 couvre presque tout son premier mois et quelques jours du suivant."""
        jours = set()
        for d in documents:
            for debut, fin in d.periodes:
                if debut and fin and fin >= debut:
                    jours.update(debut + timedelta(days=k) for k in range((fin - debut).days + 1))
        if not jours:
            return None
        couverture: dict[str, float] = {}
        jour = min(jours).replace(day=1)
        while jour <= max(jours):
            cle = f"{jour:%Y-%m}"
            dans_le_mois = monthrange(jour.year, jour.month)[1]
            couverts = sum(1 for k in range(dans_le_mois) if jour + timedelta(days=k) in jours)
            couverture[cle] = round(couverts / dans_le_mois, 2)
            jour = (jour + timedelta(days=dans_le_mois)).replace(day=1)
        return couverture

    # --- étapes LLM ----------------------------------------------------------
    def programme(self) -> AnalyseReleve:
        programme = AnalyseReleve(self.config.recurrence)
        chemin = Path(self.config.optimisation.programme_optimise)
        if chemin.exists():
            programme.load(str(chemin))
            log.info("Programme optimisé chargé : %s", chemin)
        return programme

    def analyser(self, documents: list[DocumentAnonymise]) -> dspy.Prediction:
        # LM passé explicitement par un contexte : un dspy.configure() fait à l'intérieur d'un
        # autre contexte (ex. dspy.track_usage du CLI) n'y serait pas visible (« No LM is loaded »).
        self.lm = configurer_lm(self.config.llm)
        lus = [d for d in documents if d.operations is not None]
        a_extraire = [d for d in documents if d.operations is None]
        transactions, transferts, alertes = [], [], []
        with dspy.context(lm=self.lm):
            programme = self.programme()
            if lus:
                t, transferts, alertes = self.separer_transferts(lus)
                transactions += t
                controles = [ok for d in lus for ok, _ in d.controles[:1]]
                progression.info("[1/5] Lecture directe des tableaux (sans IA) : %d opération(s) sur le compte "
                                 "principal, %d mouvement(s) entre tes comptes mis à part", len(t), len(transferts))
                progression.info("  Totaux imprimés par la banque : %d/%d relevé(s) concordant(s)%s",
                                 sum(1 for ok in controles if ok), len(controles),
                                 "" if all(ok is not False for ok in controles) else " ⚠ voir le rapport")
            if a_extraire:
                pages = [p for d in a_extraire for p in d.pages]
                progression.info("[1/5] Extraction des opérations par l'IA : %d page(s)", len(pages))
                t, retours = programme.extraire(pages)
                transactions += t
                alertes += retours
            analyse = programme.analyser_transactions(transactions, alertes)
            progression.info("[5/5] Rédaction de la synthèse…")
            nb_mois, periode = self.periode_couverte(lus) if lus and not a_extraire else (None, None)
            couverture = self.couverture_mois(lus) if lus and not a_extraire else None
            synthese = Synthetiseur()(
                transactions=analyse.transactions,
                recurrents=analyse.recurrents,
                classements=analyse.classements,
                transferts=transferts,
                nb_mois=nb_mois,
                periode=periode,
                proches_a_part=self.config.analyse.virements_a_des_proches == "a_part",
                couverture=couverture,
            )
        return dspy.Prediction(
            analyse=analyse,
            transferts=transferts,
            rapport_anonyme=synthese.rapport,
            # Dé-pseudonymisation 100 % locale : les vrais noms ne sont remis qu'ici
            rapport=self.coffre.depseudonymiser(synthese.rapport),
            # Pour la page HTML : chiffres calculés en Python + commentaire (avec pseudonymes)
            budget=synthese.budget,
            commentaire=synthese.commentaire,
        )
