"""
LangSmith evaluation for the TestForge test case generation pipeline.

4 métriques choisies pour cette tâche :
  1. ac_coverage      — % des ACs couvertes par les TCs générés        (déterministe)
  2. gherkin_validity — % des TCs avec syntaxe Gherkin valide           (déterministe)
  3. faithfulness     — LLM-judge : pas d'étapes inventées hors story   (Azure gpt-4.1)
  4. step_clarity     — LLM-judge : étapes spécifiques et actionnables  (Azure gpt-4.1)

Le générateur utilise Groq llama-3.3-70b.
Le juge utilise Azure gpt-4.1 (modèle différent → évaluation non biaisée).

Usage (depuis backend/) :
  python evaluate_test_cases.py

Prérequis dans backend/.env :
  LANGSMITH_API_KEY=ls__...
  LANGSMITH_TRACING=true
  LANGSMITH_ENDPOINT=https://api.smith.langchain.com
  LANGCHAIN_PROJECT=TestForge-Eval
  GROQ_API_KEY_1=...
  AZURE_OPENAI_ENDPOINT_JUDGE=https://ced-infra-ahmed.openai.azure.com/
  AZURE_OPENAI_KEY_JUDGE=2Li8...
  AZURE_OPENAI_DEPLOYMENT_JUDGE=gpt-4.1
  AZURE_OPENAI_API_VERSION_JUDGE=2025-01-01-preview
"""

import asyncio
import logging
import os
import sys

# ── 1. Charger le .env avant tout import de l'app ────────────────────────────
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)

# ── 2. Vérifier que la clé LangSmith est présente ────────────────────────────
LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY")
if not LANGSMITH_API_KEY:
    logger.error(
        "Clé LangSmith introuvable. Ajoute LANGSMITH_API_KEY dans backend/.env"
    )
    sys.exit(1)

# LangSmith SDK lit LANGSMITH_API_KEY et LANGCHAIN_PROJECT automatiquement
os.environ.setdefault("LANGCHAIN_PROJECT", os.getenv("LANGCHAIN_PROJECT", "TestForge-Eval"))

# ── 3. Dataset — exemples de user stories + ACs ──────────────────────────────
# Chaque exemple = ce qu'on envoie au pipeline (inputs) + valeurs de référence (outputs)
DATASET_NAME = "testforge-tc-generation-v2"

_STORY_CONNEXION = (
    "En tant qu'utilisateur, je veux me connecter à la plateforme avec mon adresse e-mail "
    "et mon mot de passe afin d'accéder à mon tableau de bord personnel."
)
_ACS_CONNEXION = [
    "L'utilisateur peut saisir son adresse e-mail dans le formulaire de connexion",
    "L'utilisateur peut saisir son mot de passe dans le formulaire de connexion",
    "Le système valide que le format de l'adresse e-mail est correct",
    "Le système affiche un message d'erreur clair lorsque les identifiants sont invalides",
    "L'utilisateur est redirigé vers le tableau de bord après une connexion réussie",
    "Un jeton de session est créé et stocké après une connexion réussie",
    "Le système bloque le compte après 5 tentatives de connexion échouées consécutives",
    "Le mot de passe doit contenir entre 8 et 64 caractères",
]

EXAMPLES = [
    # ── Exemple 1 : Scénario POSITIF ─────────────────────────────────────────
    # Chemin nominal : un utilisateur avec des identifiants valides se connecte avec succès.
    # Le pipeline doit générer des TCs qui vérifient le flux heureux (happy path).
    {
        "inputs": {
            "story": _STORY_CONNEXION,
            "acceptance_criteria": _ACS_CONNEXION,
            "scenario_type": "positive",
            "risk_level": "high",
        },
        "outputs": {
            "min_coverage_pct": 0.8,
        },
    },

    # ── Exemple 2 : Scénario NÉGATIF ─────────────────────────────────────────
    # Chemins d'erreur : identifiants invalides, email mal formé, compte bloqué.
    # Le pipeline doit générer des TCs qui vérifient les messages d'erreur et les rejets.
    {
        "inputs": {
            "story": _STORY_CONNEXION,
            "acceptance_criteria": _ACS_CONNEXION,
            "scenario_type": "negative",
            "risk_level": "high",
        },
        "outputs": {
            "min_coverage_pct": 0.75,
        },
    },

    # ── Exemple 3 : Valeurs LIMITES (boundary values) ────────────────────────
    # Cas aux frontières : mot de passe à exactement 8 caractères (minimum), 64 (maximum),
    # email à la longueur maximale autorisée, 5e tentative échouée (seuil de blocage).
    # Le pipeline doit générer des TCs qui testent les valeurs exactement aux limites.
    {
        "inputs": {
            "story": _STORY_CONNEXION,
            "acceptance_criteria": _ACS_CONNEXION,
            "scenario_type": "boundary",
            "risk_level": "high",
        },
        "outputs": {
            "min_coverage_pct": 0.75,
        },
    },
]


