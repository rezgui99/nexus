"""
NEXUS EMPLOI — Bloc 2 : NER des CV candidats via LLM
=====================================================
Auteur  : Aziz Rezgui (Projet de fin d'études MSc Data Management 2025-2026)
Objectif: Extraire les entités structurées depuis les CV bruts MongoDB
          et les stocker dans PostgreSQL.

Pipeline :
  MongoDB (raw_cv, statut="raw")
      │
      ▼
  LLM NER (LangChain + Gemini/Groq)
      │
      ▼
  Structured JSON validé (Pydantic)
      │
      ├──► MongoDB : mise à jour statut → "structured"
      └──► PostgreSQL : insertion dans table cv_structures
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
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("nexus_ner_cv")

MONGO_URI    = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:nexus_password@localhost:5432/nexus_emploi")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
LLM_MODEL    = os.getenv("LLM_MODEL", "gemini-2.0-flash")
BATCH_SIZE   = 10


# ---------------------------------------------------------------------------
# Schéma Pydantic — CV structuré
# ---------------------------------------------------------------------------

class FormationCV(BaseModel):
    diplome:        Optional[str] = None
    etablissement:  Optional[str] = None
    annee:          Optional[str] = None   # "2020" ou "2020-2025"
    domaine:        Optional[str] = None

class ExperienceCV(BaseModel):
    poste:          Optional[str] = None
    entreprise:     Optional[str] = None
    debut:          Optional[str] = None   # "2022" ou "2022-03"
    fin:            Optional[str] = None   # "2024" ou "present"
    duree_mois:     Optional[int] = None
    description:    Optional[str] = None

class LocalisationCV(BaseModel):
    ville:          Optional[str] = None
    region:         Optional[str] = None
    mobilite:       Optional[str] = None   # "locale" | "nationale" | "internationale"

class CVStructure(BaseModel):
    """Schéma complet d'un CV après NER."""
    # Identité (anonymisée — pas de nom/email stocké en clair)
    annees_experience_total: Optional[int]  = Field(None, description="Total années d'expérience")
    niveau_seniorite:        Optional[str]  = Field(None, description="junior|confirme|senior|lead")
    langue_cv:               str            = Field("fr")  # fr | en | ar

    # Compétences
    competences_techniques:  list[str]      = Field(default_factory=list)
    competences_soft:        list[str]      = Field(default_factory=list)
    langues_parles:          list[str]      = Field(default_factory=list, description="français, anglais, etc.")

    # Formations & expériences
    formations:              list[FormationCV]    = Field(default_factory=list)
    experiences:             list[ExperienceCV]   = Field(default_factory=list)
    dernier_poste:           Optional[str]        = Field(None, description="Intitulé du dernier poste")
    dernier_secteur:         Optional[str]        = None

    # Souhaits (si mentionnés)
    type_contrat_souhaite:   Optional[str]  = Field(None, description="CDI|CDD|Stage|Alternance|Freelance")
    salaire_souhaite_min:    Optional[int]  = None
    salaire_souhaite_max:    Optional[int]  = None
    localisation:            Optional[LocalisationCV] = None

    # Diplôme le plus élevé
    diplome_max:             Optional[str]  = Field(None, description="Bac+2|Bac+3|Bac+5|Doctorat")


# ---------------------------------------------------------------------------
# Extracteur NER CV
# ---------------------------------------------------------------------------

PROMPT_CV = (
    "You are an expert HR analyst. "
    "The CV may be in Arabic, French or English. "
    "Respond ONLY with valid JSON, no markdown.\n\n"
    "Fill this exact JSON schema (keep all keys):\n"
    '{{"annees_experience_total": null, '
    '"niveau_seniorite": null, '
    '"langue_cv": "fr", '
    '"competences_techniques": [], '
    '"competences_soft": [], '
    '"langues_parles": [], '
    '"formations": [], '
    '"experiences": [], '
    '"dernier_poste": null, '
    '"dernier_secteur": null, '
    '"type_contrat_souhaite": null, '
    '"salaire_souhaite_min": null, '
    '"salaire_souhaite_max": null, '
    '"localisation": null, '
    '"diplome_max": null}}\n\n'
    "Rules:\n"
    "- niveau_seniorite: junior|confirme|senior|lead|null\n"
    "- diplome_max: Bac+2|Bac+3|Bac+5|Doctorat|null\n"
    "- annee in formations: string like 2020\n"
    "- annees_experience_total: integer or null\n\n"
    "CV TEXT:\n{texte_cv}"
)


