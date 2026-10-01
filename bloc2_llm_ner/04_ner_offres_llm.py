"""
NEXUS EMPLOI — Bloc 2 : NER via LLM (LangChain + Gemini/Groq)
==============================================================
Auteur  : Aziz Rezgui (Projet de fin d'études MSc Data Management 2025-2026)
Objectif: Extraire les entités structurées (compétences, salaire, localisation…)
          depuis les offres brutes MongoDB et les stocker dans PostgreSQL.

Pipeline :
  MongoDB (raw_offres, statut="raw")
      │
      ▼
  LLM NER (LangChain + Gemini/Groq)
      │
      ▼
  Structured JSON validé (Pydantic)
      │
      ├──► MongoDB : mise à jour statut → "structured"
      └──► PostgreSQL : insertion dans table offres_structurees

Dépendances:
    pip install langchain langchain-google-genai langchain-groq langsmith
                pydantic sqlalchemy psycopg2-binary pymongo python-dotenv
"""

import os
import json
import logging
from datetime import datetime, timezone
from typing import Optional
from dotenv import load_dotenv

from pydantic import BaseModel, Field
from pymongo import MongoClient
from sqlalchemy import create_engine, text

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("nexus_ner_offres")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MONGO_URI    = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:nexus_password@localhost:5432/nexus_emploi")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")   # gemini | groq
LLM_MODEL    = os.getenv("LLM_MODEL", "gemini-2.0-flash")
BATCH_SIZE   = 20   # Nombre d'offres traitées par run


# ---------------------------------------------------------------------------
# Schéma Pydantic — Données structurées d'une offre
# ---------------------------------------------------------------------------

class Salaire(BaseModel):
    min:    Optional[int]   = Field(None, description="Salaire minimum annuel en euros")
    max:    Optional[int]   = Field(None, description="Salaire maximum annuel en euros")
    devise: str             = Field("EUR", description="Devise")

class Experience(BaseModel):
    intitule:    Optional[str] = Field(None, description="Intitulé du poste requis")
    duree_min:   Optional[int] = Field(None, description="Durée minimale en années")
    duree_max:   Optional[int] = Field(None, description="Durée maximale en années")

class Localisation(BaseModel):
    ville:       Optional[str] = Field(None)
    code_postal: Optional[str] = Field(None)
    region:      Optional[str] = Field(None)
    teletravail: Optional[str] = Field(None, description="full | partial | none | unknown")

class OffreStructuree(BaseModel):
    """Schéma complet d'une offre d'emploi après NER."""
    # Identité
    titre_normalise:    str              = Field(..., description="Titre normalisé du poste")
    type_contrat:       Optional[str]   = Field(None, description="CDI | CDD | Stage | Alternance | Freelance")
    secteur:            Optional[str]   = Field(None, description="Secteur d'activité")

    # Compétences
    competences_techniques: list[str]   = Field(default_factory=list, description="Langages, frameworks, outils")
    competences_soft:       list[str]   = Field(default_factory=list, description="Soft skills")
    diplome_requis:         Optional[str] = Field(None, description="Bac+2 | Bac+3 | Bac+5 | Doctorat")

    # Expérience & salaire
    experience:         Optional[Experience]   = None
    salaire:            Optional[Salaire]      = None
    localisation:       Optional[Localisation] = None

    # Métadonnées
    langue_annonce:     str = Field("fr", description="fr | en")
    niveau_seniorite:   Optional[str] = Field(None, description="junior | confirme | senior | lead | directeur")


# ---------------------------------------------------------------------------
# Initialisation du LLM
# ---------------------------------------------------------------------------