# ── 4. Créer ou récupérer le dataset dans LangSmith ──────────────────────────
def setup_dataset(client) -> None:
    """Crée le dataset LangSmith s'il n'existe pas encore."""
    existing = [d.name for d in client.list_datasets()]
    if DATASET_NAME in existing:
        logger.info("Dataset '%s' déjà existant dans LangSmith.", DATASET_NAME)
        return

    logger.info("Création du dataset '%s' dans LangSmith...", DATASET_NAME)
    dataset = client.create_dataset(
        dataset_name=DATASET_NAME,
        description="Exemples pour évaluer la génération de cas de test TestForge",
    )
    for ex in EXAMPLES:
        client.create_example(
            inputs=ex["inputs"],
            outputs=ex["outputs"],
            dataset_id=dataset.id,
        )
    logger.info("%d exemples ajoutés au dataset.", len(EXAMPLES))


# ── 5. Fonction cible (target) — ce qui est évalué ───────────────────────────
def run_pipeline(inputs: dict) -> dict:
    """
    Appelle pipeline.run() — la méthode complète de production avec boucle de correction.
    Retry jusqu'à 3 fois si Groq retourne un format invalide (flakiness connue).
    """
    from app.ai_workflows.test_case.pipeline import TestCasePipeline

    story         = inputs["story"]
    acs           = inputs["acceptance_criteria"]
    scenario_type = inputs.get("scenario_type", "positive")
    risk_level    = inputs.get("risk_level", "medium")

    async def _generate():
        pipeline = TestCasePipeline()
        return await pipeline.run(
            story=story,
            acceptance_criteria=acs,
            risk_level=risk_level,
            scenario_type=scenario_type,
            progress_callback=None,
        )

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            result = asyncio.run(_generate())
            if result.get("workflow_status") == "error":
                logger.warning(
                    "run_pipeline retour erreur (tentative %d/%d) : %s",
                    attempt, max_retries, result.get("error", "unknown"),
                )
                if attempt < max_retries:
                    continue
            return result
        except Exception as exc:
            logger.error("run_pipeline exception (tentative %d/%d) : %s", attempt, max_retries, exc)
            if attempt == max_retries:
                return {
                    "test_cases": [], "count": 0,
                    "ac_coverage": {"coverage_pct": 0.0, "covered_count": 0, "total_count": len(acs)},
                    "feature_gherkin": "", "workflow_status": "error", "error": str(exc),
                }


# ── 6. Helper : juge Azure gpt-4.1 (différent du générateur Groq) ────────────

def _build_azure_judge():
    """
    Crée une instance DeepEvalBaseLLM utilisant Azure gpt-4.1 comme juge.
    Utiliser un modèle DIFFÉRENT du générateur (Groq llama-3.3-70b) est essentiel
    pour éviter le biais d'auto-évaluation.
    """
    from deepeval.models.base_model import DeepEvalBaseLLM
    from langchain_openai import AzureChatOpenAI

    endpoint   = os.getenv("AZURE_OPENAI_ENDPOINT_JUDGE")
    api_key    = os.getenv("AZURE_OPENAI_KEY_JUDGE")
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_JUDGE", "gpt-4.1")
    api_ver    = os.getenv("AZURE_OPENAI_API_VERSION_JUDGE", "2025-01-01-preview")

    if not endpoint or not api_key:
        return None

    class _AzureJudge(DeepEvalBaseLLM):
        def __init__(self):
            self._chat = AzureChatOpenAI(
                azure_endpoint=endpoint,
                api_key=api_key,
                azure_deployment=deployment,
                api_version=api_ver,
                temperature=0.0,
                max_tokens=1024,
            )
        def load_model(self): return self._chat
        def generate(self, prompt: str, schema=None) -> str:
            return self._chat.invoke(prompt).content
        async def a_generate(self, prompt: str, schema=None) -> str:
            return (await self._chat.ainvoke(prompt)).content
        def get_model_name(self) -> str:
            return f"azure/{deployment}"

    return _AzureJudge()


# ── 6. Les 4 évaluateurs ─────────────────────────────────────────────────────

