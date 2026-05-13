"""
Pydantic models for Risk-Based Testing.
Définit la forme exacte de chaque donnée qui circule dans le pipeline.
"""

from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


# ============================================================
# 1. INPUT : Ce que l'utilisateur envoie
# ============================================================

class RiskAnalysisInput(BaseModel):
    """Données d'entrée : une User Story + ses critères d'acceptation."""
    user_story: str = Field(
        ..., 
        min_length=5, 
        description="Le texte de la User Story"
    )
    acceptance_criteria: List[str] = Field(
        default_factory=list,
        description="La liste des critères d'acceptation"
    )
    user_story_id: Optional[str] = None


# ============================================================
# 2. ML OUTPUT : Ce que le modèle ML prédit
# ============================================================

class MLPrediction(BaseModel):
    """Sortie du modèle ML : P, I, et un score de confiance."""
    probability: int = Field(
        ge=1, le=5, 
        description="Probabilité de défaut (1 à 5)"
    )
    impact: int = Field(
        ge=1, le=5, 
        description="Impact si défaut (1 à 5)"
    )
    confidence: float = Field(
        default=0.0, 
        ge=0.0, le=1.0,
        description="Score de confiance du ML (0 à 1). 0.85 = 85% de confiance"
    )
    source: str = Field(
        default="ml",
        description="Source de la prédiction : 'ml', 'llm_fallback', 'rules_fallback', 'default'"
    )


# ============================================================
# 3. SCORER OUTPUT : Résultat des calculs
# ============================================================

class ScorerResult(BaseModel):
    """Résultat du calculateur : score, priorité, effort, stratégie de test."""
    probability: int = Field(ge=1, le=5)
    impact: int = Field(ge=1, le=5)
    risk_score: int = Field(ge=1, le=25)
    priority: str = Field(pattern="^(critical|high|medium|low)$")
    effort: float = Field(ge=0.0, le=1.0)
    test_depth: str
    test_techniques: List[str]

    @field_validator("risk_score")
    @classmethod
    def score_must_equal_p_times_i(cls, v: int, info) -> int:
        """Vérifie que risk_score = probability × impact."""
        if "probability" in info.data and "impact" in info.data:
            expected = info.data["probability"] * info.data["impact"]
            if v != expected:
                raise ValueError(f"risk_score {v} ne correspond pas à P×I ({expected})")
        return v


# ============================================================
# 4. LLM OUTPUT : L'explication générée
# ============================================================

class LLMExplanation(BaseModel):
    """Sortie du LLM : explications, pas de P ni I."""
    description: str = Field(
        max_length=100,
        description="Risque spécifique identifié (max 15 mots)"
    )
    mitigation: str = Field(
        max_length=100,
        description="Action de test pour réduire le risque (max 12 mots)"
    )
    reasoning: str = Field(
        description="Justification : pourquoi ce P, pourquoi ce I, résultat du calcul"
    )


# ============================================================
# 5. OUTPUT FINAL : Tout ce qui est renvoyé au frontend
# ============================================================

class RiskAnalysisResult(BaseModel):
    """Résultat complet de l'analyse de risque."""
    user_story_id: Optional[str] = None

    # Scores
    probability: int = Field(ge=1, le=5)
    impact: int = Field(ge=1, le=5)
    risk_score: int = Field(ge=1, le=25)
    priority: str

    # Stratégie de test
    effort: float
    test_depth: str
    test_techniques: List[str]

    # Explication LLM
    description: str
    mitigation: str
    reasoning: str

    # Métadonnées
    is_ai_generated: bool = True
    is_accepted: Optional[bool] = None  # None = pas encore validé
    ml_confidence: Optional[float] = None
    source: str = "ml"  # "ml", "llm_fallback", "rules_fallback", "default", "human_modified"
    workflow_status: str = "success"
    error: Optional[str] = None


# ============================================================
# 6. FEEDBACK : Correction humaine pour réentraînement
# ============================================================

class HumanFeedback(BaseModel):
    """Correction humaine sauvegardée pour améliorer le ML."""
    user_story: str
    acceptance_criteria: List[str]
    
    # Ce que le ML avait prédit
    ml_probability: int
    ml_impact: int
    
    # Ce que l'humain a corrigé
    corrected_probability: int = Field(ge=1, le=5)
    corrected_impact: int = Field(ge=1, le=5)
    
    # Qui a modifié, quand, pourquoi
    modified_at: Optional[str] = None
    comment: Optional[str] = None