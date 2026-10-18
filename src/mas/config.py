"""Chargement de la configuration YAML en objets typés."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class ConfigLLM(BaseModel):
    modele: str = "mistral/mistral-small-latest"
    temperature: float | None = 0.0    # None = non envoyée (Claude Sonnet/Opus 5.5 la refusent)
    max_tokens: int = 8000


class Identite(BaseModel):
    noms: list[str] = Field(default_factory=list)
    adresses: list[str] = Field(default_factory=list)
    ibans: list[str] = Field(default_factory=list)
    numeros_compte: list[str] = Field(default_factory=list)
    telephones: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)
    autres: list[str] = Field(default_factory=list)

    def termes(self) -> list[tuple[str, str]]:
        """(valeur, type d'entité) pour chaque donnée personnelle déclarée."""
        paires = []
        for champ, entite in [
            ("noms", "PERSON"),
            ("adresses", "FR_ADRESSE"),
            ("ibans", "IBAN_CODE"),
            ("numeros_compte", "FR_NUM_COMPTE"),
            ("telephones", "FR_TELEPHONE"),
            ("emails", "EMAIL_ADDRESS"),
            ("autres", "DONNEE_PERSO"),
        ]:
            for valeur in getattr(self, champ):
                if valeur and valeur.strip():
                    paires.append((valeur.strip(), entite))
                    # Variante "NOM PRENOM" pour les noms, fréquente sur les relevés
                    if champ == "noms" and " " in valeur.strip():
                        mots = valeur.split()
                        paires.append((" ".join(reversed(mots)), entite))
        return paires


class ConfigGliner(BaseModel):
    actif: bool = False
    modele: str = "urchade/gliner_multi_pii-v1"
    seuil: float = 0.5


class ConfigAnonymisation(BaseModel):
    modele_spacy: str = "fr_core_news_md"
    seuil_score: float = 0.5
    entites: list[str] = Field(
        default_factory=lambda: [
            "PERSON", "EMAIL_ADDRESS", "IBAN_CODE", "CREDIT_CARD",
            "FR_TELEPHONE", "FR_RIB", "FR_NIR", "FR_NUM_COMPTE", "FR_ADRESSE",
            "FR_CIVILITE_NOM", "FR_REFERENCE_MANDAT",
        ]
    )
    liste_blanche: list[str] = Field(default_factory=list)
    gliner: ConfigGliner = Field(default_factory=ConfigGliner)


class ConfigLLMLocal(BaseModel):
    actif: bool = False
    modele: str = "ollama_chat/qwen2.5:3b"
    api_base: str = "http://localhost:11434"


class ConfigVerification(BaseModel):
    iterations_max: int = 3
    llm_local: ConfigLLMLocal = Field(default_factory=ConfigLLMLocal)


class ConfigCoffre(BaseModel):
    chemin: str = "~/.mas/coffre.bin"


class ConfigRecurrence(BaseModel):
    occurrences_min: int = 3
    tolerance_intervalle: float = 0.25
    tolerance_montant: float = 0.30


class ConfigOptimisation(BaseModel):
    modele_reflexion: str = "mistral/mistral-large-latest"
    temperature_reflexion: float | None = 1.0   # None = non envoyée (Claude Opus 5.5 la refuse)
    n_train: int = 24
    n_val: int = 12
    auto: str = "light"
    dossier_donnees: str = "donnees/synthetiques"
    dossier_logs: str = "artefacts/gepa_logs"
    programme_optimise: str = "artefacts/programme_optimise.json"
    threads: int = 4


class ConfigAnalyse(BaseModel):
    """Ce qui compte comme dépense. L'argent qui ne fait que changer de compte (vers tes livrets,
    vers tes autres comptes) est montré à part, pas comme une dépense."""
    # Virements vers un bénéficiaire qui porte ton nom (identite.noms) : « transfert » = mis à part
    # comme un mouvement entre tes comptes ; « depense » = compté comme une dépense (homonyme, proche…)
    virements_a_ton_nom: Literal["transfert", "depense"] = "transfert"
    # Tes comptes dans d'autres banques (IBAN, code BIC, nom de la banque…) : les virements qui les
    # mentionnent sont mis à part, sans déduction sur le nom du bénéficiaire
    comptes_personnels: list[str] = Field(default_factory=list)
    # Virements à des proches : « depense » (par défaut) ou « a_part » (montrés à part)
    virements_a_des_proches: Literal["depense", "a_part"] = "depense"
    # Loyer payé à un particulier sans le mot « loyer » : virements presque tous les mois vers une
    # même personne, d'un montant stable d'au moins loyer_montant_min € → comptés dans Logement
    loyers_sans_libelle: Literal["detecter", "non"] = "detecter"
    loyer_montant_min: float = 300.0


class Config(BaseModel):
    llm: ConfigLLM = Field(default_factory=ConfigLLM)
    analyse: ConfigAnalyse = Field(default_factory=ConfigAnalyse)
    identite: Identite = Field(default_factory=Identite)
    anonymisation: ConfigAnonymisation = Field(default_factory=ConfigAnonymisation)
    verification: ConfigVerification = Field(default_factory=ConfigVerification)
    coffre: ConfigCoffre = Field(default_factory=ConfigCoffre)
    recurrence: ConfigRecurrence = Field(default_factory=ConfigRecurrence)
    optimisation: ConfigOptimisation = Field(default_factory=ConfigOptimisation)


def charger_config(chemin: str | Path | None = None) -> Config:
    """Charge config.yaml (ou le chemin fourni). Sans fichier : valeurs par défaut."""
    candidats = [Path(chemin)] if chemin else [Path("config.yaml")]
    for c in candidats:
        if c.exists():
            donnees = yaml.safe_load(c.read_text(encoding="utf-8")) or {}
            return Config.model_validate(donnees)
    if chemin:
        raise FileNotFoundError(f"Configuration introuvable : {chemin}")
    return Config()
