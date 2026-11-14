"""Les nombres à la française : 1 234,56 €, 3,5 %, « janvier 2026 »."""
from __future__ import annotations

MOIS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
        "novembre", "décembre")
MOIS_COURTS = ("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc.")


def nombre(x: float, decimales: int = 2) -> str:
    texte = f"{abs(x):,.{decimales}f}".replace(",", " ").replace(".", ",")
    return ("−" if x < 0 and round(abs(x), decimales) else "") + texte


def eur(x: float, decimales: int = 2) -> str:
    return f"{nombre(x, decimales)} €"


def signe_eur(x: float, decimales: int = 0) -> str:
    return ("+" if round(x, decimales) > 0 else "") + eur(x, decimales)


def pct(x: float, decimales: int = 1) -> str:
    """x en pour cent (2.4 → « 2,4 % »)."""
    return f"{nombre(x, decimales)} %"


def signe_pct(x: float, decimales: int = 1) -> str:
    return ("+" if round(x, decimales) > 0 else "") + pct(x, decimales)


def mois_lisible(aaaa_mm: str, court: bool = False) -> str:
    noms = MOIS_COURTS if court else MOIS
    return f"{noms[int(aaaa_mm[5:7]) - 1]} {aaaa_mm[:4]}"
