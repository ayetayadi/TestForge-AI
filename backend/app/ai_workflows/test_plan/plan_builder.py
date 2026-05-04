"""
Pure functions for test plan construction (ISTQB §5.1.1).

No LLM, no I/O:
  - summarize_risks       → aggregate risk distribution and identify critical areas
  - recommend_test_types  → derive required test types from risk content
  - estimate_duration     → PERT 3-point estimation in working days
  - build_plan_record     → assemble the final dict for TestPlan persistence
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.ai_workflows.test_plan.config import (
    DAYS_PER_STORY,
    OVERHEAD_DAYS,
    REGRESSION_THRESHOLD,
    SECURITY_KEYWORDS,
    PERFORMANCE_KEYWORDS,
    VALID_TEST_TYPES,
    VALID_TEST_LEVELS,
    VALID_ENVIRONMENTS,
)

logger = logging.getLogger(__name__)


# ============================================================
# RISK SUMMARIZATION
# ============================================================

# plan_builder.py

def summarize_risks(risks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Aggregate risk_analysis results into a summary for the LLM prompt and duration estimate.
    Maintenant avec aggregation des test_techniques et mitigations.
    """
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    scored: List[tuple] = []
    
    # Pour agréger les techniques de test
    all_techniques = []  # Toutes les techniques recommandées
    technique_frequency = {}  # Fréquence de chaque technique
    
    for r in risks:
        level = (r.get("level") or "low").lower()
        if level in counts:
            counts[level] += 1
        
        score = r.get("risk_score", 0.0)
        description = r.get("description", "")
        mitigation = r.get("mitigation", "")
        test_techniques = r.get("test_techniques", [])
        test_depth = r.get("test_depth", "standard")
        
        # Agréger les techniques
        if isinstance(test_techniques, list):
            all_techniques.extend(test_techniques)
            for tech in test_techniques:
                technique_frequency[tech] = technique_frequency.get(tech, 0) + 1
        
        if description:
            scored.append((score, description, mitigation, test_techniques, test_depth))

    scored.sort(key=lambda x: x[0], reverse=True)
    
    # Extraire les top risques avec TOUTES les infos
    top_risks = []
    risk_lines = []
    for score, desc, mitigation, techniques, depth in scored[:5]:
        risk_info = {
            "description": desc,
            "score": score,
            "mitigation": mitigation,
            "test_techniques": techniques,
            "test_depth": depth
        }
        top_risks.append(risk_info)
        
        # Format pour le LLM
        line = f"  • [{score:.1f}] {desc}"
        if depth:
            line += f"\n    Test depth: {depth}"
        if mitigation:
            line += f"\n    Mitigation: {mitigation}"
        if techniques:
            line += f"\n    Recommended techniques: {', '.join(techniques)}"
        risk_lines.append(line)
    
    risk_text = "\n".join(risk_lines) if risk_lines else "  (none)"
    
    # Agréger les techniques les plus fréquentes
    most_common_techniques = sorted(
        technique_frequency.items(), 
        key=lambda x: x[1], 
        reverse=True
    )[:5]  # Top 5
    
    aggregated_techniques = [tech for tech, freq in most_common_techniques]
    
    total = len(risks)
    high_risk_ratio = (counts["critical"] + counts["high"]) / total if total > 0 else 0.0

    logger.debug(
        f"[PLAN BUILDER] risk summary: {counts} "
        f"high_ratio={high_risk_ratio:.0%} "
        f"top_techniques={aggregated_techniques}"
    )

    return {
        "counts": counts,
        "top_risks": top_risks,  # ← Maintenant avec mitigation + techniques
        "risk_text": risk_text,  # ← Format enrichi pour le LLM
        "high_risk_ratio": high_risk_ratio,
        "all_descriptions": [desc for _, desc, _, _, _ in scored],
        "all_mitigations": [mit for _, _, mit, _, _ in scored if mit],
        "all_techniques": [tech for _, _, _, techs, _ in scored for tech in techs],
        "aggregated_techniques": aggregated_techniques,  # ← NOUVEAU
        "technique_frequency": technique_frequency,  # ← NOUVEAU
    }

