"""Le net annoncé par chaque bulletin contre le virement reçu sur tes relevés, et les mois de prime à venir.

Lit les données de tes bulletins (« mas-paie/1 », voir paie/export.py). Calcul local, sans IA.
"""
from __future__ import annotations

import json
from pathlib import Path

from .export import FORMAT
TOLERANCE_EUR = 1.0         # un virement de salaire arrive au centime ; 1 € d'écart couvre un arrondi
JOURS_DE_RETARD = 10        # un salaire de fin de mois peut arriver au début du mois suivant
NOMS = {"treizieme": "13e mois", "variable": "part variable", "interessement": "intéressement",
        "exceptionnelle": "prime exceptionnelle", "rappel": "rappel d'augmentation"}


def charger_paie(chemin: str | Path | None) -> dict | None:
    """Le contenu de paie.json, ou None (pas de fichier, ou un format inconnu)."""
    if not chemin:
        return None
    p = Path(chemin).expanduser()
    if not p.exists():
        return None
    try:
        donnees = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return None
    return donnees if donnees.get("format") == FORMAT and isinstance(donnees.get("bulletins"), list) else None


def _mois_suivant(aaaa_mm: str) -> str:
    a, m = int(aaaa_mm[:4]), int(aaaa_mm[5:7])
    return f"{a + m // 12}-{m % 12 + 1:02d}"


def rapprocher(paie: dict | None, operations: list[dict], debut: str, fin: str) -> dict | None:
    """Pour chaque bulletin de la période (AAAA-MM), le virement reçu du même montant, à 1 € près : dans le mois du
    bulletin ou les dix premiers jours du suivant. Chaque virement ne sert qu'une fois."""
    if not paie:
        return None
    credits = [o for o in operations if o.get("montant", 0) > 0 and o.get("date")]
    pris: set[int] = set()
    mois = []
    for b in sorted(paie["bulletins"], key=lambda b: b["mois"]):
        m = b["mois"]
        if not (debut <= m <= fin):
            continue
        suivant = _mois_suivant(m)
        candidats = [(abs(o["montant"] - b["net_paye"]), i, o) for i, o in enumerate(credits)
                     if i not in pris and abs(o["montant"] - b["net_paye"]) <= TOLERANCE_EUR
                     and (o["date"][:7] == m or (o["date"][:7] == suivant and int(o["date"][8:10]) <= JOURS_DE_RETARD))]
        if candidats:
            _, i, o = min(candidats, key=lambda c: (c[0], c[1]))
            pris.add(i)
            mois.append({"mois": m, "net_paye": b["net_paye"], "recu": round(o["montant"], 2), "date": o["date"][:10],
                         "ecart": round(o["montant"] - b["net_paye"], 2)})
        else:
            mois.append({"mois": m, "net_paye": b["net_paye"], "recu": None, "date": None, "ecart": None})
    if not mois:
        return None
    a_venir = [{"mois": p["mois"], "net_paye": p["net_paye"], "extras": p.get("extras") or {}}
               for p in paie.get("prevision") or [] if p["mois"] > fin][:6]
    return {"mois": mois, "a_venir": a_venir, "net_ordinaire": paie.get("net_ordinaire"), "cet": paie.get("cet") or {}}


def phrase_extras(extras: dict, eur) -> str:
    return ", ".join(f"{NOMS.get(n, n)} {eur(v, 0)}" for n, v in extras.items())
