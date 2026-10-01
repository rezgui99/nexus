"""
NEXUS EMPLOI — Bloc 3 : Vectorisation & Matching Sémantique
============================================================
Auteur  : Aziz Rezgui (Projet de fin d'études MSc Data Management 2025-2026)

Pipeline :
  PostgreSQL (offres_structurees + cv_structures)
        │
        ▼
  FastEmbed (vectorisation texte → vecteurs 384 dimensions)
        │
        ▼
  Qdrant (stockage et recherche vectorielle)
        │
        ▼
  Score de similarité cosinus CV ↔ Offres → Top N matches

Dépendances:
    pip install fastembed qdrant-client sqlalchemy pg8000 python-dotenv
"""

import os
import json
import logging
from typing import Optional
from dotenv import load_dotenv

from fastembed import TextEmbedding
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams,
    PointStruct, Filter, FieldCondition, MatchValue
)
from sqlalchemy import create_engine, text

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("nexus_matching")

DATABASE_URL         = os.getenv("DATABASE_URL")
QDRANT_HOST          = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT          = int(os.getenv("QDRANT_PORT", 6333))
COLLECTION_OFFRES    = os.getenv("QDRANT_COLLECTION_OFFRES", "offres_vecteurs")
COLLECTION_CV        = os.getenv("QDRANT_COLLECTION_CV", "cv_vecteurs")
VECTOR_SIZE          = 384   # Dimension du modèle BAAI/bge-small-en-v1.5
TOP_N                = 10    # Nombre de résultats retournés


# ---------------------------------------------------------------------------
# 1. Connexions
# ---------------------------------------------------------------------------

def get_postgres():
    engine = create_engine(DATABASE_URL)
    logger.info("✅ PostgreSQL connecté")
    return engine

def get_qdrant():
    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    logger.info("✅ Qdrant connecté — %s:%d", QDRANT_HOST, QDRANT_PORT)
    return client

def get_embedder():
    logger.info("⏳ Chargement du modèle FastEmbed...")
    embedder = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
    logger.info("✅ Modèle FastEmbed chargé")
    return embedder


# ---------------------------------------------------------------------------
# 2. Initialisation des collections Qdrant
# ---------------------------------------------------------------------------

def init_collections(client: QdrantClient):
    """Crée les collections Qdrant si elles n'existent pas."""
    for collection_name in [COLLECTION_OFFRES, COLLECTION_CV]:
        existing = [c.name for c in client.get_collections().collections]
        if collection_name not in existing:
            client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(
                    size=VECTOR_SIZE,
                    distance=Distance.COSINE   # Similarité cosinus
                )
            )
            logger.info("✅ Collection Qdrant créée : %s", collection_name)
        else:
            logger.info("✅ Collection déjà existante : %s", collection_name)


# ---------------------------------------------------------------------------
# 3. Construction du texte à vectoriser
# ---------------------------------------------------------------------------

def build_offre_text(offre: dict) -> str:
    """
    Construit un texte riche représentant l'offre pour la vectorisation.
    Plus le texte est informatif, meilleur sera le matching.
    """
    parts = []

    if offre.get("titre_normalise"):
        parts.append(f"Poste: {offre['titre_normalise']}")

    if offre.get("competences_techniques"):
        competences = offre["competences_techniques"]
        if isinstance(competences, str):
            competences = json.loads(competences)
        parts.append(f"Compétences techniques: {', '.join(competences)}")

    if offre.get("competences_soft"):
        soft = offre["competences_soft"]
        if isinstance(soft, str):
            soft = json.loads(soft)
        parts.append(f"Soft skills: {', '.join(soft)}")

    if offre.get("secteur"):
        parts.append(f"Secteur: {offre['secteur']}")

    if offre.get("type_contrat"):
        parts.append(f"Contrat: {offre['type_contrat']}")

    if offre.get("niveau_seniorite"):
        parts.append(f"Niveau: {offre['niveau_seniorite']}")

    if offre.get("ville"):
        parts.append(f"Localisation: {offre['ville']}")

    if offre.get("diplome_requis"):
        parts.append(f"Diplôme requis: {offre['diplome_requis']}")

    if offre.get("experience_duree_min"):
        parts.append(f"Expérience: {offre['experience_duree_min']} à {offre.get('experience_duree_max', '?')} ans")

    return " | ".join(parts)


def build_cv_text(cv: dict) -> str:
    """
    Construit un texte riche représentant le CV pour la vectorisation.
    """
    parts = []

    if cv.get("dernier_poste"):
        parts.append(f"Poste actuel: {cv['dernier_poste']}")

    if cv.get("competences_techniques"):
        competences = cv["competences_techniques"]
        if isinstance(competences, str):
            competences = json.loads(competences)
        parts.append(f"Compétences techniques: {', '.join(competences)}")

    if cv.get("competences_soft"):
        soft = cv["competences_soft"]
        if isinstance(soft, str):
            soft = json.loads(soft)
        parts.append(f"Soft skills: {', '.join(soft)}")

    if cv.get("dernier_secteur"):
        parts.append(f"Secteur: {cv['dernier_secteur']}")

    if cv.get("niveau_seniorite"):
        parts.append(f"Niveau: {cv['niveau_seniorite']}")

    if cv.get("diplome_max"):
        parts.append(f"Diplôme: {cv['diplome_max']}")

    if cv.get("annees_experience_total"):
        parts.append(f"Expérience totale: {cv['annees_experience_total']} ans")

    if cv.get("ville"):
        parts.append(f"Localisation: {cv['ville']}")

    if cv.get("type_contrat_souhaite"):
        parts.append(f"Contrat souhaité: {cv['type_contrat_souhaite']}")

    return " | ".join(parts)


