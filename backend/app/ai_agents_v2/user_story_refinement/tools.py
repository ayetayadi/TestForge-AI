# ============================================================
# ai_agents_v2/user_story/tools.py (FINAL)
# ============================================================
"""
Tools for ReAct Agent.

✅ TOOLS DEFINITION:
- extract_acceptance_criteria: Service tool (LLM can't do this)
- score_story: Evaluation tool (agent MUST call multiple times)
- validate_constraints: Guard tool (final validation)

✅ ARCHITECTURE:
- Tools are CALLED by agent during Think→Act loop
- Agent decides WHEN to call each tool
- Agent re-calls score_story after improvements
"""

import re

from langchain_core.tools import tool
from typing import List, Dict, Any
import asyncio
import logging

from app.ai_agents_v2.user_story_refinement.utils.testability import compute_testability_deterministic


logger = logging.getLogger(__name__)

# ============================================================
# TOOL 1: Extract Acceptance Criteria
# ============================================================
@tool
async def extract_acceptance_criteria(
    story: str, 
    existing_ac: List[str] = None
) -> Dict[str, Any]:
    """
    TOOL 1 - SERVICE: Extract or improve acceptance criteria.
    
    Agent calls this when:
    - "I need better AC from this story"
    - "Extract measurable criteria"
    - "Generate testable AC"
    
    Args:
        story: The user story text
        existing_ac: Current AC (if any)
        
    Returns:
        - status: "success" or "error"
        - acceptance_criteria: List of extracted AC
        - count: Number of AC extracted
    """
    from app.ai_agents_v2.user_story_refinement.services.ac_extraction_service import ac_extraction_service
    
    try:
        logger.info("[TOOL] extract_acceptance_criteria called")
        
        ac_field = "\n".join(existing_ac) if existing_ac else ""
        
        extraction_result = ac_extraction_service.extract(
            description=story,
            acceptance_criteria_field=ac_field,
            jira_id="unknown"
        )
        
        logger.info(f"✓ Extracted {len(extraction_result.acceptance_criteria)} AC")
        
        return {
            "status": "success",
            "acceptance_criteria": extraction_result.acceptance_criteria,
            "count": len(extraction_result.acceptance_criteria),
        }
    except Exception as e:
        logger.error(f"AC extraction failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "acceptance_criteria": [],
        }


# ============================================================
# TOOL 2: Score Story (PRIMARY - Called Multiple Times)
# ============================================================
@tool
async def score_story(
    story: str,
    acceptance_criteria: List[str] = None,
) -> Dict[str, Any]:
    """
    TOOL 2 - EVALUATION: Calculate comprehensive story score.
    
    ✅ DÉTERMINISTE - Basé sur des règles métier
    ✅ L'AGENT reste le seul à "penser"
    """
    from app.ai_agents_v2.user_story_refinement.utils.rule_engine import rule_engine
    from app.ai_agents_v2.user_story_refinement.utils.nlp_checker import nlp_checker
    from app.ai_agents_v2.user_story_refinement.utils.garbage_detector import garbage_detector
    from app.ai_agents_v2.user_story_refinement.services.ac_service import ac_service
    from app.ai_agents_v2.user_story_refinement.utils.text_processing import detect_language
    from app.ai_agents_v2.user_story_refinement.services.scoring_service import ScoreComponents
    
    try:

        if acceptance_criteria is None:
            logger.info("[TOOL] acceptance_criteria was null, converting to []")
            acceptance_criteria = []

        logger.info("[TOOL] score_story called")
        logger.info(f"  Story length: {len(story)} chars")
        logger.info(f"  AC count: {len(acceptance_criteria)}")

        
        # ============================================================
        # Détection de langue
        # ============================================================
        language = detect_language(story)
        
        # ============================================================
        # Testability Analysis (DÉTERMINISTE)
        # ============================================================
        testability = compute_testability_deterministic(story, acceptance_criteria)
        testability_score = testability["score"]
        testability_issues = testability["issues"]
        is_testable = testability["is_testable"]
        
        # ============================================================
        # Parallel Scoring (DÉTERMINISTE)
        # ============================================================
        rule_task = asyncio.to_thread(rule_engine.evaluate, story)
        nlp_task = asyncio.to_thread(nlp_checker.analyze, story)
        
        rule_result, nlp_result = await asyncio.gather(rule_task, nlp_task)
        
        rule_score = float(rule_result.get("rule_score", 0.0))
        nlp_score = float(nlp_result.get("nlp_score", 0.0))
        ac_score = ac_service.compute_score(acceptance_criteria)
        is_garbage = garbage_detector.is_garbage(story)
        
        # ============================================================
        # Final Score (Pondération)
        # ============================================================
        components = ScoreComponents(
            ac_score=ac_score,
            rule_score=rule_score,
            nlp_score=nlp_score,
            testability_score=testability_score,
            is_garbage=is_garbage
        )
        
        final_score = components.normalized
        
        logger.info(f"  ✓ Final Score: {final_score:.3f} (Testability: {testability_score:.3f})")
        
        # ============================================================
        # Suggestions basées sur les règles
        # ============================================================
        suggestions = (
            rule_result.get("rule_suggestions", [])[:2] +
            nlp_result.get("nlp_suggestions", [])[:2] +
            testability.get("suggestions", [])[:2]
        )
        
        return {
            "status": "success",
            "final_score": round(final_score, 3),
            "rule_score": round(rule_score, 3),
            "nlp_score": round(nlp_score, 3),
            "ac_score": round(ac_score, 3),
            "testability_score": round(testability_score, 3),
            "is_testable": is_testable,
            "is_garbage": is_garbage,
            "language": language,
            "testability_issues": testability_issues,
            "issues": rule_result.get("rule_issues", [])[:2] + nlp_result.get("nlp_issues", [])[:2],
            "suggestions": suggestions,
        }
    
    except Exception as e:
        logger.error(f"Scoring failed: {e}", exc_info=True)
        return {
            "status": "error",
            "final_score": 0.0,
            "testability_score": 0.0,
            "error": str(e),
            "testability_issues": ["Error during scoring"],
        }


