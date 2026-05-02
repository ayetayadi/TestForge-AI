"""
Calculator — Calculs purs pour le Risk-Based Testing.
Aucune IA, aucun LLM. Juste des mathématiques basées sur le document.

Règles du document :
  - Risk Score = Probability × Impact (1 à 25)
  - Critical ≥ 20 | High ≥ 12 | Medium ≥ 6 | Low ≥ 1
  - Effort : 60% critical, 25% high, 10% medium, 5% low
"""

import logging
from typing import Tuple

from .config import (
    PRIORITY_CRITICAL_MIN,
    PRIORITY_HIGH_MIN,
    PRIORITY_MEDIUM_MIN,
    EFFORT_ALLOCATION,
    TEST_DEPTH,
)
from .models import ScorerResult

logger = logging.getLogger(__name__)


# ============================================================
# 1. CALCUL DU SCORE
# ============================================================

def compute_risk_score(probability: int, impact: int) -> int:
    """
    Calcule le score de risque : P × I.
    
    Args:
        probability : entier entre 1 et 5
        impact : entier entre 1 et 5
        
    Returns:
        entier entre 1 et 25
        
    Example:
        compute_risk_score(4, 5) → 20
        compute_risk_score(2, 3) → 6
    """
    if not (1 <= probability <= 5):
        raise ValueError(f"Probability doit être entre 1 et 5, reçu : {probability}")
    if not (1 <= impact <= 5):
        raise ValueError(f"Impact doit être entre 1 et 5, reçu : {impact}")
    
    return probability * impact


# ============================================================
# 2. CLASSIFICATION DE LA PRIORITÉ
# ============================================================

def classify_priority(risk_score: int) -> str:
    """
    Détermine la priorité à partir du score de risque.
    
    Règles du document :
      - 20 à 25 → Critical
      - 12 à 19 → High
      - 6 à 11  → Medium
      - 1 à 5   → Low
    
    Args:
        risk_score : entier entre 1 et 25
        
    Returns:
        "critical", "high", "medium", ou "low"
        
    Example:
        classify_priority(20) → "critical"
        classify_priority(15) → "high"
        classify_priority(9)  → "medium"
        classify_priority(3)  → "low"
    """
    if risk_score >= PRIORITY_CRITICAL_MIN:   # ≥ 20
        return "critical"
    if risk_score >= PRIORITY_HIGH_MIN:       # ≥ 12
        return "high"
    if risk_score >= PRIORITY_MEDIUM_MIN:     # ≥ 6
        return "medium"
    return "low"


# ============================================================
# 3. ALLOCATION DE L'EFFORT
# ============================================================

def get_effort(priority: str) -> float:
    """
    Retourne le pourcentage d'effort recommandé pour une priorité.
    
    Règles du document :
      - Critical : 60% de l'effort de test
      - High     : 25%
      - Medium   : 10%
      - Low      : 5%
    
    Example:
        get_effort("critical") → 0.60
        get_effort("low")      → 0.05
    """
    return EFFORT_ALLOCATION.get(priority, 0.05)


# ============================================================
# 4. STRATÉGIE DE TEST
# ============================================================

def get_test_strategy(priority: str) -> dict:
    """
    Retourne la profondeur de test et les techniques recommandées.
    
    Règles du document :
      - Critical : comprehensive (unit, integration, e2e, performance, security)
      - High     : thorough (unit, integration, e2e)
      - Medium   : standard (unit, integration)
      - Low      : smoke (smoke tests uniquement)
    
    Example:
        get_test_strategy("critical") → {"depth": "comprehensive", "techniques": [...]}
    """
    return TEST_DEPTH.get(priority, TEST_DEPTH["low"])


# ============================================================
# 5. FONCTION COMPLÈTE : P, I → ScorerResult
# ============================================================

def compute_full_result(probability: int, impact: int) -> ScorerResult:
    """
    Calcule tout d'un coup à partir de P et I.
    
    Args:
        probability : entier 1-5
        impact : entier 1-5
        
    Returns:
        ScorerResult avec score, priorité, effort, stratégie
        
    Example:
        compute_full_result(4, 5) → ScorerResult(
            probability=4, impact=5, risk_score=20,
            priority="critical", effort=0.60,
            test_depth="comprehensive",
            test_techniques=["unit", "integration", "e2e", "performance", "security"]
        )
    """
    # Étape 1 : calculer le score
    score = compute_risk_score(probability, impact)
    
    # Étape 2 : déterminer la priorité
    priority = classify_priority(score)
    
    # Étape 3 : allouer l'effort
    effort = get_effort(priority)
    
    # Étape 4 : choisir la stratégie de test
    strategy = get_test_strategy(priority)
    
    # Étape 5 : construire le résultat
    result = ScorerResult(
        probability=probability,
        impact=impact,
        risk_score=score,
        priority=priority,
        effort=effort,
        test_depth=strategy["depth"],
        test_techniques=strategy["techniques"],
    )
    
    logger.debug(
        f"Score calculé : P={probability} × I={impact} = {score} → {priority} "
        f"(effort: {effort*100:.0f}%, tests: {', '.join(strategy['techniques'])})"
    )
    
    return result