# ---------------------------------------------------------------------------
# 4. Indexation des offres dans Qdrant
# ---------------------------------------------------------------------------

def index_offres(engine, client: QdrantClient, embedder: TextEmbedding):
    """
    Récupère toutes les offres structurées depuis PostgreSQL,
    les vectorise et les indexe dans Qdrant.
    """
    logger.info("📥 Récupération des offres depuis PostgreSQL...")

    with engine.connect() as conn:
        result = conn.execute(text("SELECT * FROM offres_structurees"))
        offres = [dict(row._mapping) for row in result]

    logger.info("📊 %d offres à indexer", len(offres))

    if not offres:
        logger.warning("⚠️  Aucune offre trouvée — lance d'abord le Bloc 2")
        return 0

    # Construire les textes
    textes = [build_offre_text(o) for o in offres]

    # Vectoriser en batch
    logger.info("🔢 Vectorisation en cours...")
    vecteurs = list(embedder.embed(textes))

    # Indexer dans Qdrant
    points = []
    for i, (offre, vecteur) in enumerate(zip(offres, vecteurs)):
        points.append(PointStruct(
            id=offre["id"],
            vector=vecteur.tolist(),
            payload={
                "mongo_id":             offre.get("mongo_id"),
                "titre_normalise":      offre.get("titre_normalise"),
                "titre_brut":           offre.get("titre_brut"),
                "entreprise_brute":     offre.get("entreprise_brute"),
                "type_contrat":         offre.get("type_contrat"),
                "secteur":              offre.get("secteur"),
                "ville":                offre.get("ville"),
                "niveau_seniorite":     offre.get("niveau_seniorite"),
                "salaire_min":          offre.get("salaire_min"),
                "salaire_max":          offre.get("salaire_max"),
                "competences_techniques": offre.get("competences_techniques"),
                "url":                  offre.get("url"),
                "texte_vectorise":      textes[i],
            }
        ))

    # Upload par batch de 100
    batch_size = 100
    for i in range(0, len(points), batch_size):
        batch = points[i:i + batch_size]
        client.upsert(collection_name=COLLECTION_OFFRES, points=batch)

    logger.info("✅ %d offres indexées dans Qdrant", len(points))
    return len(points)


# ---------------------------------------------------------------------------
# 5. Indexation des CV dans Qdrant
# ---------------------------------------------------------------------------

def index_cv(engine, client: QdrantClient, embedder: TextEmbedding):
    """
    Récupère tous les CV structurés depuis PostgreSQL,
    les vectorise et les indexe dans Qdrant.
    """
    logger.info("📥 Récupération des CV depuis PostgreSQL...")

    with engine.connect() as conn:
        result = conn.execute(text("SELECT * FROM cv_structures"))
        cvs = [dict(row._mapping) for row in result]

    logger.info("📊 %d CV à indexer", len(cvs))

    if not cvs:
        logger.warning("⚠️  Aucun CV trouvé — lance d'abord le Bloc 2 CV")
        return 0

    textes = [build_cv_text(cv) for cv in cvs]

    logger.info("🔢 Vectorisation CV en cours...")
    vecteurs = list(embedder.embed(textes))

    points = []
    for i, (cv, vecteur) in enumerate(zip(cvs, vecteurs)):
        points.append(PointStruct(
            id=cv["id"],
            vector=vecteur.tolist(),
            payload={
                "candidat_id":           cv.get("candidat_id"),
                "dernier_poste":         cv.get("dernier_poste"),
                "niveau_seniorite":      cv.get("niveau_seniorite"),
                "annees_experience":     cv.get("annees_experience_total"),
                "competences_techniques": cv.get("competences_techniques"),
                "diplome_max":           cv.get("diplome_max"),
                "ville":                 cv.get("ville"),
                "type_contrat_souhaite": cv.get("type_contrat_souhaite"),
                "texte_vectorise":       textes[i],
            }
        ))

    client.upsert(collection_name=COLLECTION_CV, points=points)
    logger.info("✅ %d CV indexés dans Qdrant", len(points))
    return len(points)


# ---------------------------------------------------------------------------
# 6. Matching CV ↔ Offres
# ---------------------------------------------------------------------------

