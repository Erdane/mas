"""Moteur d'anonymisation : Presidio (spaCy FR) + regex FR + GLiNER optionnel
+ recherche exacte des données personnelles déclarées, puis pseudonymisation
cohérente via le coffre."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from functools import cached_property

from ..config import ConfigAnonymisation
from .coffre import Coffre
from .reconnaisseurs import MOTS_NON_NOMS, GlinerRecognizer, construire_reconnaisseurs

# Le reconnaisseur d'emails télécharge la liste des suffixes publics ; hors
# ligne il utilise sa copie embarquée, inutile d'afficher la trace d'erreur.
logging.getLogger("tldextract").setLevel(logging.CRITICAL)

VARIANTES = {
    "a": "aàâä", "e": "eéèêë", "i": "iîï", "o": "oôö", "u": "uùûü", "c": "cç", "y": "yÿ",
}


def motif_souple(terme: str) -> str:
    """Regex tolérante à la casse, aux accents et aux séparateurs.

    "Jean Dupont" trouve "JEAN  DUPONT" ; "FR76 3000..." trouve "FR7630000..." ;
    "06 12 34 56 78" trouve "06.12.34.56.78".
    """
    compact = re.sub(r"[\s.\-]", "", terme)
    if compact.isalnum() and sum(c.isdigit() for c in compact) >= 5:
        return r"[\s.\-]?".join(re.escape(c) for c in compact)
    morceaux = []
    for c in terme.strip():
        if c.isspace():
            if not morceaux or morceaux[-1] != r"[\s\-]+":
                morceaux.append(r"[\s\-]+")
            continue
        base = next((b for b, v in VARIANTES.items() if c.lower() in v), None)
        morceaux.append(f"[{VARIANTES[base]}]" if base else re.escape(c))
    return r"(?<!\w)" + "".join(morceaux) + r"(?!\w)"


@dataclass
class Detection:
    entite: str
    debut: int
    fin: int
    score: float
    source: str


@dataclass
class ResultatAnonymisation:
    texte: str
    remplacements: list[tuple[str, str, str]] = field(default_factory=list)  # (entité, original, pseudo)

    @property
    def nb(self) -> int:
        return len(self.remplacements)


class Anonymiseur:
    def __init__(
        self,
        config: ConfigAnonymisation,
        coffre: Coffre,
        termes_personnels: list[tuple[str, str]] | None = None,
    ):
        self.config = config
        self.coffre = coffre
        self.termes_personnels = list(termes_personnels or [])
        self.liste_blanche = {m.upper() for m in [*config.liste_blanche, *MOTS_NON_NOMS]}

    @cached_property
    def analyseur(self):
        from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
        from presidio_analyzer.nlp_engine import NlpEngineProvider

        nlp = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "fr", "model_name": self.config.modele_spacy}],
                # Le modèle français étiquette aussi MISC (divers), qui ne fait pas partie des
                # entités demandées : l'ignorer évite un avertissement par entité trouvée.
                "ner_model_configuration": {"labels_to_ignore": ["MISC"]},
            }
        ).create_engine()
        registre = RecognizerRegistry(supported_languages=["fr"])
        # Presidio signale chaque reconnaisseur prédéfini d'une autre langue (en, es, it, pl)
        # qu'il écarte : c'est voulu, on coupe ces avertissements le temps du chargement.
        journal_presidio = logging.getLogger("presidio-analyzer")
        niveau = journal_presidio.level
        journal_presidio.setLevel(logging.ERROR)
        try:
            registre.load_predefined_recognizers(languages=["fr"], nlp_engine=nlp)
        finally:
            journal_presidio.setLevel(niveau)
        for r in construire_reconnaisseurs(self.config.liste_blanche):
            registre.add_recognizer(r)
        if self.config.gliner.actif:
            registre.add_recognizer(
                GlinerRecognizer(
                    self.config.gliner.modele, self.config.gliner.seuil, self.config.liste_blanche
                )
            )
        return AnalyzerEngine(nlp_engine=nlp, registry=registre, supported_languages=["fr"])

    # ------------------------------------------------------------------
    def _rogner_liste_blanche(self, texte: str, d: Detection) -> Detection | None:
        """Retire les mots de la liste blanche aux bords d'une détection NER.

        spaCy prend parfois "PRLV SEPA EDF" ou "LOYER" dans une entité PERSON.
        """
        segment = texte[d.debut:d.fin]
        mots = list(re.finditer(r"\S+", segment))
        while mots and mots[0].group().strip(".,:;").upper() in self.liste_blanche:
            mots.pop(0)
        while mots and mots[-1].group().strip(".,:;").upper() in self.liste_blanche:
            mots.pop()
        if not mots:
            return None
        debut, fin = d.debut + mots[0].start(), d.debut + mots[-1].end()
        contenu = texte[debut:fin]
        # Une "personne" faite de chiffres, de montants ou d'une seule lettre : faux positif
        if d.entite == "PERSON" and (re.search(r"\d", contenu) or len(contenu) < 3):
            return None
        return Detection(d.entite, debut, fin, d.score, d.source)

    def detecter(self, texte: str, termes_supplementaires=()) -> list[Detection]:
        detections: list[Detection] = []

        for r in self.analyseur.analyze(
            text=texte,
            language="fr",
            entities=self.config.entites,
            score_threshold=self.config.seuil_score,
            allow_list=sorted(self.liste_blanche),
        ):
            d = Detection(r.entity_type, r.start, r.end, r.score, "presidio")
            if r.entity_type == "PERSON":
                d = self._rogner_liste_blanche(texte, d)
            if d:
                detections.append(d)

        # Données personnelles déclarées + fuites signalées par le vérificateur : priorité max
        for valeur, entite in [*self.termes_personnels, *termes_supplementaires]:
            for m in re.finditer(motif_souple(valeur), texte, flags=re.IGNORECASE):
                detections.append(Detection(entite, m.start(), m.end(), 1.01, "identite"))

        # Résolution des chevauchements : meilleur score, puis plus longue détection
        detections.sort(key=lambda d: (-d.score, -(d.fin - d.debut)))
        retenues: list[Detection] = []
        for d in detections:
            if all(d.fin <= r.debut or d.debut >= r.fin for r in retenues):
                retenues.append(d)
        return sorted(retenues, key=lambda d: d.debut)

    def anonymiser(self, texte: str, termes_supplementaires=()) -> ResultatAnonymisation:
        detections = self.detecter(texte, termes_supplementaires)
        resultat = ResultatAnonymisation(texte="")
        morceaux, curseur = [], 0
        for d in detections:
            original = texte[d.debut:d.fin]
            pseudo = self.coffre.pseudonyme(d.entite, original)
            morceaux += [texte[curseur:d.debut], pseudo]
            curseur = d.fin
            resultat.remplacements.append((d.entite, original, pseudo))
        morceaux.append(texte[curseur:])
        resultat.texte = "".join(morceaux)
        return resultat
