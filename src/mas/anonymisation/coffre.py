"""Coffre de pseudonymisation : valeur réelle <-> pseudonyme, chiffré sur disque.

Le même nom ou IBAN reçoit toujours le même pseudonyme, y compris d'un mois sur
l'autre : c'est indispensable pour détecter un loyer versé chaque mois au même
propriétaire. Le coffre ne quitte jamais la machine.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

LIBELLES = {
    "PERSON": "PERSONNE",
    "FR_CIVILITE_NOM": "PERSONNE",
    "EMAIL_ADDRESS": "EMAIL",
    "PHONE_NUMBER": "TELEPHONE",
    "FR_TELEPHONE": "TELEPHONE",
    "IBAN_CODE": "IBAN",
    "CREDIT_CARD": "CARTE",
    "FR_RIB": "RIB",
    "FR_NIR": "NIR",
    "FR_NUM_COMPTE": "COMPTE",
    "FR_ADRESSE": "ADRESSE",
    "FR_REFERENCE_MANDAT": "REF",
    "DONNEE_PERSO": "PERSO",
}
CIVILITES = {"M", "MR", "MME", "MLLE", "MONSIEUR", "MADAME"}
MOTIF_PSEUDO = re.compile(r"\[([A-Z]+_\d+)\]")


def sans_accents(texte: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texte) if unicodedata.category(c) != "Mn"
    )


def normaliser(libelle: str, valeur: str) -> str:
    v = sans_accents(valeur).upper()
    if libelle == "PERSONNE":
        # "M. DUPONT Jean" et "Jean Dupont" -> même pseudonyme
        mots = [m for m in re.split(r"[\s.\-']+", v) if m and m not in CIVILITES]
        return libelle + ":" + " ".join(sorted(mots))
    if libelle in {"IBAN", "CARTE", "RIB", "NIR", "COMPTE", "TELEPHONE"}:
        v = re.sub(r"[^A-Z0-9]", "", v)
        if libelle == "TELEPHONE":
            v = re.sub(r"^(0033|33)(0)?", "0", v)
        return libelle + ":" + v
    return libelle + ":" + re.sub(r"\s+", " ", v).strip()


class Coffre:
    def __init__(self, chemin: str | Path | None = None):
        """chemin=None : coffre en mémoire uniquement (données synthétiques, tests)."""
        self.chemin = Path(chemin).expanduser() if chemin else None
        self.cles: dict[str, str] = {}
        self.valeurs: dict[str, str] = {}
        self.compteurs: dict[str, int] = {}
        if self.chemin and self.chemin.exists():
            self._charger()

    # --- chiffrement -------------------------------------------------------
    def _fernet(self) -> Fernet:
        cle = os.environ.get("MAS_CLE_COFFRE")
        if not cle:
            fichier = self.chemin.parent / "cle.key"
            if not fichier.exists():
                fichier.parent.mkdir(parents=True, exist_ok=True)
                fichier.write_bytes(Fernet.generate_key())
                fichier.chmod(0o600)
            cle = fichier.read_bytes().decode()
        return Fernet(cle.encode() if isinstance(cle, str) else cle)

    def _charger(self) -> None:
        try:
            brut = self._fernet().decrypt(self.chemin.read_bytes())
        except InvalidToken:
            raise RuntimeError(
                f"Impossible de déchiffrer le coffre {self.chemin} : la clé ne correspond pas. "
                "Vérifie la variable MAS_CLE_COFFRE ou le fichier cle.key à côté du coffre."
            ) from None
        donnees = json.loads(brut)
        self.cles, self.valeurs = donnees["cles"], donnees["valeurs"]
        self.compteurs = donnees["compteurs"]

    def sauvegarder(self) -> None:
        if not self.chemin:
            return
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        brut = json.dumps(
            {"cles": self.cles, "valeurs": self.valeurs, "compteurs": self.compteurs}
        ).encode()
        self.chemin.write_bytes(self._fernet().encrypt(brut))
        self.chemin.chmod(0o600)

    # --- pseudonymisation --------------------------------------------------
    def pseudonyme(self, entite: str, valeur: str) -> str:
        libelle = LIBELLES.get(entite, "PERSO")
        cle = normaliser(libelle, valeur)
        if cle not in self.cles:
            self.compteurs[libelle] = self.compteurs.get(libelle, 0) + 1
            jeton = f"{libelle}_{self.compteurs[libelle]}"
            self.cles[cle] = jeton
            self.valeurs[jeton] = valeur.strip()
        return f"[{self.cles[cle]}]"

    def valeurs_reelles(self) -> list[str]:
        return list(self.valeurs.values())

    def depseudonymiser(self, texte: str) -> str:
        return MOTIF_PSEUDO.sub(lambda m: self.valeurs.get(m.group(1), m.group(0)), texte)
