"""
Dataset de test pour le benchmark LLM — User Story Refinement.

8 stories réparties en 3 catégories :
  - BAD    (score attendu < 0.40) : 3 stories
  - MEDIUM (score attendu 0.40–0.65) : 4 stories
  - GOOD   (score attendu >= 0.65) : 1 story

Langues : EN et FR, avec et sans AC.
Objectif : mesurer la capacité de chaque modèle à améliorer des stories.

Critères de sélection (réduit depuis 12) :
  - BAD-FR-02 supprimée  : trop triviale (2 mots), cas limite pas représentatif
  - MED-EN-03 supprimée  : dépendance inter-story (cas spécial, biais pour le benchmark)
  - GOOD-FR-01 supprimée : doublon fonctionnel avec GOOD-EN-01 (même feature : login)
  - GOOD-EN-02 supprimée : 1 bonne story suffit (les bonnes ne testent pas l'amélioration)
"""

from typing import List, TypedDict


class StoryEntry(TypedDict):
    id: str
    category: str        # "bad" | "medium" | "good"
    language: str        # "en" | "fr"
    story: str
    acceptance_criteria: List[str]
    expected_issues: List[str]


DATASET: List[StoryEntry] = [

    # ─── BAD STORIES ─────────────────────────────────────────────────────────
    # Pas de format INVEST, aucun AC, très vague ou trop court.

    {
        "id": "BAD-EN-01",
        "category": "bad",
        "language": "en",
        "story": "As a user, I want the system to work well and be fast.",
        "acceptance_criteria": [],
        "expected_issues": [
            "Missing 'so that' clause (no business value)",
            "Vague terms: 'work well', 'fast'",
            "No acceptance criteria",
        ],
    },
    {
        "id": "BAD-EN-02",
        "category": "bad",
        "language": "en",
        "story": (
            "As a developer, I want to build the user authentication module "
            "using React for the frontend and PostgreSQL for the database "
            "so that users can log in."
        ),
        "acceptance_criteria": [],
        "expected_issues": [
            "Prescribes implementation technology (N - Negotiable)",
            "No acceptance criteria",
            "Implementation details (React, PostgreSQL) should not appear",
        ],
    },
    {
        "id": "BAD-FR-01",
        "category": "bad",
        "language": "fr",
        "story": "En tant qu'administrateur, je veux que l'application soit rapide et intuitive.",
        "acceptance_criteria": [],
        "expected_issues": [
            "Termes vagues : 'rapide', 'intuitive'",
            "Pas de clause 'afin de' (valeur métier manquante)",
            "Aucun critère d'acceptation",
        ],
    },
    # ─── MEDIUM STORIES ───────────────────────────────────────────────────────
    # Format As a / I want présent mais AC absents ou faibles.

    {
        "id": "MED-EN-01",
        "category": "medium",
        "language": "en",
        "story": (
            "As a registered user, I want to log in to my account "
            "so that I can access my personal dashboard."
        ),
        "acceptance_criteria": [],
        "expected_issues": [
            "No acceptance criteria",
            "No measurable conditions",
        ],
    },
    {
        "id": "MED-EN-02",
        "category": "medium",
        "language": "en",
        "story": (
            "As a customer, I want to view my order history "
            "so that I can track my past purchases."
        ),
        "acceptance_criteria": [
            "The page shows previous orders",
            "Orders are sorted by date",
        ],
        "expected_issues": [
            "AC not verifiable (no action verbs, no measurable conditions)",
            "No time or quantity constraints in AC",
        ],
    },
    {
        "id": "MED-FR-01",
        "category": "medium",
        "language": "fr",
        "story": (
            "En tant qu'utilisateur, je veux pouvoir réinitialiser mon mot de passe "
            "afin d'accéder à mon compte si je l'oublie."
        ),
        "acceptance_criteria": [],
        "expected_issues": [
            "Aucun critère d'acceptation",
            "Pas de condition mesurable",
        ],
    },
    {
        "id": "MED-FR-02",
        "category": "medium",
        "language": "fr",
        "story": (
            "En tant que responsable RH, je veux consulter les candidatures reçues "
            "afin de sélectionner les meilleurs profils pour un entretien."
        ),
        "acceptance_criteria": [
            "La liste des candidatures est affichée",
            "Le responsable peut filtrer par poste",
            "Les candidatures sont triées par date de dépôt",
        ],
        "expected_issues": [
            "AC sans verbe d'action clair ni condition mesurable",
            "Pas de limite de temps ou de quantité spécifiée",
        ],
    },

    # ─── GOOD STORIES ─────────────────────────────────────────────────────────
    # Déjà bien formées — mesure si le modèle préserve sans dégrader.

    {
        "id": "GOOD-EN-01",
        "category": "good",
        "language": "en",
        "story": (
            "As a registered user, I want to reset my password via email "
            "so that I can regain access to my account when I forget my credentials."
        ),
        "acceptance_criteria": [
            "The system sends a password reset email within 2 minutes of the request",
            "The reset link expires after 24 hours",
            "The user receives a confirmation message after successfully changing the password",
            "The new password must contain at least 8 characters including one number",
        ],
        "expected_issues": [],
    },
]
