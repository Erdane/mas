"""Suivi d'une analyse : durées, tokens et coût estimé (sans réseau)."""
from mas.suivi import consommation, duree_lisible, estimer_cout, montant_lisible, nombre_lisible

HAIKU = "anthropic/claude-haiku-4-5-20251001"


def test_formats_lisibles():
    assert duree_lisible(4.6) == "5 s"
    assert duree_lisible(92) == "1 min 32 s"
    assert duree_lisible(3700) == "1 h 01 min"
    assert nombre_lisible(61240) == "61 240"
    assert montant_lisible(0.1534) == "0,153 $" and montant_lisible(12.5) == "12,50 $"


def test_consommation_par_modele():
    appels = [{"prompt_tokens": 1200, "completion_tokens": 300},
              {"prompt_tokens": 800, "completion_tokens": 200}]
    (c,) = consommation({HAIKU: appels})
    assert (c.appels, c.tokens_entree, c.tokens_sortie) == (2, 2000, 500)
    # tarif Haiku 4.5 : 1 $ / M tokens en entrée, 5 $ / M en sortie
    assert abs(c.cout_usd - (2000 * 1e-6 + 500 * 5e-6)) < 1e-9


def test_modele_inconnu_sans_tarif():
    assert estimer_cout("inconnu/modele-x", 10, 10) is None
    assert consommation({"inconnu/modele-x": [{"prompt_tokens": 5}]})[0].cout_usd is None