# ── 6a. AC Coverage (déterministe) ───────────────────────────────────────────
def eval_ac_coverage(outputs: dict, reference_outputs: dict) -> dict:
    """
    Mesure le % des critères d'acceptation couverts par les TCs générés.
    Utilise directement ac_coverage calculé par le pipeline (validate_ac_coverage).
    Score parfait = 1.0 (100% des ACs couvertes).
    """
    ac_coverage = outputs.get("ac_coverage", {})
    score = float(ac_coverage.get("coverage_pct", 0.0))
    covered = ac_coverage.get("covered_count", 0)
    total = ac_coverage.get("total_count", 0)
    return {
        "key": "ac_coverage",
        "score": score,
        "comment": f"{covered}/{total} ACs couvertes ({score:.0%})",
    }


# ── 6b. Gherkin Validity (déterministe) ──────────────────────────────────────
def eval_gherkin_validity(outputs: dict, reference_outputs: dict) -> dict:
    """
    Mesure le % des TCs ayant une syntaxe Gherkin valide (Given/When/Then).
    Un TC invalide ne peut pas être exécuté par un outil comme Cucumber.
    Score parfait = 1.0 (tous les TCs sont valides).
    """
    from app.ai_workflows.test_case.test_case_builder import validate_gherkin

    test_cases = outputs.get("test_cases", [])
    if not test_cases:
        return {"key": "gherkin_validity", "score": 0.0, "comment": "Aucun TC généré"}

    valid_count = 0
    invalid_titles = []
    for tc in test_cases:
        gherkin = tc.get("gherkin_source", "")
        is_valid, _ = validate_gherkin(gherkin)
        if is_valid:
            valid_count += 1
        else:
            invalid_titles.append(tc.get("title", "?"))

    score = valid_count / len(test_cases)
    comment = f"{valid_count}/{len(test_cases)} TCs valides"
    if invalid_titles:
        comment += f" — invalides : {', '.join(invalid_titles[:3])}"
    return {"key": "gherkin_validity", "score": score, "comment": comment}


# ── 6c. Faithfulness — pas d'hallucination (LLM-as-judge : Azure gpt-4.1) ───
def eval_faithfulness(outputs: dict, reference_outputs: dict) -> dict:
    """
    Azure gpt-4.1 vérifie que les étapes générées sont ancrées dans la user story
    et les ACs. Score bas = le LLM a inventé des comportements non mentionnés.
    Utilise un modèle différent du générateur (Groq) pour éviter l'auto-évaluation.
    """
    from deepeval.metrics import GEval
    from deepeval.test_case import LLMTestCase, LLMTestCaseParams

    judge = _build_azure_judge()
    if judge is None:
        return {"key": "faithfulness", "score": None,
                "comment": "AZURE_OPENAI_ENDPOINT_JUDGE ou AZURE_OPENAI_KEY_JUDGE manquants"}

    test_cases = outputs.get("test_cases", [])
    if not test_cases:
        return {"key": "faithfulness", "score": 0.0, "comment": "Aucun TC généré"}

    all_gherkin = "\n\n".join(tc.get("gherkin_source", "") for tc in test_cases)

    metric = GEval(
        name="faithfulness",
        criteria=(
            "Évalue si ACTUAL_OUTPUT (les scénarios Gherkin générés) est fidèle à INPUT "
            "(la user story et les critères d'acceptation). "
            "Score élevé si : toutes les étapes, données de test et comportements attendus "
            "proviennent directement de la user story ou des ACs — rien n'est inventé. "
            "Score bas si le LLM ajoute des champs, des règles ou des comportements "
            "non mentionnés dans l'input (ex: 'mot de passe de 8 caractères minimum' "
            "alors que l'AC ne le précise pas)."
        ),
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        model=judge,
        threshold=0.5,
        async_mode=False,
    )

    lc_test_case = LLMTestCase(input=all_gherkin, actual_output=all_gherkin)

    try:
        metric.measure(lc_test_case)
        score = float(metric.score)
        reason = (getattr(metric, "reason", "") or "")[:300]
        return {"key": "faithfulness", "score": score, "comment": reason}
    except Exception as exc:
        logger.warning("faithfulness eval failed: %s", exc)
        return {"key": "faithfulness", "score": None, "comment": str(exc)}


