"""
NEXUS EMPLOI — Script maître : Lance tout le pipeline
======================================================
Auteur  : Aziz Rezgui (Projet de fin d'études MSc Data Management 2025-2026)

Lance dans l'ordre :
  0. Infrastructure  → Docker (MongoDB, PostgreSQL, Qdrant)
  1. Bloc 1          → Scraping APEC + ingestion CV
  2. Bloc 2          → NER LLM (offres + CV)
  3. Bloc 3          → Vectorisation + Matching Qdrant
  4. Bloc 5          → Application Streamlit

Usage :
    python run_all.py                    # Pipeline complet
    python run_all.py --skip-scraping    # Sans re-scraper
    python run_all.py --only-app         # Lance juste Streamlit
    python run_all.py --blocs 1 2 3      # Blocs spécifiques
"""

import os
import sys
import time
import socket
import subprocess
import argparse
import logging
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent.resolve()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(BASE_DIR / "pipeline.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("nexus_pipeline")

PYTHON = sys.executable   # Utilise le même Python que celui qui lance ce script

SCRIPTS = {
    "docker":      None,
    "scraper":     BASE_DIR / "bloc1_ingestion" / "scraper_offres_mongodb.py",
    "cv":          BASE_DIR / "bloc1_ingestion" / "cv_parser_mongodb.py",
    "ner_offres":  BASE_DIR / "bloc2_llm_ner" / "04_ner_offres_llm.py",
    "ner_cv":      BASE_DIR / "bloc2_llm_ner" / "05_ner_cv_llm.py",
    "matching":    BASE_DIR / "bloc3_matching" / "06_matching_qdrant.py",
    "seed":        BASE_DIR / "seed_data.py",
    "app":         BASE_DIR / "app" / "app.py",
    "dashboard":   BASE_DIR / "app" / "dashboard.py",
}

POSTGRES_PORT = 5433


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------

def separator(title: str):
    print()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)



# ---------------------------------------------------------------------------
# Extraction automatique des mots-clés depuis les CV
# ---------------------------------------------------------------------------

def extract_keywords_from_cv() -> str:
    """
    Lit les CV dans le dossier cv/ et extrait automatiquement
    les mots-clés pertinents pour le scraping APEC.
    Utilise PyPDF sans LLM — fonctionne même sans quota.
    """
    cv_dir = BASE_DIR / "cv"
    if not cv_dir.exists():
        return None

    cv_files = list(cv_dir.glob("*.pdf")) + list(cv_dir.glob("*.docx")) + list(cv_dir.glob("*.txt"))
    if not cv_files:
        return None

    # Mots-clés techniques courants à détecter dans le CV
    TECH_KEYWORDS = [
        # Langages
        "python", "java", "scala", "r", "sql", "javascript", "typescript",
        # Data Engineering
        "spark", "kafka", "airflow", "dbt", "hadoop", "flink", "nifi",
        "databricks", "snowflake", "redshift", "bigquery", "hive",
        # Cloud
        "aws", "azure", "gcp", "google cloud",
        # ML/IA
        "machine learning", "deep learning", "nlp", "tensorflow", "pytorch",
        "scikit-learn", "mlflow", "kubeflow",
        # Bases de données
        "postgresql", "mongodb", "elasticsearch", "cassandra", "redis",
        # DevOps/Data
        "docker", "kubernetes", "terraform", "ci/cd", "git",
        # BI
        "power bi", "tableau", "looker", "qlik", "dax",
        # Postes
        "data engineer", "data scientist", "data analyst", "ml engineer",
        "analytics engineer", "data architect", "mlops",
    ]

    # Lire le texte de tous les CV
    all_text = ""
    for cv_file in cv_files[:3]:  # Max 3 CV
        try:
            if cv_file.suffix.lower() == ".pdf":
                try:
                    from pypdf import PdfReader
                    reader = PdfReader(str(cv_file))
                    for page in reader.pages:
                        all_text += (page.extract_text() or "") + " "
                except Exception:
                    pass
            elif cv_file.suffix.lower() == ".txt":
                all_text += cv_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass

    all_text_lower = all_text.lower()

    # Détecter les mots-clés présents dans le CV
    found = []
    for kw in TECH_KEYWORDS:
        if kw in all_text_lower:
            found.append(kw)

    if not found:
        return None

    # Prioriser les postes puis les techs principales
    postes = [k for k in found if k in ["data engineer", "data scientist", "data analyst", "ml engineer", "analytics engineer", "data architect", "mlops"]]
    techs  = [k for k in found if k not in postes][:5]

    # Construire la requête de recherche
    keywords_parts = postes[:2] + techs[:3]
    keywords = " ".join(keywords_parts[:4])  # Max 4 mots-clés

    logger.info("🎯 Mots-clés extraits du CV : %s", keywords)
    return keywords if keywords else None

