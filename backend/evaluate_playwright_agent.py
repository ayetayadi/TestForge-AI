"""
LangSmith evaluation for the TestForge Playwright ReAct agent.

3 métriques :
  1. task_success       — le PASS/FAIL de l'agent correspond-il au résultat attendu ?  (déterministe)
  2. step_success_rate  — quelle proportion des steps Gherkin a été validée ?           (déterministe)
  3. script_quality     — le script TypeScript généré est-il valide et fidèle au TC ?   (Azure gpt-4.1)

Usage (depuis backend/, avec l'app sur localhost:3010 et MCP sur localhost:8931) :
  python evaluate_playwright_agent.py

Prérequis dans backend/.env :
  LANGSMITH_API_KEY=...
  LANGCHAIN_PROJECT=TestForge-Eval
  TEST_APPLICATION_URL=http://localhost:3010
  MCP_PLAYWRIGHT_SERVER_URL=http://localhost:8931
  TEST_USER_EMAIL=...
  TEST_USER_PASSWORD=...
  AZURE_OPENAI_ENDPOINT_JUDGE=...
  AZURE_OPENAI_KEY_JUDGE=...
  AZURE_OPENAI_DEPLOYMENT_JUDGE=gpt-4.1
"""

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)

LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY")
if not LANGSMITH_API_KEY:
    logger.error("Clé LangSmith introuvable. Ajoute LANGSMITH_API_KEY dans backend/.env")
    sys.exit(1)

os.environ.setdefault("LANGCHAIN_PROJECT", os.getenv("LANGCHAIN_PROJECT", "TestForge-Eval"))

APP_URL = os.getenv("TEST_APPLICATION_URL", "http://localhost:3010")

DATASET_NAME = "testforge-playwright-react-v1"

# ── Dataset ────────────────────────────────────────────────────────────────────
# Chaque exemple = un test case que l'agent doit exécuter contre l'app réelle.
# expected_verdict : "PASS" si l'app se comporte normalement, "FAIL" si le test
# doit échouer (ex : login avec mauvais mot de passe).
EXAMPLES = [
    # ── Exemple 1 : Login avec identifiants valides ──────────────────────────
    # L'agent doit naviguer sur /login, remplir les champs, cliquer, et vérifier
    # qu'il est redirigé vers le dashboard. Résultat attendu : PASS.
    {
        "inputs": {
            "test_case": {
                "title": "Login with valid credentials",
                "gherkin_source": (
                    "Given I am on the login page\n"
                    "When I enter valid email and password\n"
                    "And I click the Login button\n"
                    "Then I should be redirected to the dashboard"
                ),
                "test_data": {
                    "email": os.getenv("TEST_USER_EMAIL", ""),
                    "password": os.getenv("TEST_USER_PASSWORD", ""),
                },
                "expected_results": [
                    "User is redirected to the main dashboard after login",
                    "No error message is displayed",
                ],
            },
            "app_url": APP_URL,
        },
        "outputs": {
            "expected_verdict": "PASS",
        },
    },

    # ── Exemple 2 : Login avec mauvais mot de passe ──────────────────────────
    # L'agent doit détecter le message d'erreur affiché et conclure FAIL.
    # Résultat attendu : FAIL (le comportement de l'app est correct, mais le TC
    # vérifie qu'une erreur est bien déclenchée — l'agent doit la détecter).
    {
        "inputs": {
            "test_case": {
                "title": "Login with wrong password",
                "gherkin_source": (
                    "Given I am on the login page\n"
                    "When I enter a valid email and an incorrect password\n"
                    "And I click the Login button\n"
                    "Then I should see an error message\n"
                    "And I should remain on the login page"
                ),
                "test_data": {
                    "email": os.getenv("TEST_USER_EMAIL", ""),
                    "password": "WrongPassword999!",
                },
                "expected_results": [
                    "An error message is displayed (invalid credentials)",
                    "The user is NOT redirected to the dashboard",
                ],
            },
            "app_url": APP_URL,
        },
        "outputs": {
            "expected_verdict": "PASS",  # l'agent doit trouver le message d'erreur → test PASS
        },
    },

    # ── Exemple 3 : Créer un nouveau projet ──────────────────────────────────
    # L'agent est auto-loggué, navigue vers la page projets, crée un projet.
    # Résultat attendu : PASS si la création réussit.
    {
        "inputs": {
            "test_case": {
                "title": "Create a new project",
                "gherkin_source": (
                    "Given I am logged in and on the Projects page\n"
                    "When I click the New Project button\n"
                    "And I fill in the project name\n"
                    "And I submit the form\n"
                    "Then the new project should appear in the projects list"
                ),
                "test_data": {
                    "project_name": "Eval Test Project",
                },
                "expected_results": [
                    "A new project named 'Eval Test Project' appears in the list",
                    "No error message is shown",
                ],
            },
            "app_url": APP_URL,
        },
        "outputs": {
            "expected_verdict": "PASS",
        },
    },
]


