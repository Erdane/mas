"""Reconnaisseurs Presidio adaptés aux documents français (relevés bancaires en priorité)."""

from __future__ import annotations

import re
from functools import cache
from typing import Callable

from presidio_analyzer import EntityRecognizer, RecognizerResult
from presidio_analyzer.predefined_recognizers import CreditCardRecognizer

from .validateurs import luhn_valide, nir_valide, rib_valide

LANGUE = "fr"

# Mots fréquents sur les relevés qui ne sont jamais des noms de personnes.
# Ils s'ajoutent à la liste blanche de la configuration.
MOTS_NON_NOMS = [
    "TEL", "TÉL", "IBAN", "BIC", "COMPTE", "RELEVE", "RELEVÉ", "SOLDE", "DATE", "LIBELLE",
    "LIBELLÉ", "DEBIT", "DÉBIT", "CREDIT", "CRÉDIT", "EUR", "EUROS", "REMBOURSEMENT", "REMB",
    "CADEAU", "WEEKEND", "RESTO", "LOYER", "SALAIRE", "PAIE", "ACOMPTE", "FACTURE", "COTISATION",
    "ECHEANCE", "ÉCHÉANCE", "PRET", "PRÊT", "MOIS", "PARTICIPATION", "VACANCES", "ANNIVERSAIRE",
    "JANVIER", "FEVRIER", "FÉVRIER", "MARS", "AVRIL", "MAI", "JUIN", "JUILLET", "AOUT", "AOÛT",
    "SEPTEMBRE", "OCTOBRE", "NOVEMBRE", "DECEMBRE", "DÉCEMBRE", "BANQUE", "AGENCE", "CLIENT",
    # Noms de comptes d'épargne : spaCy prend « Livret A » ou « Solidaire » pour des personnes
    "LIVRET", "LDD", "LDDS", "LEP", "PEL", "CEL", "PEA", "EPARGNE", "ÉPARGNE", "DURABLE",
    "SOLIDAIRE", "DEVELOPPEMENT", "DÉVELOPPEMENT", "POSTE", "PRINCIPAL", "PLAN", "LOGEMENT",
]

# Numéro de téléphone français. Le séparateur doit être le même partout (\1) : sans cette règle,
# une suite de dates de relevé (« 08.04 08.04 13.04 ») passait pour un numéro et était masquée.
MOTIF_TELEPHONE = (r"(?<![\d,])(?:(?:\+|00)33\s?(?:\(0\)\s?)?|0)([1-9])([\s.\-]?)\d{2}(?:\2\d{2}){3}(?![\d,])")
_DATE_JJ_MM = re.compile(r"\d{2}[./]\d{2}")
_TELEPHONE = re.compile(MOTIF_TELEPHONE)


def valeur_plausible(valeur: str, mots_communs: set[str]) -> bool:
    """Une valeur du coffre n'est recherchée comme donnée personnelle que si elle en a l'air.
    Les analyses précédentes ont pu y enregistrer de faux positifs (suites de dates prises pour
    un téléphone, « Livret A » pris pour une personne) : on les ignore sans modifier le coffre."""
    if len(_DATE_JJ_MM.findall(valeur)) >= 2 and not _TELEPHONE.fullmatch(valeur.strip()):
        return False
    mots = re.findall(r"[A-Za-zÀ-ÿ]+", valeur.upper())
    if mots and all(m in mots_communs or len(m) == 1 for m in mots):
        return False
    return True


class RegexGroupeRecognizer(EntityRecognizer):
    """Reconnaisseur regex qui ne retient qu'un groupe de capture.

    Utile quand le contexte ("VIR SEPA DE", "RUM :") doit être reconnu mais pas
    pseudonymisé. Un validateur optionnel élimine les faux positifs.
    """

    def __init__(
        self,
        entite: str,
        motif: str,
        groupe: int | str = 0,
        score: float = 0.85,
        flags: int = 0,
        validateur: Callable[[re.Match], bool] | None = None,
        nom: str | None = None,
    ):
        self.regex = re.compile(motif, flags)
        self.groupe = groupe
        self.score = score
        self.validateur = validateur
        super().__init__(
            supported_entities=[entite],
            supported_language=LANGUE,
            name=nom or f"{entite}_regex",
        )

    def load(self) -> None:  # rien à charger
        pass

    def analyze(self, text, entities, nlp_artifacts=None):
        resultats = []
        for m in self.regex.finditer(text):
            if self.validateur and not self.validateur(m):
                continue
            debut, fin = m.span(self.groupe)
            if debut == fin:
                continue
            resultats.append(
                RecognizerResult(self.supported_entities[0], debut, fin, self.score)
            )
        return resultats


