"""
Unit tests for risk scoring logic — ISTQB §5.2.3 (risk-based testing).

Tests pure functions in risk_scorer.py without any DB or LLM calls.
"""

import pytest
from app.ai_workflows.risk_analysis.risk_scorer import (
    compute_risk_score,
    classify_level,
    get_test_depth,
    clamp_values,
    build_risk_record,
)


# ─── compute_risk_score ──────────────────────────────────────────────────────

@pytest.mark.parametrize("probability,impact,expected", [
    (1, 1, 1),
    (5, 5, 25),
    (4, 5, 20),
    (3, 3, 9),
    (2, 4, 8),
])
def test_compute_risk_score(probability, impact, expected):
    """Risk score = Probability × Impact (ISTQB risk matrix)."""
    assert compute_risk_score(probability, impact) == expected


# ─── classify_level ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("score,expected_level", [
    (25, "critical"),
    (20, "critical"),
    (19, "high"),
    (12, "high"),
    (11, "medium"),
    (6,  "medium"),
    (5,  "low"),
    (1,  "low"),
])
def test_classify_level(score, expected_level):
    """Classification must follow ISTQB thresholds: critical≥20, high≥12, medium≥6, low<6."""
    assert classify_level(score) == expected_level


# ─── get_test_depth ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("level,expected_depth", [
    ("critical", "comprehensive"),
    ("high",     "thorough"),
    ("medium",   "standard"),
    ("low",      "smoke"),
])
def test_get_test_depth(level, expected_depth):
    """Test depth must map to ISTQB effort allocation per risk level."""
    result = get_test_depth(level)
    assert result["depth"] == expected_depth


# ─── clamp_values ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("p_in,i_in,p_out,i_out", [
    (0,  0,  1, 1),
    (6,  6,  5, 5),
    (3,  3,  3, 3),
    (-1, 10, 1, 5),
])
def test_clamp_values(p_in, i_in, p_out, i_out):
    """P and I must be clamped to 1-5 scale."""
    p, i = clamp_values(p_in, i_in)
    assert p == p_out
    assert i == i_out


# ─── build_risk_record ───────────────────────────────────────────────────────

def test_build_risk_record_critical():
    """P=4, I=5 → score=20 → critical → comprehensive."""
    record = build_risk_record(
        probability=4, impact=5,
        description="Payment failure under load",
        mitigation="Load test with 1000 concurrent users",
        user_story_id="us-1",
    )
    assert record["risk_score"] == 20
    assert record["level"] == "critical"
    assert record["test_depth"] == "comprehensive"
    assert record["is_ai_generated"] is True
    assert record["user_story_id"] == "us-1"


def test_build_risk_record_low():
    """P=1, I=2 → score=2 → low → smoke."""
    record = build_risk_record(
        probability=1, impact=2,
        description="Minor UI glitch",
        mitigation=None,
    )
    assert record["risk_score"] == 2
    assert record["level"] == "low"
    assert record["test_depth"] == "smoke"
    assert record["mitigation"] == ""


def test_build_risk_record_clamps_out_of_range():
    """Values outside 1-5 must be clamped before scoring."""
    record = build_risk_record(
        probability=10, impact=0,
        description="Edge case",
        mitigation=None,
    )
    assert record["probability"] == 5
    assert record["impact"] == 1
    assert record["risk_score"] == 5
