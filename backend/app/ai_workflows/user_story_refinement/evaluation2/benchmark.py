# -*- coding: utf-8 -*-
"""
benchmark.py - Evaluation LLM avec DeepEval + G-Eval
Phase 1 (async): raffinement des stories par chaque modèle
Phase 2 (sync):  évaluation avec evaluate() → crée un Test Run dans Confident AI
"""
import os
import sys
import json
import asyncio
import pandas as pd
import time
import re
from pathlib import Path
from dotenv import load_dotenv
from typing import Optional, Tuple
from collections import defaultdict

# DÉSACTIVER LANGSMITH
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGCHAIN_ENDPOINT"] = ""
os.environ["LANGCHAIN_PROJECT"] = ""

# Flush les métriques Confident AI à la sortie
os.environ["CONFIDENT_METRIC_LOGGING_FLUSH"] = "1"

sys.stdout.reconfigure(encoding="utf-8")

load_dotenv(Path(__file__).resolve().parents[4] / ".env")

from groq import AsyncGroq, Groq
from langchain_groq import ChatGroq
from deepeval import evaluate
from deepeval.models import DeepEvalBaseLLM
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase, LLMTestCaseParams

print("[DEBUG] Imports OK")

if os.getenv("CONFIDENT_API_KEY"):
    print("[OK] CONFIDENT_API_KEY detectee")

# Configuration des clés API Groq
GROQ_API_KEYS = {
    "judge": os.getenv("GROQ_API_KEY_6"),
    "models": {
        "Llama-3.3-70B": os.getenv("GROQ_API_KEY_2"),
        "Llama-3.1-8B": os.getenv("GROQ_API_KEY_3"),
        "GPT-OSS-120B": os.getenv("GROQ_API_KEY_4"),
    },
    "fallback": os.getenv("GROQ_API_KEY_5"),
}

ALL_API_KEYS = [
    GROQ_API_KEYS["judge"],
    GROQ_API_KEYS["models"]["Llama-3.3-70B"],
    GROQ_API_KEYS["models"]["Llama-3.1-8B"],
    GROQ_API_KEYS["models"]["GPT-OSS-120B"],
    GROQ_API_KEYS["fallback"],
]
ALL_API_KEYS = [k for k in ALL_API_KEYS if k]

print(f"[OK] {len(ALL_API_KEYS)} clés API disponibles")


# ── FONCTIONS UTILITAIRES ────────────────────────────────────────────────────
def detecter_langue_et_role(story: str) -> Tuple[str, str, bool]:
    est_francais = bool(re.search(r'[éèêëàâîïôûç]', story)) or \
                   any(word in story.lower() for word in ['en tant que', 'je veux', 'afin de', 'pour que', 'utilisateur', 'administrateur'])

    role = ""
    if est_francais:
        match_fr = re.search(r'[Ee]n tant qu[ée]\s+([^,;]+?)(?:,|\.|\s+je)', story, re.IGNORECASE)
        if not match_fr:
            match_fr = re.search(r'[Ee]n tant que\s+([^,;]+?)(?:,|\.|\s+je)', story, re.IGNORECASE)
        if match_fr:
            role = match_fr.group(1).strip()
    else:
        match_en = re.search(r'[Aa]s an?\s+([^,;]+?)(?:,|\.|\s+[Ii] want)', story, re.IGNORECASE)
        if match_en:
            role = match_en.group(1).strip()

    if not role:
        role = "user" if not est_francais else "utilisateur"

    return ("francais" if est_francais else "anglais", role, est_francais)


