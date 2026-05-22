"""
benchmark_models.py — Génère un rapport HTML comparatif de tous les modèles Groq.
Ouvrez le fichier HTML dans votre navigateur et faites une capture d'écran.
"""
import json
from pathlib import Path
from datetime import datetime

# ═══════════════════════════════════════════════════════════════════════════════
# 1. CHARGER LE FICHIER JSON ENRICHI
# ═══════════════════════════════════════════════════════════════════════════════

JSON_PATH = Path(__file__).parent / "groq_models_enriched.json"

if not JSON_PATH.exists():
    print(f"ERREUR : Fichier introuvable : {JSON_PATH}")
    print("   Lance d'abord : python -m app.tests.fetch_groq_models")
    exit(1)

with open(JSON_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

models = data["models"]

# ═══════════════════════════════════════════════════════════════════════════════
# 2. FILTRER : ne garder que les modèles de texte
# ═══════════════════════════════════════════════════════════════════════════════

TEXT_MODELS = []
for m in models:
    caps = m.get("capabilities", {})
    if caps.get("audio"):
        continue
    if m.get("type") == "Safety Guard":
        continue
    if "compound" in m["id"]:
        continue
    TEXT_MODELS.append(m)

# ═══════════════════════════════════════════════════════════════════════════════
# 3. EXTRAIRE LES 5 MODÈLES SUGGÉRÉS
# ═══════════════════════════════════════════════════════════════════════════════

SUGGESTED_IDS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "qwen/qwen3-32b",
]

SUGGESTED_MODELS = [m for m in TEXT_MODELS if m["id"] in SUGGESTED_IDS]
OTHER_MODELS = [m for m in TEXT_MODELS if m["id"] not in SUGGESTED_IDS]

# ═══════════════════════════════════════════════════════════════════════════════
# 4. GÉNÉRER LE RAPPORT HTML
# ═══════════════════════════════════════════════════════════════════════════════

def model_row(m: dict, highlight: bool = False) -> str:
    """Génère une ligne HTML pour un modèle."""
    bg = "#e8f5e9" if highlight else "#ffffff"
    
    model_id = m["id"]
    provider = m.get("provider", "?")
    arch = m.get("architecture", "?")
    typ = m.get("type", "?")
    params = m.get("parameters", "?")
    category = m.get("category", "?")
    
    perf = m.get("performance", {})
    speed = perf.get("speed_tps", "-")
    speed_str = f"{speed} t/s" if speed else "-"
    ifeval = perf.get("ifeval_score", "-")
    mmlu = perf.get("mmlu_score", "-")
    ifeval_str = f"{ifeval:.1f}" if isinstance(ifeval, (int, float)) else "-"
    mmlu_str = f"{mmlu:.1f}" if isinstance(mmlu, (int, float)) else "-"
    
    pricing = m.get("pricing", {})
    price_in = pricing.get("price_input_per_1M", "-")
    price_out = pricing.get("price_output_per_1M", "-")
    price_in_str = f"${price_in}" if price_in else "-"
    price_out_str = f"${price_out}" if price_out else "-"
    
    caps = m.get("capabilities", {})
    tool = "Yes" if caps.get("tool_calling") else "No"
    reason = "Yes" if caps.get("reasoning") else "No"
    json_mode = "Yes" if caps.get("json_mode") else "No"
    
    ctx = m.get("context_window", "-")
    ctx_str = f"{ctx//1024}K" if ctx and ctx > 1000 else str(ctx)
    
    max_tokens = m.get("max_completion_tokens", "-")
    max_tokens_str = f"{max_tokens//1024}K" if max_tokens and max_tokens > 1000 else str(max_tokens)
    
    category_badge = ""
    if category == "Production":
        category_badge = '<span class="badge badge-production">Production</span>'
    elif category == "Preview":
        category_badge = '<span class="badge badge-preview">Preview</span>'
    
    return f"""
    <tr style="background: {bg};">
        <td style="font-weight: 600; color: #1e40af;">{model_id}</td>
        <td>{provider}</td>
        <td style="font-size: 12px;">{arch}</td>
        <td style="font-size: 12px;">{typ}</td>
        <td style="text-align: center;">{params}</td>
        <td style="text-align: center;">{ctx_str} / {max_tokens_str}</td>
        <td style="text-align: center;">{speed_str}</td>
        <td style="text-align: center;">{price_in_str}</td>
        <td style="text-align: center;">{price_out_str}</td>
        <td style="text-align: center;">{tool}</td>
        <td style="text-align: center;">{reason}</td>
        <td style="text-align: center;">{json_mode}</td>
        <td style="text-align: center;">{ifeval_str}</td>
        <td style="text-align: center;">{mmlu_str}</td>
        <td style="text-align: center;">{category_badge}</td>
    </tr>"""