def get_llm():
    """Retourne le LLM configuré selon LLM_PROVIDER."""
    if LLM_PROVIDER == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=LLM_MODEL,
            google_api_key=os.getenv("GEMINI_API_KEY"),
            temperature=0,
        )
    elif LLM_PROVIDER == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(
            model=LLM_MODEL or "llama-3.3-70b-versatile",
            api_key=os.getenv("GROQ_API_KEY"),
            temperature=0,
        )
    elif LLM_PROVIDER == "openrouter":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=LLM_MODEL or "meta-llama/llama-3.3-70b-instruct:free",
            openai_api_key=os.getenv("OPENROUTER_API_KEY"),
            openai_api_base="https://openrouter.ai/api/v1",
            temperature=0,
            default_headers={
                "HTTP-Referer": "https://nexus-emploi.app",
                "X-Title": "Nexus Emploi",
            }
        )
    else:
        raise ValueError(f"LLM_PROVIDER inconnu : {LLM_PROVIDER}")


# ---------------------------------------------------------------------------
# Extracteur NER
# ---------------------------------------------------------------------------

PROMPT_TEMPLATE = """Tu es un expert en analyse d'offres d'emploi.
Analyse l'offre ci-dessous et extrais les informations structurées.

Règles strictes :
- Réponds UNIQUEMENT en JSON valide, sans markdown ni texte autour.
- Si une information est absente, utilise null.
- Les compétences_techniques = langages, frameworks, outils, certifications.
- Les compétences_soft = communication, leadership, autonomie, etc.
- Le niveau_seniorite doit être : junior (0-2 ans) | confirme (2-5 ans) | senior (5-8 ans) | lead (8+ ans) | directeur.
- Le salaire doit être en euros annuels bruts.
- Le teletravail doit être : full | partial | none | unknown.

Schéma JSON attendu :
{{
  "titre_normalise": "string",
  "type_contrat": "CDI|CDD|Stage|Alternance|Freelance|null",
  "secteur": "string|null",
  "competences_techniques": ["string"],
  "competences_soft": ["string"],
  "diplome_requis": "Bac+2|Bac+3|Bac+5|Doctorat|null",
  "experience": {{"intitule": "string|null", "duree_min": int|null, "duree_max": int|null}},
  "salaire": {{"min": int|null, "max": int|null, "devise": "EUR"}},
  "localisation": {{"ville": "string|null", "code_postal": "string|null", "region": "string|null", "teletravail": "full|partial|none|unknown"}},
  "langue_annonce": "fr|en",
  "niveau_seniorite": "junior|confirme|senior|lead|directeur|null"
}}

--- OFFRE À ANALYSER ---
Titre : {titre}
Entreprise : {entreprise}
Localisation : {localisation}
Description :
{description}
--- FIN DE L'OFFRE ---

JSON :"""


class NERExtractor:
    """Orchestre l'extraction NER via LLM avec validation Pydantic."""

    def __init__(self):
        self.llm = get_llm()
        logger.info("✅ LLM initialisé — Provider: %s | Modèle: %s", LLM_PROVIDER, LLM_MODEL)

    def extraire(self, offre_brute: dict) -> Optional[OffreStructuree]:
        """
        Envoie l'offre brute au LLM et retourne un objet OffreStructuree validé.
        Retourne None en cas d'échec.
        """
        prompt = PROMPT_TEMPLATE.format(
            titre       = offre_brute.get("titre_brut", ""),
            entreprise  = offre_brute.get("entreprise_brute", "Non précisé"),
            localisation= offre_brute.get("localisation_brute", "Non précisé"),
            description = offre_brute.get("description_brute", "")[:4000],  # Limite tokens
        )

        try:
            response = self.llm.invoke(prompt)
            raw_json = response.content.strip()

            # Nettoyage si le LLM ajoute des backticks malgré les consignes
            # Nettoyage robuste des backticks markdown
            if "```" in raw_json:
                parts = raw_json.split("```")
                for part in parts:
                    if "{" in part:
                        raw_json = part
                        if raw_json.startswith("json"):
                            raw_json = raw_json[4:]
                        break

            # Extraire le JSON entre { et }
            start_idx = raw_json.find("{")
            end_idx = raw_json.rfind("}")
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                raw_json = raw_json[start_idx:end_idx+1]

            data = json.loads(raw_json)
            # Garantir que les listes ne sont jamais None
            if not data.get("competences_techniques"):
                data["competences_techniques"] = []
            if not data.get("competences_soft"):
                data["competences_soft"] = []
            offre_structuree = OffreStructuree(**data)
            return offre_structuree

        except json.JSONDecodeError as e:
            logger.error("❌ JSON invalide pour '%s' : %s", offre_brute.get("titre_brut", "?")[:40], e)
            return None
        except Exception as e:
            logger.error("❌ Erreur LLM pour '%s' : %s", offre_brute.get("titre_brut", "?")[:40], e)
            return None


