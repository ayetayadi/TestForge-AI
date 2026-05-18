"""
Dataset de test pour le benchmark LLM — User Story Refinement.

12 stories réparties en 3 catégories :
  - BAD    (score attendu < 0.40) : 4 stories
  - MEDIUM (score attendu 0.40–0.65) : 5 stories
  - GOOD   (score attendu >= 0.65) : 3 stories

Langues : EN et FR, avec et sans AC.
Objectif : mesurer la capacité de chaque modèle à améliorer des stories.
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
    {
        "id": "BAD-FR-02",
        "category": "bad",
        "language": "fr",
        "story": "Fonctionnalité de connexion.",
        "acceptance_criteria": [],
        "expected_issues": [
            "Trop court (< 5 mots)",
            "Pas de format En tant que / Je veux",
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
        "id": "MED-EN-03",
        "category": "medium",
        "language": "en",
        "story": (
            "As a project manager, I want to assign tasks to team members "
            "so that I can distribute work efficiently across the team."
            " This story depends on story US-42 (user management) being completed first."
        ),
        "acceptance_criteria": [
            "The manager can select a team member from a dropdown",
            "The assigned user receives a notification",
        ],
        "expected_issues": [
            "Cross-story dependency (I - Independent)",
            "AC lack measurable conditions",
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
    # Déjà bien formées — le modèle doit les améliorer légèrement ou les valider.

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
    {
        "id": "GOOD-FR-01",
        "category": "good",
        "language": "fr",
        "story": (
            "En tant qu'utilisateur enregistré, je veux me connecter via email et mot de passe "
            "afin d'accéder à mon espace personnel et retrouver mes données."
        ),
        "acceptance_criteria": [
            "Le système affiche un message d'erreur si les identifiants sont incorrects",
            "Le compte est bloqué après 5 tentatives échouées consécutives",
            "La connexion redirige vers le tableau de bord en moins de 3 secondes",
            "Un token de session est créé et expire après 30 minutes d'inactivité",
        ],
        "expected_issues": [],
    },
    {
        "id": "GOOD-EN-02",
        "category": "good",
        "language": "en",
        "story": (
            "As an e-commerce customer, I want to add items to my shopping cart "
            "so that I can purchase multiple products in a single transaction."
        ),
        "acceptance_criteria": [
            "The cart displays a running total updated within 1 second of each addition",
            "The user can add at least 20 distinct items to the cart",
            "Removing an item from the cart updates the total immediately",
            "Cart contents persist for at least 7 days without requiring login",
        ],
        "expected_issues": [],
    },
]
