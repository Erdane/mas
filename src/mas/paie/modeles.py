"""Un bulletin de paie, qu'il vienne de ton classeur Excel ou du PDF de ton employeur."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Ligne:
    libelle: str
    montant: float              # part salariale : positif, un gain ; négatif, une retenue
    nature: str = "autre"       # voir natures.NATURES
    code: str = ""              # code de rubrique du bulletin PDF (« 001 », « 34C »…), vide pour l'Excel


@dataclass
class Bulletin:
    mois: str                   # AAAA-MM
    lignes: list[Ligne]
    cotisations: float          # total des cotisations et contributions salariales (nombre positif)
    net_avant_impot: float      # net à payer avant impôt sur le revenu
    impot: float                # prélèvement à la source
    source: str                 # excel | pdf
    net_imposable: float | None = None
    taux_pas: float | None = None       # en %, lu sur le bulletin
    net_social: float | None = None
    brut_bulletin: float | None = None  # le « montant brut » imprimé sur le bulletin
    fichier: str | None = None
    retenues_apres_net: list[Ligne] = field(default_factory=list)   # PDF : lignes après le net social
    taux_neutre: bool = False   # PDF : prélèvement au taux non personnalisé (grille de l'administration)

    @property
    def annee(self) -> int:
        return int(self.mois[:4])

    @property
    def net_paye(self) -> float:
        return round(self.net_avant_impot - self.impot, 2)

    def somme(self, *natures: str) -> float:
        return round(sum(l.montant for l in self.lignes if l.nature in natures), 2)

    @property
    def base(self) -> float:
        return self.somme("base")

    @property
    def brut(self) -> float:
        """Tout ce qui est versé avant cotisations, frais remboursés compris (les retenues comme le CET en moins)."""
        return round(sum(l.montant for l in self.lignes), 2)

    @property
    def taux_impot(self) -> float | None:
        """Le taux du prélèvement à la source : celui du bulletin, sinon impôt / net avant impôt hors frais."""
        if self.taux_pas is not None:
            return self.taux_pas
        assiette = self.net_avant_impot - self.somme("frais")
        return round(100 * self.impot / assiette, 2) if assiette > 0 else None

    @property
    def ecart(self) -> float:
        """Net avant impôt − (lignes − cotisations) : zéro quand toutes les lignes du bulletin sont là."""
        return round(self.net_avant_impot - (self.brut - self.cotisations), 2)