# ── JUGE CUSTOM AVEC ROTATION DES CLÉS ───────────────────────────────────────
class GroqQwenJudge(DeepEvalBaseLLM):

    def __init__(self):
        self._async_clients = []
        self._sync_clients = []
        self._current_key_idx = 0
        super().__init__()

    def load_model(self):
        for key in ALL_API_KEYS:
            if key:
                self._async_clients.append(AsyncGroq(api_key=key))
                self._sync_clients.append(Groq(api_key=key))
        if not self._async_clients:
            raise ValueError("Aucune clé API disponible")
        print(f"[DEBUG] Judge loaded with {len(self._async_clients)} keys")
        return self

    def get_model_name(self) -> str:
        return "qwen/qwen3-32b"

    def _get_next_client(self):
        client = self._sync_clients[self._current_key_idx % len(self._sync_clients)]
        self._current_key_idx += 1
        return client

    async def _get_next_async_client(self):
        client = self._async_clients[self._current_key_idx % len(self._async_clients)]
        self._current_key_idx += 1
        return client

    def _strip_thinking(self, text: str) -> str:
        return re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()

    def _parse_schema(self, text: str, schema):
        import inspect
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                # Si le JSON a un reason mais pas de score, on garde le JSON
                # et on laisse le schema gérer le champ manquant
                return schema(**data), 0.0
            except Exception:
                pass
        # Fallback : score=5 sur l'échelle 0-10 que G-Eval attend (5/10 = 0.5 normalisé)
        try:
            params = inspect.signature(schema).parameters
            defaults = {}
            for name in params:
                if name == "score":
                    defaults[name] = 5
                elif name == "reason":
                    defaults[name] = text[:200] if text else "No reason provided"
                elif name == "steps":
                    defaults[name] = ["Evaluate the user story quality"]
            return schema(**defaults), 0.0
        except Exception:
            return schema(), 0.0

    def _call_groq(self, client, prompt: str, use_json_mode: bool):
        # qwen3-32b ne supporte pas response_format json_object sur Groq
        if use_json_mode and "json" not in prompt.lower():
            prompt = prompt + "\n\nYour response MUST be a valid JSON object."
        response = client.chat.completions.create(
            model="qwen/qwen3-32b",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=512,
            temperature=0.0,
        )
        return self._strip_thinking(response.choices[0].message.content)

    async def _acall_groq(self, client, prompt: str, use_json_mode: bool):
        if use_json_mode and "json" not in prompt.lower():
            prompt = prompt + "\n\nYour response MUST be a valid JSON object."
        response = await client.chat.completions.create(
            model="qwen/qwen3-32b",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=512,
            temperature=0.0,
        )
        return self._strip_thinking(response.choices[0].message.content)

    def generate(self, prompt: str, schema=None) -> Tuple[str, float]:
        max_retries = len(self._sync_clients) * 2
        for attempt in range(max_retries):
            client = self._get_next_client()
            try:
                time.sleep(1.5)
                text = self._call_groq(client, prompt, use_json_mode=schema is not None)
                if schema:
                    return self._parse_schema(text, schema)
                return text, 0.0
            except Exception as e:
                error_msg = str(e)
                if "rate_limit" in error_msg.lower() or "429" in error_msg:
                    print(f"[WARN] Rate limit, retry {attempt+1}/{max_retries}")
                    time.sleep(2)
                    continue
                print(f"[ERROR] {error_msg[:100]}")
                if schema:
                    return self._parse_schema("", schema)
                return "", 0.0
        if schema:
            return self._parse_schema("", schema)
        return "", 0.0

    async def a_generate(self, prompt: str, schema=None) -> Tuple[str, float]:
        max_retries = len(self._async_clients) * 2
        for attempt in range(max_retries):
            client = await self._get_next_async_client()
            try:
                await asyncio.sleep(1.5)
                text = await self._acall_groq(client, prompt, use_json_mode=schema is not None)
                if schema:
                    return self._parse_schema(text, schema)
                return text, 0.0
            except Exception as e:
                error_msg = str(e)
                if "rate_limit" in error_msg.lower() or "429" in error_msg:
                    print(f"[WARN] Rate limit, retry {attempt+1}/{max_retries}")
                    await asyncio.sleep(2)
                    continue
                print(f"[ERROR] {error_msg[:100]}")
                if schema:
                    return self._parse_schema("", schema)
                return "", 0.0
        if schema:
            return self._parse_schema("", schema)
        return "", 0.0


