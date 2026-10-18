"""Catégories : définitions envoyées à l'IA, page qui les explique, réponses rattachées (sans IA)."""
from pathlib import Path

import dspy

from mas.agents.programme import AnalyseReleve
from mas.agents.signatures import CategoriserLibelles, LibelleCategorise
from mas.modeles import CATEGORIES, DEFINITIONS_CATEGORIES, Transaction
from mas.page import CATEGORIES as NOMS_AFFICHES

DOC = Path(__file__).resolve().parents[1] / "docs" / "categories.md"


def test_chaque_categorie_a_sa_definition_dans_les_consignes():
    assert list(DEFINITIONS_CATEGORIES) == CATEGORIES
    for cle, definition in DEFINITIONS_CATEGORIES.items():
        assert f"- {cle} : {definition}" in CategoriserLibelles.instructions


def test_la_doc_cite_chaque_definition():
    doc = " ".join(DOC.read_text(encoding="utf-8").replace("> ", " ").split())
    assert [n for n in NOMS_AFFICHES.values() if n not in doc] == []
    assert [c for c, d in DEFINITIONS_CATEGORIES.items() if d not in doc] == []


def test_reponse_recopiee_avec_d_autres_espaces_ou_oubliee():
    programme = AnalyseReleve()

    def categoriseur(libelles):
        # l'IA change les espaces et la casse, et oublie le dernier libellé
        return dspy.Prediction(categories=[
            LibelleCategorise(libelle=" " + l.lower().replace(" ", "  "), categorie="logement")
            for l in libelles[:-1]
        ])

    programme.categoriseur = categoriseur
    operations = [Transaction(date="2026-04-03", libelle="VIR SEPA PERMANENT LOYER", montant=-800.0),
                  Transaction(date="2026-04-09", libelle="CHEQUE 1234567", montant=-40.0)]
    assert [t.categorie for t in programme.categoriser(operations)] == ["logement", "autre"]
