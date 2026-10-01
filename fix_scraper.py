"""
Fix du scraper APEC :
1. Meilleure extraction mots-cles depuis le CV
2. URLs correctes des offres APEC
3. Extraction description et entreprise depuis le JSON XHR
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

# Afficher la vraie structure d'une offre XHR APEC
# pour trouver les bonnes cles et le bon format d'URL
import os, json
from dotenv import load_dotenv
load_dotenv()

from pymongo import MongoClient
client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))

# Voir toutes les offres et leurs source_id
print("Offres en base avec source_id :")
for o in client["nexus_emploi"]["raw_offres"].find(
    {"source_site": "apec"}, 
    {"source_id": 1, "titre_brut": 1, "url": 1}
).limit(5):
    print(f"  source_id: {o.get('source_id')}")
    print(f"  titre: {o.get('titre_brut', '')[:50]}")
    print(f"  url: {o.get('url', '')}")
    print()