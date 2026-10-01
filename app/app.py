"""
NEXUS EMPLOI — Bloc 5 : Application Streamlit
==============================================
Auteur  : Aziz Rezgui (Projet de fin d'études MSc Data Management 2025-2026)

Deux vues :
  👤 Vue Candidat  : Upload CV → NER → Matching → Top offres
  🏢 Vue Organisme : KPI du marché de l'emploi en temps réel

Lancement :
    streamlit run app/app.py

Dépendances :
    pip install streamlit plotly pandas fastembed qdrant-client
               sqlalchemy pg8000 langchain langchain-google-genai
               pymongo python-dotenv unstructured pypdf python-docx
"""

import os
import json
import time
import tempfile
import logging
from pathlib import Path
from typing import Optional

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration page
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Nexus Emploi",
    page_icon="🔗",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ---------------------------------------------------------------------------
# CSS personnalisé
# ---------------------------------------------------------------------------

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Sans:wght@300;400;500&display=swap');

    :root {
        --primary: #0A0F1E;
        --accent: #4361EE;
        --accent2: #F72585;
        --success: #06D6A0;
        --warning: #FFB703;
        --surface: #111827;
        --surface2: #1F2937;
        --text: #F9FAFB;
        --text2: #9CA3AF;
        --border: #374151;
    }

    html, body, [class*="css"] {
        font-family: 'DM Sans', sans-serif;
        background-color: var(--primary);
        color: var(--text);
    }

    h1, h2, h3 { font-family: 'Syne', sans-serif; }

    .main { background-color: var(--primary); }

    /* Header principal */
    .nexus-header {
        background: linear-gradient(135deg, #0A0F1E 0%, #1a1f3a 50%, #0A0F1E 100%);
        border-bottom: 1px solid var(--border);
        padding: 2rem 0 1.5rem 0;
        margin-bottom: 2rem;
        text-align: center;
    }
    .nexus-logo {
        font-family: 'Syne', sans-serif;
        font-size: 2.8rem;
        font-weight: 800;
        background: linear-gradient(90deg, #4361EE, #F72585);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        letter-spacing: -1px;
    }
    .nexus-tagline {
        color: var(--text2);
        font-size: 0.95rem;
        letter-spacing: 0.15em;
        text-transform: uppercase;
        margin-top: 0.3rem;
    }

    /* Cards */
    .card {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 16px;
        padding: 1.5rem;
        margin-bottom: 1rem;
        transition: border-color 0.2s;
    }
    .card:hover { border-color: var(--accent); }

    /* Score badge */
    .score-badge {
        display: inline-block;
        padding: 0.3rem 0.8rem;
        border-radius: 999px;
        font-family: 'Syne', sans-serif;
        font-weight: 700;
        font-size: 1.1rem;
    }
    .score-high  { background: rgba(6,214,160,0.15);  color: #06D6A0; border: 1px solid #06D6A0; }
    .score-mid   { background: rgba(255,183,3,0.15);   color: #FFB703; border: 1px solid #FFB703; }
    .score-low   { background: rgba(247,37,133,0.15);  color: #F72585; border: 1px solid #F72585; }

    /* Compétences tags */
    .skill-tag {
        display: inline-block;
        background: rgba(67,97,238,0.15);
        color: #818CF8;
        border: 1px solid rgba(67,97,238,0.3);
        border-radius: 6px;
        padding: 0.15rem 0.6rem;
        font-size: 0.78rem;
        margin: 0.2rem;
        font-family: 'DM Mono', monospace;
    }

    /* KPI cards */
    .kpi-card {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 1.2rem 1.5rem;
        text-align: center;
    }
    .kpi-value {
        font-family: 'Syne', sans-serif;
        font-size: 2.2rem;
        font-weight: 800;
        color: var(--accent);
    }
    .kpi-label {
        color: var(--text2);
        font-size: 0.82rem;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        margin-top: 0.3rem;
    }

    /* Barre de progression */
    .match-bar-bg {
        background: var(--surface2);
        border-radius: 999px;
        height: 6px;
        margin-top: 0.5rem;
    }
    .match-bar-fill {
        height: 6px;
        border-radius: 999px;
        background: linear-gradient(90deg, #4361EE, #F72585);
    }

    /* Sidebar */
    [data-testid="stSidebar"] {
        background: var(--surface) !important;
        border-right: 1px solid var(--border) !important;
    }

    /* Boutons */
    .stButton > button {
        background: linear-gradient(135deg, #4361EE, #3730A3);
        color: white;
        border: none;
        border-radius: 10px;
        padding: 0.6rem 1.5rem;
        font-family: 'Syne', sans-serif;
        font-weight: 600;
        letter-spacing: 0.05em;
        transition: all 0.2s;
        width: 100%;
    }
    .stButton > button:hover {
        background: linear-gradient(135deg, #F72585, #4361EE);
        transform: translateY(-1px);
    }

    /* Upload zone */
    [data-testid="stFileUploader"] {
        border: 2px dashed var(--border);
        border-radius: 12px;
        padding: 1rem;
        background: var(--surface);
    }

    /* Status */
    .status-ok   { color: var(--success); }
    .status-warn { color: var(--warning); }
    .status-err  { color: var(--accent2); }

    /* Divider */
    hr { border-color: var(--border) !important; opacity: 0.3; }

    /* Hide Streamlit branding */
    #MainMenu, footer { visibility: hidden; }
    .stDeployButton { display: none; }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.markdown("""
<div class="nexus-header">
    <div class="nexus-logo">🔗 NEXUS EMPLOI</div>
    <div class="nexus-tagline">Pilotage du marché de l'emploi par l'IA Générative</div>
</div>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Imports internes (lazy — évite les erreurs si modules absents)
# ---------------------------------------------------------------------------

@st.cache_resource(show_spinner=False)
def load_connections():
    """Charge toutes les connexions une seule fois."""
    from sqlalchemy import create_engine
    from pymongo import MongoClient
    from qdrant_client import QdrantClient
    from fastembed import TextEmbedding

    database_url = os.getenv("DATABASE_URL")
    mongo_uri    = os.getenv("MONGO_URI", "mongodb://localhost:27017")

    engine  = create_engine(database_url)
    mongo   = MongoClient(mongo_uri)
    qdrant  = QdrantClient(
        host=os.getenv("QDRANT_HOST", "localhost"),
        port=int(os.getenv("QDRANT_PORT", 6333))
    )
    embedder = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")

    return engine, mongo, qdrant, embedder


def get_llm():
    from langchain_google_genai import ChatGoogleGenerativeAI
    return ChatGoogleGenerativeAI(
        model=os.getenv("LLM_MODEL", "gemini-2.0-flash"),
        google_api_key=os.getenv("GEMINI_API_KEY"),
        temperature=0,
    )


# ---------------------------------------------------------------------------
# Sidebar — Navigation
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("### 🔗 Navigation")
    vue = st.radio(
        "Navigation",
        ["👤 Vue Candidat", "🏢 Vue Organisme"],
        label_visibility="collapsed"
    )

    st.markdown("---")
    st.markdown("### ⚙️ Paramètres")

    top_n = st.slider("Nombre de résultats", 3, 20, 10)
    filtre_contrat = st.selectbox(
        "Type de contrat",
        ["Tous", "CDI", "CDD", "Stage", "Alternance", "Freelance"]
    )
    filtre_ville = st.text_input("Ville (optionnel)", placeholder="Paris, Lyon...")

    st.markdown("---")
    st.markdown("### 📊 Statut système")

    try:
        engine, mongo, qdrant, embedder = load_connections()
        st.markdown('<span class="status-ok">● MongoDB</span>', unsafe_allow_html=True)
        st.markdown('<span class="status-ok">● PostgreSQL</span>', unsafe_allow_html=True)
        st.markdown('<span class="status-ok">● Qdrant</span>', unsafe_allow_html=True)
        st.markdown('<span class="status-ok">● FastEmbed</span>', unsafe_allow_html=True)
        connections_ok = True
    except Exception as e:
        st.markdown('<span class="status-err">● Connexion échouée</span>', unsafe_allow_html=True)
        st.error(f"Erreur : {e}")
        connections_ok = False


# ===========================================================================
# VUE CANDIDAT
# ===========================================================================

if vue == "👤 Vue Candidat":

    col1, col2 = st.columns([1, 2], gap="large")

    # ---- Colonne gauche : Upload CV ----
    with col1:
        st.markdown("### 📄 Ton CV")

        uploaded_file = st.file_uploader(
            "Dépose ton CV ici",
            type=["pdf", "docx", "txt"],
            help="Formats acceptés : PDF, DOCX, TXT"
        )

        if uploaded_file:
            st.success(f"✅ {uploaded_file.name}")

            # Afficher les infos du fichier
            st.markdown(f"""
            <div class="card">
                <div style="color: var(--text2); font-size: 0.8rem;">FICHIER</div>
                <div style="font-family: 'Syne', sans-serif; font-weight: 600; margin-top: 0.3rem;">
                    {uploaded_file.name}
                </div>
                <div style="color: var(--text2); font-size: 0.8rem; margin-top: 0.5rem;">
                    {round(uploaded_file.size / 1024, 1)} KB
                </div>
            </div>
            """, unsafe_allow_html=True)

            lancer = st.button("🚀 Lancer le matching", use_container_width=True)
        else:
            st.markdown("""
            <div class="card" style="text-align:center; padding: 2rem;">
                <div style="font-size: 2rem;">📎</div>
                <div style="color: var(--text2); margin-top: 0.5rem; font-size: 0.9rem;">
                    Dépose ton CV pour trouver<br>les offres qui te correspondent
                </div>
            </div>
            """, unsafe_allow_html=True)
            lancer = False

    # ---- Colonne droite : Résultats ----
    with col2:
        st.markdown("### 🎯 Offres recommandées")

        if uploaded_file and lancer and connections_ok:

            with st.spinner("🔍 Analyse de ton CV en cours..."):

                # 0. Extraire les mots-clés du CV pour le scraping
                import tempfile as _tf2
                suffix2 = Path(uploaded_file.name).suffix
                # Lire le contenu complet une seule fois et le garder en mémoire
                uploaded_file.seek(0)
                _file_content = uploaded_file.read()
                with _tf2.NamedTemporaryFile(delete=False, suffix=suffix2) as tmp2:
                    tmp2.write(_file_content)
                    tmp_path2 = tmp2.name

                keywords_cv = ""
                try:
                    from pypdf import PdfReader as _PDFReader
                    reader = _PDFReader(tmp_path2)
                    cv_text_raw = ""
                    for page in reader.pages:
                        cv_text_raw += (page.extract_text() or "") + " "

                    TECH_KEYWORDS = [
                        "python", "sql", "spark", "kafka", "airflow", "dbt",
                        "databricks", "snowflake", "bigquery", "docker", "kubernetes",
                        "tensorflow", "pytorch", "scikit-learn", "mlflow", "fastapi",
                        "power bi", "tableau", "looker", "aws", "azure", "gcp",
                        "data engineer", "data scientist", "data analyst", "ml engineer",
                        "machine learning", "deep learning", "nlp", "mongodb", "postgresql",
                        "elasticsearch", "git", "terraform", "scala", "java", "r",
                        "hadoop", "hive", "kafka", "redis", "mysql", "oracle",
                        "angular", "react", "spring", "php", "symfony", "django",
                        "pandas", "numpy", "matplotlib", "seaborn", "plotly",
                        "langchain", "openai", "llm", "rag", "embedding",
                        "business intelligence", "etl", "elt", "data warehouse",
                        "data lake", "pipeline", "reporting", "kpi", "dashboard",
                    ]
                    POSTES = [
                        "data engineer", "data scientist", "data analyst",
                        "ml engineer", "data manager", "business analyst",
                        "bi developer", "data architect", "mlops engineer",
                    ]
                    cv_text_lower = cv_text_raw.lower()
                    found = [kw for kw in TECH_KEYWORDS if kw in cv_text_lower]
                    postes = [k for k in found if k in POSTES]
                    techs = [k for k in found if k not in POSTES]

                    # Construire une requete plus riche
                    if postes:
                        # Poste principal + 3 meilleures techs
                        keywords_cv = " ".join([postes[0]] + techs[:3])
                    elif techs:
                        # Juste les techs si pas de poste detecte
                        keywords_cv = " ".join(techs[:4])
                    else:
                        keywords_cv = "data analyst"

                    # Limiter a 60 caracteres pour l'URL APEC
                    keywords_cv = keywords_cv[:60].strip()
                    if keywords_cv:
                        st.info(f"🎯 Mots-clés détectés : **{keywords_cv}**")
                except Exception as _e:
                    keywords_cv = "data engineer"
                    st.info("🎯 Mots-clés par défaut : **data engineer**")

                # 1. Sauvegarder le fichier temporairement
                suffix = Path(uploaded_file.name).suffix
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(_file_content)  # Utiliser le contenu déjà lu
                    tmp_path = tmp.name

                # 2. Parser le CV
                try:
                    import sys, importlib.util
                    _spec = importlib.util.spec_from_file_location(
                        "cv_parser_mongodb",
                        str(Path(__file__).parent.parent / "bloc1_ingestion" / "02_cv_parser_mongodb.py")
                    )
                    _mod = importlib.util.module_from_spec(_spec)
                    _spec.loader.exec_module(_mod)
                    CVParser = _mod.CVParser
                    CVMongoInserter = _mod.CVMongoInserter

                    parser = CVParser()
                    cv_raw = parser.parse(tmp_path)

                    if not cv_raw:
                        st.error("❌ Impossible d'extraire le texte du CV")
                        st.stop()

                    # Insérer dans MongoDB
                    inserter = CVMongoInserter(
                        os.getenv("MONGO_URI", "mongodb://localhost:27017"),
                        "nexus_emploi", "raw_cv"
                    )
                    mongo_id = inserter.insert(cv_raw)
                    inserter.close()

                except Exception as e:
                    st.error(f"❌ Erreur parsing CV : {e}")
                    st.stop()

            with st.spinner(f"📡 Scraping des offres APEC pour : {keywords_cv}..."):
                try:
                    import importlib.util as _ilu3
                    _s3 = _ilu3.spec_from_file_location(
                        "scraper",
                        str(Path(__file__).parent.parent / "bloc1_ingestion" / "scraper_offres_mongodb.py")
                    )
                    _m3 = _ilu3.module_from_spec(_s3)
                    _s3.loader.exec_module(_m3)

                    scraper = _m3.ApecXHRScraper()
                    offres = scraper.scrape(keywords=keywords_cv, nb_offres=top_n)
                    scraper.close()

                    mongo_conn = _m3.MongoConnector(
                        os.getenv("MONGO_URI", "mongodb://localhost:27017"),
                        "nexus_emploi", "raw_offres"
                    )
                    nb_inserted = 0
                    for offre in offres:
                        if offre.titre_brut:
                            if mongo_conn.insert(offre):
                                nb_inserted += 1
                    mongo_conn.close()
                    st.success(f"✅ {nb_inserted} nouvelles offres scrapées depuis APEC")
                except Exception as _e_scrap:
                    st.warning(f"⚠️ Scraping partiel : {_e_scrap}")

            with st.spinner("🤖 Extraction des entités par IA..."):
                try:
                    import importlib.util as _ilu
                    from dataclasses import asdict
                    _s2 = _ilu.spec_from_file_location(
                        "ner_cv_llm",
                        str(Path(__file__).parent.parent / "bloc2_llm_ner" / "05_ner_cv_llm.py")
                    )
                    _m2 = _ilu.module_from_spec(_s2)
                    _s2.loader.exec_module(_m2)
                    CVNERExtractor = _m2.CVNERExtractor
                    CVPostgresInserter = _m2.CVPostgresInserter

                    extractor = CVNERExtractor()
                    cv_struct = extractor.extraire(asdict(cv_raw))

                    if not cv_struct:
                        st.error("❌ Erreur NER — vérifie ta clé API")
                        st.stop()

                    pg_inserter = CVPostgresInserter(os.getenv("DATABASE_URL"))
                    from pymongo import MongoClient as _MC
                    _mc = _MC(os.getenv("MONGO_URI"))
                    cv_doc = _mc["nexus_emploi"]["raw_cv"].find_one(
                        {"content_hash": cv_raw.content_hash}
                    )
                    if cv_doc:
                        pg_inserter.insert(str(cv_doc["_id"]), asdict(cv_raw), cv_struct)
                except Exception as e:
                    import traceback
                    st.error(f"❌ Erreur NER : {e}")
                    st.code(traceback.format_exc())
                    st.stop()

            with st.spinner("🔢 Calcul du matching sémantique..."):

                # 4. Matching
                try:
                    from sqlalchemy import text as sql_text

                    # Construire le texte du CV
                    parts = []
                    if cv_struct.dernier_poste:
                        parts.append(f"Poste: {cv_struct.dernier_poste}")
                    if cv_struct.competences_techniques:
                        parts.append(f"Compétences: {', '.join(cv_struct.competences_techniques)}")
                    if cv_struct.niveau_seniorite:
                        parts.append(f"Niveau: {cv_struct.niveau_seniorite}")
                    if cv_struct.diplome_max:
                        parts.append(f"Diplôme: {cv_struct.diplome_max}")
                    texte_cv = " | ".join(parts)

                    # Vectoriser
                    vecteur = list(embedder.embed([texte_cv]))[0].tolist()

                    # Filtres
                    from qdrant_client.models import Filter, FieldCondition, MatchValue
                    filtres = []
                    if filtre_contrat != "Tous":
                        filtres.append(FieldCondition(key="type_contrat", match=MatchValue(value=filtre_contrat)))
                    if filtre_ville.strip():
                        filtres.append(FieldCondition(key="ville", match=MatchValue(value=filtre_ville.strip())))
                    query_filter = Filter(must=filtres) if filtres else None

                    # Recherche
                    resultats = qdrant.search(
                        collection_name=os.getenv("QDRANT_COLLECTION_OFFRES", "offres_vecteurs"),
                        query_vector=vecteur,
                        limit=top_n,
                        query_filter=query_filter,
                        with_payload=True,
                    )

                except Exception as e:
                    st.error(f"❌ Erreur matching : {e}")
                    st.stop()

            # 5. Afficher les résultats
            if not resultats:
                st.warning("⚠️ Aucune offre trouvée — indexe d'abord les offres (Bloc 3)")
            else:
                # Profil extrait
                with st.expander("🧠 Profil extrait par l'IA", expanded=False):
                    col_a, col_b, col_c = st.columns(3)
                    with col_a:
                        st.metric("Poste", cv_struct.dernier_poste or "?")
                    with col_b:
                        st.metric("Expérience", f"{cv_struct.annees_experience_total or '?'} ans")
                    with col_c:
                        st.metric("Niveau", cv_struct.niveau_seniorite or "?")

                    if cv_struct.competences_techniques:
                        tags = "".join([
                            f'<span class="skill-tag">{c}</span>'
                            for c in cv_struct.competences_techniques[:15]
                        ])
                        st.markdown(f"**Compétences :** {tags}", unsafe_allow_html=True)

                st.markdown(f"**{len(resultats)} offres trouvées**")
                st.markdown("---")

                # Afficher chaque offre
                for i, r in enumerate(resultats, 1):
                    score = round(r.score * 100, 1)
                    p     = r.payload

                    if score >= 75:
                        score_class = "score-high"
                    elif score >= 55:
                        score_class = "score-mid"
                    else:
                        score_class = "score-low"

                    # Salaire
                    sal = ""
                    if p.get("salaire_min") and p.get("salaire_max"):
                        sal = f"💰 {p['salaire_min']//1000}k–{p['salaire_max']//1000}k€"
                    elif p.get("salaire_min"):
                        sal = f"💰 {p['salaire_min']//1000}k€+"

                    # Compétences
                    comp = p.get("competences_techniques", [])
                    if isinstance(comp, str):
                        try: comp = json.loads(comp)
                        except: comp = []
                    tags = "".join([f'<span class="skill-tag">{c}</span>' for c in comp[:6]])

                    # Barre de progression
                    bar_width = int(score)

                    # Lien offre
                    offre_url = p.get("url", "")
                    lien_offre = ('<a href="' + offre_url + '" target="_blank" style="color:var(--accent); font-size:0.8rem;">Voir offre APEC</a>') if offre_url else ""

                    st.markdown(f"""
                    <div class="card">
                        <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                            <div style="flex:1;">
                                <div style="font-family:'Syne',sans-serif; font-weight:700; font-size:1.05rem;">
                                    #{i} {p.get('titre_normalise') or p.get('titre_brut', 'Offre')}
                                </div>
                                <div style="color:var(--text2); font-size:0.85rem; margin-top:0.3rem;">
                                    🏢 {p.get('entreprise_brute') or 'Non précisé'}
                                    &nbsp;|&nbsp; 📍 {p.get('ville') or 'Non précisé'}
                                    &nbsp;|&nbsp; 📄 {p.get('type_contrat') or '?'}
                                    {'&nbsp;|&nbsp; ' + sal if sal else ''}
                                </div>
                                <div style="margin-top:0.6rem;">{tags}</div>
                            </div>
                            <div style="text-align:center; min-width:80px;">
                                <span class="score-badge {score_class}">{score}%</span>
                            </div>
                        </div>
                        <div class="match-bar-bg">
                            <div class="match-bar-fill" style="width:{bar_width}%;"></div>
                        </div>
                        {lien_offre}
                    </div>
                    """, unsafe_allow_html=True)

        elif not connections_ok:
            st.error("❌ Connexions non disponibles — lance `python start.py` d'abord")

        else:
            # État vide
            st.markdown("""
            <div style="text-align:center; padding: 4rem 2rem; color: var(--text2);">
                <div style="font-size: 3rem; margin-bottom: 1rem;">🎯</div>
                <div style="font-family: 'Syne', sans-serif; font-size: 1.2rem; color: var(--text);">
                    Dépose ton CV et lance le matching
                </div>
                <div style="margin-top: 0.5rem; font-size: 0.9rem;">
                    L'IA analysera ton profil et trouvera les meilleures offres
                </div>
            </div>
            """, unsafe_allow_html=True)


# ===========================================================================
# VUE ORGANISME
# ===========================================================================

elif vue == "🏢 Vue Organisme":

    st.markdown("### 📊 Dashboard — Marché de l'emploi")

    if not connections_ok:
        st.error("❌ Connexions non disponibles — lance `python start.py` d'abord")
        st.stop()

    # Charger les données
    @st.cache_data(ttl=300)
    def load_offres_data():
        from sqlalchemy import text as sql_text
        engine, _, _, _ = load_connections()
        with engine.connect() as conn:
            try:
                df = pd.read_sql("SELECT * FROM offres_structurees", conn)
                return df
            except Exception:
                return pd.DataFrame()

    df = load_offres_data()

    if df.empty:
        st.warning("⚠️ Aucune donnée disponible — lance le Bloc 2 d'abord")
        st.info("```bash\npython bloc2_llm_ner/04_ner_offres_llm.py\n```")
        st.stop()

    # ---- KPI principaux ----
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-value">{len(df)}</div>
            <div class="kpi-label">Offres analysées</div>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        nb_entreprises = df["entreprise_brute"].nunique()
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-value">{nb_entreprises}</div>
            <div class="kpi-label">Entreprises</div>
        </div>
        """, unsafe_allow_html=True)

    with col3:
        sal_median = df["salaire_min"].dropna().median()
        sal_str = f"{int(sal_median//1000)}k€" if not pd.isna(sal_median) else "N/A"
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-value">{sal_str}</div>
            <div class="kpi-label">Salaire médian</div>
        </div>
        """, unsafe_allow_html=True)

    with col4:
        nb_villes = df["ville"].dropna().nunique()
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-value">{nb_villes}</div>
            <div class="kpi-label">Villes</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ---- Graphiques ----
    col_g1, col_g2 = st.columns(2, gap="large")

    PLOTLY_THEME = dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#9CA3AF", family="DM Sans"),
        margin=dict(t=30, b=10, l=10, r=10),
    )

    with col_g1:
        st.markdown("#### 🛠️ Compétences les plus demandées")
        # Parser les compétences JSON
        all_comp = []
        for row in df["competences_techniques"].dropna():
            try:
                comps = json.loads(row) if isinstance(row, str) else row
                all_comp.extend(comps)
            except Exception:
                pass

        if all_comp:
            comp_series = pd.Series(all_comp).value_counts().head(15)
            fig = go.Figure(go.Bar(
                x=comp_series.values,
                y=comp_series.index,
                orientation="h",
                marker=dict(
                    color=comp_series.values,
                    colorscale=[[0, "#4361EE"], [1, "#F72585"]],
                    showscale=False
                )
            ))
            fig.update_layout(**PLOTLY_THEME, height=380)
            fig.update_xaxes(showgrid=True, gridcolor="#374151", zeroline=False)
            fig.update_yaxes(showgrid=False)
            st.plotly_chart(fig, use_container_width=True)

    with col_g2:
        st.markdown("#### 📄 Répartition par type de contrat")
        contrat_counts = df["type_contrat"].dropna().value_counts()
        if not contrat_counts.empty:
            fig = go.Figure(go.Pie(
                labels=contrat_counts.index,
                values=contrat_counts.values,
                hole=0.5,
                marker=dict(colors=["#4361EE", "#F72585", "#06D6A0", "#FFB703", "#8B5CF6"])
            ))
            fig.update_layout(**PLOTLY_THEME, height=380,
                showlegend=True,
                legend=dict(font=dict(color="#9CA3AF")))
            fig.update_traces(textfont_color="white")
            st.plotly_chart(fig, use_container_width=True)

    col_g3, col_g4 = st.columns(2, gap="large")

    with col_g3:
        st.markdown("#### 📍 Tension géographique (top 10 villes)")
        ville_counts = df["ville"].dropna().value_counts().head(10)
        if not ville_counts.empty:
            fig = px.bar(
                x=ville_counts.index,
                y=ville_counts.values,
                color=ville_counts.values,
                color_continuous_scale=["#4361EE", "#F72585"],
            )
            fig.update_layout(**PLOTLY_THEME, height=320, coloraxis_showscale=False)
            fig.update_xaxes(title="", showgrid=False)
            fig.update_yaxes(title="Nb offres", showgrid=True, gridcolor="#374151")
            st.plotly_chart(fig, use_container_width=True)

    with col_g4:
        st.markdown("#### 🎓 Répartition par niveau de séniorité")
        seniorite_counts = df["niveau_seniorite"].dropna().value_counts()
        if not seniorite_counts.empty:
            ordre = ["junior", "confirme", "senior", "lead", "directeur"]
            seniorite_counts = seniorite_counts.reindex(
                [o for o in ordre if o in seniorite_counts.index]
            ).dropna()
            fig = go.Figure(go.Bar(
                x=seniorite_counts.index,
                y=seniorite_counts.values,
                marker=dict(color=["#06D6A0", "#4361EE", "#FFB703", "#F72585", "#8B5CF6"])
            ))
            fig.update_layout(**PLOTLY_THEME, height=320)
            fig.update_xaxes(showgrid=False)
            fig.update_yaxes(showgrid=True, gridcolor="#374151")
            st.plotly_chart(fig, use_container_width=True)

    # ---- Distribution des salaires ----
    st.markdown("#### 💰 Distribution des salaires")
    df_sal = df[df["salaire_min"].notna() & df["salaire_max"].notna()].copy()
    if not df_sal.empty:
        df_sal["salaire_moyen"] = (df_sal["salaire_min"] + df_sal["salaire_max"]) / 2
        fig = go.Figure()
        fig.add_trace(go.Histogram(
            x=df_sal["salaire_moyen"],
            nbinsx=20,
            marker_color="#4361EE",
            opacity=0.8,
            name="Salaire moyen"
        ))
        fig.update_layout(**PLOTLY_THEME, height=280,
            xaxis_title="Salaire annuel brut (€)",
            yaxis_title="Nombre d'offres",
            bargap=0.05
        )
        fig.update_xaxes(showgrid=True, gridcolor="#374151")
        fig.update_yaxes(showgrid=True, gridcolor="#374151")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Pas assez de données salariales pour afficher la distribution")

    # ---- Table des offres récentes ----
    st.markdown("#### 📋 Offres récentes structurées")
    cols_display = ["titre_normalise", "entreprise_brute", "ville",
                    "type_contrat", "niveau_seniorite", "salaire_min", "salaire_max"]
    cols_present = [c for c in cols_display if c in df.columns]
    st.dataframe(
        df[cols_present].head(20).rename(columns={
            "titre_normalise":  "Poste",
            "entreprise_brute": "Entreprise",
            "ville":            "Ville",
            "type_contrat":     "Contrat",
            "niveau_seniorite": "Niveau",
            "salaire_min":      "Salaire min (€)",
            "salaire_max":      "Salaire max (€)",
        }),
        use_container_width=True,
        hide_index=True,
    )

    # Bouton refresh
    if st.button("🔄 Actualiser les données"):
        st.cache_data.clear()
        st.rerun()