"""Journalisation : chaque message une seule fois, plus d'avertissements Presidio parasites,
et avancement de l'analyse étape par étape."""
import logging

import dspy
from faux_llm import FauxLLM

from mas.agents import AnalyseReleve
from mas.anonymisation import Anonymiseur, Coffre
from mas.cli import UneFoisParMessage
from mas.ingestion import lire_pdf


def _message(texte, niveau=logging.WARNING, nom="presidio-analyzer"):
    return logging.LogRecord(nom, niveau, __file__, 1, texte, None, None)


def test_chaque_message_passe_une_seule_fois():
    filtre = UneFoisParMessage()
    assert filtre.filter(_message("Entity MISC is not mapped"))
    assert not filtre.filter(_message("Entity MISC is not mapped"))
    assert not filtre.filter(_message("Entity MISC is not mapped"))
    assert filtre.filter(_message("autre message"))
    assert filtre.filter(_message("Entity MISC is not mapped", logging.INFO))   # autre niveau : distinct
    assert filtre.repetitions() == [("Entity MISC is not mapped", 2)]


def test_anonymisation_sans_avertissement_presidio(config, releves, caplog):
    """Ni « Entity MISC is not mapped » ni « Recognizer not added to registry »."""
    anonymiseur = Anonymiseur(config.anonymisation, Coffre(None))
    with caplog.at_level(logging.WARNING, logger="presidio-analyzer"):
        for page in lire_pdf(releves[0]).pages:
            anonymiseur.anonymiser(page.texte)
    assert [r.getMessage() for r in caplog.records if r.name == "presidio-analyzer"] == []


def test_avancement_de_l_analyse(jeu_anonymise, caplog):
    pages = jeu_anonymise[0]["pages"]
    with dspy.context(lm=FauxLLM()), caplog.at_level(logging.INFO, logger="mas.progression"):
        AnalyseReleve()(pages=pages)
    messages = [r.getMessage() for r in caplog.records if r.name == "mas.progression"]
    for etape in ["[1/5] Extraction", "[2/5] Catégorisation", "[3/5] Dépenses récurrentes", "[4/5] Classement"]:
        assert any(m.startswith(etape) for m in messages), etape
    assert any(m.startswith(f"  Page 1/{len(pages)} : extraction") for m in messages)
    # le faux LLM oublie une ligne au premier essai : la correction doit être annoncée
    assert any("correction 1/2" in m for m in messages)
    assert any(m.startswith("  → ") and "opération(s) extraite(s)" in m for m in messages)