# ---------------------------------------------------------------------------
# Stockage PostgreSQL
# ---------------------------------------------------------------------------

SQL_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS offres_structurees (
    id                      SERIAL PRIMARY KEY,
    mongo_id                VARCHAR(24) UNIQUE NOT NULL,
    source_site             VARCHAR(50),
    url                     TEXT,
    titre_brut              TEXT,
    entreprise_brute        TEXT,

    -- Données structurées (NER)
    titre_normalise         TEXT,
    type_contrat            VARCHAR(20),
    secteur                 TEXT,
    competences_techniques  JSONB,          -- ["Python", "Spark", ...]
    competences_soft        JSONB,
    diplome_requis          VARCHAR(20),
    experience_duree_min    INTEGER,
    experience_duree_max    INTEGER,
    salaire_min             INTEGER,
    salaire_max             INTEGER,
    ville                   TEXT,
    region                  TEXT,
    teletravail             VARCHAR(10),
    niveau_seniorite        VARCHAR(20),
    langue_annonce          VARCHAR(5),

    -- Métadonnées
    structured_at           TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    llm_provider            VARCHAR(20),
    llm_model               VARCHAR(50),
    pipeline_version        VARCHAR(10) DEFAULT '1.0.0'
);

-- Index pour les requêtes de matching et dashboard
CREATE INDEX IF NOT EXISTS idx_offres_competences  ON offres_structurees USING GIN(competences_techniques);
CREATE INDEX IF NOT EXISTS idx_offres_ville        ON offres_structurees(ville);
CREATE INDEX IF NOT EXISTS idx_offres_contrat      ON offres_structurees(type_contrat);
CREATE INDEX IF NOT EXISTS idx_offres_seniorite    ON offres_structurees(niveau_seniorite);
CREATE INDEX IF NOT EXISTS idx_offres_salaire      ON offres_structurees(salaire_min, salaire_max);
CREATE INDEX IF NOT EXISTS idx_offres_date         ON offres_structurees(structured_at);
"""

class PostgresInserter:
    """Gère l'insertion des offres structurées dans PostgreSQL."""

    def __init__(self, database_url: str):
        self.engine = create_engine(database_url)
        self._init_table()
        logger.info("✅ PostgreSQL connecté")

    def _init_table(self):
        with self.engine.connect() as conn:
            conn.execute(text(SQL_CREATE_TABLE))
            conn.commit()

    def insert(self, mongo_id: str, offre_brute: dict, offre_struct: OffreStructuree) -> bool:
        sql = text("""
            INSERT INTO offres_structurees (
                mongo_id, source_site, url, titre_brut, entreprise_brute,
                titre_normalise, type_contrat, secteur,
                competences_techniques, competences_soft, diplome_requis,
                experience_duree_min, experience_duree_max,
                salaire_min, salaire_max,
                ville, region, teletravail,
                niveau_seniorite, langue_annonce,
                llm_provider, llm_model
            ) VALUES (
                :mongo_id, :source_site, :url, :titre_brut, :entreprise_brute,
                :titre_normalise, :type_contrat, :secteur,
                :competences_techniques::jsonb, :competences_soft::jsonb, :diplome_requis,
                :experience_duree_min, :experience_duree_max,
                :salaire_min, :salaire_max,
                :ville, :region, :teletravail,
                :niveau_seniorite, :langue_annonce,
                :llm_provider, :llm_model
            )
            ON CONFLICT (mongo_id) DO UPDATE SET
                titre_normalise        = EXCLUDED.titre_normalise,
                competences_techniques = EXCLUDED.competences_techniques,
                structured_at          = NOW()
        """)

        exp = offre_struct.experience
        sal = offre_struct.salaire
        loc = offre_struct.localisation

        try:
            with self.engine.connect() as conn:
                conn.execute(sql, {
                    "mongo_id":               mongo_id,
                    "source_site":            offre_brute.get("source_site"),
                    "url":                    offre_brute.get("url"),
                    "titre_brut":             offre_brute.get("titre_brut"),
                    "entreprise_brute":       offre_brute.get("entreprise_brute"),
                    "titre_normalise":        offre_struct.titre_normalise,
                    "type_contrat":           offre_struct.type_contrat,
                    "secteur":                offre_struct.secteur,
                    "competences_techniques": json.dumps(offre_struct.competences_techniques),
                    "competences_soft":       json.dumps(offre_struct.competences_soft),
                    "diplome_requis":         offre_struct.diplome_requis,
                    "experience_duree_min":   exp.duree_min if exp else None,
                    "experience_duree_max":   exp.duree_max if exp else None,
                    "salaire_min":            sal.min if sal else None,
                    "salaire_max":            sal.max if sal else None,
                    "ville":                  loc.ville if loc else None,
                    "region":                 loc.region if loc else None,
                    "teletravail":            loc.teletravail if loc else None,
                    "niveau_seniorite":       offre_struct.niveau_seniorite,
                    "langue_annonce":         offre_struct.langue_annonce,
                    "llm_provider":           LLM_PROVIDER,
                    "llm_model":              LLM_MODEL,
                })
                conn.commit()
            return True
        except Exception as e:
            logger.error("❌ Erreur PostgreSQL : %s", e)
            return False


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

