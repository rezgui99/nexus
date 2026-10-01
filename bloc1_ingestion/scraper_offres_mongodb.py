"""
NEXUS EMPLOI — Bloc 1 (CORRIGÉ) : Scraper APEC avec Selenium
=============================================================
Auteur  : Aziz Rezgui (Projet de fin d'études MSc Data Management 2025-2026)

POURQUOI L'ERREUR 400 ?
  L'APEC utilise une SPA (Single Page Application).
  Le site charge les offres via des requêtes XHR/Fetch internes au navigateur.
  L'ancien endpoint /cms/webservices/ est bloqué en accès direct.

SOLUTION : Selenium intercepte les vraies requêtes réseau du navigateur
  → On ouvre la page de recherche APEC comme un vrai navigateur
  → On capture les appels XHR pour récupérer le JSON des offres
  → Fallback : scraping du HTML rendu si XHR échoue

Dépendances:
    pip install selenium webdriver-manager pymongo python-dotenv requests
"""

import os
import json
import time
import hashlib
import logging
import requests
from datetime import datetime, timezone
from dataclasses import dataclass, asdict, field
from typing import Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from pymongo import MongoClient, errors
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("nexus_apec_scraper")

MONGO_URI  = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME    = "nexus_emploi"
COLLECTION = "raw_offres"


# ---------------------------------------------------------------------------
# Schéma de données brutes (identique au Bloc 1 original)
# ---------------------------------------------------------------------------

@dataclass
class RawOffre:
    source_id:              str
    source_site:            str
    url:                    str
    titre_brut:             str
    description_brute:      str
    entreprise_brute:       Optional[str]
    localisation_brute:     Optional[str]
    date_publication_brute: Optional[str]
    type_contrat_brut:      Optional[str] = None
    salaire_brut:           Optional[str] = None
    scraped_at:             str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    pipeline_version:       str = "1.0.0"
    statut_traitement:      str = "raw"
    content_hash:           str = ""

    def compute_hash(self) -> "RawOffre":
        content = f"{self.url}{self.titre_brut}{self.description_brute}"
        self.content_hash = hashlib.sha256(content.encode()).hexdigest()
        return self


# ---------------------------------------------------------------------------
# Approche 1 : Interception des requêtes XHR via Selenium + Performance Logs
# ---------------------------------------------------------------------------

