import os
from dotenv import load_dotenv

# ============================================================
# CHARGER LE FICHIER .ENV EXPLICITEMENT
# ============================================================
load_dotenv()

# ============================================================
# LLM Configuration
# ============================================================
LLM_TEMPERATURE = 0.3
LLM_MODEL = "llama-3.3-70b-versatile"
LLM_MAX_TOKENS = 2000

# ============================================================
# Agent Configuration
# ============================================================
MAX_ITERATIONS = 2
MIN_SCORE_THRESHOLD = 0.7

# ============================================================
# MIN_SIMILARITY_THRESHOLD = 0.70
# ============================================================
# Seuil de similarité cosinus pour vérifier que la user story
# améliorée ne dérive pas sémantiquement de l'originale.
#
# Justification académique :
#
# 1. Reimers & Gurevych (2019, Section 4, Tableau 1) :
#    "We always use cosine-similarity to compare the similarity
#    between two sentence embeddings."
#    Sur le benchmark STS (Semantic Textual Similarity), les
#    phrases sémantiquement équivalentes obtiennent un score
#    de similarité cosinus moyen de 0.75 (SBERT-NLI-base: 74.89,
#    SBERT-NLI-large: 76.55 en corrélation de Spearman ×100).
#
# 2. Raharjana et al. (2026) : seuil de 0.80 pour la
#    réutilisation de user stories (précision 84%, rappel 93%).
#
# 3. Lucassen et al. (2016, Section 4.8) : seuil de 0.90 pour
#    la détection de doublons exacts dans AQUSA.
#
# 4. Manning et al. (2008) : similarité cosinus entre 0.60 et
#    0.80 indique une similarité substantielle (même sujet).
#
# Notre seuil de 0.70 est adapté à notre objectif de validation
# de non-dérive après amélioration :
#   - Supérieur au seuil de similarité "substantielle" (0.60)
#   - Proche du seuil de paraphrase identifié par SBERT (0.75)
#   - Inférieur au seuil de réutilisation (0.80) et de doublon
#     exact (0.90), car nous autorisons des reformulations
#     légitimes qui améliorent la qualité
# ============================================================
MIN_SIMILARITY_THRESHOLD = 0.70

# ============================================================
# Tool Configuration
# ============================================================
ENABLE_CACHING = os.getenv("ENABLE_CACHING", "true").lower() == "true"

# ============================================================
# Debug
# ============================================================
DEBUG = os.getenv("DEBUG", "false").lower() == "true"