def run_script(name: str, script: Path, input_data: str = None) -> bool:
    """
    Lance un script Python et retourne True si succès.
    input_data : texte envoyé sur stdin (pour les scripts interactifs)
    """
    if not script.exists():
        logger.error("❌ Script introuvable : %s", script)
        return False

    logger.info("▶️  Lancement : %s", script.name)
    start = time.time()

    try:
        result = subprocess.run(
            [PYTHON, str(script)],
            input=input_data,
            text=True,
            cwd=str(BASE_DIR),
            timeout=600,   # 10 minutes max par script
        )
        duration = round(time.time() - start, 1)

        if result.returncode == 0:
            logger.info("✅ %s terminé en %ss", name, duration)
            return True
        else:
            logger.error("❌ %s échoué (code %d) en %ss", name, result.returncode, duration)
            return False

    except subprocess.TimeoutExpired:
        logger.error("❌ %s timeout après 10 minutes", name)
        return False
    except Exception as e:
        logger.error("❌ Erreur inattendue pour %s : %s", name, e)
        return False


# ---------------------------------------------------------------------------
# Étape 0 : Infrastructure Docker
# ---------------------------------------------------------------------------

def step_docker() -> bool:
    separator("ÉTAPE 0 — Infrastructure Docker")

    # Démarrer les containers
    logger.info("🐳 Démarrage des containers...")
    result = subprocess.run(
        ["docker-compose", "up", "-d"],
        capture_output=True, text=True, cwd=str(BASE_DIR)
    )
    if result.returncode != 0:
        logger.error("❌ Docker failed : %s", result.stderr[:200])
        logger.info("💡 Ouvre Docker Desktop et réessaie")
        return False
    logger.info("✅ Containers démarrés")
    time.sleep(5)

    # Attendre MongoDB
    logger.info("⏳ Attente MongoDB...")
    for _ in range(15):
        try:
            s = socket.create_connection(("127.0.0.1", 27017), timeout=2)
            s.close()
            logger.info("✅ MongoDB prêt")
            break
        except Exception:
            time.sleep(2)
    else:
        logger.error("❌ MongoDB inaccessible")
        return False

    # Attendre PostgreSQL
    logger.info("⏳ Attente PostgreSQL...")
    host = None
    for _ in range(15):
        for h in ["127.0.0.1", "localhost"]:
            try:
                s = socket.create_connection((h, POSTGRES_PORT), timeout=2)
                s.close()
                host = h
                break
            except Exception:
                pass
        if host:
            break
        time.sleep(2)

    if not host:
        logger.error("❌ PostgreSQL inaccessible sur port %d", POSTGRES_PORT)
        return False
    logger.info("✅ PostgreSQL prêt sur %s:%d", host, POSTGRES_PORT)

    # Créer la base si nécessaire
    try:
        import pg8000
        conn = pg8000.connect(
            host=host, port=POSTGRES_PORT,
            user="postgres", password="nexus_password", database="postgres"
        )
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_database WHERE datname = 'nexus_emploi'")
        if not cur.fetchone():
            cur.execute("CREATE DATABASE nexus_emploi")
            logger.info("✅ Base 'nexus_emploi' créée")
        else:
            logger.info("✅ Base 'nexus_emploi' déjà existante")
        cur.close()
        conn.close()

        # Mettre à jour DATABASE_URL dans .env
        env_path = BASE_DIR / ".env"
        if env_path.exists():
            lines = env_path.read_text(encoding="utf-8").splitlines()
            new_url = f"DATABASE_URL=postgresql+pg8000://postgres:nexus_password@{host}:{POSTGRES_PORT}/nexus_emploi"
            new_lines = [new_url if l.startswith("DATABASE_URL=") else l for l in lines]
            if new_url not in new_lines:
                new_lines.append(new_url)
            env_path.write_text("\n".join(new_lines), encoding="utf-8")
            logger.info("✅ .env mis à jour")

    except Exception as e:
        logger.error("❌ Erreur PostgreSQL : %s", e)
        return False

    return True