html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Benchmark des Modeles Groq — User Story Refinement</title>
    <style>
        :root {{
            --primary: #6366f1;
            --primary-dark: #4f46e5;
            --primary-light: #eef2ff;
            --success: #10b981;
            --success-light: #d1fae5;
            --warning: #f59e0b;
            --warning-light: #fef3c7;
            --danger: #ef4444;
            --gray-50: #f9fafb;
            --gray-100: #f3f4f6;
            --gray-200: #e5e7eb;
            --gray-300: #d1d5db;
            --gray-500: #6b7280;
            --gray-700: #374151;
            --gray-900: #111827;
            --radius: 8px;
            --transition: 0.2s ease;
        }}
        
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        
        body {{
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            background: var(--gray-50);
            color: var(--primary-light);
            line-height: 1.5;
            min-height: 100vh;
        }}
        
        .page-content {{
            max-width: 1500px;
            margin: 0 auto;
            padding: 32px 40px 48px;
        }}
        
        @media (max-width: 768px) {{
            .page-content {{ padding: 20px 20px 32px; }}
        }}
        
        .page-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            background: white;
            border-bottom: 1px solid var(--gray-200);
            padding: 20px 40px;
            margin-bottom: 32px;
        }}
        
        @media (max-width: 768px) {{
            .page-header {{ padding: 16px 20px; flex-wrap: wrap; gap: 12px; }}
        }}
        
        .header-text h1 {{
            font-size: 1.5rem;
            font-weight: 700;
            color: var(--gray-900);
            margin: 0 0 4px;
        }}
        
        .header-text p {{
            font-size: 0.85rem;
            color: var(--gray-500);
            margin: 0;
        }}
        
        .legend {{
            background: var(--primary-light);
            border-left: 4px solid var(--primary);
            padding: 16px 20px;
            margin: 0 0 28px;
            border-radius: var(--radius);
            font-size: 0.85rem;
            color: var(--gray-700);
            line-height: 1.6;
        }}
        
        .legend strong {{
            color: var(--primary-dark);
        }}
        
        h2 {{
            font-size: 1.15rem;
            font-weight: 700;
            color: var(--gray-700);
            margin: 32px 0 16px;
            padding-bottom: 8px;
            border-bottom: 2px solid var(--gray-200);
        }}
        
        .table-wrapper {{
            overflow-x: auto;
            margin-bottom: 32px;
            border-radius: var(--radius);
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
            background: white;
        }}
        
        table {{
            border-collapse: collapse;
            width: 100%;
            min-width: 1200px;
        }}
        
        th {{
            background: var(--primary-dark);
            color: white;
            padding: 14px 10px;
            text-align: left;
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            white-space: nowrap;
            position: sticky;
            top: 0;
        }}
        
        td {{
            padding: 12px 10px;
            border-bottom: 1px solid var(--gray-100);
            font-size: 13px;
            color: var(--gray-700);
        }}
        
        tr:hover td {{
            background: #f8fafc !important;
        }}
        
        .badge {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.03em;
        }}
        
        .badge-production {{
            background: var(--success-light);
            color: #059669;
        }}
        
        .badge-preview {{
            background: var(--warning-light);
            color: #d97706;
        }}
        
        .footer {{
            margin-top: 40px;
            padding: 16px;
            background: white;
            text-align: center;
            font-size: 12px;
            color: var(--gray-500);
            border-radius: var(--radius);
            border: 1px solid var(--gray-200);
        }}
    </style>
</head>
<body>

<div class="page-header">
    <div class="header-text">
        <h1>Benchmark des Modeles Groq</h1>
        <p>Analyse comparative pour le raffinement de user stories — TestForge AI</p>
    </div>
</div>

<div class="page-content">

    <div class="legend">
        <strong>Date :</strong> {datetime.now().strftime('%d/%m/%Y a %H:%M')}<br>
        <strong>Source :</strong> {data['metadata']['source']}<br>
        <strong>Total modeles disponibles :</strong> {data['metadata']['total_models']}<br>
        <strong>Modeles de texte analyses :</strong> {len(TEXT_MODELS)}<br>
        <strong>Criteres de selection :</strong> Architecture, vitesse, prix, tool use, raisonnement, benchmarks (IFEval, MMLU)
    </div>

    <h2>Modeles Recommandes pour le Benchmark</h2>

    <div class="table-wrapper">
        <table>
            <thead>
                <tr>
                    <th>Modele</th>
                    <th>Provider</th>
                    <th>Architecture</th>
                    <th>Type</th>
                    <th>Params</th>
                    <th>Contexte (in / out)</th>
                    <th>Vitesse</th>
                    <th>Prix IN ($/1M)</th>
                    <th>Prix OUT ($/1M)</th>
                    <th>Tool Use</th>
                    <th>Raisonnement</th>
                    <th>JSON</th>
                    <th>IFEval</th>
                    <th>MMLU</th>
                    <th>Categorie</th>
                </tr>
            </thead>
            <tbody>
                {''.join(model_row(m, highlight=True) for m in SUGGESTED_MODELS)}
            </tbody>
        </table>
    </div>

    <h2>Autres Modeles Disponibles</h2>

    <div class="table-wrapper">
        <table>
            <thead>
                <tr>
                    <th>Modele</th>
                    <th>Provider</th>
                    <th>Architecture</th>
                    <th>Type</th>
                    <th>Params</th>
                    <th>Contexte (in / out)</th>
                    <th>Vitesse</th>
                    <th>Prix IN ($/1M)</th>
                    <th>Prix OUT ($/1M)</th>
                    <th>Tool Use</th>
                    <th>Raisonnement</th>
                    <th>JSON</th>
                    <th>IFEval</th>
                    <th>MMLU</th>
                    <th>Categorie</th>
                </tr>
            </thead>
            <tbody>
                {''.join(model_row(m) for m in OTHER_MODELS)}
            </tbody>
        </table>
    </div>

    <div class="footer">
        Rapport genere automatiquement — TestForge AI — {datetime.now().strftime('%Y')}
    </div>

</div>

</body>
</html>"""

# ═══════════════════════════════════════════════════════════════════════════════
# 5. SAUVEGARDER LE FICHIER HTML
# ═══════════════════════════════════════════════════════════════════════════════

OUTPUT_PATH = Path(__file__).parent / "benchmark_models.html"
with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    f.write(html)

print(f"\nRapport HTML genere : {OUTPUT_PATH}")
print(f"Ouvrez-le dans votre navigateur et faites une capture d'ecran.\n")