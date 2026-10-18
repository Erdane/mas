"""Générateur de relevés bancaires synthétiques avec vérité terrain.

Sert à entraîner et évaluer les agents (GEPA) sans jamais exposer de vraies
données au LLM : chaque relevé est accompagné d'un JSON qui liste les
transactions, leurs catégories, les dépenses récurrentes et toutes les données
personnelles qui doivent disparaître.
"""

from __future__ import annotations

import json
import random
from calendar import monthrange
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from faker import Faker

MOIS_FR = ["", "JANVIER", "FEVRIER", "MARS", "AVRIL", "MAI", "JUIN", "JUILLET", "AOUT",
           "SEPTEMBRE", "OCTOBRE", "NOVEMBRE", "DECEMBRE"]

# (motif de reconnaissance, gabarit de libellé, catégorie, nature, montant, variabilité, jour)
RECURRENTS = [
    ("LOYER", "VIR SEPA PERMANENT M {bailleur} LOYER", "logement", "obligatoire", (550, 1200), 0.0, 3),
    ("EDF", "PRLV SEPA EDF CLIENTS PARTICULIERS RUM {rum}", "energie", "obligatoire", (45, 130), 0.12, 8),
    ("ENGIE", "PRLV SEPA ENGIE GAZ ECHEANCE {ref}", "energie", "obligatoire", (30, 90), 0.0, 12),
    ("FREE MOBILE", "PRLV SEPA FREE MOBILE {ref}", "telecom", "obligatoire", (9.99, 19.99), 0.0, 6),
    ("BOUYGUES", "PRLV SEPA BOUYGUES TELECOM BBOX {ref}", "telecom", "obligatoire", (24.99, 39.99), 0.0, 15),
    ("MAIF", "PRLV SEPA MAIF ASSURANCE HABITATION {ref}", "assurance", "obligatoire", (14, 38), 0.0, 10),
    ("MUTUELLE", "PRLV SEPA HARMONIE MUTUELLE COTISATION", "assurance", "obligatoire", (35, 90), 0.0, 5),
    ("NAVIGO", "PRLV SEPA COMUTITRES NAVIGO MOIS", "transport", "obligatoire", (88.8, 88.8), 0.0, 2),
    ("CETELEM", "PRLV SEPA CETELEM ECHEANCE PRET {ref}", "credit", "obligatoire", (120, 320), 0.0, 20),
    ("DGFIP", "PRLV SEPA DGFIP IMPOT MENSUALISATION {ref}", "impots_taxes", "obligatoire", (40, 160), 0.0, 15),
    ("NETFLIX", "CB NETFLIX.COM {jj}/{mm}", "abonnement", "abonnement_optionnel", (7.99, 19.99), 0.0, 17),
    ("SPOTIFY", "CB SPOTIFY P{ref} {jj}/{mm}", "abonnement", "abonnement_optionnel", (11.12, 11.12), 0.0, 22),
    ("BASIC FIT", "PRLV SEPA BASIC FIT FRANCE {ref}", "abonnement", "abonnement_optionnel", (24.99, 34.99), 0.0, 9),
    ("DISNEY", "CB DISNEY PLUS {jj}/{mm}", "abonnement", "abonnement_optionnel", (5.99, 11.99), 0.0, 25),
    ("LE MONDE", "PRLV SEPA LE MONDE ABONNEMENT", "abonnement", "abonnement_optionnel", (9.99, 21.99), 0.0, 27),
]

VARIABLES = [
    ("CB CARREFOUR {ville} {jj}/{mm}", "alimentation", (15, 140), 5),
    ("CB LIDL {ville} {jj}/{mm}", "alimentation", (12, 90), 3),
    ("CB MONOPRIX {jj}/{mm}", "alimentation", (6, 45), 3),
    ("CB UBER EATS {jj}/{mm}", "restauration", (14, 42), 2),
    ("CB BRASSERIE DU MARCHE {jj}/{mm}", "restauration", (18, 65), 1),
    ("CB AMAZON PAYMENTS {jj}/{mm}", "shopping", (9, 120), 2),
    ("CB DECATHLON {ville} {jj}/{mm}", "shopping", (15, 90), 1),
    ("CB TOTALENERGIES {ville} {jj}/{mm}", "transport", (35, 80), 2),
    ("CB SNCF INTERNET {jj}/{mm}", "transport", (25, 110), 1),
    ("CB PHARMACIE DU CENTRE {jj}/{mm}", "sante", (5, 40), 1),
    ("RETRAIT DAB {ville} {jj}/{mm}", "retrait", (20, 100), 1),
    ("VIR INST A {ami} {motif}", "virement_personnel", (10, 80), 1),
]