# Mots d'un libellé de virement qui ne désignent pas une personne : mots outils, motifs, organismes et
# banques fréquents. Juste après la référence d'un virement, tout le reste est pris pour un nom.
MOTS_DE_VIREMENT = {
    "de", "du", "des", "la", "le", "les", "et", "a", "au", "aux", "en", "pour", "par", "sur", "etc", "sa", "sas",
    "loyer", "residence", "résidence", "remboursement", "rembourse", "remb", "reglement", "règlement",
    "quittance", "facture", "cotisation", "salaire", "appointement", "paie", "prime", "pension", "allocation",
    "aide", "cadeau", "merci", "resto", "restaurant", "courses", "avance", "part", "partie", "participation",
    "cagnotte", "anniversaire", "noel", "noël", "vacances", "voyage", "billet", "avion", "essence", "peage",
    "péage", "parking", "offre", "contrat", "dossier", "sinistre", "virement", "ech", "echeance", "échéance",
    "abonnement", "assurance", "mutuelle", "sante", "santé", "impot", "impots", "impôt", "impôts",
    "edf", "electricite", "électricité", "france", "engie", "caf", "cpam", "ameli", "urssaf", "dgfip", "ddfip",
    "tresor", "trésor", "public", "finances", "publiques", "pole", "emploi", "travail", "sncf", "ratp", "axa",
    "iard", "maif", "macif", "matmut", "allianz", "groupama", "generali", "mgen", "camieg", "sanergi", "ieg",
    "iegsante", "lydia", "paypal", "revolut", "boursobank", "boursorama", "nickel", "corner", "thecorner",
    "asos", "zalando", "amazon", "take", "off", "speedy", "bridgestone", "solutions", "transfert",
}
# Prénoms qui sont aussi des mots, des lieux ou des enseignes courantes sur un relevé
PRENOMS_EXCLUS = {
    "france", "orange", "paris", "bas", "val", "les", "park", "claude", "jules", "angus", "noel", "art", "violet",
    "berry", "man", "per", "fleur", "cuba", "toy", "siv", "stella", "uma", "london", "desi", "ville", "vic",
    "leroy", "franc", "dee", "king", "colin", "rose", "max", "mai", "juin", "avril", "star", "bio", "nova",
    "elle", "son", "trace", "page", "case", "sera", "vide", "media", "math", "add", "true", "eda",
}


@cache
def prenoms() -> frozenset[str]:
    """Prénoms de toutes les langues de Faker (près de 17 000), en minuscules, sans les mots courants."""
    import importlib
    import pkgutil

    import faker.providers.person as personnes

    trouves: set[str] = set()
    for module in pkgutil.iter_modules(personnes.__path__):
        try:
            fournisseur = importlib.import_module(f"faker.providers.person.{module.name}").Provider
        except Exception:
            continue
        for attribut in ("first_names", "first_names_male", "first_names_female"):
            valeurs = getattr(fournisseur, attribut, ())
            valeurs = valeurs.keys() if isinstance(valeurs, dict) else valeurs
            if isinstance(valeurs, (list, tuple, set, type({}.keys()))):
                trouves.update(v.lower() for v in valeurs if isinstance(v, str) and v.isascii() and len(v) >= 3)
    exclus = PRENOMS_EXCLUS | MOTS_DE_VIREMENT | {m.lower() for m in MOTS_NON_NOMS}
    return frozenset(trouves - exclus)


_JETON = re.compile(r"\[[A-Z]+_\d+\]")
_BIC = re.compile(r"[a-z]{4}(?:fr|be|de|lu|es|it|nl|gb|ch|mc|ie|pt)[a-z0-9]{2}(?:[a-z0-9]{3})?", re.IGNORECASE)


