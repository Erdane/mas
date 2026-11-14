"""Les données de tes bulletins, en JSON (« mas-paie/1 ») : ce que lisent la page croisée (salaire et budget) et,
plus tard, un tableau de bord. Les libellés y sont déjà anonymisés."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .analyses import remuneration

FORMAT = "mas-paie/1"


def donnees_paie(r: dict) -> dict:
    """`r` : le résultat de paie.analyser (bulletins, calendrier, prévision, impôts…)."""
    bulletins = r["donnees"].emploi
    pa = r.get("pouvoir_achat")
    return {
        "format": FORMAT,
        "genere_le": datetime.now().isoformat(timespec="seconds"),
        "bulletins": [{
            "mois": b.mois, "source": b.source,
            "net_paye": b.net_paye, "net_avant_impot": b.net_avant_impot, "impot": b.impot,
            "taux_impot": b.taux_impot, "cotisations": b.cotisations, "brut": b.brut, "remuneration": remuneration(b),
            "salaire_base": b.base, "cet": round(-b.somme("cet"), 2), "frais": b.somme("frais"),
            "natures": {n: v for n in ("treizieme", "variable", "interessement", "exceptionnelle", "rappel")
                        if (v := b.somme(n))},
        } for b in bulletins],
        "prevision": [{"mois": m["mois"], "net_paye": m["net_paye"], "extras": dict(m["extras"])}
                      for m in (r.get("prevision") or {}).get("mois", [])],
        "habitudes": r["calendrier"].get("habitudes", []),
        "net_ordinaire": r["calendrier"].get("net_ordinaire"),
        "cet": r["cet"],
        "changements_impot": r["impots"]["changements"],
        "par_annee": [{k: v for k, v in a.items() if k != "natures"} for a in r["par_annee"]],
        "pouvoir_achat": {k: v for k, v in pa.items() if k != "serie"} if pa else None,
    }


def ecrire(chemin: Path, donnees: dict) -> Path:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding="utf-8")
    return chemin
