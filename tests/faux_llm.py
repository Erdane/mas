"""Faux LLM déterministe pour tester le pipeline DSPy et GEPA sans clé API.

Il lit les entrées formatées par l'adaptateur DSPy et produit des réponses
plausibles : extraction des lignes de tableau, catégorisation par mots-clés,
classement par catégorie. La première tentative d'extraction « oublie » une
ligne pour exercer la boucle de correction du contrôleur.
"""

from __future__ import annotations

import json
import re

from dspy.utils.dummies import DummyLM

REGLES = [
    ("LOYER", "logement"), ("EDF", "energie"), ("ENGIE", "energie"), ("FREE", "telecom"),
    ("BOUYGUES", "telecom"), ("MAIF", "assurance"), ("MUTUELLE", "assurance"),
    ("NAVIGO", "transport"), ("CETELEM", "credit"), ("DGFIP", "impots_taxes"),
    ("NETFLIX", "abonnement"), ("SPOTIFY", "abonnement"), ("BASIC FIT", "abonnement"),
    ("DISNEY", "abonnement"), ("LE MONDE", "abonnement"), ("CARREFOUR", "alimentation"),
    ("LIDL", "alimentation"), ("MONOPRIX", "alimentation"), ("UBER", "restauration"),
    ("BRASSERIE", "restauration"), ("AMAZON", "shopping"), ("DECATHLON", "shopping"),
    ("TOTALENERGIES", "transport"), ("SNCF", "transport"), ("PHARMACIE", "sante"),
    ("RETRAIT", "retrait"), ("SALAIRE", "revenu"), ("COTISATION", "frais_bancaires"),
    ("VIR", "virement_personnel"),
]
NATURES = {"abonnement": "abonnement_optionnel", "alimentation": "courant_variable",
           "restauration": "courant_variable", "shopping": "courant_variable"}


def _champ(contenu: str, nom: str) -> str:
    m = re.search(rf"\[\[ ## {nom} ## \]\]\n(.*?)(?=\n\n\[\[ ## |\n\nRespond |\Z)", contenu, re.S)
    return m.group(1).strip() if m else ""


def _json(contenu: str, nom: str):
    texte = _champ(contenu, nom)
    return json.JSONDecoder().raw_decode(texte)[0] if texte else []


def _montant(s: str) -> float:
    return float(s.replace(" ", "").replace(" ", "").replace(",", "."))


def _categorie(libelle: str) -> str:
    return next((c for k, c in REGLES if k in libelle.upper()), "autre")


class FauxLLM(DummyLM):
    def __init__(self):
        super().__init__([], follow_examples=True)
        self.appels = 0

    def _use_example(self, messages):
        self.appels += 1
        systeme = messages[0]["content"]
        contenu = messages[-1]["content"]

        if "`transactions`" in systeme.split("Your output fields are:")[-1][:300]:
            return self._extraire(contenu)
        if "`categories`" in systeme:
            libelles = _json(contenu, "libelles")
            cats = [{"libelle": l, "categorie": _categorie(l)} for l in libelles]
            return self._formater({"categories": cats})
        if "`classements`" in systeme:
            groupes = _json(contenu, "groupes")
            cl = [{"cle": g["cle"], "nature": NATURES.get(g["categorie"], "obligatoire"),
                   "justification": "règle du faux LLM"} for g in groupes]
            return self._formater({"reasoning": "ok", "classements": cl})
        if "`synthese`" in systeme:
            return self._formater({"synthese": "Synthèse de test."})
        # Appel de réflexion GEPA : renvoie une instruction « améliorée »
        return "```\nInstruction réécrite par le faux LLM de réflexion.\n```"

    def _extraire(self, contenu: str) -> str:
        page = _champ(contenu, "page")
        retour = _champ(contenu, "retour_controleur")
        periode = _champ(contenu, "periode")
        annee = (re.findall(r"\d{4}", periode) or ["2026"])[0]
        transactions = []
        for ligne in page.splitlines():
            m = re.match(r"\| (\d{2})/(\d{2}) \| (.*?) \| ([\d ,]*) \| ([\d ,]*) \|", ligne)
            if not m:
                continue
            jj, mm, lib, debit, credit = m.groups()
            montant = -_montant(debit) if debit.strip() else _montant(credit)
            transactions.append({"date": f"{annee}-{mm}-{jj}", "libelle": lib, "montant": montant})
        if not retour and transactions:
            transactions = transactions[:-1]  # oubli volontaire -> le contrôleur doit le signaler
        return self._formater({"reasoning": "lecture du tableau", "transactions": transactions})

    def _formater(self, champs: dict) -> str:
        return self._format_answer_fields(champs)
