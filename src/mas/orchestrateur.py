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
from .recurrence import cle_beneficiaire
from .sans_ia import AnalyseSansIA, SyntheseSansIA
from .verification import Fuite, Verificateur

log = logging.getLogger("mas")
progression = logging.getLogger("mas.progression")

# Délai entre le débit dans une banque et le crédit dans l'autre : un virement du jeudi peut
# n'arriver que le mardi (week-end, jour férié)
ECART_ENTRE_BANQUES = 5
LOYER = re.compile(r"\bloyer")
PRET_DEBLOQUE = re.compile(r"(?i)(d[ée]blocage|d[ée]caissement).{0,12}(pr[eê]t|cr[ée]dit|fonds)")
PRELEVEMENT = re.compile(r"(?i)^\s*(prlv|pr[ée]l[èe]vement|prelev)|echpret|[ée]ch[ée]ance pr[eê]t")


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
    nom_partiel: bool = False       # contient un mot de ton nom, même seul ou collé (« VIRSEPAMR DUPONT »)


@dataclass
class DocumentAnonymise:
    nom: str
    pages: list[str]
    originales: list[str] = field(repr=False, default_factory=list)
    nb_remplacements: int = 0
    operations: list[OperationAnonyme] | None = None    # None : pas de tableau reconnu (extraction IA)
    periodes: list[tuple[date, date]] = field(default_factory=list)
    controles: list[tuple[bool | None, str]] = field(default_factory=list)   # un par compte
    lecture: str = ""          # comment le tableau a été lu (vide : par l'IA)
    raison: str = ""           # pourquoi il n'a pas été reconnu