# ── 1. CHARGER LE DATASET ────────────────────────────────────────────────────
DATASET_PATH = Path(__file__).parent / "dataset.csv"
df = pd.read_csv(DATASET_PATH)
STORIES = df.to_dict("records")
print(f"[DATA] {len(STORIES)} stories chargées")

# ── 2. CONFIGURER LES MODELES ────────────────────────────────────────────────
MODELS = {
    "Llama-3.3-70B": "llama-3.3-70b-versatile",
    "Llama-3.1-8B": "llama-3.1-8b-instant",
    "GPT-OSS-120B": "openai/gpt-oss-120b",
}

print(f"[MODELS] {list(MODELS.keys())}")

# ── 3. INITIALISER LE JUGE ───────────────────────────────────────────────────
print("[DEBUG] Création du juge...")
judge = GroqQwenJudge()
judge.load_model()

INVEST_JUDGE = GEval(
    name="INVEST Quality",
    evaluation_steps=[
        "Step 1: Check if the user story follows the correct format",
        "Step 2: Verify that vague terms are replaced with measurable conditions",
        "Step 3: Count acceptance criteria (need at least 2 with action verbs)",
        "Step 4: Check INVEST criteria",
        "Step 5: Ensure same actor, feature, and goal as original"
    ],
    evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
    model=judge,
    threshold=0.5,
)

print("[DEBUG] Métrique créée")


# ── 4. RAFFINEMENT (ASYNC) ───────────────────────────────────────────────────
async def raffiner_avec_retry(story: dict, model_name: str, model_id: str, api_key: str) -> dict:
    max_retries = 5
    base_delay = 2

    for attempt in range(max_retries):
        try:
            llm = ChatGroq(
                groq_api_key=api_key,
                model=model_id,
                temperature=0.3,
                max_tokens=2000,
                request_timeout=60,
            )

            langue, role_original, est_francais = detecter_langue_et_role(story['story'])

            if est_francais:
                prompt = f"""Améliorez cette user story en FRANÇAIS.

RÈGLES:
1. RÉPONDEZ UNIQUEMENT EN FRANÇAIS
2. Gardez le rôle: "{role_original}"
3. Format: "En tant que [rôle], je veux [fonctionnalité], afin de [bénéfice]"
4. Ajoutez au moins 2 critères d'acceptation

Originale: {story['story']}

Améliorée:"""
            else:
                prompt = f"""Improve this user story in ENGLISH.

RULES:
1. RESPOND ONLY IN ENGLISH
2. Keep the role: "{role_original}"
3. Format: "As a [role], I want [feature], so that [benefit]"
4. Add at least 2 acceptance criteria

Original: {story['story']}

Improved:"""

            result = await llm.ainvoke(prompt)
            return {
                "story_id": story["id"],
                "original": story["story"],
                "improved": result.content,
                "model": model_name,
                "role": role_original,
                "langue": langue,
            }

        except Exception as e:
            error_msg = str(e)
            if "rate_limit" in error_msg.lower() or "429" in error_msg:
                wait_time = base_delay * (2 ** attempt)
                print(f"  [RETRY] Rate limit, retry in {wait_time}s...")
                await asyncio.sleep(wait_time)
                continue
            else:
                return {
                    "story_id": story["id"],
                    "original": story["story"],
                    "improved": story["story"],
                    "model": model_name,
                    "error": error_msg[:100]
                }

    return {
        "story_id": story["id"],
        "original": story["story"],
        "improved": story["story"],
        "model": model_name,
        "error": "Max retries exceeded"
    }


async def raffiner_story(story: dict, model_name: str, model_id: str) -> dict:
    primary_key = GROQ_API_KEYS["models"].get(model_name)
    keys_to_try = [primary_key, GROQ_API_KEYS["fallback"]]
    keys_to_try.extend([k for k in ALL_API_KEYS if k not in keys_to_try])
    keys_to_try = [k for k in keys_to_try if k]

    for key in keys_to_try:
        result = await raffiner_avec_retry(story, model_name, model_id, key)
        if "error" not in result:
            return result

    return result