# ── Dataset setup ──────────────────────────────────────────────────────────────
def setup_dataset(client) -> None:
    existing = [d.name for d in client.list_datasets()]
    if DATASET_NAME in existing:
        logger.info("Dataset '%s' déjà existant dans LangSmith.", DATASET_NAME)
        return

    logger.info("Création du dataset '%s'...", DATASET_NAME)
    dataset = client.create_dataset(
        dataset_name=DATASET_NAME,
        description="Exemples pour évaluer le ReAct agent Playwright de TestForge",
    )
    for ex in EXAMPLES:
        client.create_example(
            inputs=ex["inputs"],
            outputs=ex["outputs"],
            dataset_id=dataset.id,
        )
    logger.info("%d exemples ajoutés.", len(EXAMPLES))


# ── Fonction cible (target) ────────────────────────────────────────────────────
def run_agent(inputs: dict) -> dict:
    """
    Lance le ReAct agent contre l'app réelle et retourne son résultat.
    Nécessite : app sur APP_URL, MCP Playwright sur MCP_PLAYWRIGHT_SERVER_URL.
    """
    from app.ai_agents_v2.playwright_e2e.agent import PlaywrightReActAgent
    from app.ai_agents_v2.playwright_e2e.tools import PlaywrightMCPClient

    test_case = inputs["test_case"]
    app_url   = inputs.get("app_url", APP_URL)

    async def _run():
        agent = PlaywrightReActAgent()
        async with PlaywrightMCPClient(headless=True, browser="chromium") as mcp:
            tools = {t.name: t for t in mcp.tools}
            return await agent.run_react(
                tools,
                test_case=test_case,
                app_url=app_url,
            )

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error("run_agent exception : %s", exc)
        return {
            "script_v2": "",
            "execution_status": "error",
            "steps_passed": 0,
            "steps_failed": 0,
            "action_log": [],
            "error": str(exc),
        }


# ── Helper : juge Azure gpt-4.1 ───────────────────────────────────────────────
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


# ── Métrique 1 : task_success (déterministe) ──────────────────────────────────
# Référence : Zhou et al. (2023) WebArena — métrique principale d'évaluation d'agents.
def eval_task_success(outputs: dict, reference_outputs: dict) -> dict:
    """
    Compare le verdict de l'agent (PASS/FAIL) avec le résultat attendu.
    execution_status == "completed" → PASS, sinon FAIL.
    Binaire : 0 ou 1, aucun seuil à justifier.
    """
    expected = reference_outputs.get("expected_verdict", "PASS").upper()
    status   = outputs.get("execution_status", "error")
    actual   = "PASS" if status == "completed" else "FAIL"

    score   = 1.0 if actual == expected else 0.0
    comment = f"agent={actual} | attendu={expected} | status={status}"
    return {"key": "task_success", "score": score, "comment": comment}


# ── Métrique 2 : step_success_rate (déterministe) ─────────────────────────────
# Référence : Zhou et al. (2023) WebArena — mesure la progression partielle.
def eval_step_success_rate(outputs: dict, reference_outputs: dict) -> dict:
    """
    Proportion des steps Gherkin validés par l'agent : steps_passed / total_steps.
    Valeur entre 0.0 (aucun step réussi) et 1.0 (tous les steps réussis).
    Pas de seuil : la valeur brute est reportée telle quelle.
    """
    passed = outputs.get("steps_passed", 0) or 0
    failed = outputs.get("steps_failed", 0) or 0
    total  = passed + failed

    if total == 0:
        return {"key": "step_success_rate", "score": 0.0,
                "comment": "steps_passed=0 steps_failed=0 — agent n'a pas avancé"}

    score   = round(passed / total, 3)
    comment = f"steps_passed={passed} steps_failed={failed} total={total}"
    return {"key": "step_success_rate", "score": score, "comment": comment}


