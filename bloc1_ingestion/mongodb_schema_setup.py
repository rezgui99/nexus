"""
NEXUS EMPLOI — Bloc 1 : Schémas MongoDB (données brutes)
=========================================================
Auteur  : Aziz Rezgui (Projet de fin d'études MSc Data Management 2025-2026)

Ce fichier contient :
  1. Les schémas JSON (exemples annotés) pour les deux collections brutes
  2. Les validators MongoDB (JSONSchema) à appliquer lors de la création
  3. Un script de création des collections avec les bons index

Collections :
  ┌─────────────────────────────────────────────────────┐
  │  nexus_emploi.raw_offres   — offres d'emploi brutes │
  │  nexus_emploi.raw_cv       — CV candidats bruts     │
  └─────────────────────────────────────────────────────┘

Cycle de vie du document :
  raw  ──► structured  ──► matched
   │            │              │
   │    (après LLM NER)   (après matching)
   │
  Stocké ici (Bloc 1)
"""

import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")


# ===========================================================================
# 1. EXEMPLES JSON ANNOTÉS (à titre documentaire)
# ===========================================================================

RAW_OFFRE_EXAMPLE = {
    # ---- Identifiants ----
    "_id":          "ObjectId (auto-généré par MongoDB)",
    "source_id":    "142857",                  # ID interne APEC / site source
    "source_site":  "apec",                    # apec | welcometothejungle | hellowork | linkedin
    "url":          "https://www.apec.fr/candidat/recherche-emploi.html/emploi/142857",

    # ---- Contenu brut (non structuré) ----
    "titre_brut":    "Data Engineer confirmé – Secteur Finance (H/F)",
    "description_brute": (
        "Au sein de la Direction Data & IA de notre groupe, vous serez en charge de :\n"
        "- Conception et maintenance de pipelines de données (Spark, Kafka, dbt)\n"
        "- Mise en place et optimisation d'un Data Lakehouse (Databricks / Azure)\n"
        "- Collaboration avec les Data Scientists pour l'industrialisation des modèles ML\n"
        "Profil : 3 à 5 ans d'expérience, maîtrise de Python et SQL, "
        "expérience Cloud obligatoire. Salaire : 55-65k€. CDI. Paris 9e."
    ),
    "entreprise_brute":    "BNP Paribas",
    "localisation_brute":  "Paris (75)",
    "date_publication_brute": "2026-03-20T08:00:00",

    # ---- Métadonnées de collecte ----
    "scraped_at":          "2026-03-26T14:32:17.432891+00:00",  # ISO 8601 UTC
    "pipeline_version":    "1.0.0",
    "statut_traitement":   "raw",              # raw | structured | matched | archived
    "content_hash":        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",

    # ---- Champs ajoutés après traitement LLM (Bloc 2 — pas encore remplis) ----
    # "structured_data": {
    #   "competences":    ["Python", "Spark", "Kafka", "dbt", "Databricks", "Azure", "SQL"],
    #   "experiences":    [{"intitule": "Data Engineer", "duree_min": 3, "duree_max": 5}],
    #   "salaire":        {"min": 55000, "max": 65000, "devise": "EUR"},
    #   "localisation":   {"ville": "Paris", "code_postal": "75009", "region": "Île-de-France"},
    #   "type_contrat":   "CDI",
    #   "secteur":        "Finance"
    # }
}


