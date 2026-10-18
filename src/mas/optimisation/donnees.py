"""Construction des jeux d'entraînement / validation pour GEPA.

Les relevés synthétiques passent par le VRAI pipeline d'anonymisation : les
agents apprennent donc sur des textes pseudonymisés identiques à ceux qu'ils
verront en production, sans qu'aucune donnée réelle ne soit utilisée.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import dspy

from ..anonymisation import Coffre
from ..config import Config
from ..orchestrateur import Orchestrateur
from ..synthetique import charger_verite, generer_jeu

log = logging.getLogger("mas")


def _anonymiser_releve(config: Config, pdf: Path) -> dict:
    verite = charger_verite(pdf)
    ident = verite["identite"]
    cfg = config.model_copy(deep=True)
    cfg.identite.noms = [ident["nom"]]
    cfg.identite.adresses = [ident["adresse"]]
    cfg.identite.ibans = [ident["iban"]]
    orchestrateur = Orchestrateur(cfg, Coffre(None))  # coffre éphémère
    docs = orchestrateur.charger_documents(pdf)
    pages = [p for d in docs for p in d.pages]
    texte = " ".join(pages).lower()
    restantes = [pii for pii in verite["pii"] if pii.lower() in texte]
    if restantes:
        raise RuntimeError(f"{pdf.name} : l'anonymisation laisse passer {restantes}")
    return {
        "nom": pdf.name,
        "pages": pages,
        "transactions": verite["transactions"],
        "recurrents": verite["recurrents"],
        "pii": verite["pii"],
    }


def construire_jeux(config: Config, regenerer: bool = False) -> tuple[list, list]:
    opt = config.optimisation
    dossier = Path(opt.dossier_donnees)
    cache = dossier / "jeu_anonymise.jsonl"
    total = opt.n_train + opt.n_val

    if regenerer or not cache.exists() or sum(1 for _ in cache.open()) < total:
        log.info("Génération de %d relevés synthétiques dans %s", total, dossier)
        pdfs = generer_jeu(dossier, total)
        with cache.open("w", encoding="utf-8") as f:
            for pdf in pdfs:
                f.write(json.dumps(_anonymiser_releve(config, pdf), ensure_ascii=False) + "\n")

    exemples = []
    with cache.open(encoding="utf-8") as f:
        for ligne in list(f)[:total]:
            d = json.loads(ligne)
            exemples.append(
                dspy.Example(
                    pages=d["pages"], transactions=d["transactions"],
                    recurrents=d["recurrents"], pii=d["pii"], nom=d["nom"],
                ).with_inputs("pages")
            )
    return exemples[: opt.n_train], exemples[opt.n_train:]
