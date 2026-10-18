"""Validations mathématiques (clés de contrôle) pour limiter les faux positifs."""

from __future__ import annotations

import re


def chiffres(texte: str) -> str:
    return re.sub(r"\D", "", texte)


def luhn_valide(numero: str) -> bool:
    nums = chiffres(numero)
    if not 13 <= len(nums) <= 19:
        return False
    total = 0
    for i, c in enumerate(reversed(nums)):
        d = int(c)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def iban_valide(iban: str) -> bool:
    iban = re.sub(r"\s", "", iban).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", iban):
        return False
    reorg = iban[4:] + iban[:4]
    converti = "".join(str(int(c, 36)) for c in reorg)
    return int(converti) % 97 == 1


def rib_valide(banque: str, guichet: str, compte: str, cle: str) -> bool:
    """Clé RIB : 97 - ((89*banque + 15*guichet + 3*compte) mod 97)."""
    table = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "12345678912345678923456789")
    try:
        b, g = int(banque), int(guichet)
        c = int(compte.upper().translate(table))
        return 97 - ((89 * b + 15 * g + 3 * c) % 97) == int(cle)
    except ValueError:
        return False


def nir_valide(nir: str) -> bool:
    nir = re.sub(r"\s", "", nir).upper().replace("2A", "19").replace("2B", "18")
    if not re.fullmatch(r"[12]\d{14}", nir):
        return False
    return 97 - (int(nir[:13]) % 97) == int(nir[13:])