def get_llm():
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
    raise ValueError(f"LLM_PROVIDER inconnu : {LLM_PROVIDER}")


class CVNERExtractor:

    def __init__(self):
        self.llm = get_llm()
        logger.info("✅ LLM initialisé — %s / %s", LLM_PROVIDER, LLM_MODEL)

    def extraire(self, cv_brut: dict) -> Optional[CVStructure]:
        texte = cv_brut.get("texte_brut", "")[:5000]  # Limite tokens
        prompt = PROMPT_CV.format(texte_cv=texte)

        try:
            response = self.llm.invoke(prompt)
            raw_json = response.content.strip()
            logger.debug("🔍 Réponse LLM brute : %s", raw_json[:300])

            # Nettoyage robuste — enlever les backticks markdown
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
            else:
                logger.error("Aucun JSON trouve dans la reponse LLM : %s", raw_json[:300])
                return None

            data = json.loads(raw_json)

            # Normaliser les champs — gérer les langues non-latines (arabe, etc.)
            # Convertir les valeurs arabes/non-ASCII en equivalents standards
            if isinstance(data.get("langue_cv"), str):
                lang = data["langue_cv"].lower().strip()
                if lang not in ["fr", "en", "ar"]:
                    data["langue_cv"] = "ar" if any(c > chr(127) for c in lang) else "fr"

            # Nettoyer les listes — garder uniquement les strings valides
            for field in ["competences_techniques", "competences_soft", "langues_parles"]:
                if isinstance(data.get(field), list):
                    data[field] = [
                        str(item) for item in data[field] 
                        if item and isinstance(item, (str, int, float))
                    ]
                elif data.get(field) is None:
                    data[field] = []

            # Nettoyer les formations — annee peut etre str ou int
            if isinstance(data.get("formations"), list):
                cleaned = []
                for f in data["formations"]:
                    if isinstance(f, dict):
                        if "annee" in f and f["annee"] is not None:
                            f["annee"] = str(f["annee"]) if f["annee"] else None
                        cleaned.append(f)
                data["formations"] = cleaned

            # Nettoyer les experiences
            if isinstance(data.get("experiences"), list):
                cleaned_exp = []
                for e in data["experiences"]:
                    if isinstance(e, dict):
                        for date_field in ["debut", "fin"]:
                            if date_field in e and e[date_field]:
                                e[date_field] = str(e[date_field])
                        cleaned_exp.append(e)
                data["experiences"] = cleaned_exp

            # Normaliser localisation — peut etre string ou dict
            if "localisation" in data and isinstance(data["localisation"], str):
                loc_str = data["localisation"].strip()
                if loc_str and loc_str.lower() != "null":
                    parts = loc_str.split(",")
                    data["localisation"] = {
                        "ville": parts[0].strip() if parts else None,
                        "region": parts[1].strip() if len(parts) > 1 else None,
                        "mobilite": None
                    }
                else:
                    data["localisation"] = None

            # Normaliser les types avant Pydantic
            # annees_experience_total doit etre int ou None
            if "annees_experience_total" in data:
                try:
                    v = data["annees_experience_total"]
                    data["annees_experience_total"] = int(v) if v is not None else None
                except (ValueError, TypeError):
                    data["annees_experience_total"] = None

            # salaires doivent etre int ou None
            for sal_field in ["salaire_souhaite_min", "salaire_souhaite_max"]:
                if sal_field in data:
                    try:
                        v = data[sal_field]
                        data[sal_field] = int(v) if v is not None else None
                    except (ValueError, TypeError):
                        data[sal_field] = None

            # niveau_seniorite doit etre en minuscules
            if data.get("niveau_seniorite"):
                niv = str(data["niveau_seniorite"]).lower().strip()
                valid = ["junior", "confirme", "senior", "lead"]
                data["niveau_seniorite"] = niv if niv in valid else None

            # diplome_max normalisation
            if data.get("diplome_max"):
                dip = str(data["diplome_max"]).strip()
                valid_dip = ["Bac+2", "Bac+3", "Bac+5", "Doctorat"]
                # Correspondances courantes
                mapping = {
                    "msc": "Bac+5", "master": "Bac+5", "m2": "Bac+5",
                    "bac+5": "Bac+5", "bac+3": "Bac+3", "bac+2": "Bac+2",
                    "doctorat": "Doctorat", "phd": "Doctorat",
                    "licence": "Bac+3", "bachelor": "Bac+3",
                }
                data["diplome_max"] = mapping.get(dip.lower(), dip if dip in valid_dip else None)

            # formations : annee doit etre str
            if isinstance(data.get("formations"), list):
                cleaned = []
                for f in data["formations"]:
                    if isinstance(f, dict):
                        if "annee" in f and f["annee"] is not None:
                            f["annee"] = str(f["annee"])
                        cleaned.append(f)
                    elif isinstance(f, str):
                        cleaned.append({"diplome": f, "etablissement": None, "annee": None, "domaine": None})
                data["formations"] = cleaned

            # experiences : debut/fin doivent etre str
            if isinstance(data.get("experiences"), list):
                cleaned_exp = []
                for e in data["experiences"]:
                    if isinstance(e, dict):
                        for date_field in ["debut", "fin", "date_debut", "date_fin"]:
                            if date_field in e and e[date_field]:
                                e[date_field] = str(e[date_field])
                        # Renommer date_debut/date_fin en debut/fin si necessaire
                        if "date_debut" in e and "debut" not in e:
                            e["debut"] = e.pop("date_debut")
                        if "date_fin" in e and "fin" not in e:
                            e["fin"] = e.pop("date_fin")
                        cleaned_exp.append(e)
                data["experiences"] = cleaned_exp

            return CVStructure(**data)

        except json.JSONDecodeError as e:
            logger.error("❌ JSON invalide pour CV %s : %s", cv_brut.get("fichier_nom", "?"), e)
            logger.error("   Raw JSON: %s", raw_json[:200])
            return None
        except Exception as e:
            logger.error("❌ Erreur LLM pour CV %s : %s", cv_brut.get("fichier_nom", "?"), e)
            import traceback
            logger.error(traceback.format_exc())
            return None