class ContrepartieRecognizer(EntityRecognizer):
    """Noms de personnes et lieux que les règles en majuscules ne voient pas : libellés en minuscules
    (BRED, Banque Populaire) ou compactés sans espaces (Boursorama).

    - nom collé : « VIRSEPAVincentDupont », « VIRINSTM.DUPONTJEAN » ;
    - contrepartie d'un virement : les mots qui suivent sa référence (« Virement instantané émis
      1a2b3c4 jean dupont … »), sauf les mots de MOTS_DE_VIREMENT, jusqu'à un pseudonyme, un code BIC
      ou un mot avec des chiffres (trois mots au plus) ;
    - civilité : « m jean-pierre », « mlle martin julie », « dr ing dupont » ;
    - commerçant qui porte un prénom : « Carte 1234567 sophie martin le 19/01/26 » ;
    - lieu d'un retrait d'espèces : « RETRAITDAB24/05/26LYON », « DAB 1234567 bp quai exemple / ».
    """

    COLLE = re.compile(r"\bVIR(?:SEPA|INST)?+(?:MR|MME|MLLE|M\.)?+([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'.\-]{3,})")
    REFERENCE = re.compile(r"\b(?:émis|emis|reçu|recu|automatique|permanent)\s+(?=[0-9a-z]*\d)[0-9a-z]{5,}\s+"
                           r"(?:(?:m|mr|mme|mlle)\.?\s+)?", re.IGNORECASE)
    CIVILITE = re.compile(r"\b(?:m|mr|mme|mlle|dr|docteur|monsieur|madame)\.?\s+([a-zà-ÿ][a-zà-ÿ'\-]+"
                          r"(?:\s+[a-zà-ÿ][a-zà-ÿ'\-]+)?)", re.IGNORECASE)
    COMMERCANT = re.compile(r"\bcarte \d{7} ([^|/\n]+?) le \d{2}/\d{2}/\d{2}", re.IGNORECASE)
    RETRAIT = re.compile(r"RETRAITDAB\d{2}/\d{2}/\d{2}(\d{0,3}[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ' \-]*?)(?=\s?CB\*|$)"
                         r"|\bDAB \d+ ([^|/\n]+?)\s*/", re.MULTILINE)

    def __init__(self, liste_blanche: list[str] | None = None):
        self.gardes = MOTS_DE_VIREMENT | {m.lower() for m in [*MOTS_NON_NOMS, *(liste_blanche or [])]}
        super().__init__(supported_entities=["PERSON", "FR_LIEU"], supported_language=LANGUE, name="contrepartie")

    def load(self) -> None:
        pass

    def _garde(self, mot: str) -> bool:
        return mot.lower().strip(".,'-") in self.gardes

    def analyze(self, text, entities, nlp_artifacts=None):
        resultats = []

        def ajouter(entite: str, debut: int, fin: int, score: float = 0.9) -> None:
            if fin > debut:
                resultats.append(RecognizerResult(entite, debut, fin, score))

        for m in self.COLLE.finditer(text):
            blob = m.group(1)
            if not any(g in blob.lower() for g in ("pret", "deblocage", "virement", "corner", "rembours")):
                ajouter("PERSON", *m.span(1))
        for ligne in re.finditer(r"[^\n]+", text):
            l, decalage = ligne.group(0), ligne.start()
            if re.search(r"(?i)\bvir", l):
                for m in self.REFERENCE.finditer(l):
                    debut = fin = None
                    for i, mot in enumerate(re.finditer(r"[^\s|]+", l[m.end():])):
                        t = mot.group(0)
                        if i >= 3 or _JETON.fullmatch(t) or re.search(r"\d", t) or _BIC.fullmatch(t) or t == "/":
                            break
                        if self._garde(t):
                            if debut is not None:
                                ajouter("PERSON", decalage + m.end() + debut, decalage + m.end() + fin)
                                debut = None
                            continue
                        debut = mot.start() if debut is None else debut
                        fin = mot.end()
                    if debut is not None:
                        ajouter("PERSON", decalage + m.end() + debut, decalage + m.end() + fin)
            for m in self.CIVILITE.finditer(l):
                nom = []                            # les mots du nom, jusqu'au premier mot gardé
                for mot in re.finditer(r"\S+", m.group(1)):
                    if self._garde(mot.group(0)):
                        break
                    nom.append(mot)
                if nom:
                    ajouter("PERSON", decalage + m.start(1) + nom[0].start(), decalage + m.start(1) + nom[-1].end())
            if re.search(r"(?i)\bvir", l):        # un prénom connu, n'importe où dans un virement
                for mot in re.finditer(r"[a-zà-ÿ][a-zà-ÿ'\-]+", l, re.IGNORECASE):
                    if mot.group(0).lower() in prenoms() and not self._garde(mot.group(0)):
                        ajouter("PERSON", decalage + mot.start(), decalage + mot.end(), 0.8)
            for m in self.COMMERCANT.finditer(l):
                mots = re.findall(r"[a-zà-ÿ]+", m.group(1).lower())
                if len(mots) <= 3 and any(mot in prenoms() for mot in mots):
                    ajouter("PERSON", decalage + m.start(1), decalage + m.end(1))
        for m in self.RETRAIT.finditer(text):
            groupe = 1 if m.group(1) else 2
            ajouter("FR_LIEU", *m.span(groupe))
        return resultats


