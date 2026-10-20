"""Suivi d'une analyse : durées lisibles, tokens consommés et coût estimé par modèle.

Les tokens viennent du compteur de DSPy (`dspy.track_usage`), qui ne compte que les appels
réellement facturés (pas les réponses servies par son cache). Le coût est estimé avec les
tarifs publics connus de LiteLLM ; la console du fournisseur fait foi.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# Une ligne par modèle et par analyse : date, modèle, appels, tokens, coût. Jamais de données des
# relevés. Lu par Muninn (projets/muninn) pour afficher le coût de l'IA.
JOURNAL_IA = Path(os.environ.get("MAS_JOURNAL_IA", "~/.mas/ia-usage.jsonl")).expanduser()


def duree_lisible(secondes: float) -> str:
    s = int(round(secondes))
    if s < 60:
        return f"{s} s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m} min {s:02d} s"
    h, m = divmod(m, 60)
    return f"{h} h {m:02d} min"


def nombre_lisible(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def montant_lisible(usd: float) -> str:
    return (f"{usd:.3f}" if usd < 1 else f"{usd:.2f}").replace(".", ",") + " $"


@dataclass
class ConsoModele:
    modele: str
    appels: int
    tokens_entree: int
    tokens_sortie: int
    cout_usd: float | None          # None : tarif inconnu de LiteLLM


def estimer_cout(modele: str, tokens_entree: int, tokens_sortie: int) -> float | None:
    try:
        import litellm

        litellm.suppress_debug_info = True      # pas de bandeau « Provider List » pour un modèle inconnu
        cout_entree, cout_sortie = litellm.cost_per_token(
            model=modele, prompt_tokens=tokens_entree, completion_tokens=tokens_sortie
        )
        return float(cout_entree + cout_sortie)
    except Exception:
        return None


def consommation(usage_par_modele: dict[str, list[dict]]) -> list[ConsoModele]:
    """À partir de `UsageTracker.usage_data` : une entrée par appel facturé, par modèle."""
    lignes = []
    for modele, appels in usage_par_modele.items():
        entree = sum(int(a.get("prompt_tokens") or 0) for a in appels)
        sortie = sum(int(a.get("completion_tokens") or 0) for a in appels)
        lignes.append(ConsoModele(modele, len(appels), entree, sortie, estimer_cout(modele, entree, sortie)))
    return lignes


def journaliser(conso: list[ConsoModele], fichier: Path | None = None) -> None:
    """Ajoute la consommation d'une analyse au journal. Une erreur d'écriture n'arrête pas l'analyse."""
    fichier = fichier or JOURNAL_IA
    quand = datetime.now(timezone.utc).isoformat()
    try:
        fichier.parent.mkdir(parents=True, exist_ok=True)
        with fichier.open("a", encoding="utf-8") as f:
            for c in conso:
                f.write(json.dumps({"ts": quand, "modele": c.modele, "appels": c.appels, "entree": c.tokens_entree,
                                    "sortie": c.tokens_sortie, "cout_usd": c.cout_usd}) + "\n")
    except OSError:
        pass