def run_ner_pipeline():
    """
    Récupère les offres brutes (statut='raw') depuis MongoDB,
    les enrichit via LLM et les stocke dans PostgreSQL.
    """
    logger.info("🚀 Démarrage pipeline NER — Bloc 2")

    # Connexions
    mongo_client = MongoClient(MONGO_URI)
    col_offres   = mongo_client["nexus_emploi"]["raw_offres"]
    extractor    = NERExtractor()
    pg_inserter  = PostgresInserter(DATABASE_URL)

    # Récupérer les offres non traitées
    offres_raw = list(col_offres.find(
        {"statut_traitement": "raw"},
        limit=BATCH_SIZE
    ))
    logger.info("📥 %d offres brutes à traiter", len(offres_raw))

    stats = {"ok": 0, "erreurs": 0}

    for offre in offres_raw:
        mongo_id = str(offre["_id"])
        titre    = offre.get("titre_brut", "?")[:50]

        logger.info("🔍 Traitement : %s", titre)

        # 1. Extraction NER via LLM
        offre_struct = extractor.extraire(offre)
        if not offre_struct:
            stats["erreurs"] += 1
            continue

        # 2. Insertion PostgreSQL
        ok = pg_inserter.insert(mongo_id, offre, offre_struct)
        if not ok:
            stats["erreurs"] += 1
            continue

        # 3. Mise à jour statut MongoDB → "structured"
        col_offres.update_one(
            {"_id": offre["_id"]},
            {"$set": {
                "statut_traitement": "structured",
                "structured_at":     datetime.now(timezone.utc).isoformat(),
                "structured_data":   offre_struct.model_dump(),
            }}
        )
        stats["ok"] += 1
        logger.info("   ✅ %s → %d compétences extraites",
                    titre, len(offre_struct.competences_techniques))

    mongo_client.close()
    logger.info(
        "🏁 Pipeline NER terminé — Succès: %d | Erreurs: %d",
        stats["ok"], stats["erreurs"]
    )
    return stats


if __name__ == "__main__":
    run_ner_pipeline()