RAW_CV_EXAMPLE = {
    # ---- Identifiants ----
    "_id":           "ObjectId (auto-généré par MongoDB)",
    "candidat_id":   "a3f7c2b1d9e4",          # 16 premiers chars du content_hash (anonymisation)
    "fichier_nom":   "CV_Jean_Dupont_DataEng.pdf",
    "fichier_format": "pdf",

    # ---- Contenu brut ----
    "texte_brut": (
        "Jean Dupont\njean.dupont@email.com | +33 6 12 34 56 78 | LinkedIn\n\n"
        "EXPÉRIENCE PROFESSIONNELLE\n\n"
        "Data Engineer — Société Générale (2022 – présent)\n"
        "- Développement de pipelines ELT avec dbt et Airflow\n"
        "- Modélisation et optimisation d'un Data Warehouse Snowflake\n\n"
        "Data Analyst — Capgemini (2020 – 2022)\n"
        "- Création de dashboards Power BI et tableaux de bord Tableau\n\n"
        "FORMATION\n"
        "Master Data Science — Université Paris-Saclay (2020)\n\n"
        "COMPÉTENCES\n"
        "Python, SQL, dbt, Airflow, Snowflake, Spark, Power BI, Azure, Docker"
    ),

    # ---- Éléments structurés (retournés par unstructured) ----
    "elements": [
        {"type": "Title",         "text": "Jean Dupont",                         "metadata": {"page_number": 1}},
        {"type": "NarrativeText", "text": "jean.dupont@email.com | +33 6 12...", "metadata": {"page_number": 1}},
        {"type": "Title",         "text": "EXPÉRIENCE PROFESSIONNELLE",          "metadata": {"page_number": 1}},
        {"type": "NarrativeText", "text": "Data Engineer — Société Générale...", "metadata": {"page_number": 1}},
        {"type": "ListItem",      "text": "Développement de pipelines ELT...",  "metadata": {"page_number": 1}},
        # ... (éléments suivants)
    ],

    # ---- Métadonnées de parsing ----
    "parsed_at":          "2026-03-26T14:35:02.112345+00:00",
    "parser_utilise":     "unstructured",      # unstructured | pypdf | python-docx | txt-native
    "nb_pages":           2,
    "nb_caracteres":      1842,
    "pipeline_version":   "1.0.0",
    "statut_traitement":  "raw",               # raw | structured | matched | archived
    "content_hash":       "d4e8f1a2b3c5...",

    # ---- Champs ajoutés après traitement LLM (Bloc 2 — pas encore remplis) ----
    # "structured_data": {
    #   "nom":            "Jean Dupont",
    #   "email":          "jean.dupont@email.com",
    #   "telephone":      "+33612345678",
    #   "competences":    ["Python", "SQL", "dbt", "Airflow", "Snowflake", "Spark"],
    #   "experiences": [
    #     {"poste": "Data Engineer", "entreprise": "Société Générale",
    #      "debut": "2022", "fin": "present", "duree_mois": 28}
    #   ],
    #   "formation": [
    #     {"diplome": "Master Data Science", "etablissement": "Université Paris-Saclay", "annee": 2020}
    #   ],
    #   "localisation": {"ville": "Paris", "mobilite": "Île-de-France"},
    #   "annees_experience": 6
    # }
}


# ===========================================================================
# 2. VALIDATORS JSONSCHEMA POUR MONGODB
#    Appliqués à la création pour garantir la cohérence minimale
# ===========================================================================

VALIDATOR_RAW_OFFRES = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["source_id", "source_site", "url", "titre_brut",
                     "description_brute", "scraped_at", "statut_traitement", "content_hash"],
        "properties": {
            "source_id":            {"bsonType": "string",  "description": "ID interne de la source"},
            "source_site":          {"bsonType": "string",  "enum": ["apec", "welcometothejungle", "hellowork", "linkedin", "html_scrape"]},
            "url":                  {"bsonType": "string",  "description": "URL canonique"},
            "titre_brut":           {"bsonType": "string",  "minLength": 3},
            "description_brute":    {"bsonType": "string",  "minLength": 10},
            "entreprise_brute":     {"bsonType": ["string", "null"]},
            "localisation_brute":   {"bsonType": ["string", "null"]},
            "date_publication_brute": {"bsonType": ["string", "null"]},
            "scraped_at":           {"bsonType": "string"},
            "pipeline_version":     {"bsonType": "string"},
            "statut_traitement":    {"bsonType": "string",  "enum": ["raw", "structured", "matched", "archived"]},
            "content_hash":         {"bsonType": "string",  "minLength": 64},
        }
    }
}

VALIDATOR_RAW_CV = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["candidat_id", "fichier_nom", "fichier_format",
                     "texte_brut", "parsed_at", "statut_traitement", "content_hash"],
        "properties": {
            "candidat_id":    {"bsonType": "string"},
            "fichier_nom":    {"bsonType": "string"},
            "fichier_format": {"bsonType": "string",  "enum": ["pdf", "docx", "doc", "txt"]},
            "texte_brut":     {"bsonType": "string",  "minLength": 50},
            "elements":       {"bsonType": "array"},
            "parsed_at":      {"bsonType": "string"},
            "parser_utilise": {"bsonType": "string",  "enum": ["unstructured", "pypdf", "python-docx", "txt-native", "fallback", "unknown"]},
            "nb_pages":       {"bsonType": ["int", "null"]},
            "nb_caracteres":  {"bsonType": "int",     "minimum": 0},
            "statut_traitement": {"bsonType": "string", "enum": ["raw", "structured", "matched", "archived"]},
            "content_hash":   {"bsonType": "string",  "minLength": 64},
        }
    }
}