# ── Métrique 3 : script_quality (Azure gpt-4.1) ───────────────────────────────
def eval_script_quality(outputs: dict, reference_outputs: dict) -> dict:
    """
    Azure gpt-4.1 évalue si le script TypeScript généré est :
    - structuré comme un vrai test Playwright (test(), page., expect())
    - fidèle aux steps Gherkin du test case
    - sans locators hardcodés (pas de [ref=eXX] qui fuient dans le script)
    """
    from deepeval.metrics import GEval
    from deepeval.test_case import LLMTestCase, LLMTestCaseParams

    judge = _build_azure_judge()
    if judge is None:
        return {"key": "script_quality", "score": None,
                "comment": "AZURE_OPENAI_ENDPOINT_JUDGE ou AZURE_OPENAI_KEY_JUDGE manquants"}

    script = outputs.get("script_v2", "")
    if not script or len(script.strip()) < 20:
        return {"key": "script_quality", "score": 0.0, "comment": "Script vide ou trop court"}

    metric = GEval(
        name="script_quality",
        criteria=(
            "Évalue si ACTUAL_OUTPUT (le script TypeScript Playwright généré) est de bonne qualité "
            "par rapport à INPUT (les steps Gherkin du test case). "
            "Score élevé si : "
            "(1) le script utilise les APIs Playwright correctes (page.click, page.fill, "
            "page.getByRole, expect(page).toHaveURL, etc.), "
            "(2) chaque step Gherkin correspond à une action dans le script, "
            "(3) il n'y a pas de références internes '[ref=eXX]' visibles dans le script final, "
            "(4) le script est structuré avec test() et await. "
            "Score bas si le script est vide, contient des placeholders non résolus, "
            "ou ne couvre pas les steps du test case."
        ),
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        model=judge,
        threshold=0.5,
        async_mode=False,
    )

    # INPUT = les steps du TC pour que le juge puisse comparer
    tc_steps = outputs.get("_tc_steps_for_judge", "(steps non disponibles)")
    lc_test_case = LLMTestCase(input=tc_steps, actual_output=script[:2000])

    try:
        metric.measure(lc_test_case)
        score  = float(metric.score)
        reason = (getattr(metric, "reason", "") or "")[:300]
        return {"key": "script_quality", "score": score, "comment": reason}
    except Exception as exc:
        logger.warning("script_quality eval failed: %s", exc)
        return {"key": "script_quality", "score": None, "comment": str(exc)}


# ── Wrapper target : injecte les steps dans l'output pour le juge ─────────────
def run_agent_with_steps(inputs: dict) -> dict:
    """
    Appelle run_agent et ajoute les steps Gherkin dans l'output
    pour que eval_script_quality puisse les passer au juge.
    """
    result = run_agent(inputs)
    tc = inputs.get("test_case", {})
    result["_tc_steps_for_judge"] = tc.get("gherkin_source", tc.get("title", ""))
    return result


# ── Main ───────────────────────────────────────────────────────────────────────
def main() -> None:
    from langsmith import Client, evaluate

    client = Client()
    setup_dataset(client)

    logger.info("Lancement de l'évaluation LangSmith — Playwright ReAct agent (3 métriques — WebArena + DeepEval)")
    logger.info("Projet  : %s", os.getenv("LANGCHAIN_PROJECT", "TestForge-Eval"))
    logger.info("Dataset : %s", DATASET_NAME)
    logger.info("App     : %s", APP_URL)

    results = evaluate(
        run_agent_with_steps,
        data=DATASET_NAME,
        evaluators=[
            eval_task_success,        # 1. verdict correct ? (WebArena)
            eval_step_success_rate,   # 2. steps validés ?   (WebArena)
            eval_script_quality,      # 3. script TS valide ? (DeepEval GEval)
        ],
        experiment_prefix="playwright-react",
        max_concurrency=1,           # les TCs tournent séquentiellement (1 browser à la fois)
    )

    print("\n" + "=" * 60)
    print("RÉSULTATS — PLAYWRIGHT REACT AGENT  (métriques : WebArena + DeepEval)")
    print("=" * 60)
    try:
        df = results.to_pandas()
        metric_cols = [c for c in df.columns if c in (
            "feedback.task_success",
            "feedback.step_success_rate",
            "feedback.script_quality",
        )]
        if metric_cols:
            print(df[metric_cols].to_string(index=False))
            print("\n--- Moyennes ---")
            for col in metric_cols:
                mean_val = df[col].mean()
                label = col.replace("feedback.", "")
                print(f"  {label:<22} {mean_val:.2f}")
        else:
            print("Colonnes disponibles :", list(df.columns))
    except Exception as exc:
        logger.warning("Résumé pandas indisponible : %s", exc)
        print("Voir les résultats dans https://smith.langchain.com")

    print(f"\nRésultats : https://smith.langchain.com → {os.getenv('LANGCHAIN_PROJECT', 'TestForge-Eval')} → Experiments")


if __name__ == "__main__":
    main()