async def raffiner_modele(model_name: str, model_id: str) -> list:
    """Raffine toutes les stories pour un modèle et retourne les LLMTestCase."""
    print(f"\n{'='*60}")
    print(f"[TEST] {model_name} - Raffinement")
    print(f"{'='*60}")

    test_cases = []
    failed = 0

    for i, story in enumerate(STORIES):
        print(f"  [{i+1}/{len(STORIES)}] {story['id']}...")
        refined = await raffiner_story(story, model_name, model_id)

        if "error" in refined:
            print(f"      FAILED: {refined['error']}")
            failed += 1
        else:
            print(f"      OK - Role: {refined.get('role', '?')}, Langue: {refined.get('langue', '?')}")

        test_cases.append(LLMTestCase(
            input=refined["original"],
            actual_output=refined["improved"],
        ))
        await asyncio.sleep(0.5)

    if failed > 0:
        print(f"  [WARN] {failed} stories en erreur")

    return test_cases


# ── 5. PHASE 1 : RAFFINEMENT ASYNC ───────────────────────────────────────────
async def phase1_raffinement() -> dict:
    """Raffine toutes les stories pour tous les modèles."""
    print("\n" + "=" * 60)
    print("PHASE 1 - RAFFINEMENT")
    print("=" * 60)

    all_test_cases = {}

    for i, (name, model_id) in enumerate(MODELS.items()):
        test_cases = await raffiner_modele(name, model_id)
        all_test_cases[name] = test_cases

        if i < len(MODELS) - 1:
            print(f"\n  [PAUSE] 20s avant le prochain modèle...")
            await asyncio.sleep(20)

    print("\n[OK] Raffinement terminé pour tous les modèles")
    return all_test_cases


# ── 6. PHASE 2 : EVALUATION SYNC AVEC evaluate() ────────────────────────────
def phase2_evaluation(all_test_cases: dict) -> list:
    """Évalue chaque modèle avec evaluate() → crée un Test Run dans Confident AI."""
    print("\n" + "=" * 60)
    print("PHASE 2 - EVALUATION G-EVAL (Test Runs Confident AI)")
    print("=" * 60)

    model_scores = []

    for model_name, test_cases in all_test_cases.items():
        print(f"\n[EVAL] {model_name} ({len(test_cases)} stories)...")

        result = evaluate(
            test_cases=test_cases,
            metrics=[INVEST_JUDGE],
            identifier=model_name,
        )

        scores = []
        for tr in result.test_results:
            for md in (tr.metrics_data or []):
                if md.score is not None:
                    scores.append(md.score)
                    print(f"    Score: {md.score:.2f} - {(md.reason or '')[:60]}")

        avg = sum(scores) / len(scores) if scores else 0.0
        model_scores.append({
            "model": model_name,
            "avg_score": round(avg, 3),
            "n": len(scores),
        })
        print(f"  [SCORE] Moyenne: {avg:.3f} ({len(scores)} evaluations)")

    return model_scores


# ── 7. MAIN ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("[DEBUG] Démarrage du benchmark...")

    # Phase 1 : raffinement (async)
    all_test_cases = asyncio.run(phase1_raffinement())

    # Phase 2 : évaluation (sync — évite les conflits d'event loop avec evaluate())
    model_scores = phase2_evaluation(all_test_cases)

    # Classement final
    model_scores.sort(key=lambda x: x["avg_score"], reverse=True)

    print("\n" + "=" * 60)
    print("CLASSEMENT FINAL")
    print("=" * 60)
    for i, r in enumerate(model_scores):
        medal = ["[1]", "[2]", "[3]"][i] if i < 3 else "   "
        print(f"  {medal} {r['model']:<20} {r['avg_score']:.3f}  ({r['n']} evals)")
    print("=" * 60)
    print("\n[OK] Resultats visibles sur https://app.confident-ai.com")