# ============================================================
# TEST TYPE RECOMMENDATION
# ============================================================

# plan_builder.py

def recommend_test_types(
    risk_summary: Dict[str, Any], 
    stories_text: str = ""
) -> Dict[str, Any]:
    """
    Derive recommended test_types and test_levels from the risk distribution,
    story content, AND aggregated test_techniques from risks.
    """
    types: list = ["functional"]  # Base obligatoire
    levels: list = ["system", "acceptance", "e2e"]
    reasons: list = [
        "functional tests are always required",
        "e2e execution via Playwright MCP is the target"
    ]
    
    # ✅ PRIORITÉ 1 : Utiliser les test_techniques agrégées des risques
    aggregated_techniques = risk_summary.get("aggregated_techniques", [])
    technique_frequency = risk_summary.get("technique_frequency", {})
    
    if aggregated_techniques:
        # Mapper les techniques vers les types de test
        TECHNIQUE_TO_TYPE = {
            "unit": "functional",  # Unit tests → functional testing
            "integration": "api",  # Integration tests → API testing
            "e2e": "e2e",  # E2E → end-to-end
            "performance": "performance",  # Performance → performance testing
            "security": "security",  # Security → security testing
            "smoke": "smoke",  # Smoke tests
            "regression": "regression",  # Regression testing
            "exploratory": "functional",  # Exploratory → functional
            "uat": "functional",  # UAT → functional acceptance
        }
        
        for technique in aggregated_techniques:
            test_type = TECHNIQUE_TO_TYPE.get(technique)
            if test_type and test_type not in types:
                types.append(test_type)
                freq = technique_frequency.get(technique, 0)
                reasons.append(
                    f"risk analysis recommends '{technique}' testing "
                    f"(in {freq} risk{'s' if freq > 1 else ''})"
                )
        
        # Déduire les niveaux de test des techniques
        if "integration" in aggregated_techniques:
            if "integration" not in levels:
                levels.append("integration")
        if "unit" in aggregated_techniques:
            if "component" not in levels:
                levels.append("component")
    
    # ✅ PRIORITÉ 2 : Analyse du texte des stories (fallback)
    all_text = (stories_text + " " + " ".join(risk_summary.get("all_descriptions", []))).lower()
    
    if risk_summary["high_risk_ratio"] >= REGRESSION_THRESHOLD:
        if "regression" not in types:
            types.append("regression")
            reasons.append(
                f"{risk_summary['high_risk_ratio']:.0%} high/critical stories → regression required"
            )
    
    counts = risk_summary["counts"]
    if counts.get("critical", 0) > 0:
        if "smoke" not in types:
            types.append("smoke")
        if "integration" not in levels:
            levels.append("integration")
        reasons.append("critical risks detected → smoke tests needed before full test run")
    
    # ✅ PRIORITÉ 3 : Détection de mots-clés (fallback si pas déjà ajouté)
    if any(kw in all_text for kw in SECURITY_KEYWORDS) and "security" not in types:
        types.append("security")
        reasons.append("security-related keywords found in stories")
    
    if any(kw in all_text for kw in PERFORMANCE_KEYWORDS) and "performance" not in types:
        types.append("performance")
        reasons.append("performance-related keywords found in stories")
    
    if any(term in all_text for term in ["api", "endpoint", "rest"]) and "api" not in types:
        types.append("api")
        if "component" not in levels:
            levels.append("component")
        reasons.append("API usage detected in stories")
    
    # Déduplication préservant l'ordre
    test_types = list(dict.fromkeys(types))
    test_levels = list(dict.fromkeys(levels))

    return {
        "test_types": test_types,
        "test_levels": test_levels,
        "reasoning": reasons,
    }