def _mots_exclus(liste_blanche: list[str]) -> str:
    mots = sorted({re.escape(m.upper()) for m in liste_blanche if m.strip()}, key=len, reverse=True)
    return r"(?!(?:" + "|".join(mots) + r")\b)" if mots else ""


def construire_reconnaisseurs(liste_blanche: list[str]) -> list[EntityRecognizer]:
    # Après "M" ou "VIR INST A", c'est forcément une personne : on n'exclut pas
    # les marchands de la liste blanche (sinon "ODILE LECLERC" fuiterait),
    # seulement les mots qui ne sont jamais des noms.
    exclus = _mots_exclus(MOTS_NON_NOMS + ["SEPA", "INST", "RECU", "EMIS", "FAV", "REF"])
    mot_nom = rf"{exclus}[A-ZÀ-Ý][A-Za-zÀ-ÿ'\-]+"

    def valide_rib(m: re.Match) -> bool:
        return rib_valide(m["banque"], m["guichet"], m["compte"], m["cle"])

    return [
        # Carte bancaire (le reconnaisseur Presidio n'existe qu'en anglais par défaut)
        CreditCardRecognizer(supported_language=LANGUE),
        RegexGroupeRecognizer(
            "CREDIT_CARD",
            r"(?<!\d)(?:\d[ \-]?){12,18}\d(?!\d)",
            validateur=lambda m: luhn_valide(m.group(0)),
            score=0.9,
            nom="carte_luhn_fr",
        ),
        RegexGroupeRecognizer(
            "FR_TELEPHONE",
            MOTIF_TELEPHONE,
            score=0.8,
        ),
        RegexGroupeRecognizer(
            "FR_RIB",
            r"(?<!\d)(?P<banque>\d{5})\s?(?P<guichet>\d{5})\s?(?P<compte>[0-9A-Z]{11})\s?(?P<cle>\d{2})(?!\d)",
            validateur=valide_rib,
            score=0.95,
        ),
        RegexGroupeRecognizer(
            "FR_NIR",
            r"(?<!\d)[12]\s?\d{2}\s?\d{2}\s?(?:\d{2}|2A|2B)\s?\d{3}\s?\d{3}\s?\d{2}(?!\d)",
            validateur=lambda m: nir_valide(m.group(0)),
            score=0.95,
        ),
        RegexGroupeRecognizer(
            "FR_NUM_COMPTE",
            r"(?:compte|cpte|n°\s*de\s*compte)[^\d\n|]{0,25}(\d[\d ]{8,20}\d)",
            groupe=1,
            flags=re.IGNORECASE,
            score=0.85,
        ),
        RegexGroupeRecognizer(
            "FR_ADRESSE",
            r"\b\d{1,4}\s?(?:bis|ter)?,?\s+(?:rue|avenue|av\.?|boulevard|bd|all[ée]e|impasse|chemin|"
            r"place|route|quai|cours|square|r[ée]sidence|lotissement|lieu[- ]dit|voie|passage)"
            r"\b[^\n|]{2,60}",
            flags=re.IGNORECASE,
            score=0.85,
        ),
        RegexGroupeRecognizer(
            "FR_ADRESSE",
            r"(?:^|,\s*)(\d{5}\s+[A-ZÀ-Ý][A-Za-zÀ-ÿ' \-]{1,40}?)\s*$",
            groupe=1,
            flags=re.MULTILINE,
            score=0.7,
            nom="code_postal_ville",
        ),
        # "M DUPONT JEAN", "MME MARTIN" : très fréquent dans les libellés de virement
        RegexGroupeRecognizer(
            "FR_CIVILITE_NOM",
            rf"\b(?:M|MR|MME|MLLE|MONSIEUR|MADAME|Monsieur|Madame|Mme|Mlle)\.?\s+"
            rf"((?:{mot_nom})(?:\s+{mot_nom}){{0,2}})",
            groupe=1,
            score=0.85,
        ),
        # Contrepartie d'un virement : "VIR SEPA DE JEAN MARTIN", "VIR INST A MARIE DURAND"
        RegexGroupeRecognizer(
            "FR_CIVILITE_NOM",
            rf"\bVIR(?:EMENT)?(?:\s+(?:SEPA|INST(?:ANTANE)?|RECU|EMIS|PERMANENT))*\s+"
            rf"(?:DE|A|À|POUR|VERS|FAV(?:EUR)?)\s+"
            rf"((?:{mot_nom})(?:\s+{mot_nom}){{1,2}})",
            groupe=1,
            score=0.75,
            nom="contrepartie_virement",
        ),
        # Libellés en minuscules ou compactés : contreparties, civilités, commerçants, lieux de retrait
        ContrepartieRecognizer(liste_blanche),
        # Référence unique de mandat (RUM) : identifiant personnel du prélèvement
        RegexGroupeRecognizer(
            "FR_REFERENCE_MANDAT",
            r"\b(?:RUM|MANDAT|REF\.?\s*MANDAT)\s*[:.]?\s*([A-Z0-9][A-Z0-9\-/]{5,34})",
            groupe=1,
            flags=re.IGNORECASE,
            score=0.8,
        ),
    ]


