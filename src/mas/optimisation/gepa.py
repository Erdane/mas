"""Boucle d'optimisation GEPA des agents d'analyse.

    ┌────────────────────────────────────────────────────────────┐
    │ relevés synthétiques ─► anonymisation ─► programme DSPy     │
    │        ▲                                      │             │
    │        │                                      ▼             │
    │  nouvelles instructions ◄── LLM de réflexion ◄── métrique   │
    │  (par prédicteur)          (lit le feedback)   + feedback   │
    └────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import dspy

from ..agents import AnalyseReleve, configurer_lm
from ..config import Config
from .donnees import construire_jeux
from .metrique import metrique_gepa, metrique_score

log = logging.getLogger("mas")


def evaluer(programme: dspy.Module, jeu: list, threads: int = 4) -> float:
    evaluation = dspy.Evaluate(
        devset=jeu, metric=metrique_score, num_threads=threads,
        display_progress=True, provide_traceback=True,
    )
    resultat = evaluation(programme)
    score = resultat.score if hasattr(resultat, "score") else resultat
    return float(score)


def optimiser(config: Config, regenerer: bool = False) -> dict:
    opt = config.optimisation
    configurer_lm(config.llm)
    reflexion = dspy.LM(opt.modele_reflexion, temperature=opt.temperature_reflexion, max_tokens=32000)

    train, val = construire_jeux(config, regenerer=regenerer)
    log.info("Jeux : %d entraînement, %d validation", len(train), len(val))

    programme = AnalyseReleve(config.recurrence)
    score_initial = evaluer(programme, val, opt.threads)
    log.info("Score initial sur la validation : %.2f", score_initial)

    gepa = dspy.GEPA(
        metric=metrique_gepa,
        auto=opt.auto,
        reflection_lm=reflexion,
        reflection_minibatch_size=3,
        candidate_selection_strategy="pareto",
        use_merge=True,
        num_threads=opt.threads,
        log_dir=opt.dossier_logs,
        track_stats=True,
    )
    optimise = gepa.compile(programme, trainset=train, valset=val)

    score_final = evaluer(optimise, val, opt.threads)
    log.info("Score optimisé sur la validation : %.2f", score_final)

    chemin = Path(opt.programme_optimise)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    optimise.save(str(chemin))

    instructions = {
        nom: predicteur.signature.instructions for nom, predicteur in optimise.named_predictors()
    }
    (chemin.parent / "instructions_optimisees.json").write_text(
        json.dumps(instructions, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "score_initial": score_initial,
        "score_final": score_final,
        "programme": str(chemin),
        "instructions": instructions,
    }
