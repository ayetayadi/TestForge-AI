# test_suite_coverage.py - VERSION SIMPLIFIÉE

from typing import Any, Dict, List


def compute_suite_coverage(
    test_cases: List[Dict[str, Any]],
    accepted_risk_ids: List[str],
) -> Dict[str, Any]:
    """
    Calcule UNIQUEMENT le Risk Coverage pour une TestSuite.
    
    Avec 1 US = 1 Risk :
        Risk Coverage ≡ US Coverage (mathématiquement équivalent)
    
    On garde le Risk Coverage car c'est la métrique de MITIGATION.
    """
    if not accepted_risk_ids:
        return {
            "risk_coverage_pct": 1.0,
            "covered_risks": 0,
            "total_risks": 0,
            "uncovered_risk_ids": [],
            "mitigation_status": "fully_mitigated",
        }
    
    covered_risks = set()
    
    for tc in test_cases:
        tc_risk_ids = tc.get("risk_ids") or tc.get("covered_risk_ids", [])
        for rid in tc_risk_ids:
            if rid and rid in accepted_risk_ids:
                covered_risks.add(rid)
    
    covered_count = len(covered_risks)
    total = len(accepted_risk_ids)
    pct = covered_count / total
    
    uncovered = [rid for rid in accepted_risk_ids if rid not in covered_risks]
    
    # Statut de mitigation
    if pct >= 1.0:
        status = "fully_mitigated"
    elif pct >= 0.80:
        status = "partially_mitigated"
    else:
        status = "not_mitigated"
    
    return {
        "risk_coverage_pct": round(pct, 3),
        "covered_risks": covered_count,
        "total_risks": total,
        "uncovered_risk_ids": uncovered,
        "mitigation_status": status,
    }