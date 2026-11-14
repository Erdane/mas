"""Pistes d'économie : chaque poste variable comparé aux propres mois de la personne (sans IA)."""
from mas.conseils import pistes_economie, pistes_markdown, quartile_bas
from mas.page import construire_page, donnees_rapport

MOIS = [f"2026-{m:02d}" for m in range(1, 9)]


def _par_mois(**lignes):
    return {"mois": MOIS, "partiels": [], "lignes": [{"categorie": c, "montants": m} for c, m in lignes.items()]}


def test_quartile_bas_comme_numpy():
    assert quartile_bas([10, 20, 30, 40, 50]) == 20
    assert quartile_bas([100, 200, 300, 400]) == 175


def test_objectif_a_mi_chemin_entre_la_moyenne_et_les_mois_sobres():
    # Restaurants : 200 € la plupart des mois, deux mois de vacances à 600 €
    resto = [200, 200, 600, 200, 200, 600, 200, 200]
    p = pistes_economie(_par_mois(restauration=resto, logement=[800] * 8), 2500.0,
                        {"restauration": 300.0, "logement": 800.0}, optionnel=25.0)
    (piste,) = p["pistes"]                      # le logement n'est pas une piste
    assert piste["categorie"] == "restauration" and piste["sobres"] == 200
    assert piste["objectif"] == 250 and piste["economie"] == 50
    assert piste["mois_au_dessus"] == 2 and [c["mois"] for c in piste["plus_chers"]] == ["2026-03", "2026-06"]
    assert p["total"] == 50 and p["abonnements_optionnels"] == 25
    r = p["repartition"]
    assert (r["besoins"]["montant"], r["envies"]["montant"], r["epargne"]["montant"]) == (800, 300, 1400)


def test_poste_regulier_ou_petit_pas_de_piste():
    # Des courses toujours au même niveau : rien à gagner en visant ses mois sobres
    p = pistes_economie(_par_mois(alimentation=[300] * 8, retrait=[20, 0, 40, 0, 20, 0, 40, 0]), 2000.0,
                        {"alimentation": 300.0, "retrait": 15.0})
    assert p["pistes"] == []


def test_pas_assez_de_mois_complets():
    par_mois = _par_mois(shopping=[100, 900, 100, 100, 100, 100, 100, 100])
    par_mois["partiels"] = MOIS[:5]
    assert pistes_economie(par_mois, 2000.0, {"shopping": 200.0}) is None


def test_rapport_texte_et_page():
    resto = [200, 200, 600, 200, 200, 600, 200, 200]
    p = pistes_economie(_par_mois(restauration=resto), 2500.0, {"restauration": 300.0})
    texte = "\n".join(pistes_markdown(p, lambda x: f"{x:.0f} €"))
    assert "| restauration | 300 € | 200 € | 250 € | 50 € | 2026-03 (600 €), 2026-06 (600 €) |" in texte
    assert "envies 12 % (repère 30 %)" in texte
    budget = {"nb_mois": 8, "periode": "2026-01 → 2026-08", "revenus_mensuels": 250.0, "depenses_mensuelles": 300.0,
              "par_categorie": {"restauration": 300.0}, "par_nature": {}, "total_obligatoire": 0.0,
              "total_optionnel": 0.0, "par_mois": _par_mois(restauration=resto)}
    budget["pistes"] = pistes_economie(budget["par_mois"], 250.0, budget["par_categorie"])
    page = construire_page(donnees_rapport(budget, [], "Synthèse."))
    assert "Où économiser" in page and "−50 €" in page and "Objectif : <strong>250 €</strong>" in page
    assert "dépassent tes revenus de 50\u00a0€ par mois en moyenne : ces pistes couvriraient ce manque." in page
    budget["revenus_mensuels"] = 200.0                  # manque de 100 € : la moitié seulement
    assert "ces pistes en couvriraient 50\u00a0%." in construire_page(donnees_rapport(budget, [], "Synthèse."))
    assert page.count('class="au-dessus"') == 2 and "mars 2026 (600 €) et juin 2026 (600 €)" in page


def test_ancien_rapport_sans_pistes_les_recalcule():
    budget = {"nb_mois": 8, "periode": "2026-01 → 2026-08", "revenus_mensuels": 2500.0, "depenses_mensuelles": 300.0,
              "par_categorie": {"restauration": 300.0}, "par_nature": {}, "total_obligatoire": 0.0,
              "total_optionnel": 0.0, "par_mois": _par_mois(restauration=[200, 200, 600, 200, 200, 600, 200, 200])}
    donnees = donnees_rapport(budget, [], "Synthèse.")
    del donnees["pistes"]
    assert "Où économiser" in construire_page(donnees)