@dataclass
class TransactionOr:
    date: str
    libelle: str
    montant: float
    categorie: str


@dataclass
class RecurrentOr:
    motif: str
    categorie: str
    nature: str
    montant_mensuel: float


@dataclass
class ReleveSynthetique:
    identite: dict
    transactions: list[TransactionOr] = field(default_factory=list)
    recurrents: list[RecurrentOr] = field(default_factory=list)
    pii: list[str] = field(default_factory=list)


def _fr(x: float) -> str:
    return f"{x:,.2f}".replace(",", " ").replace(".", ",")


def _ref(rng: random.Random, n: int = 8) -> str:
    return "".join(rng.choice("0123456789") for _ in range(n))


def generer_releve(graine: int, nb_mois: int | None = None) -> ReleveSynthetique:
    rng = random.Random(graine)
    fake = Faker("fr_FR")
    fake.seed_instance(graine)

    prenom, nom = fake.first_name(), fake.last_name().upper()
    ville = fake.city().upper()
    identite = {
        "nom": f"{prenom} {nom}",
        "adresse": fake.street_address(),
        "cp_ville": f"{fake.postcode()} {ville}",
        "iban": fake.iban(),
        "compte": _ref(rng, 11),
        "telephone": fake.phone_number(),
        "email": fake.email(),
        "employeur": fake.company().upper(),
        "bailleur": f"{fake.last_name().upper()} {fake.first_name().upper()}",
        "amis": [f"{fake.first_name().upper()} {fake.last_name().upper()}" for _ in range(3)],
    }
    releve = ReleveSynthetique(identite=identite)
    releve.pii = [
        identite["nom"], identite["adresse"], identite["iban"], identite["compte"],
        identite["telephone"], identite["email"], identite["bailleur"], *identite["amis"],
    ]

    nb_mois = nb_mois or rng.randint(3, 6)
    fin = date(2026, rng.randint(nb_mois, 12), 1)
    mois = [(fin.year, fin.month - nb_mois + 1 + i) for i in range(nb_mois)]

    choisis = rng.sample(RECURRENTS, rng.randint(6, 10))
    # Le loyer est presque toujours là
    if not any(r[0] == "LOYER" for r in choisis) and rng.random() < 0.8:
        choisis.append(RECURRENTS[0])
    params = {}
    for motif, gabarit, cat, nature, (mn, mx), var, jour in choisis:
        montant = round(rng.uniform(mn, mx), 2)
        rum = "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ0123456789") for _ in range(16))
        params[motif] = (gabarit, cat, montant, var, jour, rum, _ref(rng, 9))
        releve.recurrents.append(RecurrentOr(motif, cat, nature, montant))
        if "{rum}" in gabarit:
            releve.pii.append(rum)

    cotisation_carte = round(rng.uniform(3, 4.5), 2) if rng.random() < 0.5 else 0.0
    if cotisation_carte:
        releve.recurrents.append(
            RecurrentOr("COTISATION CARTE", "frais_bancaires", "obligatoire", cotisation_carte)
        )

    for annee, m in mois:
        dernier = monthrange(annee, m)[1]
        # Salaire
        j = min(dernier, rng.randint(26, 28))
        releve.transactions.append(TransactionOr(
            date(annee, m, j).isoformat(),
            f"VIR SEPA RECU DE {identite['employeur']} SALAIRE {MOIS_FR[m]}",
            round(rng.uniform(1900, 3600), 2), "revenu",
        ))
        for motif, (gabarit, cat, montant, var, jour, rum, ref) in params.items():
            j = max(1, min(dernier, jour + rng.randint(-2, 2)))
            valeur = round(montant * (1 + rng.uniform(-var, var)), 2)
            libelle = gabarit.format(
                bailleur=identite["bailleur"], rum=rum, ref=ref, jj=f"{j:02d}", mm=f"{m:02d}"
            )
            releve.transactions.append(
                TransactionOr(date(annee, m, j).isoformat(), libelle, -valeur, cat)
            )
        for gabarit, cat, (mn, mx), freq in VARIABLES:
            for _ in range(rng.randint(0, freq * 2)):
                j = rng.randint(1, dernier)
                libelle = gabarit.format(
                    ville=ville, jj=f"{j:02d}", mm=f"{m:02d}",
                    ami=rng.choice(identite["amis"]), motif=rng.choice(["RESTO", "CADEAU", "WEEKEND", ""]),
                ).strip()
                releve.transactions.append(TransactionOr(
                    date(annee, m, j).isoformat(), libelle, -round(rng.uniform(mn, mx), 2), cat,
                ))
        if rng.random() < 0.4:
            j = rng.randint(1, dernier)
            releve.transactions.append(TransactionOr(
                date(annee, m, j).isoformat(),
                f"VIR SEPA RECU DE {rng.choice(identite['amis'])} REMBOURSEMENT",
                round(rng.uniform(10, 60), 2), "virement_personnel",
            ))
        if cotisation_carte:
            releve.transactions.append(TransactionOr(
                date(annee, m, min(dernier, 10)).isoformat(), "COTISATION CARTE VISA CLASSIC",
                -cotisation_carte, "frais_bancaires",
            ))

    releve.transactions.sort(key=lambda t: t.date)
    return releve


