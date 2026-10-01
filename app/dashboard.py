"""
NEXUS EMPLOI — Dashboard Analytique Avancé
==========================================
Auteur  : Aziz Rezgui (Projet de fin d'études MSc Data Management 2025-2026)

KPIs et visualisations :
  - Vue marché temps réel
  - Top compétences demandées
  - Tension géographique
  - Distribution salaires
  - Analyse séniorité
  - Comparateur CV vs Marché
  - Radar compétences

Usage : intégré dans app.py (Vue Organisme)
        ou lancé seul : streamlit run dashboard.py
"""

import os
import json
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Config page (si lancé seul)
# ---------------------------------------------------------------------------

if __name__ == "__main__" or "dashboard" in __file__:
    st.set_page_config(
        page_title="Nexus Emploi — Dashboard",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded"
    )

DATABASE_URL = os.getenv("DATABASE_URL")

# ---------------------------------------------------------------------------
# CSS
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
    h1,h2,h3 { font-family: 'Syne', sans-serif; }
    .main { background-color: var(--primary); }

    .kpi-card {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 14px;
        padding: 1.3rem 1.5rem;
        text-align: center;
        transition: border-color 0.2s;
    }
    .kpi-card:hover { border-color: var(--accent); }
    .kpi-value {
        font-family: 'Syne', sans-serif;
        font-size: 2.4rem;
        font-weight: 800;
        background: linear-gradient(90deg, #4361EE, #F72585);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    .kpi-delta-up   { color: #06D6A0; font-size: 0.8rem; margin-top: 0.2rem; }
    .kpi-delta-down { color: #F72585; font-size: 0.8rem; margin-top: 0.2rem; }
    .kpi-label {
        color: var(--text2);
        font-size: 0.78rem;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        margin-top: 0.4rem;
    }
    .section-title {
        font-family: 'Syne', sans-serif;
        font-size: 1.1rem;
        font-weight: 700;
        color: var(--text);
        margin-bottom: 0.8rem;
        padding-bottom: 0.5rem;
        border-bottom: 1px solid var(--border);
    }
    .insight-card {
        background: var(--surface);
        border-left: 3px solid var(--accent);
        border-radius: 0 10px 10px 0;
        padding: 0.8rem 1rem;
        margin-bottom: 0.6rem;
        font-size: 0.88rem;
    }
    .insight-card.warning { border-left-color: var(--warning); }
    .insight-card.success { border-left-color: var(--success); }
    .tag {
        display: inline-block;
        background: rgba(67,97,238,0.15);
        color: #818CF8;
        border: 1px solid rgba(67,97,238,0.3);
        border-radius: 6px;
        padding: 0.15rem 0.6rem;
        font-size: 0.75rem;
        margin: 0.15rem;
    }
    [data-testid="stSidebar"] {
        background: var(--surface) !important;
        border-right: 1px solid var(--border) !important;
    }
    .stButton > button {
        background: linear-gradient(135deg, #4361EE, #3730A3);
        color: white; border: none; border-radius: 10px;
        font-family: 'Syne', sans-serif; font-weight: 600;
    }
    hr { border-color: var(--border) !important; opacity: 0.3; }
    #MainMenu, footer { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Thème Plotly commun
# ---------------------------------------------------------------------------

THEME = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#9CA3AF", family="DM Sans"),
    margin=dict(t=35, b=15, l=15, r=15),
)
COLORS = ["#4361EE", "#F72585", "#06D6A0", "#FFB703", "#8B5CF6",
          "#EC4899", "#14B8A6", "#F97316", "#6366F1", "#84CC16"]

# ---------------------------------------------------------------------------
# Chargement des données
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60)
def load_data():
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        try:
            offres = pd.read_sql("SELECT * FROM offres_structurees", conn)
        except Exception:
            offres = pd.DataFrame()
        try:
            cvs = pd.read_sql("SELECT * FROM cv_structures", conn)
        except Exception:
            cvs = pd.DataFrame()
    return offres, cvs


def parse_json_col(series):
    """Parse une colonne JSONB → liste Python."""
    result = []
    for v in series.dropna():
        try:
            parsed = json.loads(v) if isinstance(v, str) else v
            if isinstance(parsed, list):
                result.extend(parsed)
        except Exception:
            pass
    return result


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.markdown("""
<div style="margin-bottom:2rem;">
    <div style="font-family:'Syne',sans-serif; font-size:2rem; font-weight:800;
                background:linear-gradient(90deg,#4361EE,#F72585);
                -webkit-background-clip:text; -webkit-text-fill-color:transparent;">
        📊 Dashboard Marché de l'Emploi
    </div>
    <div style="color:#9CA3AF; font-size:0.85rem; letter-spacing:0.1em; text-transform:uppercase;">
        Nexus Emploi · Pilotage par l'IA Générative · MSc Data Management 2025-2026
    </div>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Chargement
# ---------------------------------------------------------------------------

with st.spinner("Chargement des données..."):
    offres, cvs = load_data()

if offres.empty:
    st.warning("⚠️ Aucune donnée — lance d'abord `python seed_data.py`")
    st.code("python seed_data.py", language="bash")
    st.stop()

# ---------------------------------------------------------------------------
# Sidebar — Filtres
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("### 🎛️ Filtres")

    villes_dispo = ["Toutes"] + sorted(offres["ville"].dropna().unique().tolist())
    filtre_ville = st.selectbox("Ville", villes_dispo)

    contrats_dispo = ["Tous"] + sorted(offres["type_contrat"].dropna().unique().tolist())
    filtre_contrat = st.selectbox("Type de contrat", contrats_dispo)

    niveaux_dispo = ["Tous"] + sorted(offres["niveau_seniorite"].dropna().unique().tolist())
    filtre_niveau = st.selectbox("Niveau", niveaux_dispo)

    sal_max_global = int(offres["salaire_max"].dropna().max()) if not offres["salaire_max"].dropna().empty else 100000
    sal_range = st.slider("Fourchette salariale (€)", 0, sal_max_global, (0, sal_max_global), step=5000)

    st.markdown("---")
    if st.button("🔄 Actualiser"):
        st.cache_data.clear()
        st.rerun()

    st.markdown("---")
    st.markdown(f"""
    <div style="color:#9CA3AF; font-size:0.78rem;">
        <div>📦 {len(offres)} offres analysées</div>
        <div>👤 {len(cvs)} CV traités</div>
    </div>
    """, unsafe_allow_html=True)

# Appliquer les filtres
df = offres.copy()
if filtre_ville != "Toutes":
    df = df[df["ville"] == filtre_ville]
if filtre_contrat != "Tous":
    df = df[df["type_contrat"] == filtre_contrat]
if filtre_niveau != "Tous":
    df = df[df["niveau_seniorite"] == filtre_niveau]
df = df[
    (df["salaire_min"].isna() | (df["salaire_min"] >= sal_range[0])) &
    (df["salaire_max"].isna() | (df["salaire_max"] <= sal_range[1]))
]

# ---------------------------------------------------------------------------
# Section 1 — KPI principaux
# ---------------------------------------------------------------------------

st.markdown('<div class="section-title">📈 Indicateurs clés</div>', unsafe_allow_html=True)

k1, k2, k3, k4, k5 = st.columns(5)

with k1:
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-value">{len(df)}</div>
        <div class="kpi-label">Offres</div>
    </div>""", unsafe_allow_html=True)

with k2:
    nb_ent = df["entreprise_brute"].nunique()
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-value">{nb_ent}</div>
        <div class="kpi-label">Entreprises</div>
    </div>""", unsafe_allow_html=True)

with k3:
    sal_med = df["salaire_min"].dropna().median()
    sal_str = f"{int(sal_med//1000)}k€" if not pd.isna(sal_med) else "N/A"
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-value">{sal_str}</div>
        <div class="kpi-label">Salaire médian</div>
    </div>""", unsafe_allow_html=True)

with k4:
    nb_villes = df["ville"].dropna().nunique()
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-value">{nb_villes}</div>
        <div class="kpi-label">Villes</div>
    </div>""", unsafe_allow_html=True)

with k5:
    all_comp = parse_json_col(df["competences_techniques"])
    nb_comp  = len(set(all_comp))
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-value">{nb_comp}</div>
        <div class="kpi-label">Compétences uniques</div>
    </div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Section 2 — Compétences + Contrats
# ---------------------------------------------------------------------------

st.markdown('<div class="section-title">🛠️ Analyse des compétences et contrats</div>', unsafe_allow_html=True)

col1, col2 = st.columns([3, 2], gap="large")

with col1:
    comp_series = pd.Series(all_comp).value_counts().head(15)
    if not comp_series.empty:
        fig = go.Figure(go.Bar(
            x=comp_series.values,
            y=comp_series.index,
            orientation="h",
            marker=dict(
                color=list(range(len(comp_series))),
                colorscale=[[0, "#F72585"], [0.5, "#4361EE"], [1, "#06D6A0"]],
                showscale=False,
            ),
            text=comp_series.values,
            textposition="outside",
            textfont=dict(color="#9CA3AF", size=11),
        ))
        fig.update_layout(**THEME, height=420,
            title=dict(text="Top 15 compétences demandées", font=dict(color="#F9FAFB", size=13)))
        fig.update_xaxes(showgrid=True, gridcolor="#1F2937", zeroline=False)
        fig.update_yaxes(showgrid=False, tickfont=dict(size=11))
        st.plotly_chart(fig, use_container_width=True)

with col2:
    contrat_counts = df["type_contrat"].dropna().value_counts()
    if not contrat_counts.empty:
        fig = go.Figure(go.Pie(
            labels=contrat_counts.index,
            values=contrat_counts.values,
            hole=0.6,
            marker=dict(colors=COLORS),
            textinfo="percent+label",
            textfont=dict(color="white", size=11),
        ))
        fig.add_annotation(
            text=f"<b>{len(df)}</b><br>offres",
            x=0.5, y=0.5, font=dict(size=14, color="#F9FAFB"),
            showarrow=False
        )
        fig.update_layout(**THEME, height=420,
            title=dict(text="Répartition par contrat", font=dict(color="#F9FAFB", size=13)),
            showlegend=True,
            legend=dict(font=dict(color="#9CA3AF"), orientation="v"),
        )
        st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Section 3 — Géographie + Séniorité
# ---------------------------------------------------------------------------

st.markdown('<div class="section-title">📍 Géographie & Séniorité</div>', unsafe_allow_html=True)

col3, col4 = st.columns(2, gap="large")

with col3:
    ville_counts = df["ville"].dropna().value_counts().head(12)
    if not ville_counts.empty:
        fig = go.Figure(go.Bar(
            x=ville_counts.index,
            y=ville_counts.values,
            marker=dict(
                color=ville_counts.values,
                colorscale=[[0, "#1e3a5f"], [1, "#4361EE"]],
                showscale=False,
            ),
            text=ville_counts.values,
            textposition="outside",
            textfont=dict(color="#9CA3AF"),
        ))
        fig.update_layout(**THEME, height=340,
            title=dict(text="Tension géographique — Top 12 villes", font=dict(color="#F9FAFB", size=13)))
        fig.update_xaxes(showgrid=False, tickangle=-30)
        fig.update_yaxes(showgrid=True, gridcolor="#1F2937", title="Nb offres")
        st.plotly_chart(fig, use_container_width=True)

with col4:
    ordre_niv = ["junior", "confirme", "senior", "lead", "directeur"]
    sen_counts = df["niveau_seniorite"].dropna().value_counts()
    sen_counts = sen_counts.reindex([o for o in ordre_niv if o in sen_counts.index]).dropna()

    if not sen_counts.empty:
        colors_sen = ["#06D6A0", "#4361EE", "#FFB703", "#F72585", "#8B5CF6"]
        fig = go.Figure()
        for i, (niveau, count) in enumerate(sen_counts.items()):
            fig.add_trace(go.Bar(
                name=niveau.capitalize(),
                x=[niveau.capitalize()],
                y=[count],
                marker_color=colors_sen[i % len(colors_sen)],
                text=[count],
                textposition="outside",
            ))
        fig.update_layout(**THEME, height=340, showlegend=False,
            title=dict(text="Répartition par niveau de séniorité", font=dict(color="#F9FAFB", size=13)))
        fig.update_xaxes(showgrid=False)
        fig.update_yaxes(showgrid=True, gridcolor="#1F2937")
        st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Section 4 — Salaires
# ---------------------------------------------------------------------------

st.markdown('<div class="section-title">💰 Analyse salariale</div>', unsafe_allow_html=True)

col5, col6 = st.columns(2, gap="large")

with col5:
    df_sal = df[df["salaire_min"].notna() & df["salaire_max"].notna()].copy()
    if not df_sal.empty:
        df_sal["salaire_moyen"] = (df_sal["salaire_min"] + df_sal["salaire_max"]) / 2
        fig = go.Figure()
        fig.add_trace(go.Histogram(
            x=df_sal["salaire_moyen"],
            nbinsx=15,
            marker=dict(
                color=df_sal["salaire_moyen"],
                colorscale=[[0, "#4361EE"], [1, "#F72585"]],
                showscale=False,
            ),
            opacity=0.85,
        ))
        # Ligne médiane
        median_sal = df_sal["salaire_moyen"].median()
        fig.add_vline(x=median_sal, line_dash="dash", line_color="#06D6A0",
                      annotation_text=f"Médiane: {int(median_sal//1000)}k€",
                      annotation_font_color="#06D6A0")
        fig.update_layout(**THEME, height=320,
            title=dict(text="Distribution des salaires annuels bruts", font=dict(color="#F9FAFB", size=13)),
            xaxis_title="Salaire (€)", yaxis_title="Nb offres", bargap=0.05)
        fig.update_xaxes(showgrid=True, gridcolor="#1F2937")
        fig.update_yaxes(showgrid=True, gridcolor="#1F2937")
        st.plotly_chart(fig, use_container_width=True)

with col6:
    # Salaire par niveau de séniorité
    df_sal_niv = df[df["salaire_min"].notna() & df["niveau_seniorite"].notna()].copy()
    if not df_sal_niv.empty:
        df_sal_niv["sal_moy"] = (df_sal_niv["salaire_min"] + df_sal_niv.get("salaire_max", df_sal_niv["salaire_min"])) / 2
        sal_by_niv = df_sal_niv.groupby("niveau_seniorite")["sal_moy"].mean().reindex(
            [o for o in ordre_niv if o in df_sal_niv["niveau_seniorite"].values]
        ).dropna()

        if not sal_by_niv.empty:
            fig = go.Figure(go.Bar(
                x=[n.capitalize() for n in sal_by_niv.index],
                y=sal_by_niv.values,
                marker=dict(color=COLORS[:len(sal_by_niv)]),
                text=[f"{int(v//1000)}k€" for v in sal_by_niv.values],
                textposition="outside",
                textfont=dict(color="#9CA3AF"),
            ))
            fig.update_layout(**THEME, height=320,
                title=dict(text="Salaire moyen par niveau", font=dict(color="#F9FAFB", size=13)))
            fig.update_xaxes(showgrid=False)
            fig.update_yaxes(showgrid=True, gridcolor="#1F2937", title="Salaire moyen (€)")
            st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Section 5 — Comparateur CV vs Marché
# ---------------------------------------------------------------------------

if not cvs.empty:
    st.markdown('<div class="section-title">🎯 Comparateur CV vs Marché</div>', unsafe_allow_html=True)

    # Sélection du CV
    cv_options = {
        f"CV {i+1} — {row.get('dernier_poste', 'Inconnu')} ({row.get('niveau_seniorite', '?')})": i
        for i, row in cvs.iterrows()
    }
    selected_label = st.selectbox("Sélectionne un CV à analyser", list(cv_options.keys()))
    selected_idx   = cv_options[selected_label]
    cv_row         = cvs.iloc[selected_idx]

    col7, col8 = st.columns(2, gap="large")

    with col7:
        # Compétences CV
        cv_comp = []
        try:
            cv_comp = json.loads(cv_row["competences_techniques"]) if isinstance(cv_row["competences_techniques"], str) else (cv_row["competences_techniques"] or [])
        except Exception:
            pass

        # Top compétences marché
        top_marche = pd.Series(all_comp).value_counts().head(12)

        # Intersection
        match_comp   = [c for c in cv_comp if c in top_marche.index]
        missing_comp = [c for c in top_marche.index if c not in cv_comp][:5]

        st.markdown("**Compétences du candidat**")
        tags_cv = "".join([
            f'<span class="tag" style="background:rgba(6,214,160,0.15);color:#06D6A0;border-color:#06D6A0;">{c}</span>'
            if c in top_marche.index
            else f'<span class="tag">{c}</span>'
            for c in cv_comp
        ])
        st.markdown(tags_cv or "Aucune compétence détectée", unsafe_allow_html=True)

        st.markdown("<br>**Compétences manquantes (top marché)**", unsafe_allow_html=True)
        tags_miss = "".join([
            f'<span class="tag" style="background:rgba(247,37,133,0.15);color:#F72585;border-color:#F72585;">{c}</span>'
            for c in missing_comp
        ])
        st.markdown(tags_miss or "✅ Le profil couvre les principales compétences", unsafe_allow_html=True)

    with col8:
        # Radar compétences CV vs Marché
        categories = list(top_marche.head(8).index)
        max_val    = top_marche.max()

        marche_vals = [top_marche.get(c, 0) / max_val * 100 for c in categories]
        cv_vals     = [100 if c in cv_comp else 0 for c in categories]

        fig = go.Figure()
        fig.add_trace(go.Scatterpolar(
            r=marche_vals + [marche_vals[0]],
            theta=categories + [categories[0]],
            fill="toself",
            name="Marché",
            line=dict(color="#4361EE"),
            fillcolor="rgba(67,97,238,0.2)",
        ))
        fig.add_trace(go.Scatterpolar(
            r=cv_vals + [cv_vals[0]],
            theta=categories + [categories[0]],
            fill="toself",
            name="CV",
            line=dict(color="#06D6A0"),
            fillcolor="rgba(6,214,160,0.2)",
        ))
        fig.update_layout(
            **THEME,
            height=340,
            polar=dict(
                bgcolor="rgba(0,0,0,0)",
                radialaxis=dict(visible=True, range=[0, 100],
                                gridcolor="#374151", linecolor="#374151",
                                tickfont=dict(color="#9CA3AF", size=9)),
                angularaxis=dict(gridcolor="#374151", linecolor="#374151",
                                 tickfont=dict(color="#F9FAFB", size=10)),
            ),
            legend=dict(font=dict(color="#9CA3AF")),
            title=dict(text="Radar compétences CV vs Marché", font=dict(color="#F9FAFB", size=13)),
        )
        st.plotly_chart(fig, use_container_width=True)

    # Score d'alignement
    score_align = round(len(match_comp) / max(len(top_marche.head(12)), 1) * 100)
    col_s1, col_s2, col_s3 = st.columns(3)
    with col_s1:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-value">{score_align}%</div>
            <div class="kpi-label">Alignement avec le marché</div>
        </div>""", unsafe_allow_html=True)
    with col_s2:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-value">{len(match_comp)}</div>
            <div class="kpi-label">Compétences en commun</div>
        </div>""", unsafe_allow_html=True)
    with col_s3:
        exp_str = f"{int(cv_row['annees_experience_total'])} ans" if pd.notna(cv_row.get('annees_experience_total')) else "N/A"
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-value">{exp_str}</div>
            <div class="kpi-label">Expérience</div>
        </div>""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Section 6 — Insights automatiques
# ---------------------------------------------------------------------------

st.markdown("<br>", unsafe_allow_html=True)
st.markdown('<div class="section-title">💡 Insights automatiques</div>', unsafe_allow_html=True)

insights = []

# Insight 1 : ville dominante
if not df["ville"].dropna().empty:
    top_ville = df["ville"].dropna().value_counts().index[0]
    pct_ville = round(df["ville"].value_counts(normalize=True).iloc[0] * 100)
    insights.append(("success", f"📍 {top_ville} concentre {pct_ville}% des offres — forte tension géographique sur cette ville."))

# Insight 2 : compétence la plus demandée
if all_comp:
    top_comp = pd.Series(all_comp).value_counts().index[0]
    pct_comp = round(pd.Series(all_comp).value_counts(normalize=True).iloc[0] * 100)
    insights.append(("info", f"🛠️ <b>{top_comp}</b> est la compétence la plus demandée ({pct_comp}% des offres)."))

# Insight 3 : niveau dominant
if not df["niveau_seniorite"].dropna().empty:
    top_niv = df["niveau_seniorite"].dropna().value_counts().index[0]
    insights.append(("warning", f"🎯 Le marché recherche principalement des profils <b>{top_niv}</b>."))

# Insight 4 : contrat dominant
if not df["type_contrat"].dropna().empty:
    top_contrat = df["type_contrat"].dropna().value_counts().index[0]
    pct_contrat = round(df["type_contrat"].value_counts(normalize=True).iloc[0] * 100)
    insights.append(("info", f"📄 {pct_contrat}% des offres sont en <b>{top_contrat}</b>."))

# Insight 5 : salaire
if not df["salaire_min"].dropna().empty:
    sal_mean = df["salaire_min"].dropna().mean()
    insights.append(("success", f"💰 Salaire d'entrée moyen : <b>{int(sal_mean//1000)}k€</b> brut annuel."))

for cls, text in insights:
    css_cls = "insight-card warning" if cls == "warning" else "insight-card success" if cls == "success" else "insight-card"
    st.markdown(f'<div class="{css_cls}">{text}</div>', unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Section 7 — Table détaillée
# ---------------------------------------------------------------------------

st.markdown("<br>", unsafe_allow_html=True)
st.markdown('<div class="section-title">📋 Données détaillées</div>', unsafe_allow_html=True)

cols_show = ["titre_normalise", "entreprise_brute", "ville", "type_contrat",
             "niveau_seniorite", "salaire_min", "salaire_max", "secteur"]
cols_present = [c for c in cols_show if c in df.columns]

rename_map = {
    "titre_normalise": "Poste",
    "entreprise_brute": "Entreprise",
    "ville": "Ville",
    "type_contrat": "Contrat",
    "niveau_seniorite": "Niveau",
    "salaire_min": "Sal. min (€)",
    "salaire_max": "Sal. max (€)",
    "secteur": "Secteur",
}

st.dataframe(
    df[cols_present].rename(columns=rename_map),
    use_container_width=True,
    hide_index=True,
    height=350,
)

# Export CSV
csv_data = df[cols_present].rename(columns=rename_map).to_csv(index=False).encode("utf-8")
st.download_button(
    label="⬇️ Exporter en CSV",
    data=csv_data,
    file_name="nexus_emploi_offres.csv",
    mime="text/csv",
)

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.markdown("""
<div style="text-align:center; color:#374151; font-size:0.75rem; margin-top:3rem; padding-top:1rem; border-top:1px solid #1F2937;">
    Nexus Emploi · MSc Data Management 2025-2026 · Aziz Rezgui
</div>
""", unsafe_allow_html=True)