class ApecXHRScraper:
    """
    Ouvre l'APEC dans un vrai navigateur Chrome headless,
    intercepte les appels API XHR internes et récupère le JSON des offres.
    C'est la méthode la plus robuste pour les SPA modernes.
    """

    SEARCH_PAGE = "https://www.apec.fr/candidat/recherche-emploi.html/emploi?motsCles={keywords}&nbResultats=20"

    def __init__(self):
        self.driver = self._init_driver()

    def _init_driver(self) -> webdriver.Chrome:
        """Configure Chrome headless avec les logs réseau activés."""
        options = Options()
        options.add_argument("--headless=new")          # Mode invisible
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
        # Active la capture des requêtes réseau (Performance Logs)
        options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

        service = Service(ChromeDriverManager().install())
        driver  = webdriver.Chrome(service=service, options=options)
        logger.info("✅ Chrome headless démarré")
        return driver

    def scrape(self, keywords: str = "data engineer", nb_offres: int = 10) -> list[RawOffre]:
        """
        Lance la recherche, attend le chargement XHR et parse les offres.
        """
        url = self.SEARCH_PAGE.format(keywords=keywords.replace(" ", "+"))
        logger.info("🌐 Ouverture : %s", url)
        self.driver.get(url)

        # Attendre que les offres s'affichent dans le DOM
        try:
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "div.card-offer, article.offer-card, div[class*='offer']")
                )
            )
            time.sleep(2)  # Laisser les XHR se terminer
        except Exception:
            logger.warning("⚠️  Timeout DOM — tentative XHR quand même")

        # Analyser les logs réseau pour trouver les appels API
        offres_json = self._extract_from_xhr_logs()

        if offres_json:
            logger.info("✅ %d offres récupérées via XHR", len(offres_json))
            return [self._parse_xhr_offre(o) for o in offres_json[:nb_offres]]

        # Fallback : scraping HTML
        logger.info("🔄 Fallback vers scraping HTML...")
        return self._scrape_html(nb_offres)

    def _extract_from_xhr_logs(self) -> list[dict]:
        """
        Analyse les logs réseau Chrome pour trouver les réponses XHR
        contenant des offres d'emploi.
        """
        offres = []
        try:
            logs = self.driver.get_log("performance")
            for log in logs:
                message = json.loads(log["message"])["message"]

                # On cherche les réponses réseau qui ressemblent à une API d'offres
                if (message.get("method") == "Network.responseReceived"
                        and "offre" in message.get("params", {})
                        .get("response", {}).get("url", "").lower()):

                    request_id = message["params"]["requestId"]
                    try:
                        body = self.driver.execute_cdp_cmd(
                            "Network.getResponseBody", {"requestId": request_id}
                        )
                        data = json.loads(body.get("body", "{}"))

                        # L'API APEC retourne les résultats dans différentes clés
                        for key in ["resultats", "offres", "items", "data", "results"]:
                            if key in data and isinstance(data[key], list):
                                offres.extend(data[key])
                                break
                    except Exception:
                        continue
        except Exception as e:
            logger.debug("Erreur lecture logs XHR : %s", e)

        return offres

    def _parse_xhr_offre(self, item: dict) -> RawOffre:
        """Parse une offre depuis la reponse XHR de l'APEC - version robuste."""
        import re

        # ID offre
        offre_id = str(
            item.get("numOffre") or item.get("id") or
            item.get("offreId") or item.get("identifiant") or ""
        )

        # Titre
        titre = (
            item.get("intitule") or item.get("titre") or
            item.get("libelle") or ""
        )

        # Description - chercher dans toutes les cles possibles
        description = (
            item.get("texteHtml") or item.get("texte") or
            item.get("description") or item.get("descriptif") or
            item.get("contenu") or item.get("texteOffre") or ""
        )
        # Nettoyer le HTML
        if description and "<" in description:
            description = re.sub(r'<[^>]+>', ' ', description)
            description = re.sub(r'\s+', ' ', description).strip()

        # Entreprise
        entreprise = None
        ent = item.get("entreprise")
        if isinstance(ent, dict):
            entreprise = ent.get("nom") or ent.get("raisonSociale")
        else:
            entreprise = (
                item.get("nomEntreprise") or item.get("entreprise") or
                item.get("societe") or item.get("raisonSociale")
            )

        # Localisation
        localisation = None
        lieu = item.get("lieu") or item.get("lieuTravail")
        if isinstance(lieu, dict):
            localisation = f"{lieu.get('libelle', '')} {lieu.get('codePostal', '')}".strip()
        else:
            localisation = lieu or item.get("localisation") or item.get("ville")

        # Salaire
        sal = item.get("salaire") or item.get("remuneration")
        salaire = sal.get("libelle") if isinstance(sal, dict) else sal

        # URL correcte APEC
        url = f"https://www.apec.fr/candidat/recherche-emploi.html/emploi/{offre_id}"

        return RawOffre(
            source_id              = offre_id,
            source_site            = "apec",
            url                    = url,
            titre_brut             = titre,
            description_brute      = description,
            entreprise_brute       = entreprise,
            localisation_brute     = str(localisation) if localisation else None,
            date_publication_brute = item.get("datePublication") or item.get("dateCreation"),
            type_contrat_brut      = item.get("typeContrat") or item.get("typeContratLibelle"),
            salaire_brut           = salaire,
        ).compute_hash()


    def _scrape_html(self, nb_offres: int) -> list[RawOffre]:
        """
        Fallback : scrape directement le HTML rendu par le navigateur.
        Sélecteurs CSS à ajuster si l'APEC change son DOM.
        """
        offres = []
        try:
            # Chercher les cartes d'offres dans le DOM
            cards = self.driver.find_elements(
                By.CSS_SELECTOR,
                "div.card-offer, article.offer-card, div[data-id-offre], li.offer"
            )
            logger.info("🔍 %d cartes HTML trouvées", len(cards))

            for card in cards[:nb_offres]:
                try:
                    # Extraire titre
                    titre = self._get_text(card, "h2, h3, .title-offer, [class*='title']")
                    if not titre:
                        continue

                    # Extraire les autres champs
                    entreprise  = self._get_text(card, ".company, .entreprise, [class*='company']")
                    localisation = self._get_text(card, ".location, .lieu, [class*='location']")
                    description = self._get_text(card, ".description, p, [class*='desc']")
                    lien        = card.find_element(By.TAG_NAME, "a").get_attribute("href") if card.find_elements(By.TAG_NAME, "a") else ""

                    # Générer un ID depuis l'URL
                    offre_id = hashlib.md5(lien.encode()).hexdigest()[:12] if lien else hashlib.md5(titre.encode()).hexdigest()[:12]

                    offre = RawOffre(
                        source_id              = offre_id,
                        source_site            = "apec_html",
                        url                    = lien or f"https://www.apec.fr/{offre_id}",
                        titre_brut             = titre,
                        description_brute      = description or titre,
                        entreprise_brute       = entreprise,
                        localisation_brute     = localisation,
                        date_publication_brute = None,
                    ).compute_hash()
                    offres.append(offre)

                except Exception as e:
                    logger.debug("Erreur parsing card HTML : %s", e)
                    continue

        except Exception as e:
            logger.error("❌ Erreur scraping HTML : %s", e)

        return offres

    @staticmethod
    def _get_text(element, selector: str) -> Optional[str]:
        """Essaie plusieurs sélecteurs CSS et retourne le premier texte trouvé."""
        for sel in selector.split(", "):
            try:
                els = element.find_elements(By.CSS_SELECTOR, sel.strip())
                if els:
                    text = els[0].text.strip()
                    if text:
                        return text
            except Exception:
                continue
        return None

    def close(self):
        if self.driver:
            self.driver.quit()
            logger.info("🔒 Chrome fermé")


