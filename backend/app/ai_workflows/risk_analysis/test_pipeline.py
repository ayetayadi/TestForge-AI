"""
test_pipeline.py — Test rapide du pipeline Risk Analysis
"""
import asyncio
import sys
import os

# Ajouter le backend au path
sys.path.insert(0, os.path.dirname(__file__))

from app.ai_workflows.risk_analysis import get_pipeline, reset_pipeline

async def test_risk_analysis():
    """Teste le pipeline avec quelques User Stories."""
    
    # Initialiser le pipeline
    print("🔄 Initialisation du pipeline...")
    pipeline = await get_pipeline()
    print("✅ Pipeline prêt !\n")
    
    # Cas de test
    test_cases = [
        {
            "name": "Paiement critique",
            "us": "As a customer, I want to pay by credit card with 3D Secure authentication",
            "ac": [
                "Payment must use a PCI-compliant gateway",
                "3D Secure authentication is required",
                "Failed payments must not debit the account",
                "Transaction must be logged immutably"
            ]
        },
        {
            "name": "Changement cosmétique simple",
            "us": "As a user, I want to change the dashboard accent color",
            "ac": [
                "User can select a predefined color",
                "Preference is saved",
                "No business data is affected"
            ]
        },
        {
            "name": "Export CSV basique",
            "us": "As a support agent, I want to export tickets to CSV",
            "ac": [
                "CSV includes visible columns",
                "Export respects filters",
                "File downloads with timestamp"
            ]
        },
        {
            "name": "Approbation manager",
            "us": "As a manager, I want to approve employee leave requests",
            "ac": [
                "Only managers can approve",
                "Leave balance is checked",
                "Employee receives notification",
                "Decision is logged"
            ]
        },
        {
            "name": "Intégration API externe",
            "us": "As a developer, I want to integrate shipping carrier tracking API",
            "ac": [
                "API credentials are validated",
                "Tracking status is mapped to internal states",
                "Timeouts are handled gracefully",
                "Failed calls are logged with correlation ID"
            ]
        },
    ]
    
    # Tester chaque cas
    for test in test_cases:
        print(f"{'='*60}")
        print(f"📝 {test['name']}")
        print(f"{'='*60}")
        
        result = await pipeline.run(
            user_story=test['us'],
            acceptance_criteria=test['ac']
        )
        
        # Mapping I (3 classes → label lisible)
        i_labels = {1: "Low", 2: "Medium", 3: "High"}
        i_label = i_labels.get(result.impact, str(result.impact))
        
        print(f"   User Story : {test['us'][:80]}...")
        print(f"   Résultat   :")
        print(f"     P (Probabilité) : {result.probability}/5")
        print(f"     I (Impact)      : {i_label} ({result.impact}/3)")
        print(f"     Risk Score      : {result.risk_score}/25")
        print(f"     Priorité        : {result.priority.upper()}")
        print(f"     Effort test     : {result.effort*100:.0f}%")
        print(f"     Confiance ML    : {result.ml_confidence:.0%}")
        print(f"     Source          : {result.source}")
        print(f"     Description     : {result.description}")
        print(f"     Mitigation      : {result.mitigation}")
        print()
    
    print("✅ Tests terminés !")

if __name__ == "__main__":
    asyncio.run(test_risk_analysis())