def lectures_markdown(lectures: list[dict], sans_ia: bool = False) -> str:
    if not lectures:
        return ""
    lignes = ["", "## Comment tes relevés ont été lus", "",
              "| Relevé | Pages | Lecture | Contrôle |", "|---|---|---|---|"]
    for l in lectures:
        nom = f"{l['releve']}" + (f" ({l['periode']})" if l["periode"] else "")
        lignes.append(f"| {nom} | {l['pages']} | {l['lecture']} | {l['controle']} |")
    if any(not l["directe"] for l in lectures):
        constat = "Un relevé non reconnu n'est pas compté sans l'IA." if sans_ia else \
                  "Un relevé lu par l'IA n'est pas vérifiable au centime."
        lignes += ["", f"_{constat} Pour qu'il soit lu directement : "
                       "`mas structure`, puis « Ta banque n'est pas reconnue ? » dans le README._"]
    return "\n".join(lignes) + "\n"


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
        un homonyme ou un compte joint donnerait le même résultat. Un loyer qui porte ton nom en
        référence (« residence … loyer JEAN DUPONT ») paie quelqu'un d'autre : ce n'en est pas un."""
        if "vir" not in _simple(libelle_brut) or LOYER.search(_simple(libelle_brut)):
            return False
        mots = _mots(libelle_brut)
        return any(nom <= mots for nom in self.noms_declares)

    def _nom_partiel(self, libelle_brut: str) -> bool:
        """Un mot de ton nom (5 lettres ou plus) dans le libellé en clair, même collé aux autres :
        chaque banque l'écrit à sa façon (nom seul, « MR NOM PRENOM », sans espaces). Sert seulement
        à ne pas prendre deux formes de ton nom pour deux personnes différentes."""
        compact = re.sub(r"[^a-z]", "", _simple(libelle_brut))
        return any(mot in compact for nom in self.noms_declares for mot in nom if len(mot) >= 5)

    def _compte_declare(self, libelle_brut: str) -> bool:
        compact = re.sub(r"\s", "", _simple(libelle_brut))
        return any(c in compact for c in self.comptes_declares)

    def anonymiser(self, documents: list[Document]) -> list[DocumentAnonymise]:
        resultats = []
        for doc in documents:
            originales = [p.texte for p in doc.pages]
            res = [self.anonymiseur.anonymiser(t) for t in originales]
            resultats.append(
                DocumentAnonymise(doc.nom, [r.texte for r in res], originales, sum(r.nb for r in res), raison=doc.raison)
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
                    nom_partiel=self._nom_partiel(o.libelle),
                ))
        resultat.operations = operations
        resultat.periodes = doc.structure.periodes()
        resultat.controles = [c.controle() for c in doc.structure.comptes]
        resultat.lecture = doc.structure.lecture

    @staticmethod
    def lectures(documents: list[DocumentAnonymise], sans_ia: bool = False) -> list[dict]:
        """Comment chaque relevé a été lu, pour l'utilisateur (avant l'envoi) et pour le rapport. Les relevés
        sont numérotés dans l'ordre, sans leur nom de fichier (le rapport anonyme peut être partagé)."""
        lignes = []
        for i, d in enumerate(documents, 1):
            periodes = [p for p in d.periodes if p[0] and p[1]]
            periode = (f"du {min(a for a, _ in periodes):%d/%m/%Y} au {max(b for _, b in periodes):%d/%m/%Y}"
                       if periodes else "")
            if d.operations is None:
                raison = f"mise en page non reconnue ({d.raison or 'raison inconnue'})"
                lignes.append({"releve": i, "pages": len(d.pages), "periode": periode, "directe": False,
                               "lecture": f"écarté : {raison}" if sans_ia else f"par l'IA : {raison}",
                               "controle": "pas compté dans ce rapport" if sans_ia else "non vérifiable au centime",
                               "ok": None})
                continue
            ok, detail = d.controles[0] if d.controles else (None, "")
            controle = ("juste au centime" if ok else f"écart : {detail}" if ok is False
                        else "impossible : ni total ni solde imprimé")
            lignes.append({"releve": i, "pages": len(d.pages), "periode": periode, "directe": True,
                           "lecture": f"directe : {d.lecture}", "controle": controle, "ok": ok})
        return lignes

    def charger_documents(self, entree: str | Path) -> list[DocumentAnonymise]:
        return self.anonymiser(list(iter_documents(entree)))

    # --- tri des opérations lues dans les tableaux ---------------------------
    def separer_transferts(self, documents: list[DocumentAnonymise]) -> tuple[list[Transaction], list[dict], list[str]]:
        """Compte principal seulement. Met à part l'argent qui ne fait que changer de compte :
        virements vers/depuis les livrets du même relevé (même montant, sens inverse, à 4 jours
        près), entre deux comptes courants relevés à part (voir `_entre_tes_comptes`), vers des
        comptes déclarés, et vers un bénéficiaire à ton nom (si configuré)."""
        principales = [(i, o) for i, d in enumerate(documents) for o in d.operations or [] if o.compte == 0]
        # Un livret ne reçoit que de son compte courant : jamais apparié avec le relevé d'une autre banque
        livrets = {i: [o for o in d.operations or [] if o.compte > 0] for i, d in enumerate(documents)}
        a_ton_nom_transfert = self.config.analyse.virements_a_ton_nom == "transfert"
        types: dict[int, str] = {}          # rang dans `principales` -> type de transfert
        for k, (i, o) in enumerate(principales):
            if "vir" in o.libelle.lower():
                pendant = next((e for e in livrets[i] if abs(e.montant + o.montant) < 0.01
                                and abs((date.fromisoformat(e.date) - date.fromisoformat(o.date)).days) <= 4), None)
                if pendant is not None:
                    livrets[i].remove(pendant)
                    types[k] = "epargne"
        for k in self._entre_tes_comptes(documents, principales, exclus=set(types)):
            types[k] = "entre_tes_comptes"
        for k in self._achats_exceptionnels(principales, exclus=set(types)):
            types[k] = "exceptionnel"
        transactions, transferts = [], []
        for k, (_, o) in enumerate(principales):
            type_ = types.get(k)
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
    def _entre_tes_comptes(documents: list[DocumentAnonymise], principales: list[tuple[int, OperationAnonyme]],
                           exclus: set[int]) -> set[int]:
        """Virements entre deux de tes comptes courants relevés à part (deux banques) : un débit dans
        un relevé, un crédit du même montant dans un autre, à ECART_ENTRE_BANQUES jours près. Rangs
        appariés dans `principales`.

        Les deux relevés doivent couvrir ensemble le jour du débit ou celui du crédit : deux relevés
        successifs d'un même compte ne se chevauchent pas, leurs opérations ne sont jamais appariées.
        Deux libellés qui nomment deux personnes différentes non plus (tu paies l'un, l'autre te
        rembourse le même montant) ; ton nom, sous quelque forme que ce soit, ne contredit rien."""
        def couverture(i: int) -> list[tuple[date, date]]:
            # Période imprimée sur le relevé, sinon les mois entiers de ses opérations (un relevé
            # mensuel dont la première opération tombe le 3 couvre aussi le 1er)
            connues = [(debut, fin) for debut, fin in documents[i].periodes if debut and fin]
            jours = [date.fromisoformat(o.date) for j, o in principales if j == i]
            if connues or not jours:
                return connues
            fin = max(jours)
            return [(min(jours).replace(day=1), fin.replace(day=monthrange(fin.year, fin.month)[1]))]

        couvertures = {i: couverture(i) for i in {i for i, _ in principales}}

        def couvre(i: int, jour: date) -> bool:
            return any(debut <= jour <= fin for debut, fin in couvertures[i])

        def qui(o: OperationAnonyme) -> str | None:
            # « toi » (ton nom, même en partie), le pseudonyme d'une autre personne, ou personne
            if o.a_ton_nom or o.nom_partiel:
                return "toi"
            jeton = re.search(r"\[(PERSONNE_\d+)\]", o.libelle)
            return jeton.group(1) if jeton else None

        def compatibles(a: OperationAnonyme, b: OperationAnonyme, strict: bool) -> bool:
            qa, qb = qui(a), qui(b)
            return qa == qb == "toi" if strict else qa is None or qb is None or qa == qb

        virements = [(k, i, o, date.fromisoformat(o.date)) for k, (i, o) in enumerate(principales)
                     if k not in exclus and "vir" in o.libelle.lower() and not LOYER.search(o.libelle.lower())]
        debits = sorted((v for v in virements if v[2].montant < 0), key=lambda v: v[3])
        credits = [v for v in virements if v[2].montant > 0]
        apparies: set[int] = set()
        # D'abord les paires où les deux libellés portent ton nom : un virement à un ami du même
        # montant, la veille, ne prend pas la place de ton virement entre tes comptes
        for strict in (True, False):
            for k, i, o, jour in debits:
                if k in apparies:
                    continue
                candidats = [c for c in credits
                             if c[0] not in apparies and c[1] != i and abs(c[2].montant + o.montant) < 0.01
                             and abs((c[3] - jour).days) <= ECART_ENTRE_BANQUES
                             and any(couvre(i, x) and couvre(c[1], x) for x in (jour, c[3]))
                             and compatibles(o, c[2], strict)]
                if candidats:
                    apparies |= {k, min(candidats, key=lambda c: abs((c[3] - jour).days))[0]}
        return apparies

    def _achats_exceptionnels(self, principales: list[tuple[int, OperationAnonyme]], exclus: set[int]) -> set[int]:
        """Un achat exceptionnel (voiture, travaux…) : les paiements à un même bénéficiaire en 7 jours
        qui font ensemble au moins analyse.achat_exceptionnel_min € (prélèvements exceptés : impôts et
        mensualités comptent), et un prêt débloqué, qui n'est pas un revenu. Rangs dans `principales`."""
        seuil = self.config.analyse.achat_exceptionnel_min
        if seuil <= 0:
            return set()
        retenus = {k for k, (_, o) in enumerate(principales)
                   if k not in exclus and o.montant > 0 and PRET_DEBLOQUE.search(o.libelle)}
        debits = sorted(((k, o, date.fromisoformat(o.date)) for k, (_, o) in enumerate(principales)
                         if k not in exclus and o.montant < 0 and not PRELEVEMENT.search(o.libelle)
                         and not LOYER.search(o.libelle.lower()) and not o.a_ton_nom and not o.compte_declare),
                        key=lambda d: d[2])
        par_beneficiaire: dict[str, list[tuple[int, OperationAnonyme, date]]] = {}
        for d in debits:
            par_beneficiaire.setdefault(cle_beneficiaire(d[1].libelle), []).append(d)
        for liste in par_beneficiaire.values():
            for i, (_, _, debut) in enumerate(liste):
                fenetre = [d for d in liste[i:] if (d[2] - debut).days <= 7]
                if -sum(d[1].montant for d in fenetre) >= seuil:
                    retenus |= {d[0] for d in fenetre}
        return retenus

    @staticmethod
    def periode_couverte(documents: list[DocumentAnonymise]) -> tuple[float | None, str | None]:
        """Nombre de mois d'après les dates des relevés (solde précédent -> nouveau solde),
        arrondi au demi-mois ; plus fiable que les dates d'opérations. Les jours couverts par
        plusieurs relevés (deux banques, mêmes mois) ne comptent qu'une fois."""
        periodes = [p for d in documents for p in d.periodes if p[0] and p[1] and p[1] > p[0]]
        if not periodes:
            return None, None
        jours: set[date] = set()
        for debut, fin in periodes:
            jours.update(debut + timedelta(days=k) for k in range((fin - debut).days))
        mois = max(0.5, round(len(jours) / 30.44 * 2) / 2)
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
        analyse = self.config.analyse
        programme = AnalyseReleve(
            self.config.recurrence,
            loyer_montant_min=analyse.loyer_montant_min if analyse.loyers_sans_libelle == "detecter" else None,
            categories=analyse.categories,
        )
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
            analyse = programme.analyser_transactions(transactions, alertes, en_clair=self.coffre.depseudonymiser)
            progression.info("[5/5] Rédaction de la synthèse…")
            return self._conclure(Synthetiseur(), documents, analyse, transferts,
                                  connus=lus if not a_extraire else [])

    def analyser_sans_ia(self, documents: list[DocumentAnonymise]) -> dspy.Prediction:
        """Aucun modèle n'est configuré ici : un appel à l'IA échouerait au lieu de partir.
        Les relevés que seule l'IA sait lire sont écartés et signalés dans le rapport."""
        lus = [d for d in documents if d.operations is not None]
        transactions, transferts, alertes = self.separer_transferts(lus)
        progression.info("[1/5] Lecture directe des tableaux : %d opération(s) sur le compte principal, "
                         "%d mouvement(s) entre tes comptes mis à part", len(transactions), len(transferts))
        analyse_cfg = self.config.analyse
        programme = AnalyseSansIA(
            self.config.recurrence,
            loyer_montant_min=analyse_cfg.loyer_montant_min if analyse_cfg.loyers_sans_libelle == "detecter" else None,
            categories=analyse_cfg.categories,
            en_clair=self.coffre.depseudonymiser,
        )
        analyse = programme.analyser_transactions(transactions, alertes, en_clair=self.coffre.depseudonymiser)
        progression.info("[5/5] Calcul des constats…")
        return self._conclure(SyntheseSansIA(), documents, analyse, transferts, connus=lus, sans_ia=True)

    def _conclure(self, synthetiseur: Synthetiseur, documents: list[DocumentAnonymise], analyse: dspy.Prediction,
                  transferts: list[dict], connus: list[DocumentAnonymise], sans_ia: bool = False) -> dspy.Prediction:
        """`connus` : les relevés dont on connaît les dates (la période vient d'eux)."""
        nb_mois, periode = self.periode_couverte(connus) if connus else (None, None)
        couverture = self.couverture_mois(connus) if connus else None
        synthese = synthetiseur(
            transactions=analyse.transactions,
            recurrents=analyse.recurrents,
            classements=analyse.classements,
            transferts=transferts,
            nb_mois=nb_mois,
            periode=periode,
            proches_a_part=self.config.analyse.virements_a_des_proches == "a_part",
            recus_de_proches=self.config.analyse.recus_de_proches,
            couverture=couverture,
            loyers=analyse.get("loyers", []),
        )
        lectures = self.lectures(documents, sans_ia)
        section = lectures_markdown(lectures, sans_ia)     # écrite ici, en Python : jamais envoyée à l'IA
        return dspy.Prediction(
            analyse=analyse,
            transferts=transferts,
            lectures=lectures,
            rapport_anonyme=synthese.rapport + section,
            # Dé-pseudonymisation 100 % locale : les vrais noms ne sont remis qu'ici
            rapport=self.coffre.depseudonymiser(synthese.rapport) + section,
            # Pour la page HTML : chiffres calculés en Python + commentaire (avec pseudonymes)
            budget=synthese.budget,
            commentaire=synthese.commentaire,
        )
