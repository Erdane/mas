"""Modèles de données partagés entre agents, détection et métriques."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Categorie = Literal[
    "logement", "energie", "telecom", "assurance", "transport", "alimentation", "restauration",
    "abonnement", "sante", "impots_taxes", "credit", "epargne", "shopping", "loisirs",
    "frais_bancaires", "retrait", "virement_personnel", "revenu", "autre",
]

# Ce que l'IA reçoit pour chaque catégorie (agents/signatures.py, CategoriserLibelles).
# docs/categories.md explique les mêmes définitions : garde les deux d'accord.
DEFINITIONS_CATEGORIES: dict[str, str] = {
    "logement": "loyer, mensualité de crédit immobilier, charges de copropriété, frais d'agence",
    "energie": "électricité, gaz, eau, fioul, bois de chauffage",
    "telecom": "box internet, forfait mobile, téléphone fixe",
    "assurance": "assurances habitation, auto, moto, emprunteur, mutuelle santé, prévoyance",
    "transport": ("carburant, recharge électrique, péages, parking, transports en commun, billets de "
                  "train, d'avion ou de car, taxis et VTC, location de véhicule, entretien et réparation "
                  "du véhicule"),
    "alimentation": "courses : supermarché, épicerie, boulangerie, marché, boucherie, primeur",
    "restauration": "restaurants, fast-foods, cafés et bars, cantine, livraison de repas",
    "abonnement": ("abonnements résiliables : streaming, musique, logiciels, applications, stockage en "
                   "ligne, presse, salle de sport"),
    "sante": "pharmacie, médecin, dentiste, opticien, kiné, hôpital, laboratoire",
    "impots_taxes": ("impôt sur le revenu, taxe foncière, taxe d'habitation, cotisations URSSAF "
                     "d'indépendant, amendes, timbres fiscaux"),
    "credit": ("remboursement d'un prêt autre qu'immobilier : crédit à la consommation, crédit auto, "
               "crédit renouvelable, prêt étudiant, paiement en plusieurs fois"),
    "epargne": ("versements vers ou retraits depuis un livret, une assurance-vie, un PEA, un PEL, "
                "l'épargne salariale"),
    "shopping": ("vêtements, beauté et coiffeur, high-tech, maison (meubles, électroménager, bricolage, "
                 "décoration, jardin), achats en ligne non alimentaires"),
    "loisirs": ("sorties et culture (cinéma, concerts, musées, livres, jeux), sport hors abonnement, "
                "vacances (hébergement, activités, parcs de loisirs), jeux d'argent"),
    "frais_bancaires": ("cotisation de carte, tenue de compte, agios, commissions, frais de rejet, "
                        "frais sur les paiements à l'étranger"),
    "retrait": "retraits d'espèces au distributeur (DAB, GAB) ou au guichet, dépôts d'espèces",
    "virement_personnel": ("virements vers ou depuis des particuliers ([PERSONNE_n], un prénom), y compris "
                           "par Lydia, Wero, Paylib ou PayPal entre particuliers"),
    "revenu": ("salaire, primes, retraite, allocations (CAF, France Travail), indemnités, aides, "
               "revenus d'une activité"),
    "autre": ("ce qui ne correspond à aucune catégorie (chèque sans précision, don, école ou garde "
              "d'enfants, vétérinaire…) ou dont le libellé ne permet pas de décider"),
}

CATEGORIES: list[str] = list(Categorie.__args__)

Nature = Literal["obligatoire", "abonnement_optionnel", "courant_variable"]


class Transaction(BaseModel):
    date: str = Field(description="Date au format AAAA-MM-JJ")
    libelle: str = Field(description="Libellé complet, jetons [XXX_n] inclus, tel qu'il apparaît")
    montant: float = Field(description="Négatif pour un débit, positif pour un crédit")


class TransactionCategorisee(Transaction):
    categorie: Categorie = "autre"


class GroupeRecurrent(BaseModel):
    cle: str
    libelle: str
    categorie: str
    periodicite: str
    occurrences: int
    montant_moyen: float
    montant_mensuel: float
    montant_variable: bool
    dates: list[str]


class Classement(BaseModel):
    cle: str = Field(description="Clé du groupe récurrent, recopiée exactement")
    nature: Nature
    justification: str = Field(description="Une phrase courte")
