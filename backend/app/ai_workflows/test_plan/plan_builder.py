"""
Pure functions for test plan construction (ISTQB §5.1.1).

No LLM, no I/O:
  - build_plan_record     → assemble the final dict for TestPlan persistence
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.ai_workflows.test_plan.config import (
    VALID_ENVIRONMENTS,
)

logger = logging.getLogger(__name__)


# ============================================================
# RISK SUMMARIZATION
# ============================================================

# plan_builder.py

def summarize_risks(risks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Aggregate risk_analysis results into a summary for the LLM prompt.
    Maintenant avec aggregation mitigations.
    """
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    scored: List[tuple] = []

    for r in risks:
        level = (r.get("level") or "low").lower()
        if level in counts:
            counts[level] += 1
        
        score = r.get("risk_score", 0.0)
        description = r.get("description", "")
        mitigation = r.get("mitigation", "")
        test_depth = r.get("test_depth", "standard")

        if description:
            scored.append((score, description, mitigation, test_depth))

    scored.sort(key=lambda x: x[0], reverse=True)
    
    # Extraire les top risques avec TOUTES les infos
    top_risks = []
    risk_lines = []
    for score, desc, mitigation, depth in scored[:5]:
        risk_info = {
            "description": desc,
            "score": score,
            "mitigation": mitigation,
            "test_depth": depth
        }
        top_risks.append(risk_info)
        
        # Format pour le LLM
        line = f"  • [{score:.1f}] {desc}"
        if depth:
            line += f"\n    Test depth: {depth}"
        if mitigation:
            line += f"\n    Mitigation: {mitigation}"
        risk_lines.append(line)
    
    risk_text = "\n".join(risk_lines) if risk_lines else "  (none)"
    
    total = len(risks)
    high_risk_ratio = (counts["critical"] + counts["high"]) / total if total > 0 else 0.0

    logger.debug(
        f"[PLAN BUILDER] risk summary: {counts} "
        f"high_ratio={high_risk_ratio:.0%} "
    )

    return {
        "counts": counts,
        "top_risks": top_risks,  # ← Maintenant avec mitigation
        "risk_text": risk_text,  # ← Format enrichi pour le LLM
        "high_risk_ratio": high_risk_ratio,
        "all_descriptions": [desc for _, desc, *_ in scored],
        "all_mitigations": [mit for _, _, mit, _ in scored if mit],
    }

# ============================================================
# FINAL RECORD ASSEMBLY
# ============================================================

def sanitize_list(values: List[str], allowed: set) -> List[str]:
    """Keep only allowed values, lowercase, deduped."""
    return list(dict.fromkeys(v.lower() for v in values if v.lower() in allowed))

def build_plan_record(
    llm_output: Dict[str, Any],
    risk_summary: Dict[str, Any],
    project_id: str,
    scope_type: str,
    scope_refs: List[str],
    environment_override: Optional[str] = None,
    user_stories: List[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Merge LLM draft with computed data into a dict ready for TestPlan persistence.
    ALL computed fields are now VISIBLE in the final record (no underscore prefixes).
    """
    now = datetime.now(timezone.utc)
    user_stories = user_stories or []

    # Sanitize environment
    env = (environment_override or llm_output.get("environment", "staging")).lower()
    if env not in VALID_ENVIRONMENTS:
        env = "staging"   

    scope = (scope_type or "manual").lower()
    if scope not in {"epic", "sprint", "release", "manual", "spec_document"}:
        scope = "manual"

    # ============================================================
    # SECTION VISIBLE 1 : ANALYSE DES RISQUES DÉTAILLÉE
    # ============================================================
    
    # Mapping US → Risque (pour le tableau de traçabilité)
    risk_mapping_table = []
    for story in user_stories:
        risk_info = {
            "issue_key": story.get("issue_key", "?"),
            "title": story.get("title", "")[:80],
            "risk_level": story.get("risk_level", "unknown"),
            "risk_score": story.get("risk_score", 0.0),
            "risk_description": story.get("risk_description", ""),
            "probability": story.get("probability", None),
            "impact": story.get("impact", None),
            "mitigation": story.get("risk_mitigation", ""),
            "test_depth": story.get("test_depth", "standard"),
            "reasoning": story.get("reasoning", ""),
        }
        risk_mapping_table.append(risk_info)
    
    # Trier par risque décroissant
    risk_mapping_table.sort(key=lambda x: x["risk_score"], reverse=True)
    
    # Recommandations agrégées
    aggregated_recommendations = {
        "test_depth_distribution": {
            "comprehensive": sum(1 for s in user_stories if s.get("test_depth") == "comprehensive"),
            "thorough": sum(1 for s in user_stories if s.get("test_depth") == "thorough"),
            "standard": sum(1 for s in user_stories if s.get("test_depth") == "standard"),
            "smoke": sum(1 for s in user_stories if s.get("test_depth") == "smoke"),
        }
    }

    # Distribution pour graphique
    risk_distribution = {
        "critical": risk_summary["counts"].get("critical", 0),
        "high": risk_summary["counts"].get("high", 0),
        "medium": risk_summary["counts"].get("medium", 0),
        "low": risk_summary["counts"].get("low", 0),
        "total": sum(risk_summary["counts"].values()),
        "high_risk_ratio": round(risk_summary.get("high_risk_ratio", 0.0), 2),
    }
    
    # Formules de calcul des risques
    risk_formulas = {
        "risk_score": "Risk Score = Probability × Impact",
        "probability_scale": "Probability: 0.0 (impossible) → 1.0 (certain)",
        "impact_scale": "Impact: 1 (très faible) → 5 (catastrophique)",
        "thresholds": {
            "critical": "Risk Score ≥ 4.0",
            "high": "2.5 ≤ Risk Score < 4.0",
            "medium": "1.0 ≤ Risk Score < 2.5",
            "low": "Risk Score < 1.0",
        },
    }

    # ============================================================
    # ASSEMBLAGE FINAL
    # ============================================================
    
    return {
        # Champs existants (base de données)
        "project_id": project_id,
        "title": llm_output.get("title", "Test Plan"),
        "description": llm_output.get("description", ""),
        "objective": llm_output.get("objective", ""),
        "scope_type": scope,
        "scope_refs": scope_refs or [],
        "in_scope": llm_output.get("in_scope", ""),
        "out_of_scope": llm_output.get("out_of_scope", ""),
        "environment": env,
        "entry_criteria": llm_output.get("entry_criteria", ""),
        "exit_criteria": llm_output.get("exit_criteria", ""),
        "approach": llm_output.get("approach", ""),
        "assumptions": llm_output.get("assumptions", ""),
        "constraints": llm_output.get("constraints", ""),
        "stakeholders": llm_output.get("stakeholders", ""),
        "communication": llm_output.get("communication", ""),
        "status": "ai_proposed",
        "ai_draft_generated_at": now,
        
        # ========================================================
        # NOUVEAUX CHAMPS VISIBLES (à stocker en BDD ou JSON field)
        # ========================================================
        
        # Section Risques (TOUT est visible)
        "risk_analysis": {
            "distribution": risk_distribution,
            "formulas": risk_formulas,
            "mapping_table": risk_mapping_table,  # ← Tableau US → Risque
            "top_risks": risk_summary.get("top_risks", []),
            "aggregated_recommendations": aggregated_recommendations,
        },
                
      
        
        # Raisonnement IA
        "ai_reasoning": llm_output.get("reasoning", ""),
    }