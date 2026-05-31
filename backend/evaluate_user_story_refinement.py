"""
LangSmith evaluation for the TestForge user story refinement pipeline.

4 métriques choisies pour cette tâche :
  1. score_improvement   — gain de score qualité initial→final              (déterministe)
  2. invest_compliance   — respect des principes INVEST                      (déterministe)
  3. ac_completeness     — ACs complètes, vérifiables et mesurables          (Azure gpt-4.1)
  4. story_clarity       — story claire, au bon format, sans termes vagues   (Azure gpt-4.1)

Le raffineur utilise Groq llama-3.3-70b.
Le juge utilise Azure gpt-4.1 (modèle différent → évaluation non biaisée).

Usage (depuis backend/) :
  python evaluate_user_story_refinement.py

Prérequis dans backend/.env :
  LANGSMITH_API_KEY=ls__...
  LANGSMITH_TRACING=true
  LANGSMITH_ENDPOINT=https://api.smith.langchain.com
  LANGCHAIN_PROJECT=TestForge-Eval
  GROQ_API_KEY_1=...
  AZURE_OPENAI_ENDPOINT_JUDGE=https://...
  AZURE_OPENAI_KEY_JUDGE=...
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
    logger.error("Clé LangSmith introuvable. Ajoute LANGSMITH_API_KEY dans backend/.env")
    sys.exit(1)

os.environ.setdefault("LANGCHAIN_PROJECT", os.getenv("LANGCHAIN_PROJECT", "TestForge-Eval"))

# ── 3. Dataset — exemples de user stories à raffiner ─────────────────────────
DATASET_NAME = "testforge-us-refinement-v1"

EXAMPLES = [
    # ── Exemple 1 : Story de mauvaise qualité ────────────────────────────────
    # Vague, pas de format As a…/I want…/so that…, pas d'ACs.
    # Le pipeline doit améliorer significativement le score.
    {
        "inputs": {
            "story": (
                "L'utilisateur veut se connecter rapidement et facilement au système "
                "afin de pouvoir accéder aux fonctionnalités."
            ),
            "acceptance_criteria": [],
            "language": "fr",
        },
        "outputs": {
            "min_final_score": 0.55,
            "must_improve": True,
        },
    },

    # ── Exemple 2 : Story de qualité moyenne — format correct, ACs insuffisantes ──
    # Format présent mais ACs non mesurables et manque la clause de valeur.
    # Le pipeline doit enrichir les ACs et améliorer la testabilité.
    {
        "inputs": {
            "story": (
                "En tant qu'utilisateur, je veux réinitialiser mon mot de passe "
                "afin de récupérer l'accès à mon compte si je l'oublie."
            ),
            "acceptance_criteria": [
                "L'utilisateur peut demander une réinitialisation",
                "Un email est envoyé",
                "Le lien expire",
            ],
            "language": "fr",
        },
        "outputs": {
            "min_final_score": 0.65,
            "must_improve": True,
        },
    },

    # ── Exemple 3 : Story de bonne qualité avec ACs complètes ────────────────
    # Format correct, ACs mesurables. Le pipeline doit maintenir ou améliorer
    # sans casser la story (role_preserved, language_consistent).
    {
        "inputs": {
            "story": (
                "En tant qu'utilisateur enregistré, je veux me connecter à la plateforme "
                "avec mon adresse e-mail et mon mot de passe afin d'accéder à mon tableau "
                "de bord personnel."
            ),
            "acceptance_criteria": [
                "L'utilisateur peut saisir son adresse e-mail dans le formulaire de connexion",
                "Le système valide que le format de l'adresse e-mail est correct",
                "Le système affiche un message d'erreur clair lorsque les identifiants sont invalides",
                "L'utilisateur est redirigé vers le tableau de bord après une connexion réussie",
                "Un jeton de session est créé et stocké après une connexion réussie",
                "Le système bloque le compte après 5 tentatives de connexion échouées consécutives",
                "Le mot de passe doit contenir entre 8 et 64 caractères",
            ],
            "language": "fr",
        },
        "outputs": {
            "min_final_score": 0.75,
            "must_improve": False,
        },
    },
]


# ── 4. Créer ou récupérer le dataset dans LangSmith ──────────────────────────
def setup_dataset(client) -> None:
    existing = [d.name for d in client.list_datasets()]
    if DATASET_NAME in existing:
        logger.info("Dataset '%s' déjà existant dans LangSmith.", DATASET_NAME)
        return

    logger.info("Création du dataset '%s' dans LangSmith...", DATASET_NAME)
    dataset = client.create_dataset(
        dataset_name=DATASET_NAME,
        description="Exemples pour évaluer le raffinement de user stories TestForge",
    )
    for ex in EXAMPLES:
        client.create_example(
            inputs=ex["inputs"],
            outputs=ex["outputs"],
            dataset_id=dataset.id,
        )
    logger.info("%d exemples ajoutés au dataset.", len(EXAMPLES))


# ── 5. Fonction cible (target) ────────────────────────────────────────────────
def run_pipeline(inputs: dict) -> dict:
    """
    Appelle UserStoryRefinementPipeline.run() — pipeline complet de production.
    Retry jusqu'à 3 fois si le LLM retourne un format invalide.
    """
    from app.ai_workflows.user_story_refinement.workflow import UserStoryRefinementPipeline

    story = inputs["story"]
    acs   = inputs.get("acceptance_criteria", [])
    lang  = inputs.get("language", "fr")

    async def _refine():
        pipeline = UserStoryRefinementPipeline()
        return await pipeline.run(
            story=story,
            acceptance_criteria=acs,
            language=lang,
            progress_callback=None,
        )

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            result = asyncio.run(_refine())
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
                    "improved_story": story,
                    "acceptance_criteria": acs,
                    "is_improved": False,
                    "valid": False,
                    "initial_score": 0.0,
                    "final_score": 0.0,
                    "score": 0.0,
                    "testability_score": 0.0,
                    "invest_score": 0.0,
                    "is_testable": False,
                    "similarity": 1.0,
                    "language_consistent": False,
                    "role_preserved": False,
                    "workflow_status": "error",
                    "error": str(exc),
                }


# ── 6. Helper : juge Azure gpt-4.1 ───────────────────────────────────────────
def _build_azure_judge():
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


# ── 7. Les 4 évaluateurs ─────────────────────────────────────────────────────

# ── 7a. Score Improvement (déterministe) ─────────────────────────────────────
def eval_score_improvement(outputs: dict, reference_outputs: dict) -> dict:
    """
    Mesure le gain de score qualité entre la story originale et la story améliorée.
    Score = final_score du pipeline (0→1).
    On vérifie aussi que le pipeline a atteint le seuil min attendu.
    """
    final_score   = float(outputs.get("final_score", 0.0))
    initial_score = float(outputs.get("initial_score", 0.0))
    delta = final_score - initial_score
    min_expected  = float(reference_outputs.get("min_final_score", 0.0))
    must_improve  = reference_outputs.get("must_improve", True)

    # Score normalisé : on récompense d'atteindre le seuil cible
    score = min(1.0, final_score / max(min_expected, 0.01)) if min_expected > 0 else final_score

    # Pénalité si la story devait s'améliorer mais ne l'a pas fait
    if must_improve and delta <= 0:
        score = max(0.0, score - 0.2)

    comment = (
        f"score {initial_score:.3f} → {final_score:.3f} (Δ{delta:+.3f}) "
        f"| seuil attendu ≥ {min_expected:.2f} | status={outputs.get('workflow_status', '?')}"
    )
    return {"key": "score_improvement", "score": round(score, 3), "comment": comment}


# ── 7b. INVEST Compliance (déterministe) ─────────────────────────────────────
def eval_invest_compliance(outputs: dict, reference_outputs: dict) -> dict:
    """
    Vérifie que la story améliorée respecte les principes INVEST.
    Utilise invest_score calculé par le pipeline (score interne déterministe).
    Score parfait = 1.0 (aucun problème INVEST détecté).
    """
    invest_score = float(outputs.get("invest_score", 0.0))
    invest_issues = outputs.get("invest_issues", [])
    role_preserved = outputs.get("role_preserved", True)
    language_consistent = outputs.get("language_consistent", True)

    # Pénalité légère si le rôle ou la langue ont changé
    adjusted = invest_score
    if not role_preserved:
        adjusted = max(0.0, adjusted - 0.15)
    if not language_consistent:
        adjusted = max(0.0, adjusted - 0.15)

    issues_str = "; ".join(invest_issues[:3]) if invest_issues else "aucun"
    comment = (
        f"invest_score={invest_score:.3f} | rôle préservé={role_preserved} "
        f"| langue cohérente={language_consistent} | problèmes: {issues_str}"
    )
    return {"key": "invest_compliance", "score": round(adjusted, 3), "comment": comment}


# ── 7c. AC Completeness — ACs vérifiables et mesurables (Azure gpt-4.1) ──────
def eval_ac_completeness(outputs: dict, reference_outputs: dict) -> dict:
    """
    Azure gpt-4.1 évalue si les critères d'acceptation générés sont :
    - complets (couvrent les cas nominaux + erreurs)
    - vérifiables (verbe d'action + résultat observable)
    - mesurables (valeurs quantifiables : délai, nombre, longueur)
    Score bas = ACs vagues ou trop peu nombreuses.
    """
    from deepeval.metrics import GEval
    from deepeval.test_case import LLMTestCase, LLMTestCaseParams

    judge = _build_azure_judge()
    if judge is None:
        return {"key": "ac_completeness", "score": None,
                "comment": "AZURE_OPENAI_ENDPOINT_JUDGE ou AZURE_OPENAI_KEY_JUDGE manquants"}

    acs = outputs.get("acceptance_criteria", [])
    story = outputs.get("improved_story", "")

    if not acs:
        return {"key": "ac_completeness", "score": 0.0,
                "comment": "Aucun critère d'acceptation généré"}

    ac_text = "\n".join(f"- {ac}" for ac in acs)

    metric = GEval(
        name="ac_completeness",
        criteria=(
            "Évalue si ACTUAL_OUTPUT (les critères d'acceptation) est complet, "
            "vérifiable et mesurable par rapport à INPUT (la user story améliorée). "
            "Score élevé si : "
            "(1) chaque AC utilise un verbe d'action précis (affiche, retourne, redirige, bloque), "
            "(2) au moins un AC inclut une valeur mesurable (durée, nombre, longueur, pourcentage), "
            "(3) les cas nominaux ET les cas d'erreur sont couverts, "
            "(4) aucun AC n'est vague ('fonctionne correctement', 'répond bien'). "
            "Score bas si les ACs sont trop génériques, non mesurables, ou si des scénarios "
            "importants sont absents (ex: story de connexion sans AC sur les erreurs)."
        ),
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        model=judge,
        threshold=0.5,
        async_mode=False,
    )

    lc_test_case = LLMTestCase(input=story, actual_output=ac_text)

    try:
        metric.measure(lc_test_case)
        score = float(metric.score)
        reason = (getattr(metric, "reason", "") or "")[:300]
        return {"key": "ac_completeness", "score": score, "comment": reason}
    except Exception as exc:
        logger.warning("ac_completeness eval failed: %s", exc)
        return {"key": "ac_completeness", "score": None, "comment": str(exc)}


# ── 7d. Story Clarity — format et clarté (Azure gpt-4.1) ─────────────────────
def eval_story_clarity(outputs: dict, reference_outputs: dict) -> dict:
    """
    Azure gpt-4.1 évalue si la story améliorée est claire et bien formulée :
    - Format respecté (As a… / I want… / so that…)
    - Pas de termes vagues (rapidement, facilement, intuitivement)
    - Une seule fonctionnalité par story (S - Small)
    Score bas = story toujours vague ou trop longue après raffinement.
    """
    from deepeval.metrics import GEval
    from deepeval.test_case import LLMTestCase, LLMTestCaseParams

    judge = _build_azure_judge()
    if judge is None:
        return {"key": "story_clarity", "score": None,
                "comment": "AZURE_OPENAI_ENDPOINT_JUDGE ou AZURE_OPENAI_KEY_JUDGE manquants"}

    improved_story = outputs.get("improved_story", "")
    if not improved_story:
        return {"key": "story_clarity", "score": 0.0, "comment": "Story vide"}

    metric = GEval(
        name="story_clarity",
        criteria=(
            "Évalue si ACTUAL_OUTPUT (la user story améliorée) est claire, bien formatée "
            "et exempte de termes vagues. "
            "Score élevé si : "
            "(1) le format est respecté : 'En tant que [rôle], je veux [action], afin de [bénéfice]' "
            "ou équivalent anglais 'As a [role], I want [feature], so that [benefit]', "
            "(2) aucun terme vague n'est présent (rapidement, facilement, efficacement, "
            "intuitivement, seamless, robust), "
            "(3) la story décrit UNE SEULE fonctionnalité (pas un ensemble), "
            "(4) la story est concise (idéalement 15-40 mots). "
            "Score bas si : format manquant, termes vagues présents, story trop large ou trop vague."
        ),
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        model=judge,
        threshold=0.5,
        async_mode=False,
    )

    lc_test_case = LLMTestCase(
        input="Évaluer la clarté et le format de cette user story améliorée:",
        actual_output=improved_story,
    )

    try:
        metric.measure(lc_test_case)
        score = float(metric.score)
        reason = (getattr(metric, "reason", "") or "")[:300]
        return {"key": "story_clarity", "score": score, "comment": reason}
    except Exception as exc:
        logger.warning("story_clarity eval failed: %s", exc)
        return {"key": "story_clarity", "score": None, "comment": str(exc)}


# ── 8. Lancer l'évaluation ───────────────────────────────────────────────────
def main() -> None:
    from langsmith import Client, evaluate

    client = Client()

    setup_dataset(client)

    logger.info("Lancement de l'évaluation LangSmith — 4 métriques (user story refinement)...")
    logger.info("Projet  : %s", os.getenv("LANGCHAIN_PROJECT", "TestForge-Eval"))
    logger.info("Dataset : %s", DATASET_NAME)

    results = evaluate(
        run_pipeline,
        data=DATASET_NAME,
        evaluators=[
            eval_score_improvement,   # 1. Score improvement (déterministe)
            eval_invest_compliance,   # 2. INVEST compliance (déterministe)
            eval_ac_completeness,     # 3. AC completeness (LLM-as-judge)
            eval_story_clarity,       # 4. Story clarity (LLM-as-judge)
        ],
        experiment_prefix="us-refinement",
        max_concurrency=1,
    )

    print("\n" + "=" * 60)
    print("RÉSULTATS DE L'ÉVALUATION — USER STORY REFINEMENT")
    print("=" * 60)
    try:
        df = results.to_pandas()
        metric_cols = [c for c in df.columns if c in (
            "feedback.score_improvement", "feedback.invest_compliance",
            "feedback.ac_completeness", "feedback.story_clarity",
        )]
        if metric_cols:
            display_cols = (
                ["inputs.story"] + metric_cols
                if "inputs.story" in df.columns else metric_cols
            )
            subset = df[display_cols].copy()
            if "inputs.story" in subset.columns:
                subset["inputs.story"] = subset["inputs.story"].str[:55] + "..."
                subset = subset.rename(columns={"inputs.story": "story"})
            print(subset.to_string(index=False))

            print("\n--- Moyennes ---")
            for col in metric_cols:
                mean_val = df[col].mean()
                label = col.replace("feedback.", "")
                print(f"  {label:<25} {mean_val:.2f}")
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