class GlinerRecognizer(EntityRecognizer):
    """Deuxième détecteur basé sur GLiNER (optionnel, CPU OK)."""

    ETIQUETTES = {
        "person": "PERSON",
        "email": "EMAIL_ADDRESS",
        "phone number": "PHONE_NUMBER",
        "address": "FR_ADRESSE",
        "iban": "IBAN_CODE",
        "credit card number": "CREDIT_CARD",
        "social security number": "FR_NIR",
        "bank account number": "FR_NUM_COMPTE",
    }

    def __init__(self, modele: str, seuil: float = 0.5, liste_blanche: list[str] | None = None):
        self.nom_modele = modele
        self.seuil = seuil
        self.liste_blanche = {m.upper() for m in (liste_blanche or [])}
        self.modele = None
        super().__init__(
            supported_entities=sorted(set(self.ETIQUETTES.values())),
            supported_language=LANGUE,
            name="gliner",
        )

    def load(self) -> None:
        try:
            from gliner import GLiNER
        except ImportError as e:
            raise ImportError('GLiNER non installé : pip install "mas[gliner]"') from e
        self.modele = GLiNER.from_pretrained(self.nom_modele)

    @staticmethod
    def _morceaux(texte: str, taille: int = 1200):
        """Découpe en blocs de lignes (GLiNER a une fenêtre limitée)."""
        debut, courant = 0, 0
        for ligne in texte.splitlines(keepends=True):
            if courant - debut + len(ligne) > taille and courant > debut:
                yield debut, texte[debut:courant]
                debut = courant
            courant += len(ligne)
        if courant > debut:
            yield debut, texte[debut:courant]

    def analyze(self, text, entities, nlp_artifacts=None):
        if self.modele is None:
            self.load()
        resultats = []
        for decalage, morceau in self._morceaux(text):
            for ent in self.modele.predict_entities(
                morceau, list(self.ETIQUETTES), threshold=self.seuil
            ):
                if ent["text"].strip().upper() in self.liste_blanche:
                    continue
                entite = self.ETIQUETTES.get(ent["label"])
                if entite and (not entities or entite in entities):
                    resultats.append(
                        RecognizerResult(
                            entite, decalage + ent["start"], decalage + ent["end"],
                            float(ent["score"]),
                        )
                    )
        return resultats