# ---------------------------------------------------------------------------
# Stockage PostgreSQL
# ---------------------------------------------------------------------------

SQL_CREATE_TABLE_CV = """
CREATE TABLE IF NOT EXISTS cv_structures (
    id                      SERIAL PRIMARY KEY,
    mongo_id                VARCHAR(24) UNIQUE NOT NULL,
    candidat_id             VARCHAR(16),        -- Pseudo-anonyme

    -- Données structurées (NER)
    annees_experience_total INTEGER,
    niveau_seniorite        VARCHAR(20),
    langue_cv               VARCHAR(5),
    competences_techniques  JSONB,
    competences_soft        JSONB,
    langues_parles          JSONB,
    formations              JSONB,
    experiences             JSONB,
    dernier_poste           TEXT,
    dernier_secteur         TEXT,
    type_contrat_souhaite   VARCHAR(20),
    salaire_souhaite_min    INTEGER,
    salaire_souhaite_max    INTEGER,
    ville                   TEXT,
    region                  TEXT,
    mobilite                VARCHAR(20),
    diplome_max             VARCHAR(20),

    -- Métadonnées
    structured_at           TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    llm_provider            VARCHAR(20),
    llm_model               VARCHAR(50),
    pipeline_version        VARCHAR(10) DEFAULT '1.0.0'
);

CREATE INDEX IF NOT EXISTS idx_cv_competences ON cv_structures USING GIN(competences_techniques);
CREATE INDEX IF NOT EXISTS idx_cv_seniorite   ON cv_structures(niveau_seniorite);
CREATE INDEX IF NOT EXISTS idx_cv_ville       ON cv_structures(ville);
CREATE INDEX IF NOT EXISTS idx_cv_diplome     ON cv_structures(diplome_max);
CREATE INDEX IF NOT EXISTS idx_cv_salaire     ON cv_structures(salaire_souhaite_min, salaire_souhaite_max);
"""