# ---------------------------------------------------------------------------
# Étape 1 : Scraping APEC
# ---------------------------------------------------------------------------

def step_scraping(keywords: str = "data engineer", nb_offres: int = 20) -> bool:
    separator("ÉTAPE 1 — Scraping APEC")
    logger.info("🔍 Mots-clés : %s | Nb offres : %d", keywords, nb_offres)

    # Passer les paramètres via stdin (le scraper lit keywords et nb_offres)
    input_data = f"{keywords}\n{nb_offres}\n"
    return run_script("Scraper APEC", SCRIPTS["scraper"], input_data=input_data)


# ---------------------------------------------------------------------------
# Étape 1b : Ingestion CV (si dossier cv/ présent)
# ---------------------------------------------------------------------------

def step_cv_ingestion() -> bool:
    separator("ÉTAPE 1b — Ingestion des CV")

    cv_dir = BASE_DIR / "cv"
    if not cv_dir.exists():
        logger.warning("⚠️  Dossier 'cv/' introuvable — création du dossier")
        cv_dir.mkdir()
        logger.info("📁 Dossier créé : %s", cv_dir)
        logger.info("   → Dépose tes CV (PDF/DOCX) dans ce dossier et relance")
        return True   # Pas bloquant

    cv_files = list(cv_dir.glob("*.pdf")) + list(cv_dir.glob("*.docx"))
    if not cv_files:
        logger.warning("⚠️  Aucun CV trouvé dans cv/ — étape ignorée")
        return True   # Pas bloquant

    logger.info("📄 %d CV trouvés dans cv/", len(cv_files))
    input_data = f"{str(cv_dir)}\n"
    return run_script("Parser CV", SCRIPTS["cv"], input_data=input_data)


# ---------------------------------------------------------------------------
# Étape 2 : NER LLM
# ---------------------------------------------------------------------------

def step_ner() -> bool:
    separator("ÉTAPE 2 — NER LLM (extraction entités)")

    logger.info("🤖 NER des offres d'emploi...")
    ok_offres = run_script("NER Offres", SCRIPTS["ner_offres"])

    if not ok_offres:
        logger.warning("⚠️  NER offres échoué — vérifie le quota Gemini/Groq")
        logger.info("   💡 Si quota épuisé, attends minuit ou change LLM_MODEL dans .env")

    logger.info("🤖 NER des CV...")
    ok_cv = run_script("NER CV", SCRIPTS["ner_cv"])

    return ok_offres   # Au moins les offres doivent être traitées


# ---------------------------------------------------------------------------
# Étape 3 : Matching Qdrant
# ---------------------------------------------------------------------------

def step_matching() -> bool:
    separator("ÉTAPE 3 — Vectorisation & Matching Qdrant")
    return run_script("Matching", SCRIPTS["matching"])


# ---------------------------------------------------------------------------
# Étape seed : Données fictives (si tables vides)
# ---------------------------------------------------------------------------

def step_seed() -> bool:
    separator("ÉTAPE SEED — Données fictives")
    logger.info("🌱 Injection données fictives dans PostgreSQL...")
    return run_script("Seed Data", SCRIPTS["seed"])


# ---------------------------------------------------------------------------
# Étape 5 : Streamlit
# ---------------------------------------------------------------------------

def step_app(mode: str = "app"):
    """
    mode = "app"       → Vue candidat + organisme (port 8501)
    mode = "dashboard" → Dashboard analytique     (port 8502)
    mode = "both"      → Les deux en parallele
    """
    if mode == "both":
        separator("ÉTAPE 5 — Applications Streamlit")
        logger.info("🌐 App principale  → http://localhost:8501")
        logger.info("📊 Dashboard       → http://localhost:8502")
        logger.info("   Appuie sur Ctrl+C pour arrêter")
        print()
        # Lancer le dashboard en arriere-plan
        dashboard_proc = subprocess.Popen(
            ["streamlit", "run", str(SCRIPTS["dashboard"]),
             "--server.port", "8502",
             "--server.headless", "true"],
            cwd=str(BASE_DIR)
        )
        # Lancer l app principale au premier plan
        try:
            subprocess.run(
                ["streamlit", "run", str(SCRIPTS["app"]),
                 "--server.port", "8501",
                 "--server.headless", "false"],
                cwd=str(BASE_DIR)
            )
        finally:
            dashboard_proc.terminate()

    else:
        script_key = "dashboard" if mode == "dashboard" else "app"
        port       = "8502" if mode == "dashboard" else "8501"
        separator(f"ÉTAPE 5 — Streamlit ({mode})")
        logger.info("🌐 Lancement sur http://localhost:%s", port)
        logger.info("   Appuie sur Ctrl+C pour arrêter")
        print()
        subprocess.run(
            ["streamlit", "run", str(SCRIPTS[script_key]),
             "--server.port", port,
             "--server.headless", "false"],
            cwd=str(BASE_DIR)
        )


