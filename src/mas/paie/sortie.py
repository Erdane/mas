"""Les pages des bulletins, posées à côté du rapport de budget et reliées à lui par un menu commun :

    rapport_X.html          ton budget (rapport_X_anonyme.html : sa version anonyme)
    rapport_X_paie.html     tes fiches de paie (rapport_X_paie.json : leurs données)
    rapport_X_croise.html   ton salaire et ton budget

Sans rapport de budget, la page des bulletins seule : rapports/fiches_de_paie_AAAA-MM-JJ_HHMM.html.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..navigation import ajouter_navigation, navigation
from .chargement import analyser
from .croise import construire_page as page_croisee
from .croise import croiser
from .export import donnees_paie, ecrire
from .page import construire_page as page_paie


def fichiers(base: Path) -> dict[str, Path]:
    return {"budget": base.with_suffix(".html"), "budget_anonyme": base.with_name(base.name + "_anonyme.html"),
            "paie": base.with_name(base.name + "_paie.html"), "croise": base.with_name(base.name + "_croise.html")}


def relier(base: Path) -> list[Path]:
    """Pose le menu commun dans chaque page du rapport qui existe. Une page de budget renvoie à elle-même (la
    version personnelle reste personnelle, l'anonyme reste anonyme) ; les autres, à la version personnelle si elle
    existe."""
    f = {k: p for k, p in fichiers(base).items() if p.exists()}
    budget = f.get("budget") or f.get("budget_anonyme")
    autres = {k: f[k].name for k in ("paie", "croise") if k in f}
    for cle, page in f.items():
        liens = dict(autres)
        if cle.startswith("budget"):
            liens["budget"] = page.name
        elif budget:
            liens["budget"] = budget.name
        actif = "budget" if cle.startswith("budget") else cle
        page.write_text(ajouter_navigation(page.read_text(encoding="utf-8"), navigation(actif, liens)), encoding="utf-8")
    return list(f.values())


def dernier_budget(dossier: Path) -> Path | None:
    """Le rapport de budget le plus récent du dossier (son JSON de données)."""
    candidats = [p for p in dossier.glob("rapport_*.json") if not p.stem.endswith(("_paie",))]
    return max(candidats, key=lambda p: p.stat().st_mtime) if candidats else None


def ecrire_pages(config, coffre, budget_json: Path | None = None, dossier: Path = Path("rapports"),
                 rafraichir_prix: bool | None = None, progression=None) -> dict | None:
    """Lit les bulletins, écrit leur page et leurs données ; avec un rapport de budget, la page croisée aussi, et
    relie les pages. Renvoie {pages, analyse, croise} ; None sans bulletin."""
    r = analyser(config, coffre, rafraichir_prix, progression)
    if r is None:
        return None
    donnees = donnees_paie(r)
    dossier.mkdir(parents=True, exist_ok=True)
    if budget_json is None:
        base = dossier / f"fiches_de_paie_{datetime.now():%Y-%m-%d_%H%M}"
        page = base.with_suffix(".html")
        page.write_text(page_paie(r), encoding="utf-8")
        ecrire(base.with_suffix(".json"), donnees)
        return {"pages": {"paie": page}, "analyse": r, "croise": None}
    base = budget_json.with_suffix("")
    f = fichiers(base)
    f["paie"].write_text(page_paie(r), encoding="utf-8")
    ecrire(base.with_name(base.name + "_paie.json"), donnees)
    c = croiser(json.loads(budget_json.read_text(encoding="utf-8")), donnees)
    if c:
        f["croise"].write_text(page_croisee(c), encoding="utf-8")
    elif f["croise"].exists():
        f["croise"].unlink()                     # plus aucun mois en commun : l'ancienne page ne vaut plus
    relier(base)
    return {"pages": {k: p for k, p in f.items() if p.exists()}, "analyse": r, "croise": c}