def ecrire_pdf(releve: ReleveSynthetique, chemin: str | Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    ident = releve.identite
    doc = SimpleDocTemplate(str(chemin), pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm)
    elements = []
    par_mois: dict[str, list[TransactionOr]] = {}
    for t in releve.transactions:
        par_mois.setdefault(t.date[:7], []).append(t)

    solde = round(random.Random(len(releve.transactions)).uniform(200, 3000), 2)
    for i, (cle, transactions) in enumerate(sorted(par_mois.items())):
        annee, mois = int(cle[:4]), int(cle[5:])
        dernier = monthrange(annee, mois)[1]
        if i:
            elements.append(PageBreak())
        elements += [
            Paragraph("<b>BANQUE EXEMPLE</b> - Relevé de compte courant", styles["Title"]),
            Paragraph(f"M. {ident['nom']}<br/>{ident['adresse']}<br/>{ident['cp_ville']}", styles["Normal"]),
            Paragraph(f"Tél : {ident['telephone']} - {ident['email']}", styles["Normal"]),
            Paragraph(f"Compte n° {ident['compte']} - IBAN : {ident['iban']}", styles["Normal"]),
            Spacer(1, 0.3 * cm),
            Paragraph(f"Relevé du 01/{mois:02d}/{annee} au {dernier:02d}/{mois:02d}/{annee}", styles["Heading3"]),
            Paragraph(f"Ancien solde au 01/{mois:02d}/{annee} : {_fr(solde)} EUR", styles["Normal"]),
            Spacer(1, 0.2 * cm),
        ]
        lignes = [["Date", "Libellé", "Débit", "Crédit"]]
        for t in transactions:
            jj, mm = t.date[8:10], t.date[5:7]
            debit = _fr(-t.montant) if t.montant < 0 else ""
            credit = _fr(t.montant) if t.montant > 0 else ""
            lignes.append([f"{jj}/{mm}", t.libelle, debit, credit])
            solde += t.montant
        table = Table(lignes, colWidths=[1.6 * cm, 11 * cm, 2.4 * cm, 2.4 * cm], repeatRows=1)
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ALIGN", (2, 1), (3, -1), "RIGHT"),
        ]))
        elements += [
            table, Spacer(1, 0.2 * cm),
            Paragraph(f"Nouveau solde au {dernier:02d}/{mois:02d}/{annee} : {_fr(solde)} EUR", styles["Normal"]),
        ]
    doc.build(elements)


def generer_jeu(dossier: str | Path, n: int, graine_depart: int = 0) -> list[Path]:
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    chemins = []
    for k in range(n):
        releve = generer_releve(graine_depart + k)
        pdf = dossier / f"releve_{graine_depart + k:04d}.pdf"
        ecrire_pdf(releve, pdf)
        pdf.with_suffix(".json").write_text(
            json.dumps(asdict(releve), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        chemins.append(pdf)
    return chemins


def charger_verite(pdf: str | Path) -> dict:
    return json.loads(Path(pdf).with_suffix(".json").read_text(encoding="utf-8"))
