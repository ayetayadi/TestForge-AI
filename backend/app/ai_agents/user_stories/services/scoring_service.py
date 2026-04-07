from typing import Dict, Any, Tuple
from dataclasses import dataclass


# ============================================================
# CONFIGURATION
# ============================================================
# Seuils de décision
THRESHOLD_HIGH_QUALITY = 0.95
THRESHOLD_GOOD_QUALITY = 0.85
THRESHOLD_ACCEPTABLE = 0.60
THRESHOLD_IMPROVEMENT = 0.02
THRESHOLD_DEGRADATION = -0.02
THRESHOLD_STAGNATION = 0.01

# Pénalités
GARBAGE_PENALTY_MAX_SCORE = 0.3
GUARD_FAILURE_MAX_SCORE = 0.4

# Pondérations avec AC
WEIGHT_LLM_WITH_AC = 0.20
WEIGHT_AC_WITH_AC = 0.40
WEIGHT_RULE_WITH_AC = 0.25
WEIGHT_NLP_WITH_AC = 0.15

# Pondérations sans AC
WEIGHT_LLM_WITHOUT_AC = 0.30
WEIGHT_RULE_WITHOUT_AC = 0.40
WEIGHT_NLP_WITHOUT_AC = 0.30


# ============================================================
# SCORE COMPONENTS
# ============================================================
@dataclass
class ScoreComponents:
    llm_score: float
    ac_score: float
    rule_score: float
    nlp_score: float
    is_garbage: bool = False

    def _clamp(self, value: float) -> float:
        return max(0.0, min(1.0, value))

    # =========================
    # BASE SCORE (AVANT PENALTIES)
    # =========================
    def _base_score(self) -> float:
        llm = self._clamp(self.llm_score)
        ac = self._clamp(self.ac_score)
        rule = self._clamp(self.rule_score)
        nlp = self._clamp(self.nlp_score)

        if ac > 0:
            return (
                llm * WEIGHT_LLM_WITH_AC +
                ac * WEIGHT_AC_WITH_AC +
                rule * WEIGHT_RULE_WITH_AC +
                nlp * WEIGHT_NLP_WITH_AC
            )
        else:
            return (
                llm * WEIGHT_LLM_WITHOUT_AC +
                rule * WEIGHT_RULE_WITHOUT_AC +
                nlp * WEIGHT_NLP_WITHOUT_AC
            )

    # =========================
    # PENALTIES
    # =========================
    def _apply_penalties(self, score: float) -> float:
        if self.is_garbage:
            score = min(score, GARBAGE_PENALTY_MAX_SCORE)
        return score

    # =========================
    # FINAL SCORE
    # =========================
    @property
    def final(self) -> float:
        score = self._base_score()
        score = self._apply_penalties(score)
        return self._clamp(score)

    @property
    def normalized(self) -> float:
        return round(self.final, 3)
# ============================================================
# SCORING SERVICE
# ============================================================
class ScoringService:
    """Service de calcul et gestion des scores."""

    # ============================================================
    # IMPROVEMENT CALCULATION
    # ============================================================
    @staticmethod
    def compute_improvement(before: float, after: float) -> Dict[str, Any]:
        """
        Calcule l'amélioration entre deux scores.
        
        Args:
            before: Score précédent
            after: Nouveau score
            
        Returns:
            Dict avec delta, status, percentage
        """
        delta = round(after - before, 4)

        if delta > THRESHOLD_IMPROVEMENT:
            status = "improved"
        elif delta < THRESHOLD_DEGRADATION:
            status = "degraded"
        else:
            status = "stable"

        return {
            "before": round(before, 3),
            "after": round(after, 3),
            "delta": delta,
            "status": status,
            "percentage": round(delta * 100, 2)
        }

    # ============================================================
    # STOP LOGIC
    # ============================================================
    @staticmethod
    def should_stop(
        score: float,
        iteration: int,
        delta: float = 0.0,
        max_iterations: int = 2
    ) -> Tuple[bool, str]:
    
        if score >= THRESHOLD_HIGH_QUALITY:
            return True, "high_quality"
    
        # FIX stagnation
        if abs(delta) < THRESHOLD_STAGNATION and iteration > 1:
            return True, "no_improvement"
    
        # FIX degradation cohérente
        if delta < THRESHOLD_DEGRADATION:
            return True, "degraded"
    
        if iteration >= max_iterations:
            return True, "max_iterations"
    
        return False, "continue"
    
    # ============================================================
    # QUALITY ASSESSMENT
    # ============================================================
    @staticmethod
    def assess_quality(score: float) -> str:
        """
        Évalue la qualité basée sur le score.
        
        Returns:
            "high", "good", "acceptable", "poor"
        """
        if score >= THRESHOLD_HIGH_QUALITY:
            return "high"
        elif score >= THRESHOLD_GOOD_QUALITY:
            return "good"
        elif score >= THRESHOLD_ACCEPTABLE:
            return "acceptable"
        else:
            return "poor"

    # ============================================================
    # PENALTIES
    # ============================================================
    @staticmethod
    def apply_garbage_penalty(score: float, is_garbage: bool) -> float:
        """
        Applique une pénalité si la story est du garbage.
        
        Args:
            score: Score actuel
            is_garbage: True si détecté comme garbage
            
        Returns:
            Score pénalisé (max 0.3 si garbage)
        """
        if is_garbage:
            return min(score, GARBAGE_PENALTY_MAX_SCORE)
        return score

    @staticmethod
    def apply_guard_penalty(score: float, guard_failed: bool) -> float:
        """
        Applique une pénalité si le guard a échoué.
        
        Args:
            score: Score actuel
            guard_failed: True si le guard a détecté des problèmes critiques
            
        Returns:
            Score pénalisé (max 0.4 si guard failed)
        """
        if guard_failed:
            return min(score, GUARD_FAILURE_MAX_SCORE)
        return score

    @staticmethod
    def apply_all_penalties(
        score: float,
        is_garbage: bool = False,
        guard_failed: bool = False
    ) -> float:
        if is_garbage:
            score = min(score, GARBAGE_PENALTY_MAX_SCORE)

        if guard_failed:
            score = min(score, GUARD_FAILURE_MAX_SCORE)

        return score

    # ============================================================
    # UTILITY METHODS
    # ============================================================
    @staticmethod
    def normalize_score(score: float) -> float:
        """Normalise un score entre 0 et 1."""
        return max(0.0, min(1.0, round(score, 3)))

    @staticmethod
    def compute_delta(before: float, after: float) -> float:
        """Calcule le delta simple entre deux scores."""
        return round(after - before, 4)

    @staticmethod
    def is_significant_improvement(delta: float) -> bool:
        """Vérifie si l'amélioration est significative."""
        return delta > THRESHOLD_IMPROVEMENT

    @staticmethod
    def is_significant_degradation(delta: float) -> bool:
        """Vérifie si la dégradation est significative."""
        return delta < THRESHOLD_DEGRADATION


# Singleton
scoring_service = ScoringService()