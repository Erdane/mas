"""Reconnaisseurs Presidio adaptés aux documents français (relevés bancaires en priorité)."""

from __future__ import annotations

import re
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