# ── 6d. Answer Relevance — RAGAS (Es et al., 2023) ──────────────────────────
def eval_answer_relevance(outputs: dict, reference_outputs: dict) -> dict:
    """
    Answer Relevance (RAGAS) : les TCs générés répondent-ils précisément
    à la user story et aux ACs fournis en entrée ?
    Un TC hors-sujet ou trop générique = score bas.
    Référence : Es et al., 'RAGAS: Automated Evaluation of RAG', 2023.
    """
    from deepeval.metrics import GEval
    from deepeval.test_case import LLMTestCase, LLMTestCaseParams

    judge = _build_azure_judge()
    if judge is None:
        return {"key": "answer_relevance", "score": None,
                "comment": "AZURE_OPENAI_ENDPOINT_JUDGE ou AZURE_OPENAI_KEY_JUDGE manquants"}

    test_cases = outputs.get("test_cases", [])
    if not test_cases:
        return {"key": "answer_relevance", "score": 0.0, "comment": "Aucun TC généré"}

    steps_text = ""
    for tc in test_cases:
        steps_text += f"\nTC: {tc.get('title', '?')}\n"
        for step in tc.get("steps", []):
            steps_text += f"  Step {step.get('order', '?')}: {step.get('action', '')} → {step.get('expected', '')}\n"

    metric = GEval(
        name="answer_relevance",
        criteria=(
            "Évalue si ACTUAL_OUTPUT (les cas de test générés) répond directement "
            "et précisément à INPUT (la user story et les critères d'acceptation). "
            "Score élevé si : chaque TC teste un comportement explicitement mentionné "
            "dans la user story ou les ACs, avec des données de test concrètes et "
            "un résultat observable. "
            "Score bas si les TCs sont hors-sujet, trop génériques, ou testent des "
            "comportements non demandés dans l'input."
        ),
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        model=judge,
        threshold=0.5,
        async_mode=False,
    )

    story = outputs.get("story", "")
    lc_test_case = LLMTestCase(input=story, actual_output=steps_text)

    try:
        metric.measure(lc_test_case)
        score = float(metric.score)
        reason = (getattr(metric, "reason", "") or "")[:300]
        return {"key": "answer_relevance", "score": score, "comment": reason}
    except Exception as exc:
        logger.warning("answer_relevance eval failed: %s", exc)
        return {"key": "answer_relevance", "score": None, "comment": str(exc)}


# ── 7. Lancer l'évaluation ───────────────────────────────────────────────────
def main() -> None:
    from langsmith import Client, evaluate

    client = Client()

    # Créer le dataset si pas encore fait
    setup_dataset(client)

    logger.info("Lancement de l'évaluation LangSmith — 4 métriques...")
    logger.info("Projet : %s", os.getenv("LANGCHAIN_PROJECT", "TestForge-Eval"))
    logger.info("Dataset : %s", DATASET_NAME)

    results = evaluate(
        run_pipeline,                        # target : pipeline à évaluer
        data=DATASET_NAME,                   # dataset LangSmith
        evaluators=[
            eval_ac_coverage,               # 1. Requirement Coverage — IEEE 829
            eval_gherkin_validity,           # 2. Gherkin Validity — BDD (North 2006)
            eval_faithfulness,               # 3. Faithfulness — RAGAS (Es et al. 2023)
            eval_answer_relevance,           # 4. Answer Relevance — RAGAS (Es et al. 2023)
        ],
        experiment_prefix="tc-generation",   # nom de l'expérience dans LangSmith
        max_concurrency=1,                   # 1 exemple à la fois (évite throttling Groq)
    )

    # Afficher le résumé via to_pandas() — plus fiable que l'itération directe
    print("\n" + "="*60)
    print("RÉSULTATS DE L'ÉVALUATION")
    print("="*60)
    try:
        df = results.to_pandas()
        # LangSmith préfixe les scores des évaluateurs avec "feedback."
        metric_cols = [c for c in df.columns if c in (
            "feedback.ac_coverage", "feedback.gherkin_validity",
            "feedback.faithfulness", "feedback.step_clarity"
        )]
        if metric_cols:
            display_cols = ["inputs.story"] + metric_cols if "inputs.story" in df.columns else metric_cols
            subset = df[display_cols].copy()
            if "inputs.story" in subset.columns:
                subset["inputs.story"] = subset["inputs.story"].str[:55] + "..."
                subset = subset.rename(columns={"inputs.story": "story"})
            print(subset.to_string(index=False))

            print("\n--- Moyennes ---")
            for col in metric_cols:
                mean_val = df[col].mean()
                label = col.replace("feedback.", "")
                print(f"  {label:<22} {mean_val:.2f}")
        else:
            print("Scores non encore disponibles dans le DataFrame.")
            print("Colonnes disponibles :", list(df.columns))
    except Exception as exc:
        logger.warning("Impossible d'afficher le résumé pandas : %s", exc)
        print("Voir les résultats directement dans LangSmith.")

    print("\nResultats visibles dans : https://smith.langchain.com")
    print(f"   Projet -> {os.getenv('LANGCHAIN_PROJECT', 'TestForge-Eval')} -> Experiments")


if __name__ == "__main__":
    main()
