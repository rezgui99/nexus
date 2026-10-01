"""
Debug : voir la structure JSON exacte retournee par l'APEC
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
import os, json
from dotenv import load_dotenv
load_dotenv()

from pymongo import MongoClient
client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))

# Prendre une offre et afficher toutes ses cles
offre = client["nexus_emploi"]["raw_offres"].find_one({"source_site": "apec"})
if offre:
    print("Cles disponibles dans l'offre MongoDB:")
    for k, v in offre.items():
        if k != "_id":
            val_str = str(v)[:100] if v else "VIDE"
            print(f"  {k:30s} : {val_str}")
else:
    print("Aucune offre trouvee")