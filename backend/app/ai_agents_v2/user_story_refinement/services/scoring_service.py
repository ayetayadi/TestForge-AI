from dataclasses import dataclass
from typing import Any, Dict, Tuple

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

# Pondérations avec AC (maintenant inclut testability)
WEIGHT_AC_WITH_AC = 0.35             
WEIGHT_RULE_WITH_AC = 0.15          
WEIGHT_NLP_WITH_AC = 0.10           
WEIGHT_TESTABILITY_WITH_AC = 0.40  

# Pondérations sans AC
WEIGHT_RULE_WITHOUT_AC = 0.40
WEIGHT_NLP_WITHOUT_AC = 0.20
WEIGHT_TESTABILITY_WITHOUT_AC = 0.40

# ============================================================
# SCORE COMPONENTS
# ============================================================
@dataclass
class ScoreComponents:
    ac_score: float
    rule_score: float
    nlp_score: float
    is_garbage: bool = False
    testability_score: float = 0.0 
    is_testable: bool = False

    def _clamp(self, value: float) -> float:
        return max(0.0, min(1.0, value))

    # =========================
    # BASE SCORE (AVANT PENALTIES)
    # =========================
    def _base_score(self) -> float:
        ac = self._clamp(self.ac_score)
        rule = self._clamp(self.rule_score)
        nlp = self._clamp(self.nlp_score)
        testability = self._clamp(self.testability_score)  # ✅ AJOUTÉ

        if ac > 0:
            return (
                ac * WEIGHT_AC_WITH_AC +
                rule * WEIGHT_RULE_WITH_AC +
                nlp * WEIGHT_NLP_WITH_AC +
                testability * WEIGHT_TESTABILITY_WITH_AC  # ✅ AJOUTÉ
            )
        else:
            return (
                rule * WEIGHT_RULE_WITHOUT_AC +
                nlp * WEIGHT_NLP_WITHOUT_AC +
                testability * WEIGHT_TESTABILITY_WITHOUT_AC  # ✅ AJOUTÉ
            )

    # =========================
    # PENALTIES
    # =========================
    def _apply_penalties(self, score: float) -> float:
        if self.is_garbage:
            score = min(score, GARBAGE_PENALTY_MAX_SCORE)
        # ✅ Si non testable, pénalité supplémentaire
        if not self.is_testable:
            max_allowed = max(0.65, min(0.90, score * 0.95))
            score = min(score, max_allowed)
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



# Singleton
scoring_service = ScoringService()