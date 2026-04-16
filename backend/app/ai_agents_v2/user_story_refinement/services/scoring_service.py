from dataclasses import dataclass
from typing import Any, Dict, List
import re

# ============================================================
# CONFIGURATION - CORRIGÉE
# ============================================================

# Seuils de décision
THRESHOLD_HIGH_QUALITY = 0.85          # Ajusté (était 0.95)
THRESHOLD_GOOD_QUALITY = 0.75          # Ajusté (était 0.85)
THRESHOLD_ACCEPTABLE = 0.55            # Ajusté (était 0.60)
THRESHOLD_IMPROVEMENT = 0.03           # +3% = amélioration significative
THRESHOLD_DEGRADATION = -0.03          # -3% = dégradation
THRESHOLD_STAGNATION = 0.02            # Entre -2% et +2% = stagnation

# Pénalités
GARBAGE_PENALTY_MAX_SCORE = 0.3
GUARD_FAILURE_MAX_SCORE = 0.4

# ✅ NOUVELLES PONDÉRATIONS - Testabilité INTÉGRÉE
WEIGHT_AC_WITH_AC = 0.40              # 40% pour structure AC
WEIGHT_RULE_WITH_AC = 0.20            # 20% pour règles INVEST
WEIGHT_NLP_WITH_AC = 0.10             # 10% pour clarté NLP
WEIGHT_TESTABILITY_WITH_AC = 0.30     # 30% pour testabilité ⭐

# Pondérations sans AC
WEIGHT_RULE_WITHOUT_AC = 0.40
WEIGHT_NLP_WITHOUT_AC = 0.25
WEIGHT_TESTABILITY_WITHOUT_AC = 0.35  # 35% pour testabilité ⭐

# ============================================================
# SCORE COMPONENTS - CORRIGÉ
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

    def _base_score(self) -> float:
        ac = self._clamp(self.ac_score)
        rule = self._clamp(self.rule_score)
        nlp = self._clamp(self.nlp_score)
        testability = self._clamp(self.testability_score)

        if ac > 0:
            # ✅ Testabilité compte MAINTENANT
            return (
                ac * WEIGHT_AC_WITH_AC +
                rule * WEIGHT_RULE_WITH_AC +
                nlp * WEIGHT_NLP_WITH_AC +
                testability * WEIGHT_TESTABILITY_WITH_AC  # ← PLUS 0.0 !
            )
        else:
            return (
                rule * WEIGHT_RULE_WITHOUT_AC +
                nlp * WEIGHT_NLP_WITHOUT_AC +
                testability * WEIGHT_TESTABILITY_WITHOUT_AC  # ← PLUS 0.0 !
            )

    def _apply_penalties(self, score: float) -> float:
        if self.is_garbage:
            score = min(score, GARBAGE_PENALTY_MAX_SCORE)
        
        # ✅ Pénalité plus intelligente pour non-testable
        if not self.is_testable:
            # Plafond basé sur le score de testabilité
            if self.testability_score < 0.3:
                max_allowed = 0.50  # Très mauvais
            elif self.testability_score < 0.5:
                max_allowed = 0.65  # Médiocre
            elif self.testability_score < 0.7:
                max_allowed = 0.75  # Moyen
            else:
                max_allowed = 0.85  # Presque bon
            score = min(score, max_allowed)
        
        return score

    @property
    def final(self) -> float:
        score = self._base_score()
        score = self._apply_penalties(score)
        return self._clamp(score)

    @property
    def normalized(self) -> float:
        return round(self.final, 3)


# ============================================================
# SCORING SERVICE - AVEC DÉTECTION D'AMÉLIORATION
# ============================================================
class ScoringService:
    @staticmethod
    def compute_improvement(before: float, after: float) -> Dict[str, Any]:
        delta = round(after - before, 4)
        
        # ✅ Détection plus fine
        if delta > THRESHOLD_IMPROVEMENT:
            status = "improved"
            message = f"Amélioration significative de +{delta*100:.1f}%"
        elif delta < THRESHOLD_DEGRADATION:
            status = "degraded"
            message = f"Dégradation de {delta*100:.1f}%"
        elif abs(delta) <= THRESHOLD_STAGNATION:
            status = "stagnant"
            message = "Score stagnant, besoin d'améliorations plus importantes"
        else:
            status = "stable"
            message = f"Variation mineure de {delta*100:.1f}%"

        return {
            "before": round(before, 3),
            "after": round(after, 3),
            "delta": delta,
            "status": status,
            "percentage": round(delta * 100, 2),
            "message": message,
            "is_improved": delta > THRESHOLD_IMPROVEMENT,
            "is_degraded": delta < THRESHOLD_DEGRADATION
        }


scoring_service = ScoringService()


# ============================================================
# FONCTION DE TEST POUR VALIDER
# ============================================================
def test_improvement_detection():
    """Vérifie que l'amélioration est bien détectée"""
    
    # Cas 1: Avant amélioration (testabilité faible)
    before = ScoreComponents(
        ac_score=1.0,
        rule_score=1.0,
        nlp_score=1.0,
        testability_score=0.41,
        is_testable=False
    )
    
    # Cas 2: Après amélioration (testabilité meilleure)
    after = ScoreComponents(
        ac_score=1.0,
        rule_score=1.0,
        nlp_score=1.0,
        testability_score=0.53,
        is_testable=False
    )
    
    print("=" * 50)
    print("TEST D'AMÉLIORATION AVEC NOUVELLES PONDÉRATIONS")
    print("=" * 50)
    
    score_before = before.final
    score_after = after.final
    
    print(f"Avant: ac=1.0, rule=1.0, nlp=1.0, testability=0.41")
    print(f"Score final avant: {score_before}")
    print(f"\nAprès: ac=1.0, rule=1.0, nlp=1.0, testability=0.53")
    print(f"Score final après: {score_after}")
    
    improvement = scoring_service.compute_improvement(score_before, score_after)
    print(f"\n📊 Résultat: {improvement['status'].upper()}")
    print(f"   Delta: {improvement['delta']} ({improvement['percentage']}%)")
    print(f"   {improvement['message']}")
    
    return improvement


if __name__ == "__main__":
    result = test_improvement_detection()
    
    # Vérification
    print("\n" + "=" * 50)
    if result['delta'] > 0:
        print("✅ SUCCÈS: L'amélioration est détectée !")
        print(f"   Score a augmenté de {result['percentage']}%")
    else:
        print("❌ ÉCHEC: L'amélioration n'est pas détectée")