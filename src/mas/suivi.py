"""Suivi d'une analyse : durées lisibles, tokens consommés et coût estimé par modèle.

Les tokens viennent du compteur de DSPy (`dspy.track_usage`), qui ne compte que les appels
réellement facturés (pas les réponses servies par son cache). Le coût est estimé avec les
tarifs publics connus de LiteLLM ; la console du fournisseur fait foi.
"""

from __future__ import annotations

from dataclasses import dataclass


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