# ============================================================
# PERT 3-POINT ESTIMATION
# ============================================================

def estimate_duration(
    risk_summary: Dict[str, Any],
    story_count: int,
) -> Dict[str, Any]:
    """
    PERT estimate: E = (O + 4×M + P) / 6

    Each story contributes a number of days based on its risk level.
    Returns optimistic, realistic (PERT), pessimistic in working days.
    """
    if story_count == 0:
        return {"optimistic": 1, "realistic": 2, "pessimistic": 3, "formula": "no stories"}

    counts = risk_summary["counts"]
    total = sum(counts.values()) or story_count

    # Weight each level proportionally
    o_days = p_days = m_days = 0.0
    for level, count in counts.items():
        if level not in DAYS_PER_STORY:
            continue
        weight = count / total
        o_days += weight * DAYS_PER_STORY[level]["optimistic"] * story_count
        m_days += weight * DAYS_PER_STORY[level]["realistic"] * story_count
        p_days += weight * DAYS_PER_STORY[level]["pessimistic"] * story_count

    o_total = max(1, round(o_days + OVERHEAD_DAYS))
    m_total = max(2, round(m_days + OVERHEAD_DAYS))
    p_total = max(3, round(p_days + OVERHEAD_DAYS * 1.5))

    pert = round((o_total + 4 * m_total + p_total) / 6)

    logger.debug(f"[PLAN BUILDER] PERT: O={o_total} M={m_total} P={p_total} PERT={pert}")

    return {
        "optimistic": o_total,
        "realistic": pert,
        "pessimistic": p_total,
        "formula": f"PERT = ({o_total} + 4×{m_total} + {p_total}) / 6 = {pert} days",
    }


# ============================================================
# FINAL RECORD ASSEMBLY
# ============================================================

def sanitize_list(values: List[str], allowed: set) -> List[str]:
    """Keep only allowed values, lowercase, deduped."""
    return list(dict.fromkeys(v.lower() for v in values if v.lower() in allowed))


def _safe_parse_effort(value: str) -> float:
    """Parse effort allocation string like '60%' → 60.0 safely."""
    try:
        return float(str(value).rstrip('%').strip())
    except (ValueError, AttributeError):
        return 0.0