# ===========================================================================
# 3. CRÉATION DES COLLECTIONS AVEC INDEX ET VALIDATORS
# ===========================================================================

def setup_mongodb():
    """
    Initialise la base nexus_emploi avec les deux collections et leurs index.
    À exécuter une seule fois au démarrage du projet.
    """
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client["nexus_emploi"]

    collections_existantes = db.list_collection_names()

    # ---- Collection : raw_offres ----
    if "raw_offres" not in collections_existantes:
        db.create_collection("raw_offres", validator=VALIDATOR_RAW_OFFRES)
        print("✅ Collection 'raw_offres' créée avec validator")
    else:
        # Mise à jour du validator sans recréer la collection
        db.command("collMod", "raw_offres", validator=VALIDATOR_RAW_OFFRES)
        print("♻️  Collection 'raw_offres' déjà existante — validator mis à jour")

    raw_offres = db["raw_offres"]
    raw_offres.create_index("content_hash",        unique=True, name="idx_dedup_hash")
    raw_offres.create_index("statut_traitement",              name="idx_statut")
    raw_offres.create_index("source_site",                    name="idx_source")
    raw_offres.create_index("scraped_at",                     name="idx_date_collecte")
    raw_offres.create_index([("source_id", 1), ("source_site", 1)], unique=True, name="idx_source_id_site")
    print("   Index raw_offres : ✅")

    # ---- Collection : raw_cv ----
    if "raw_cv" not in collections_existantes:
        db.create_collection("raw_cv", validator=VALIDATOR_RAW_CV)
        print("✅ Collection 'raw_cv' créée avec validator")
    else:
        db.command("collMod", "raw_cv", validator=VALIDATOR_RAW_CV)
        print("♻️  Collection 'raw_cv' déjà existante — validator mis à jour")

    raw_cv = db["raw_cv"]
    raw_cv.create_index("content_hash",    unique=True, name="idx_dedup_hash")
    raw_cv.create_index("statut_traitement",           name="idx_statut")
    raw_cv.create_index("candidat_id",                 name="idx_candidat")
    raw_cv.create_index("parsed_at",                   name="idx_date_parse")
    print("   Index raw_cv : ✅")

    client.close()
    print("\n🏁 Setup MongoDB terminé — Base 'nexus_emploi' prête")


# ===========================================================================
# 4. REQUÊTES UTILES (exemples pour les prochaines étapes du pipeline)
# ===========================================================================

REQUETES_UTILES = """
-- Requêtes MongoDB utiles pour la suite du pipeline (Bloc 2 : traitement LLM)

// Récupérer toutes les offres brutes non encore traitées (statut = "raw")
db.raw_offres.find({ statut_traitement: "raw" }).limit(50)

// Récupérer les CV bruts non traités
db.raw_cv.find({ statut_traitement: "raw" })

// Statistiques par source
db.raw_offres.aggregate([
  { $group: { _id: "$source_site", count: { $sum: 1 } } },
  { $sort: { count: -1 } }
])

// Compter les documents par statut de traitement
db.raw_offres.aggregate([
  { $group: { _id: "$statut_traitement", count: { $sum: 1 } } }
])

// Marquer une offre comme traitée (après le NER LLM — Bloc 2)
db.raw_offres.updateOne(
  { _id: ObjectId("...") },
  { $set: { statut_traitement: "structured", structured_data: { ... } } }
)
"""


# ===========================================================================
# Point d'entrée
# ===========================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  NEXUS EMPLOI — Initialisation MongoDB")
    print("=" * 60)
    setup_mongodb()
    print()
    print("📋 Exemples de schémas disponibles dans les variables :")
    print("   RAW_OFFRE_EXAMPLE")
    print("   RAW_CV_EXAMPLE")
    print()
    print("💡 Requêtes utiles pour la suite du pipeline :")
    print(REQUETES_UTILES)