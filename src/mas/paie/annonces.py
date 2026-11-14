"""Ce que l'entreprise t'a annoncé, comparé à ce qui est arrivé sur tes bulletins.

Les annonces viennent de config.yaml (`paie.annonces`), une par ligne :

    - mois: 2026-01
      augmentation: 0.5          # en %, sur le salaire de base, à partir de ce mois
    - mois: 2025-01
      salaire_base: 3520.75      # le salaire de base mensuel annoncé à partir de ce mois
    - annee: 2026
      ligne: perf                # un mot du libellé de la ligne (« Remu perf contract »)
      montant: 3500
    - annee: 2026
      remuneration_annuelle: 46000   # brut annuel annoncé, hors frais remboursés

Une hausse annoncée en janvier mais versée en avril avec un rappel des trois premiers mois est conforme.
"""
from __future__ import annotations

from .analyses import augmentations, mois_entre, mois_plus, remuneration
from .format import eur, mois_lisible, pct
from .modeles import Bulletin
from .natures import normaliser


def _mois(v) -> str:
    texte = str(v)
    return texte if len(texte) == 7 else f"{texte[:4]}-{int(texte[5:]):02d}"


def _hausse(bulletins: list[Bulletin], depuis: str, attendu: float, quoi: str) -> dict:
    par_mois = {b.mois: b for b in bulletins}
    apres = [b for b in bulletins if b.mois >= depuis]
    if not apres:
        return {"annonce": quoi, "constat": "pas encore de bulletin pour ce mois", "statut": "attente"}
    atteint = next((b for b in apres if b.base >= attendu - 0.5), None)
    if atteint is None:
        return {"annonce": quoi, "constat": f"salaire de base de {eur(apres[-1].base)} en {mois_lisible(apres[-1].mois)}",
                "statut": "ecart"}
    retard = mois_entre(depuis, atteint.mois)
    if not retard:
        return {"annonce": quoi, "constat": f"{eur(atteint.base)} dès {mois_lisible(atteint.mois)}", "statut": "conforme"}
    aug = next((a for a in augmentations(bulletins) if a["mois"] == atteint.mois), None)
    if aug and aug["effet"] <= depuis:
        return {"annonce": quoi, "constat": f"{eur(atteint.base)} versés à partir de {mois_lisible(atteint.mois)}, avec un "
                f"rappel de {eur(aug['rappel'])} pour les mois d'avant ({mois_lisible(aug['mois_rappel'])})", "statut": "conforme"}
    manque = sum(max(0.0, attendu - par_mois[m].base) for m in par_mois if depuis <= m < atteint.mois)
    return {"annonce": quoi, "constat": f"appliqué en {mois_lisible(atteint.mois)} seulement, sans rappel : il manque "
            f"environ {eur(manque)} pour les {retard} mois d'avant", "statut": "ecart"}


def verifier(bulletins: list[Bulletin], annonces: list[dict]) -> list[dict]:
    res = []
    par_mois = {b.mois: b for b in bulletins}
    for a in annonces or []:
        if "mois" in a and ("augmentation" in a or "salaire_base" in a):
            depuis = _mois(a["mois"])
            avant = par_mois.get(mois_plus(depuis, -1))
            if "salaire_base" in a:
                attendu = float(a["salaire_base"])
                quoi = f"salaire de base de {eur(attendu)} à partir de {mois_lisible(depuis)}"
            elif avant is None:
                res.append({"annonce": f"augmentation de {pct(float(a['augmentation']))} en {mois_lisible(depuis)}",
                            "constat": "pas de bulletin du mois d'avant pour la mesurer", "statut": "attente"})
                continue
            else:
                attendu = round(avant.base * (1 + float(a["augmentation"]) / 100), 2)
                quoi = (f"augmentation de {pct(float(a['augmentation']))} en {mois_lisible(depuis)}, soit {eur(attendu)} "
                        "de salaire de base")
            res.append(_hausse(bulletins, depuis, attendu, quoi))
        elif "annee" in a and "ligne" in a:
            an, mot, attendu = int(a["annee"]), normaliser(str(a["ligne"])), float(a["montant"])
            lignes = [(b.mois, l) for b in bulletins if b.annee == an for l in b.lignes if mot in normaliser(l.libelle)]
            verse = round(sum(l.montant for _, l in lignes), 2)
            quoi = f"« {a['ligne']} » de {eur(attendu)} en {an}"
            if not lignes:
                res.append({"annonce": quoi, "constat": "pas encore versée", "statut": "attente"})
            else:
                quand = ", ".join(sorted({mois_lisible(m) for m, _ in lignes}))
                res.append({"annonce": quoi, "constat": f"{eur(verse)} versés ({quand})",
                            "statut": "conforme" if abs(verse - attendu) < 1 else "ecart"})
        elif "annee" in a and "remuneration_annuelle" in a:
            an, attendu = int(a["annee"]), float(a["remuneration_annuelle"])
            mois = [b for b in bulletins if b.annee == an]
            verse = round(sum(remuneration(b) for b in mois), 2)
            quoi = f"rémunération annuelle de {eur(attendu, 0)} en {an}"
            if len(mois) < 12:
                res.append({"annonce": quoi, "constat": f"{eur(verse, 0)} sur {len(mois)} mois : l'année n'est pas finie",
                            "statut": "attente"})
            else:
                res.append({"annonce": quoi, "constat": f"{eur(verse, 0)} versés",
                            "statut": "conforme" if verse >= attendu - 1 else "ecart"})
        else:
            res.append({"annonce": str(a), "constat": "annonce non comprise : voir le modèle dans config.example.yaml",
                        "statut": "attente"})
    return res
