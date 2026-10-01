import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

print("STEP 1: imports basiques")
import os, json
print("STEP 2: dotenv")
from dotenv import load_dotenv
load_dotenv()
print("STEP 3: chargement module NER")

import importlib.util
spec = importlib.util.spec_from_file_location(
    "ner",
    r"C:\Users\h_ref\Desktop\nexus\bloc2_llm_ner\05_ner_cv_llm.py"
)
mod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(mod)
    print("STEP 4: module chargé OK")
except Exception as e:
    print(f"ERREUR chargement module: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("STEP 5: MongoDB")
from pymongo import MongoClient
client = MongoClient("mongodb://localhost:27017")
cv = client["nexus_emploi"]["raw_cv"].find_one({"fichier_nom": "tmpvk7wl6sw.pdf"})
print(f"CV trouvé: {cv['fichier_nom']} | {len(cv['texte_brut'])} chars")

print("STEP 6: NER")
extractor = mod.CVNERExtractor()
result = extractor.extraire(cv)
print(f"RESULTAT: {result}")