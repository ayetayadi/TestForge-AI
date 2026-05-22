"""
fetch_groq_models.py
Récupère la liste des modèles Groq via l'API et enrichit chaque modèle
avec ses métadonnées (architecture, capacités, prix, vitesse, benchmarks).
Génère un fichier JSON complet : groq_models_enriched.json
"""

import os
import json
import requests
import sys
import re
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# BASE DE MÉTADONNÉES (sources : docs Groq, pages modèles, model cards)
# ============================================================

MODEL_METADATA = {
    # ── Production Models ─────────────────────────────────────────────────
    "llama-3.3-70b-versatile": {
        "architecture": "Dense (Transformer optimisé, GQA)",
        "category": "Production",
        "type": "Chat",
        "parameters": "70B",
        "training_data": "15T tokens",
        "languages": ["en", "fr", "de", "it", "pt", "hi", "es", "th"],
        "knowledge_cutoff": "2023-12",
        "fine_tuning": "SFT + RLHF",
        "tool_calling": "Parallel",
        "reasoning": False,
        "json_mode": True,
        "vision": False,
        "audio": False,
        "ifeval_score": 92.1,
        "mmlu_score": 86.0,
        "speed_tps": 280,
        "price_input_per_1M": 0.59,
        "price_output_per_1M": 0.79,
        "rate_limit_tpm": 300000,
        "rate_limit_rpm": 1000,
        "provider": "Meta",
    },
    "llama-3.1-8b-instant": {
        "architecture": "Dense (Transformer, GQA)",
        "category": "Production",
        "type": "Chat",
        "parameters": "8B",
        "training_data": "15T tokens",
        "languages": ["en", "fr", "de", "it", "pt", "hi", "es", "th"],
        "knowledge_cutoff": "2023-12",
        "fine_tuning": "SFT + RLHF",
        "tool_calling": "Parallel",
        "reasoning": False,
        "json_mode": True,
        "vision": False,
        "audio": False,
        "ifeval_score": 80.4,
        "mmlu_score": 73.0,
        "speed_tps": 560,
        "price_input_per_1M": 0.05,
        "price_output_per_1M": 0.08,
        "rate_limit_tpm": 250000,
        "rate_limit_rpm": 1000,
        "provider": "Meta",
    },
    "openai/gpt-oss-120b": {
        "architecture": "MoE (120B total, ~18B actifs, Top-4 routing)",
        "category": "Production",
        "type": "Chat + Raisonnement",
        "parameters": "120B",
        "training_data": "N/A",
        "languages": ["en", "multilingual"],
        "knowledge_cutoff": "N/A",
        "fine_tuning": "N/A",
        "tool_calling": "Built-in (Web Search, Code Execution, Browser)",
        "reasoning": True,
        "reasoning_efforts": ["low", "medium", "high"],
        "json_mode": True,
        "vision": False,
        "audio": False,
        "mmlu_score": 85.3,
        "swe_bench_score": 60.7,
        "aime_score": 98.7,
        "speed_tps": 500,
        "price_input_per_1M": 0.15,
        "price_output_per_1M": 0.60,
        "rate_limit_tpm": 250000,
        "rate_limit_rpm": 1000,
        "provider": "OpenAI",
    },
    "openai/gpt-oss-20b": {
        "architecture": "MoE (20B total, 3.6B actifs, Top-4 routing, 24 layers, 32 experts)",
        "category": "Production",
        "type": "Chat + Raisonnement",
        "parameters": "20B",
        "training_data": "N/A",
        "languages": ["en", "multilingual"],
        "knowledge_cutoff": "N/A",
        "fine_tuning": "N/A",
        "tool_calling": "Built-in (Web Search, Code Execution, Browser)",
        "reasoning": True,
        "reasoning_efforts": ["low", "medium", "high"],
        "json_mode": True,
        "vision": False,
        "audio": False,
        "mmlu_score": 85.3,
        "swe_bench_score": 60.7,
        "aime_score": 98.7,
        "speed_tps": 1000,
        "price_input_per_1M": 0.075,
        "price_output_per_1M": 0.30,
        "rate_limit_tpm": 250000,
        "rate_limit_rpm": 1000,
        "provider": "OpenAI",
    },
    "openai/gpt-oss-safeguard-20b": {
        "architecture": "MoE (20B total)",
        "category": "Preview",
        "type": "Safety Guard",
        "parameters": "20B",
        "tool_calling": False,
        "reasoning": False,
        "json_mode": True,
        "vision": False,
        "audio": False,
        "speed_tps": 1000,
        "price_input_per_1M": 0.075,
        "price_output_per_1M": 0.30,
        "rate_limit_tpm": 150000,
        "rate_limit_rpm": 1000,
        "provider": "OpenAI",
    },
    "qwen/qwen3-32b": {
        "architecture": "Dense",
        "category": "Preview",
        "type": "Chat + Raisonnement",
        "parameters": "32B",
        "languages": ["en", "multilingual"],
        "tool_calling": "Parallel",
        "reasoning": True,
        "reasoning_efforts": ["none", "default"],
        "json_mode": True,
        "vision": False,
        "audio": False,
        "speed_tps": 400,
        "price_input_per_1M": 0.29,
        "price_output_per_1M": 0.59,
        "rate_limit_tpm": 300000,
        "rate_limit_rpm": 1000,
        "provider": "Alibaba Cloud",
    },
    "meta-llama/llama-4-scout-17b-16e-instruct": {
        "architecture": "MoE (16 Experts, 17B actifs / 288B totaux)",
        "category": "Preview",
        "type": "Chat",
        "parameters": "17B actifs / 288B totaux",
        "tool_calling": "Parallel",
        "reasoning": False,
        "json_mode": True,
        "vision": True,
        "audio": False,
        "speed_tps": 750,
        "price_input_per_1M": 0.11,
        "price_output_per_1M": 0.34,
        "rate_limit_tpm": 300000,
        "rate_limit_rpm": 1000,
        "provider": "Meta",
    },

    # ── Systems ──────────────────────────────────────────────────────────
    "groq/compound": {
        "architecture": "Système (Multiple modèles + outils)",
        "category": "Production System",
        "type": "Agentic System",
        "parameters": "N/A",
        "tool_calling": "Built-in (Web Search, Code Execution)",
        "reasoning": True,
        "json_mode": True,
        "vision": False,
        "audio": False,
        "speed_tps": 450,
        "price_input_per_1M": 0,
        "price_output_per_1M": 0,
        "provider": "Groq",
    },
    "groq/compound-mini": {
        "architecture": "Système (Multiple modèles + outils)",
        "category": "Production System",
        "type": "Agentic System",
        "parameters": "N/A",
        "tool_calling": "Built-in (Web Search, Code Execution)",
        "reasoning": True,
        "json_mode": True,
        "vision": False,
        "audio": False,
        "speed_tps": 450,
        "price_input_per_1M": 0,
        "price_output_per_1M": 0,
        "provider": "Groq",
    },

    # ── Audio Models ─────────────────────────────────────────────────────
    "whisper-large-v3": {
        "architecture": "Transformer (Audio Encoder-Decoder)",
        "category": "Production",
        "type": "Audio (Speech-to-Text)",
        "parameters": "1.5B",
        "tool_calling": False,
        "reasoning": False,
        "json_mode": False,
        "vision": False,
        "audio": True,
        "speed_tps": None,
        "price_per_hour": 0.111,
        "provider": "OpenAI",
    },
    "whisper-large-v3-turbo": {
        "architecture": "Transformer (Audio Encoder-Decoder)",
        "category": "Production",
        "type": "Audio (Speech-to-Text)",
        "parameters": "800M",
        "tool_calling": False,
        "reasoning": False,
        "json_mode": False,
        "vision": False,
        "audio": True,
        "speed_tps": None,
        "price_per_hour": 0.04,
        "provider": "OpenAI",
    },
    "canopylabs/orpheus-arabic-saudi": {
        "architecture": "Dense (TTS)",
        "category": "Preview",
        "type": "Audio (Text-to-Speech)",
        "parameters": "N/A",
        "tool_calling": False,
        "reasoning": False,
        "json_mode": False,
        "vision": False,
        "audio": True,
        "speed_tps": None,
        "price_per_1M_chars": 40.00,
        "provider": "Canopy Labs",
    },
    "canopylabs/orpheus-v1-english": {
        "architecture": "Dense (TTS)",
        "category": "Preview",
        "type": "Audio (Text-to-Speech)",
        "parameters": "N/A",
        "tool_calling": False,
        "reasoning": False,
        "json_mode": False,
        "vision": False,
        "audio": True,
        "speed_tps": None,
        "price_per_1M_chars": 22.00,
        "provider": "Canopy Labs",
    },

    # ── Guard / Safety Models ────────────────────────────────────────────
    "meta-llama/llama-prompt-guard-2-22m": {
        "architecture": "Dense (Classifier)",
        "category": "Preview",
        "type": "Safety Guard",
        "parameters": "22M",
        "tool_calling": False,
        "reasoning": False,
        "json_mode": False,
        "vision": False,
        "audio": False,
        "speed_tps": None,
        "price_input_per_1M": 0.03,
        "price_output_per_1M": 0.03,
        "provider": "Meta",
    },
    "meta-llama/llama-prompt-guard-2-86m": {
        "architecture": "Dense (Classifier)",
        "category": "Preview",
        "type": "Safety Guard",
        "parameters": "86M",
        "tool_calling": False,
        "reasoning": False,
        "json_mode": False,
        "vision": False,
        "audio": False,
        "speed_tps": None,
        "price_input_per_1M": 0.04,
        "price_output_per_1M": 0.04,
        "provider": "Meta",
    },
}