class CVPostgresInserter:

    def __init__(self, database_url: str):
        self.engine = create_engine(database_url)
        with self.engine.connect() as conn:
            conn.execute(text(SQL_CREATE_TABLE_CV))
            conn.commit()
        logger.info("✅ Table cv_structures prête")

    def insert(self, mongo_id: str, cv_brut: dict, cv_struct: CVStructure) -> bool:
        sql = text("""
            INSERT INTO cv_structures (
                mongo_id, candidat_id,
                annees_experience_total, niveau_seniorite, langue_cv,
                competences_techniques, competences_soft, langues_parles,
                formations, experiences,
                dernier_poste, dernier_secteur,
                type_contrat_souhaite, salaire_souhaite_min, salaire_souhaite_max,
                ville, region, mobilite, diplome_max,
                llm_provider, llm_model
            ) VALUES (
                :mongo_id, :candidat_id,
                :annees_experience_total, :niveau_seniorite, :langue_cv,
                :competences_techniques::jsonb, :competences_soft::jsonb, :langues_parles::jsonb,
                :formations::jsonb, :experiences::jsonb,
                :dernier_poste, :dernier_secteur,
                :type_contrat_souhaite, :salaire_souhaite_min, :salaire_souhaite_max,
                :ville, :region, :mobilite, :diplome_max,
                :llm_provider, :llm_model
            )
            ON CONFLICT (mongo_id) DO UPDATE SET
                competences_techniques  = EXCLUDED.competences_techniques,
                niveau_seniorite        = EXCLUDED.niveau_seniorite,
                structured_at           = NOW()
        """)

        loc = cv_struct.localisation
        try:
            with self.engine.connect() as conn:
                conn.execute(sql, {
                    "mongo_id":                 mongo_id,
                    "candidat_id":              cv_brut.get("candidat_id"),
                    "annees_experience_total":  cv_struct.annees_experience_total,
                    "niveau_seniorite":         cv_struct.niveau_seniorite,
                    "langue_cv":                cv_struct.langue_cv,
                    "competences_techniques":   json.dumps(cv_struct.competences_techniques),
                    "competences_soft":         json.dumps(cv_struct.competences_soft),
                    "langues_parles":           json.dumps(cv_struct.langues_parles),
                    "formations":               json.dumps([f.model_dump() for f in cv_struct.formations]),
                    "experiences":              json.dumps([e.model_dump() for e in cv_struct.experiences]),
                    "dernier_poste":            cv_struct.dernier_poste,
                    "dernier_secteur":          cv_struct.dernier_secteur,
                    "type_contrat_souhaite":    cv_struct.type_contrat_souhaite,
                    "salaire_souhaite_min":     cv_struct.salaire_souhaite_min,
                    "salaire_souhaite_max":     cv_struct.salaire_souhaite_max,
                    "ville":                    loc.ville if loc else None,
                    "region":                   loc.region if loc else None,
                    "mobilite":                 loc.mobilite if loc else None,
                    "diplome_max":              cv_struct.diplome_max,
                    "llm_provider":             LLM_PROVIDER,
                    "llm_model":                LLM_MODEL,
                })
                conn.commit()
            return True
        except Exception as e:
            logger.error("❌ Erreur PostgreSQL CV : %s", e)
            return False


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

def run_ner_cv_pipeline():
    logger.info("🚀 Démarrage pipeline NER CV — Bloc 2")

    mongo_client = MongoClient(MONGO_URI)
    col_cv       = mongo_client["nexus_emploi"]["raw_cv"]
    extractor    = CVNERExtractor()
    pg_inserter  = CVPostgresInserter(DATABASE_URL)

    cvs_raw = list(col_cv.find({"statut_traitement": "raw"}, limit=BATCH_SIZE))
    logger.info("📥 %d CV bruts à traiter", len(cvs_raw))

    stats = {"ok": 0, "erreurs": 0}

    for cv in cvs_raw:
        mongo_id = str(cv["_id"])
        fichier  = cv.get("fichier_nom", "?")

        logger.info("🔍 Traitement : %s", fichier)

        cv_struct = extractor.extraire(cv)
        if not cv_struct:
            stats["erreurs"] += 1
            continue

        ok = pg_inserter.insert(mongo_id, cv, cv_struct)
        if not ok:
            stats["erreurs"] += 1
            continue

        col_cv.update_one(
            {"_id": cv["_id"]},
            {"$set": {
                "statut_traitement": "structured",
                "structured_at":     datetime.now(timezone.utc).isoformat(),
                "structured_data":   cv_struct.model_dump(),
            }}
        )
        stats["ok"] += 1
        logger.info("   ✅ %s → %d compétences | %s ans exp.",
                    fichier,
                    len(cv_struct.competences_techniques),
                    cv_struct.annees_experience_total or "?")

    mongo_client.close()
    logger.info("🏁 Pipeline NER CV terminé — Succès: %d | Erreurs: %d",
                stats["ok"], stats["erreurs"])
    return stats


if __name__ == "__main__":
    run_ner_cv_pipeline()