# ---------------------------------------------------------------------------
# Rapport final
# ---------------------------------------------------------------------------

def print_report(results: dict):
    separator("RAPPORT FINAL")
    total = len(results)
    success = sum(1 for v in results.values() if v)

    for step, ok in results.items():
        status = "✅" if ok else "❌"
        print(f"  {status}  {step}")

    print()
    print(f"  Résultat : {success}/{total} étapes réussies")
    print(f"  Log      : {BASE_DIR / 'pipeline.log'}")
    print()

    if success == total:
        print("  🎉 Pipeline complet — Lance l'app :")
        print("     streamlit run app/app.py")
    else:
        print("  ⚠️  Certaines étapes ont échoué — consulte pipeline.log")
    print()


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Nexus Emploi — Pipeline complet")
    parser.add_argument("--skip-scraping", action="store_true",
                        help="Ne pas relancer le scraping (si déjà fait)")
    parser.add_argument("--skip-ner",      action="store_true",
                        help="Ne pas relancer le NER (si déjà fait)")
    parser.add_argument("--skip-matching", action="store_true",
                        help="Ne pas relancer le matching")
    parser.add_argument("--only-app",      action="store_true",
                        help="Lancer uniquement Streamlit")
    parser.add_argument("--keywords",      type=str, default="data engineer",
                        help="Mots-clés de recherche APEC (défaut: 'data engineer')")
    parser.add_argument("--nb-offres",     type=int, default=20,
                        help="Nombre d'offres à scraper (défaut: 20)")
    parser.add_argument("--no-app",        action="store_true",
                        help="Ne pas lancer Streamlit à la fin")
    parser.add_argument("--app-mode",      type=str, default="both",
                        choices=["app", "dashboard", "both"],
                        help="Mode Streamlit : app | dashboard | both (défaut: both)")
    parser.add_argument("--seed",          action="store_true",
                        help="Injecter des données fictives (utile si quota LLM épuisé)")

    args = parser.parse_args()

    print()
    print("╔══════════════════════════════════════════════════════╗")
    print("║         NEXUS EMPLOI — Pipeline Complet              ║")
    print("║    MSc Data Management — Aziz Rezgui — 2025-2026     ║")
    print("╚══════════════════════════════════════════════════════╝")
    print(f"  Démarré le : {datetime.now().strftime('%d/%m/%Y à %H:%M:%S')}")
    print()

    results = {}

    if args.only_app:
        step_app()
        return

    # Étape 0 : Docker (toujours)
    results["Infrastructure Docker"] = step_docker()
    if not results["Infrastructure Docker"]:
        logger.error("❌ Infrastructure échouée — arrêt du pipeline")
        print_report(results)
        sys.exit(1)

    # Étape 1 : Scraping
    if not args.skip_scraping:
        results["Scraping APEC"] = step_scraping(
            keywords=args.keywords,
            nb_offres=args.nb_offres
        )
        results["Ingestion CV"] = step_cv_ingestion()
    else:
        logger.info("⏩ Scraping ignoré (--skip-scraping)")

    # Étape 2 : NER
    if not args.skip_ner:
        results["NER LLM"] = step_ner()
    else:
        logger.info("⏩ NER ignoré (--skip-ner)")

    # Étape 3 : Matching
    if not args.skip_matching:
        results["Matching Qdrant"] = step_matching()
    else:
        logger.info("⏩ Matching ignoré (--skip-matching)")

    # Rapport
    print_report(results)

    # Seed (optionnel)
    if args.seed:
        results["Seed données"] = step_seed()

    # Rapport
    print_report(results)

    # Étape 5 : App Streamlit
    if not args.no_app:
        step_app(mode=args.app_mode)


if __name__ == "__main__":
    main()