def _extract_parameters(model_id: str) -> str:
    """Extrait une estimation des paramètres depuis l'ID du modèle."""
    model_lower = model_id.lower()
    match = re.search(r'(\d+)x(\d+)\s*[bB]', model_lower)
    if match:
        return f"{match.group(1)}x{match.group(2)}B (MoE)"
    match = re.search(r'(\d+)\s*[bB]', model_lower)
    if match:
        return f"{match.group(1)}B"
    match = re.search(r'(\d+)\s*[mM]', model_lower)
    if match:
        return f"{match.group(1)}M"
    return "N/A"


def _deduce_type(model_id: str) -> str:
    """Déduit le type de modèle depuis son ID."""
    model_lower = model_id.lower()
    if any(kw in model_lower for kw in ["whisper", "orpheus"]):
        return "Audio"
    if any(kw in model_lower for kw in ["guard", "safeguard", "safety"]):
        return "Safety Guard"
    if "compound" in model_lower:
        return "Agentic System"
    if any(kw in model_lower for kw in ["deepseek", "r1"]):
        return "Raisonnement"
    if any(kw in model_lower for kw in ["gpt-oss", "qwen"]):
        return "Chat + Raisonnement"
    return "Chat"


def enrich_model(model: dict) -> dict:
    """
    Enrichit un modèle brut (depuis l'API) avec toutes les métadonnées disponibles.
    """
    model_id = model.get("id", "unknown")

    # Chercher les métadonnées connues
    metadata = MODEL_METADATA.get(model_id, {})

    # Construire l'objet enrichi
    enriched = {
        # Champs bruts de l'API
        "id": model_id,
        "object": model.get("object", "model"),
        "created": model.get("created"),
        "owned_by": model.get("owned_by", "unknown"),
        "active": model.get("active", True),
        "context_window": model.get("context_window"),
        "max_completion_tokens": model.get("max_completion_tokens"),

        # Métadonnées enrichies
        "architecture": metadata.get("architecture", _deduce_architecture(model_id, model.get("context_window", 0))),
        "category": metadata.get("category", "Inconnue"),
        "type": metadata.get("type", _deduce_type(model_id)),
        "parameters": metadata.get("parameters", _extract_parameters(model_id)),
        "provider": metadata.get("provider", model.get("owned_by", "unknown")),

        # Capacités
        "capabilities": {
            "tool_calling": metadata.get("tool_calling", False),
            "reasoning": metadata.get("reasoning", False),
            "reasoning_efforts": metadata.get("reasoning_efforts", None),
            "json_mode": metadata.get("json_mode", False),
            "vision": metadata.get("vision", False),
            "audio": metadata.get("audio", False),
        },

        # Performance
        "performance": {
            "speed_tps": metadata.get("speed_tps"),
            "ifeval_score": metadata.get("ifeval_score"),
            "mmlu_score": metadata.get("mmlu_score"),
        },

        # Prix
        "pricing": {
            "price_input_per_1M": metadata.get("price_input_per_1M"),
            "price_output_per_1M": metadata.get("price_output_per_1M"),
            "price_per_hour": metadata.get("price_per_hour"),
        },

        # Rate limits
        "rate_limits": {
            "tpm": metadata.get("rate_limit_tpm"),
            "rpm": metadata.get("rate_limit_rpm"),
        },

        # Informations complémentaires
        "training_data": metadata.get("training_data"),
        "languages": metadata.get("languages"),
        "knowledge_cutoff": metadata.get("knowledge_cutoff"),
        "fine_tuning": metadata.get("fine_tuning"),
    }

    # Nettoyer les valeurs None
    enriched = {k: v for k, v in enriched.items() if v is not None}

    return enriched


