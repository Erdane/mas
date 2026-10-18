"""Signatures DSPy des agents. Les docstrings sont les instructions de départ :
GEPA les réécrit pendant l'optimisation à partir des retours de la métrique."""

from __future__ import annotations

import dspy
from pydantic import BaseModel

from ..modeles import DEFINITIONS_CATEGORIES, Categorie, Classement, GroupeRecurrent, Transaction


class ExtraireTransactions(dspy.Signature):
    """Tu extrais les opérations d'une page de relevé bancaire français pseudonymisé.

    - Une opération = une ligne datée avec un montant. Ignore les soldes, totaux et reports.
    - Montant négatif pour un débit, positif pour un crédit. Utilise la colonne
      (Débit / Crédit) quand le tableau en a deux.
    - Les montants français s'écrivent "1 234,56" : convertis en 1234.56.
    - Dates au format AAAA-MM-JJ ; déduis l'année de la période du relevé.
    - Recopie le libellé tel quel, y compris les jetons entre crochets comme [PERSONNE_2].
    - Si un retour du contrôleur est fourni, corrige précisément les erreurs signalées."""

    page: str = dspy.InputField(desc="Texte d'une page ; les tableaux sont rendus en | col | col |")
    periode: str = dspy.InputField(desc="Période du relevé, ex. 'du 01/03/2026 au 31/03/2026'")
    retour_controleur: str = dspy.InputField(desc="Erreurs détectées à la tentative précédente, ou vide")
    transactions: list[Transaction] = dspy.OutputField()


class LibelleCategorise(BaseModel):
    libelle: str
    categorie: Categorie


class CategoriserLibelles(dspy.Signature):
    """Instructions construites juste après la classe, à partir de DEFINITIONS_CATEGORIES."""

    libelles: list[str] = dspy.InputField()
    categories: list[LibelleCategorise] = dspy.OutputField()


def instructions_categories() -> str:
    definitions = "\n".join(f"- {cle} : {texte}" for cle, texte in DEFINITIONS_CATEGORIES.items())
    return f"""Tu classes des libellés d'opérations bancaires françaises dans une catégorie de budget.

Repères : PRLV = prélèvement, VIR = virement, CB = paiement par carte, DAB = retrait.
Les noms de personnes sont masqués ([PERSONNE_n]) : décide d'après les autres mots du libellé.

Catégories :
{definitions}

Règles :
- Un virement vers ou depuis [PERSONNE_n] est un virement_personnel, sauf si le libellé indique
  un loyer (logement) ou un salaire (revenu).
- Un remboursement venant d'un commerçant ou d'un organisme (Assurance maladie, mutuelle, impôts…)
  va dans la catégorie de la dépense remboursée, pas dans revenu : il sera déduit de cette catégorie.
- Un paiement passé par un intermédiaire (PayPal, SumUp…) va dans la catégorie du marchand quand
  le libellé l'indique.
- Billets de train, d'avion ou de car : transport, même pour des vacances.
- autre seulement si aucune catégorie ne convient ou si le libellé ne permet pas de décider.

Renvoie exactement un élément par libellé, avec le libellé recopié à l'identique."""


# L'IA reçoit exactement les définitions expliquées dans docs/categories.md
CategoriserLibelles.instructions = instructions_categories()


class ClasserRecurrences(dspy.Signature):
    """Tu classes des dépenses récurrentes détectées sur un compte bancaire.

    - obligatoire : on ne peut pas s'en passer à court terme sans conséquence
      (logement, énergie, assurances obligatoires, crédits, impôts, mutuelle,
      box/mobile de base, transport domicile-travail).
    - abonnement_optionnel : résiliable sans conséquence majeure (streaming,
      salle de sport, presse, applications, jeux).
    - courant_variable : achat régulier mais variable (courses, carburant, restaurant).
    Renvoie un classement par groupe, avec la clé recopiée exactement."""

    groupes: list[GroupeRecurrent] = dspy.InputField()
    classements: list[Classement] = dspy.OutputField()


class RedigerSynthese(dspy.Signature):
    """Tu rédiges en français une synthèse budgétaire claire et factuelle.

    Les chiffres fournis sont exacts : ne les recalcule pas, ne les invente pas.
    Garde les jetons entre crochets ([PERSONNE_1]...) tels quels.
    Structure : un paragraphe de constat, puis 3 à 5 pistes concrètes d'économies
    portant sur les abonnements optionnels et les postes variables."""

    resume_chiffre: str = dspy.InputField()
    synthese: str = dspy.OutputField(desc="Markdown, 150 à 300 mots")