# ============================================================
# TOOL 3: Validate Constraints (Guard Rail)
# ============================================================

@tool
async def validate_constraints(
    original_story: str,
    improved_story: str,
    acceptance_criteria: List[str] = None
) -> Dict[str, Any]:
    """
    TOOL 3 - GUARD: Validate business constraints.
    
    Agent calls this:
    - Before accepting final improved version
    - To ensure no violations occurred
    - To verify similarity >= 65%
    
    Checks:
    - Language consistency
    - Role preservation (actor not invented)
    - Similarity >= 65%
    - No metadata violations
    """
    from app.ai_agents_v2.user_story_refinement.utils.constraint_guard import constraint_guard
    from app.core.embedding import embed, cosine_similarity
    import asyncio
    
    try:
        logger.info("[TOOL] validate_constraints called")
        
        acceptance_criteria = acceptance_criteria or []
        
        # ============================================================
        # 1. Validation des contraintes métier (constraint_guard)
        # ============================================================
        result = await asyncio.to_thread(
            constraint_guard.validate,
            original=original_story,
            improved=improved_story,
            acceptance_criteria=acceptance_criteria
        )
        
        is_safe = result.get("is_safe", True)
        violations = result.get("violations", [])
        language_match = result.get("language_match", True)
        role_preserved = result.get("role_preserved", True)
        
        # ============================================================
        # 2. Calcul de similarité via VOTRE module embeddings
        # ============================================================
        similarity = 0.0
        
        try:
            # ✅ Utiliser votre fonction embed() avec cache intégré
            emb_original = await asyncio.to_thread(embed, original_story)
            emb_improved = await asyncio.to_thread(embed, improved_story)
            
            if emb_original is not None and emb_improved is not None:
                # ✅ Utiliser votre fonction cosine_similarity
                similarity = cosine_similarity(emb_original, emb_improved)
                logger.info(f"  Similarity calculated: {similarity:.3f}")
                
                # ✅ Vérifier le seuil de similarité (65%)
                if similarity < 0.65:
                    is_safe = False
                    violations.append(
                        f"Similarité trop faible: {similarity:.1%} (minimum 65%)"
                    )
                else:
                    logger.info(f"  ✓ Similarity OK: {similarity:.3f} >= 0.65")
            else:
                logger.warning("  Embeddings returned None")
                
        except Exception as e:
            logger.warning(f"  Similarity calculation failed: {e}")
            similarity = 0.0
        
        logger.info(f"  Safety: {is_safe}")
        if violations:
            logger.warning(f"  Violations: {violations}")
        
        return {
            "status": "success",
            "is_safe": is_safe,
            "violations": violations,
            "similarity": round(similarity, 3),
            "language_match": language_match,
            "role_preserved": role_preserved,
        }
        
    except Exception as e:
        logger.error(f"Constraint validation failed: {e}")
        return {
            "status": "error",
            "is_safe": False,
            "error": str(e),
            "violations": ["Validation error"],
            "similarity": 0.0,
        }
    
# ============================================================
# EXPORT TOOLS
# ============================================================
TOOLS = [
    extract_acceptance_criteria,    # For AC extraction
    score_story,                    # For evaluation (CALLED MULTIPLE TIMES)
    validate_constraints,           # For guardrails
]

logger.info(f"✓ Tools initialized: {len(TOOLS)} tools available")