def match_cv_to_offres(
    cv_id: int,
    engine,
    client: QdrantClient,
    embedder: TextEmbedding,
    top_n: int = TOP_N,
    filtre_ville: Optional[str] = None,
    filtre_contrat: Optional[str] = None,
) -> list[dict]:
    """
    Trouve les offres les plus proches d'un CV donné.
    Retourne une liste triée par score de similarité décroissant.
    """
    # Récupérer le CV depuis PostgreSQL
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT * FROM cv_structures WHERE id = :id"),
            {"id": cv_id}
        )
        cv = result.fetchone()

    if not cv:
        logger.error("❌ CV id=%d introuvable", cv_id)
        return []

    cv_dict = dict(cv._mapping)
    texte_cv = build_cv_text(cv_dict)
    logger.info("🔍 Matching pour CV id=%d — %s", cv_id, cv_dict.get("dernier_poste", "?"))
    logger.info("   Texte vectorisé : %s", texte_cv[:100])

    # Vectoriser le CV
    vecteur_cv = list(embedder.embed([texte_cv]))[0].tolist()

    # Construire les filtres optionnels
    filtres = []
    if filtre_ville:
        filtres.append(FieldCondition(key="ville", match=MatchValue(value=filtre_ville)))
    if filtre_contrat:
        filtres.append(FieldCondition(key="type_contrat", match=MatchValue(value=filtre_contrat)))

    query_filter = Filter(must=filtres) if filtres else None

    # Recherche dans Qdrant
    resultats = client.search(
        collection_name=COLLECTION_OFFRES,
        query_vector=vecteur_cv,
        limit=top_n,
        query_filter=query_filter,
        with_payload=True,
    )

    # Formater les résultats
    matches = []
    for r in resultats:
        matches.append({
            "score":           round(r.score * 100, 2),   # Score en %
            "titre":           r.payload.get("titre_normalise") or r.payload.get("titre_brut"),
            "entreprise":      r.payload.get("entreprise_brute"),
            "ville":           r.payload.get("ville"),
            "type_contrat":    r.payload.get("type_contrat"),
            "niveau":          r.payload.get("niveau_seniorite"),
            "salaire_min":     r.payload.get("salaire_min"),
            "salaire_max":     r.payload.get("salaire_max"),
            "url":             r.payload.get("url"),
            "competences":     r.payload.get("competences_techniques"),
        })

    logger.info("✅ %d offres matchées", len(matches))
    return matches


# ---------------------------------------------------------------------------
# 7. Affichage des résultats
# ---------------------------------------------------------------------------

def afficher_matches(matches: list[dict], cv_info: str = ""):
    print()
    print("=" * 65)
    print(f"  🎯 TOP {len(matches)} OFFRES MATCHÉES — {cv_info}")
    print("=" * 65)

    for i, m in enumerate(matches, 1):
        score_bar = "█" * int(m["score"] / 10) + "░" * (10 - int(m["score"] / 10))
        salaire = ""
        if m.get("salaire_min") and m.get("salaire_max"):
            salaire = f" | 💰 {m['salaire_min']//1000}k-{m['salaire_max']//1000}k€"
        elif m.get("salaire_min"):
            salaire = f" | 💰 {m['salaire_min']//1000}k€+"

        print(f"\n  #{i} [{score_bar}] {m['score']}%")
        print(f"     📋 {m['titre']}")
        print(f"     🏢 {m['entreprise'] or 'Non précisé'}")
        print(f"     📍 {m['ville'] or 'Non précisé'} | {m['type_contrat'] or '?'}{salaire}")
        if m.get("competences"):
            comp = m["competences"]
            if isinstance(comp, str):
                comp = json.loads(comp)
            print(f"     🛠️  {', '.join(comp[:5])}")
        if m.get("url"):
            print(f"     🔗 {m['url']}")

    print()
    print("=" * 65)


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

def run_matching_pipeline():
    """
    Pipeline complet :
    1. Indexe toutes les offres et CV dans Qdrant
    2. Lance le matching pour tous les CV
    """
    logger.info("🚀 Démarrage pipeline Matching — Bloc 3")

    engine   = get_postgres()
    client   = get_qdrant()
    embedder = get_embedder()

    # Initialiser les collections
    init_collections(client)

    # Indexer les offres
    nb_offres = index_offres(engine, client, embedder)

    # Indexer les CV
    nb_cv = index_cv(engine, client, embedder)

    if nb_offres == 0:
        logger.error("❌ Aucune offre indexée — vérifie le Bloc 2")
        return

    if nb_cv == 0:
        logger.warning("⚠️  Aucun CV indexé — ingère des CV d'abord")
        logger.info("   Lance : python bloc1_ingestion/02_cv_parser_mongodb.py mon_cv.pdf")
        logger.info("   Puis  : python bloc2_llm_ner/05_ner_cv_llm.py")
        return

    # Matching pour chaque CV
    with engine.connect() as conn:
        cvs = conn.execute(text("SELECT id, dernier_poste, candidat_id FROM cv_structures")).fetchall()

    for cv_row in cvs:
        matches = match_cv_to_offres(
            cv_id=cv_row.id,
            engine=engine,
            client=client,
            embedder=embedder,
            top_n=TOP_N,
        )
        afficher_matches(matches, cv_info=cv_row.dernier_poste or cv_row.candidat_id)

    logger.info("🏁 Pipeline Matching terminé")


if __name__ == "__main__":
    run_matching_pipeline()