def _deduce_architecture(model_id: str, context_window: int) -> str:
    """Déduit l'architecture probable depuis l'ID."""
    model_lower = model_id.lower()
    if "compound" in model_lower:
        return "Système"
    if any(kw in model_lower for kw in ["whisper", "orpheus"]):
        return "Transformer (Audio)"
    if any(kw in model_lower for kw in ["guard", "safeguard"]):
        return "Dense (Classifier)"
    if re.search(r'\d+x\d+[bB]', model_lower) or "mixtral" in model_lower:
        return "MoE"
    if "gpt-oss" in model_lower:
        return "MoE"
    return "Dense"


# ============================================================
# 1. VÉRIFICATION DE LA CLÉ API
# ============================================================

api_key = os.environ.get("GROQ_API_KEY_5")

if not api_key:
    print("❌ ERREUR : GROQ_API_KEY_5 non trouvée !")
    sys.exit(1)

print(f"🔑 Clé API : {api_key[:10]}...{api_key[-4:]}")

# ============================================================
# 2. APPEL DE L'API
# ============================================================

url = "https://api.groq.com/openai/v1/models"
headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}

print(f"\n📡 Appel à : {url}")

try:
    response = requests.get(url, headers=headers, timeout=30)

    if response.status_code != 200:
        print(f"\n❌ ERREUR HTTP {response.status_code}")
        print(f"   {response.text}")
        sys.exit(1)

    data = response.json()
    models = data.get("data", [])

    if not models:
        print("\n⚠️  Aucun modèle trouvé")
        sys.exit(1)

    print(f"✅ {len(models)} modèles récupérés")

    # ============================================================
    # 3. ENRICHIR CHAQUE MODÈLE
    # ============================================================

    enriched_models = [enrich_model(model) for model in models]

    # ============================================================
    # 4. GÉNÉRER LE FICHIER JSON
    # ============================================================

    output = {
        "metadata": {
            "source": "Groq API + Docs + Model Cards",
            "fetched_at": datetime.now().isoformat(),
            "total_models": len(models),
        },
        "summary": {
            "total": len(models),
            "by_category": {},
            "by_type": {},
            "by_architecture": {},
            "chat_models": sum(1 for m in enriched_models if m.get("capabilities", {}).get("json_mode")),
            "reasoning_models": sum(1 for m in enriched_models if m.get("capabilities", {}).get("reasoning")),
            "audio_models": sum(1 for m in enriched_models if m.get("capabilities", {}).get("audio")),
            "tool_calling_models": sum(1 for m in enriched_models if m.get("capabilities", {}).get("tool_calling")),
        },
        "models": enriched_models,
    }

    # Compter par catégorie
    for m in enriched_models:
        cat = m.get("category", "Inconnue")
        output["summary"]["by_category"][cat] = output["summary"]["by_category"].get(cat, 0) + 1

    # Compter par type
    for m in enriched_models:
        typ = m.get("type", "Inconnu")
        output["summary"]["by_type"][typ] = output["summary"]["by_type"].get(typ, 0) + 1

    # Compter par architecture
    for m in enriched_models:
        arch = m.get("architecture", "Inconnue")
        output["summary"]["by_architecture"][arch] = output["summary"]["by_architecture"].get(arch, 0) + 1

    output_path = "groq_models_enriched.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    # ============================================================
    # 5. AFFICHAGE RÉSUMÉ
    # ============================================================

    print(f"\n{'='*80}")
    print(f"📊 MODÈLES GROQ ENRICHIS")
    print(f"{'='*80}")
    print(f"  Total              : {len(models)}")
    print(f"  Chat               : {output['summary']['chat_models']}")
    print(f"  Raisonnement       : {output['summary']['reasoning_models']}")
    print(f"  Audio              : {output['summary']['audio_models']}")
    print(f"  Tool Calling       : {output['summary']['tool_calling_models']}")

    print(f"\n  Par catégorie :")
    for cat, count in sorted(output["summary"]["by_category"].items()):
        print(f"    • {cat:<20} : {count}")

    print(f"\n  Par architecture :")
    for arch, count in sorted(output["summary"]["by_architecture"].items()):
        print(f"    • {arch:<40} : {count}")

    # Afficher les modèles pour le benchmark
    print(f"\n{'='*80}")
    print(f"🎯 MODÈLES PERTINENTS POUR VOTRE BENCHMARK")
    print(f"{'='*80}")
    print(f"{'ID':<35} {'Type':<20} {'Architecture':<20} {'Params':<10}")
    print("-" * 90)

    benchmark_models = [
        "llama-3.3-70b-versatile",
        "qwen/qwen3-32b",
        "llama-3.1-8b-instant",
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
    ]
    for model_id in benchmark_models:
        for m in enriched_models:
            if m["id"] == model_id:
                print(
                    f"{m['id']:<35} "
                    f"{m.get('type', '?'):<20} "
                    f"{m.get('architecture', '?'):<20} "
                    f"{m.get('parameters', '?'):<10}"
                )
                break

    print("-" * 90)
    print(f"\n💾 Fichier sauvegardé : {output_path}")
    print(f"   Taille : {os.path.getsize(output_path):,} octets")

except Exception as e:
    print(f"\n❌ Erreur : {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)