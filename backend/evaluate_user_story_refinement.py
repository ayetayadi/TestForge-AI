"""
LangSmith evaluation for the TestForge user story refinement pipeline.

4 métriques issues de la littérature :
  1. semantic_similarity — similarité sémantique SBERT original→amélioré    (Reimers & Gurevych, 2019)
  2. invest_compliance   — respect du framework INVEST                       (Wake, 2003 ; Cohn, 2004)
  3. verifiability       — ACs vérifiables et mesurables (IEEE 830)          (Azure gpt-4.1 / G-Eval)
  4. aqusa_quality       — qualité AQUSA : format, clarté, atomicité         (Lucassen et al., 2016)

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

# ── 7a. Semantic Similarity — SBERT (Reimers & Gurevych, 2019) ───────────────
def eval_semantic_similarity(outputs: dict, reference_outputs: dict) -> dict:
    """
    Mesure la similarité sémantique cosinus entre la story originale et la story
    améliorée, calculée via paraphrase-multilingual-MiniLM-L12-v2 (SBERT).
    Un score élevé garantit que le sens et l'intention sont préservés après
    raffinement — contrainte essentielle pour éviter la dérive sémantique.
    Référence : Reimers & Gurevych, 'Sentence-BERT', EMNLP 2019.
    """
    similarity = float(outputs.get("similarity", 0.0))
    is_improved = outputs.get("is_improved", False)
    status = outputs.get("workflow_status", "?")
    comment = (
        f"similarité cosinus SBERT = {similarity:.3f} "
        f"| is_improved={is_improved} | status={status}"
    )
    return {"key": "semantic_similarity", "score": round(similarity, 3), "comment": comment}


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


# ── 7c. Verifiability — IEEE 830 (LLM-as-judge : Azure gpt-4.1) ─────────────
def eval_verifiability(outputs: dict, reference_outputs: dict) -> dict:
    """
    IEEE 830 exige que chaque exigence soit 'verifiable' : il doit exister
    un processus fini et économiquement viable pour vérifier qu'elle est satisfaite.
    Évalue si les ACs générées sont vérifiables par test (verbe d'action précis,
    valeur mesurable, résultat observable).
    Référence : IEEE Std 830-1998, section 4.3.
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
        return {"key": "verifiability", "score": 0.0,
                "comment": "Aucun critère d'acceptation généré"}

    ac_text = "\n".join(f"- {ac}" for ac in acs)

    metric = GEval(
        name="verifiability",
        criteria=(
            "Évalue si ACTUAL_OUTPUT (les critères d'acceptation) est vérifiable "
            "au sens IEEE 830 par rapport à INPUT (la user story améliorée). "
            "Score élevé si : "
            "(1) chaque AC utilise un verbe d'action précis (affiche, retourne, redirige, bloque), "
            "(2) au moins un AC inclut une valeur mesurable (durée, nombre, longueur, pourcentage), "
            "(3) les cas nominaux ET les cas d'erreur sont couverts, "
            "(4) aucun AC n'est vague ('fonctionne correctement', 'répond bien'). "
            "Score bas si les ACs sont ambiguës, non mesurables, ou non testables "
            "par un processus défini — critères IEEE 830 section 4.3."
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
        return {"key": "verifiability", "score": score, "comment": reason}
    except Exception as exc:
        logger.warning("verifiability eval failed: %s", exc)
        return {"key": "verifiability", "score": None, "comment": str(exc)}


# ── 7d. AQUSA Quality — Lucassen et al., 2016 (LLM-as-judge : Azure gpt-4.1) ─
def eval_aqusa_quality(outputs: dict, reference_outputs: dict) -> dict:
    """
    Évalue la qualité de la user story selon les critères AQUSA
    (Automatic Quality User Story Artisan) : well-formed, atomic, unambiguous.
    - Well-formed : format 'En tant que [rôle] / je veux / afin de' respecté
    - Atomic : une seule fonctionnalité par story (critère S d'INVEST)
    - Unambiguous : absence de termes vagues (rapidement, facilement, etc.)
    Référence : Lucassen et al., 'Forging High-Quality User Stories', RE 2016.
    """
    from deepeval.metrics import GEval
    from deepeval.test_case import LLMTestCase, LLMTestCaseParams

    judge = _build_azure_judge()
    if judge is None:
        return {"key": "story_clarity", "score": None,
                "comment": "AZURE_OPENAI_ENDPOINT_JUDGE ou AZURE_OPENAI_KEY_JUDGE manquants"}

    improved_story = outputs.get("improved_story", "")
    if not improved_story:
        return {"key": "aqusa_quality", "score": 0.0, "comment": "Story vide"}

    metric = GEval(
        name="aqusa_quality",
        criteria=(
            "Évalue si ACTUAL_OUTPUT (la user story améliorée) satisfait les critères "
            "AQUSA (Lucassen et al., 2016) : well-formed, atomic, unambiguous. "
            "Score élevé si : "
            "(1) Well-formed : format respecté 'En tant que [rôle], je veux [action], "
            "afin de [bénéfice]' ou 'As a [role], I want [feature], so that [benefit]', "
            "(2) Unambiguous : aucun terme vague (rapidement, facilement, efficacement, "
            "intuitivement, seamless, robust), "
            "(3) Atomic : la story décrit UNE SEULE fonctionnalité (critère S d'INVEST), "
            "(4) Minimal : concise, idéalement 15-40 mots, sans détails d'implémentation. "
            "Score bas si : format manquant (not well-formed), termes vagues (ambiguous), "
            "ou plusieurs fonctionnalités (not atomic)."
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
        return {"key": "aqusa_quality", "score": score, "comment": reason}
    except Exception as exc:
        logger.warning("aqusa_quality eval failed: %s", exc)
        return {"key": "aqusa_quality", "score": None, "comment": str(exc)}


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
            eval_semantic_similarity, # 1. Semantic Similarity — SBERT (Reimers & Gurevych, 2019)
            eval_invest_compliance,   # 2. INVEST Compliance — Wake 2003, Cohn 2004
            eval_verifiability,       # 3. Verifiability — IEEE 830 (LLM-as-judge)
            eval_aqusa_quality,       # 4. AQUSA Quality — Lucassen et al. 2016 (LLM-as-judge)
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
            "feedback.semantic_similarity", "feedback.invest_compliance",
            "feedback.verifiability", "feedback.aqusa_quality",
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