# ---------------------------------------------------------------------------
# Approche 2 : Requêtes directes avec session et cookies (plus rapide)
# ---------------------------------------------------------------------------

class ApecSessionScraper:
    """
    Utilise d'abord Selenium pour obtenir les cookies de session APEC,
    puis fait les requêtes directement avec requests (beaucoup plus rapide).
    Utile pour scraper en masse sans relancer Chrome à chaque fois.
    """

    SEARCH_URL = "https://www.apec.fr/cms/webservices/rechercheOffre/resultatRecherche"

    HEADERS = {
        "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept":          "application/json, text/plain, */*",
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Referer":         "https://www.apec.fr/candidat/recherche-emploi.html/emploi",
        "Origin":          "https://www.apec.fr",
        "X-Requested-With": "XMLHttpRequest",
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self._init_cookies()

    def _init_cookies(self):
        """
        Ouvre brièvement Chrome pour récupérer les cookies APEC valides,
        puis les injecte dans la session requests.
        """
        logger.info("🍪 Initialisation des cookies APEC via Chrome...")
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        try:
            service = Service(ChromeDriverManager().install())
            driver  = webdriver.Chrome(service=service, options=options)
            driver.get("https://www.apec.fr/candidat/recherche-emploi.html/emploi")
            time.sleep(4)  # Laisser les cookies s'initialiser

            # Transférer les cookies vers requests
            for cookie in driver.get_cookies():
                self.session.cookies.set(cookie["name"], cookie["value"])

            driver.quit()
            logger.info("✅ %d cookies récupérés", len(self.session.cookies))

        except Exception as e:
            logger.warning("⚠️  Impossible d'initialiser les cookies : %s", e)

    def search(self, keywords: str = "data engineer", nb_offres: int = 10) -> list[dict]:
        """Tente plusieurs endpoints connus de l'APEC."""

        # Liste des endpoints à essayer (l'APEC change régulièrement)
        endpoints = [
            {
                "url": "https://www.apec.fr/cms/webservices/rechercheOffre/resultatRecherche",
                "method": "POST",
                "json": {
                    "motsCles": keywords,
                    "nombreResultatsParPage": nb_offres,
                    "debuts": 0,
                }
            },
            {
                "url": "https://www.apec.fr/api/v1/offres",
                "method": "GET",
                "params": {"q": keywords, "size": nb_offres}
            },
            {
                "url": f"https://www.apec.fr/candidat/recherche-emploi.html/emploi?motsCles={keywords.replace(' ', '+')}&nbResultats={nb_offres}",
                "method": "GET",
                "params": {}
            }
        ]

        for ep in endpoints:
            try:
                if ep["method"] == "POST":
                    resp = self.session.post(ep["url"], json=ep.get("json"), timeout=15)
                else:
                    resp = self.session.get(ep["url"], params=ep.get("params", {}), timeout=15)

                if resp.status_code == 200:
                    data = resp.json()
                    for key in ["resultats", "offres", "items", "data", "results"]:
                        if key in data and isinstance(data[key], list):
                            logger.info("✅ %d offres via endpoint %s", len(data[key]), ep["url"])
                            return data[key]

            except Exception as e:
                logger.debug("Endpoint %s échoué : %s", ep["url"], e)
                continue

        logger.warning("⚠️  Tous les endpoints échoués")
        return []


# ---------------------------------------------------------------------------
# Connecteur MongoDB
# ---------------------------------------------------------------------------

class MongoConnector:

    def __init__(self, uri: str, db: str, collection: str):
        self.client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        self.client.server_info()
        self.col = self.client[db][collection]
        self.col.create_index("content_hash", unique=True, sparse=True)
        self.col.create_index("statut_traitement")
        logger.info("✅ MongoDB connecté — %s.%s", db, collection)

    def insert(self, offre: RawOffre) -> Optional[str]:
        doc = asdict(offre)
        result = self.col.update_one(
            {"content_hash": offre.content_hash},
            {"$setOnInsert": doc},
            upsert=True
        )
        if result.upserted_id:
            logger.info("  ✅ Insérée : %s", offre.titre_brut[:55])
            return str(result.upserted_id)
        logger.debug("  ⏩ Doublon ignoré : %s", offre.content_hash[:12])
        return None

    def close(self):
        self.client.close()


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

def run_pipeline(keywords: str = "data engineer", nb_offres: int = 10):
    """
    Pipeline complet avec stratégie en cascade :
    1. Interception XHR via Selenium (le plus fiable)
    2. Requête directe avec cookies (plus rapide)
    """
    logger.info("🚀 Démarrage pipeline Nexus Emploi — APEC Selenium")
    logger.info("   Mots-clés : %s | Nb offres : %d", keywords, nb_offres)

    mongo   = MongoConnector(MONGO_URI, DB_NAME, COLLECTION)
    scraper = ApecXHRScraper()
    offres  = []

    try:
        offres = scraper.scrape(keywords=keywords, nb_offres=nb_offres)
    finally:
        scraper.close()

    stats = {"inserees": 0, "doublons": 0, "erreurs": 0}

    for offre in offres:
        try:
            if not offre.titre_brut:
                stats["erreurs"] += 1
                continue
            inserted = mongo.insert(offre)
            if inserted:
                stats["inserees"] += 1
            else:
                stats["doublons"] += 1
        except Exception as e:
            logger.error("Erreur insertion : %s", e)
            stats["erreurs"] += 1

    mongo.close()
    logger.info(
        "✅ Pipeline terminé — Insérées: %d | Doublons: %d | Erreurs: %d",
        stats["inserees"], stats["doublons"], stats["erreurs"]
    )
    return stats


if __name__ == "__main__":
    print("=" * 50)
    print("  NEXUS EMPLOI — Scraper APEC")
    print("=" * 50)

    keywords = input("\n🔍 Mots-clés de recherche (ex: data engineer) : ").strip()
    if not keywords:
        keywords = "data engineer"

    nb_input = input("📦 Nombre d'offres à récupérer (défaut: 10) : ").strip()
    nb_offres = int(nb_input) if nb_input.isdigit() else 10

    print()
    run_pipeline(keywords=keywords, nb_offres=nb_offres)