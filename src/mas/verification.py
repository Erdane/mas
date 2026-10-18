"""Vérificateur de fuites : dernier contrôle avant tout envoi vers le LLM cloud.

Il est volontairement indépendant du moteur d'anonymisation (regex + clés de
contrôle + recherche exacte), pour ne pas reproduire les mêmes angles morts.
Un LLM local (Ollama) peut s'y ajouter en option.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .anonymisation.moteur import motif_souple
from .anonymisation.validateurs import iban_valide, luhn_valide, nir_valide
from .config import ConfigVerification


@dataclass(frozen=True)
class Fuite:
    entite: str
    valeur: str
    source: str

    def __str__(self) -> str:
        return f"{self.entite} « {self.valeur} » ({self.source})"


CONTROLES = [
    ("IBAN_CODE", re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,4})?\b"), iban_valide),
    ("CREDIT_CARD", re.compile(r"(?<!\d)(?:\d[ \-]?){12,18}\d(?!\d)"), luhn_valide),
    ("EMAIL_ADDRESS", re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+"), None),
    # mobiles 06/07, même séparateur partout (une suite de dates n'est pas un numéro)
    ("FR_TELEPHONE", re.compile(r"(?<![\d,])(?:(?:\+|00)33\s?(?:\(0\)\s?)?|0)[67]([\s.\-]?)\d{2}(?:\1\d{2}){3}(?![\d,])"), None),
    ("FR_NIR", re.compile(r"(?<!\d)[12]\s?\d{2}\s?\d{2}\s?(?:\d{2}|2A|2B)\s?\d{3}\s?\d{3}\s?\d{2}(?!\d)"), nir_valide),
]


class Verificateur:
    def __init__(self, config: ConfigVerification, termes_sensibles: list[tuple[str, str]]):
        self.config = config
        self.termes = [(v, e) for v, e in termes_sensibles if len(v.strip()) >= 4]
        self._llm = None

    def verifier(self, texte: str, valeurs_coffre: list[str] = ()) -> list[Fuite]:
        fuites: set[Fuite] = set()

        for entite, regex, validateur in CONTROLES:
            for m in regex.finditer(texte):
                if validateur is None or validateur(m.group(0)):
                    fuites.add(Fuite(entite, m.group(0).strip(), "regex"))

        # Toute valeur déjà pseudonymisée ailleurs ne doit pas réapparaître en clair
        candidats = list(self.termes) + [
            (v, "DONNEE_PERSO") for v in valeurs_coffre if len(v.strip()) >= 4
        ]
        for valeur, entite in candidats:
            m = re.search(motif_souple(valeur), texte, flags=re.IGNORECASE)
            if m:
                fuites.add(Fuite(entite, m.group(0), "valeur connue"))

        if self.config.llm_local.actif:
            fuites.update(self._verifier_llm(texte))
        return sorted(fuites, key=lambda f: (f.entite, f.valeur))

    def _verifier_llm(self, texte: str) -> list[Fuite]:
        import dspy

        class DetecterDonneesPersonnelles(dspy.Signature):
            """Le texte est un document déjà pseudonymisé : les données personnelles
            sont remplacées par des jetons entre crochets comme [PERSONNE_1].
            Liste les données personnelles qui restent EN CLAIR : nom ou prénom
            d'un particulier, adresse, téléphone, email, numéro de compte ou de
            client. Les noms d'entreprises et de commerçants ne sont PAS des
            données personnelles. Recopie chaque valeur exactement."""

            texte: str = dspy.InputField()
            valeurs_en_clair: list[str] = dspy.OutputField()

        if self._llm is None:
            cfg = self.config.llm_local
            self._llm = dspy.LM(cfg.modele, api_base=cfg.api_base, temperature=0.0)
        detecteur = dspy.Predict(DetecterDonneesPersonnelles)
        fuites = []
        with dspy.context(lm=self._llm):
            for i in range(0, len(texte), 3000):
                bloc = texte[i:i + 3000]
                for v in detecteur(texte=bloc).valeurs_en_clair:
                    if v and len(v) >= 3 and v in bloc and not v.startswith("["):
                        fuites.append(Fuite("DONNEE_PERSO", v, "llm local"))
        return fuites