def build_plan_record(
    llm_output: Dict[str, Any],
    risk_summary: Dict[str, Any],
    duration: Dict[str, Any],
    project_id: str,
    scope_type: str,
    scope_refs: List[str],
    environment_override: Optional[str] = None,
    user_stories: List[Dict[str, Any]] = None,  # ← NOUVEAU paramètre
    recommendations: Dict[str, Any] = None,      # ← NOUVEAU paramètre
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
    
    # Sanitize test_types et test_levels UNE SEULE FOIS
    if recommendations and recommendations.get("test_types"):
        test_types = sanitize_list(recommendations["test_types"], VALID_TEST_TYPES)
        logger.info(f"[PLAN BUILDER] Using computed test_types: {test_types}")
    else:
        test_types = sanitize_list(llm_output.get("test_types", []), VALID_TEST_TYPES)
        logger.warning("[PLAN BUILDER] Falling back to LLM test_types")
    
    if recommendations and recommendations.get("test_levels"):
        test_levels = sanitize_list(recommendations["test_levels"], VALID_TEST_LEVELS)
    else:
        test_levels = sanitize_list(llm_output.get("test_levels", []), VALID_TEST_LEVELS)
    
    if not test_types:
        test_types = ["functional"]
    if not test_levels:
        test_levels = ["system"]

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
            "test_techniques": story.get("test_techniques", []),
            "test_depth": story.get("test_depth", "standard"),
            "effort_allocation": story.get("effort_allocation", "N/A"),
            "reasoning": story.get("reasoning", ""),
        }
        risk_mapping_table.append(risk_info)
    
    # Trier par risque décroissant
    risk_mapping_table.sort(key=lambda x: x["risk_score"], reverse=True)

    # ============================================================
    # SECTION : AGRÉGATION DES TECHNIQUES PAR RISQUE
    # ============================================================
    aggregated_techniques = risk_summary.get("aggregated_techniques", [])
    technique_frequency = risk_summary.get("technique_frequency", {})
    
    # Recommandations agrégées
    aggregated_recommendations = {
        "most_recommended_techniques": aggregated_techniques,
        "technique_distribution": technique_frequency,
        "test_depth_distribution": {
            "comprehensive": sum(1 for s in user_stories if s.get("test_depth") == "comprehensive"),
            "thorough": sum(1 for s in user_stories if s.get("test_depth") == "thorough"),
            "standard": sum(1 for s in user_stories if s.get("test_depth") == "standard"),
            "smoke": sum(1 for s in user_stories if s.get("test_depth") == "smoke"),
        },
        "effort_breakdown": {
            "critical_effort": f"{sum(_safe_parse_effort(s.get('effort_allocation', '0')) for s in user_stories if s.get('risk_level') == 'critical')}%",
            "high_effort": f"{sum(_safe_parse_effort(s.get('effort_allocation', '0')) for s in user_stories if s.get('risk_level') == 'high')}%",
            "medium_effort": f"{sum(_safe_parse_effort(s.get('effort_allocation', '0')) for s in user_stories if s.get('risk_level') == 'medium')}%",
            "low_effort": f"{sum(_safe_parse_effort(s.get('effort_allocation', '0')) for s in user_stories if s.get('risk_level') == 'low')}%",
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
    # SECTION VISIBLE 2 : ESTIMATION PERT DÉTAILLÉE
    # ============================================================
    
    # Détail du calcul PERT par niveau de risque
    pert_details = {
        "formula": "E = (O + 4 × M + P) / 6",
        "inputs": {
            "optimistic": duration["optimistic"],
            "most_likely": duration["realistic"],
            "pessimistic": duration["pessimistic"],
        },
        "calculation": duration.get("formula", ""),
        "standard_deviation": f"SD = (P - O) / 6 = ({duration['pessimistic']} - {duration['optimistic']}) / 6 = {round((duration['pessimistic'] - duration['optimistic']) / 6, 1)}",
        "confidence_interval": f"{duration['realistic']} ± {round((duration['pessimistic'] - duration['optimistic']) / 6, 1)} working days",
        "breakdown_by_risk": [],
    }
    
    # Breakdown par niveau de risque
    if user_stories:
        for level in ["critical", "high", "medium", "low"]:
            count = risk_summary["counts"].get(level, 0)
            if count > 0 and level in DAYS_PER_STORY:
                days = DAYS_PER_STORY[level]
                pert_details["breakdown_by_risk"].append({
                    "level": level,
                    "story_count": count,
                    "days_per_story_optimistic": days["optimistic"],
                    "days_per_story_realistic": days["realistic"],
                    "days_per_story_pessimistic": days["pessimistic"],
                    "subtotal_optimistic": count * days["optimistic"],
                    "subtotal_realistic": count * days["realistic"],
                    "subtotal_pessimistic": count * days["pessimistic"],
                })

    # ============================================================
    # SECTION VISIBLE 3 : RECOMMENDATIONS DÉTAILLÉES
    # ============================================================
    
    recommendations_detail = {}
    if recommendations:
        recommendations_detail = {
            "test_types": recommendations.get("test_types", []),
            "test_levels": recommendations.get("test_levels", []),
            "reasoning": recommendations.get("reasoning", []),
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
        "test_types": test_types,
        "test_levels": test_levels,
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
        
        # Section Estimation (TOUT est visible)
        "estimation": pert_details,
        
        # Section Recommandations
        "recommendations_detail": recommendations_detail,
        
        # Raisonnement IA
        "ai_reasoning": llm_output.get("reasoning", ""),
    }