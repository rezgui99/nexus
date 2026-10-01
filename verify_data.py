"""
NEXUS EMPLOI -- Verification des donnees dans MongoDB et PostgreSQL
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
import os
import json
from dotenv import load_dotenv

load_dotenv()

print("=" * 60)
print("  NEXUS EMPLOI -- Verification des donnees")
print("=" * 60)

# ---- MongoDB ----
print("\n[MONGODB]")
print("-" * 40)
from pymongo import MongoClient
client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = client["nexus_emploi"]

# Verifier raw_offres
col_offres = db["raw_offres"]
total_offres = col_offres.count_documents({})
real_offres = col_offres.count_documents({"source_site": {"$ne": "seed"}})
seed_offres = col_offres.count_documents({"source_site": "seed"})
apec_offres = col_offres.count_documents({"source_site": {"$in": ["apec", "france_travail"]}})

print(f"raw_offres : {total_offres} total")
print(f"  - APEC (reelles)  : {apec_offres}")
print(f"  - seed (fictives) : {seed_offres}")

# Afficher les 3 dernieres offres reelles
print("\n  Dernieres offres APEC reelles :")
for o in col_offres.find({"source_site": "apec"}).sort("_id", -1).limit(3):
    print(f"    OK {o.get('titre_brut', '?')[:50]}")
    print(f"       Entreprise : {o.get('entreprise_brute', '?')}")
    print(f"       Desc (100c): {o.get('description_brute', '')[:100]}")
    print(f"       Statut     : {o.get('statut_traitement', '?')}")
    print()

# Verifier raw_cv
col_cv = db["raw_cv"]
total_cv = col_cv.count_documents({})
print(f"raw_cv : {total_cv} CV")
for cv in col_cv.find().sort("_id", -1).limit(3):
    chars = cv.get("nb_caracteres", 0)
    texte = cv.get("texte_brut", "")
    print(f"  - {cv.get('fichier_nom', '?')} | {chars} chars | statut: {cv.get('statut_traitement', '?')}")
    if texte:
        print(f"    Extrait: {texte[:80]}")
    else:
        print(f"    WARN  Texte VIDE")

# ---- PostgreSQL ----
print("\n[POSTGRESQL]")
print("-" * 40)
try:
    from sqlalchemy import create_engine, text
    engine = create_engine(os.getenv("DATABASE_URL"))
    with engine.connect() as conn:
        # offres_structurees
        try:
            r = conn.execute(text("SELECT COUNT(*) FROM offres_structurees"))
            total = r.fetchone()[0]
            r2 = conn.execute(text("SELECT COUNT(*) FROM offres_structurees WHERE llm_provider = 'seed'"))
            seed = r2.fetchone()[0]
            real = total - seed
            print(f"offres_structurees : {total} total")
            print(f"  - reelles (NER)  : {real}")
            print(f"  - fictives (seed): {seed}")

            # Afficher exemples reels
            r3 = conn.execute(text("""
                SELECT titre_normalise, entreprise_brute, ville, 
                       competences_techniques, niveau_seniorite, salaire_min, salaire_max
                FROM offres_structurees 
                WHERE llm_provider != 'seed'
                LIMIT 3
            """))
            rows = r3.fetchall()
            if rows:
                print("\n  Offres structurees reelles :")
                for row in rows:
                    comp = json.loads(row[3]) if row[3] else []
                    print(f"    OK {row[0]}")
                    print(f"       {row[1]} | {row[2]} | {row[4]}")
                    print(f"       Comp: {', '.join(comp[:4])}")
                    print(f"       Sal: {row[5]}-{row[6]} EUR")
                    print()
            else:
                print("  WARN  Aucune offre structuree reelle (NER pas encore lance)")

        except Exception as e:
            print(f"  WARN  Table offres_structurees : {e}")

        # cv_structures
        try:
            r = conn.execute(text("SELECT COUNT(*) FROM cv_structures"))
            total_cv_pg = r.fetchone()[0]
            print(f"cv_structures : {total_cv_pg} CV")
        except Exception as e:
            print(f"  WARN  Table cv_structures : {e}")

except Exception as e:
    print(f"Erreur PostgreSQL : {e}")

# ---- Qdrant ----
print("\n[QDRANT]")
print("-" * 40)
try:
    from qdrant_client import QdrantClient
    qclient = QdrantClient(
        host=os.getenv("QDRANT_HOST", "localhost"),
        port=int(os.getenv("QDRANT_PORT", 6333))
    )
    collections = qclient.get_collections().collections
    if collections:
        for col in collections:
            info = qclient.get_collection(col.name)
            print(f"  {col.name} : {info.points_count} vecteurs")
    else:
        print("  WARN  Aucune collection (matching pas encore lance)")
except Exception as e:
    print(f"  Erreur Qdrant : {e}")

print("\n" + "=" * 60)
print("RESUME :")
print(f"  MongoDB offres APEC reelles : {apec_offres}")
print(f"  MongoDB offres fictives     : {seed_offres}")
print(f"  MongoDB CV                  : {total_cv}")
print("=" * 60)