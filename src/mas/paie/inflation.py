"""L'indice des prix à la consommation de l'INSEE (ensemble des ménages, France, base 2025), mois par mois.

Téléchargé depuis le service public de l'INSEE (aucune donnée de ta paie n'est envoyée : l'adresse est la même pour
tout le monde), puis gardé dans ~/.mas/ipc.json : mas ne le redemande qu'une fois par semaine.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from pathlib import Path

SERIE = "011814630"     # IPC - Base 2025 - Ensemble des ménages - France - Ensemble
URL = f"https://bdm.insee.fr/series/sdmx/data/SERIES_BDM/{SERIE}?startPeriod=2015-01"
SEMAINE = 7 * 24 * 3600


def telecharger(url: str = URL, delai: float = 30) -> dict[str, float]:
    requete = urllib.request.Request(url, headers={"User-Agent": "mas"})
    with urllib.request.urlopen(requete, timeout=delai) as reponse:
        xml = reponse.read().decode("utf-8")
    return {m: float(v) for m, v in re.findall(r'TIME_PERIOD="(\d{4}-\d{2})" OBS_VALUE="([\d.]+)"', xml)}


def indices(cache: Path | str, rafraichir: bool | None = None) -> tuple[dict[str, float], str]:
    """(indice par mois AAAA-MM, d'où il vient). Sans réseau, le cache sert tel quel ; sans cache ni réseau,
    un dictionnaire vide : les comparaisons au coût de la vie ne s'affichent pas."""
    cache = Path(cache)
    contenu = {}
    if cache.exists():
        try:
            contenu = json.loads(cache.read_text())
        except ValueError:
            contenu = {}
    vieux = time.time() - contenu.get("le", 0) > SEMAINE
    if rafraichir or (rafraichir is None and vieux):
        try:
            serie = telecharger()
            if serie:
                contenu = {"le": time.time(), "serie": SERIE, "indices": dict(sorted(serie.items()))}
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(contenu, indent=0))
        except OSError:
            pass
    serie = contenu.get("indices") or {}
    if not serie:
        return {}, "indisponible"
    derniere = max(serie)
    return serie, f"INSEE, indice des prix à la consommation (série {SERIE}), jusqu'à {derniere}"


def indice_au(serie: dict[str, float], mois: str) -> float | None:
    """L'indice du mois, sinon le dernier connu avant lui (les prix du mois en cours ne sont pas encore publiés)."""
    if mois in serie:
        return serie[mois]
    avant = [m for m in serie if m <= mois]
    return serie[max(avant)] if avant else None
