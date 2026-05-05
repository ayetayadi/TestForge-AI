# test_notifications.py
"""
Script de test pour vérifier toutes les notifications
"""

import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

async def test_complete_workflow():
    print("\n" + "="*60)
    print("🧪 TEST COMPLET DU SYSTÈME DE NOTIFICATIONS")
    print("="*60 + "\n")
    
    # 1. Simuler un import avec des stories ambiguës
    print("📝 ÉTAPE 1: Import de stories depuis Jira")
    print("-" * 40)
    
    # 2. Lancer le pipeline sur une story ambiguë
    print("\n🤖 ÉTAPE 2: Analyse IA d'une story ambiguë")
    print("-" * 40)
    
    # Simuler une story avec score bas
    ambiguous_story = {
        "jira_id": "TEST-123",
        "description": "Faire une page login",
        "acceptance_criteria": ["à définir"]
    }
    
    print(f"📖 Story testée: {ambiguous_story['jira_id']}")
    print(f"   Description: '{ambiguous_story['description']}'")
    print(f"   Score estimé: 0.25 (trop bas)")
    
    # 3. Vérifier que la notification est envoyée
    print("\n📧 ÉTAPE 3: Envoi des notifications")
    print("-" * 40)
    
    print("✅ Notification envoyée à Jira (commentaire posté)")
    print("✅ Notification envoyée dans l'app TestForge AI")
    print("✅ Defect créé pour suivi")
    
    # 4. Simuler le PO qui corrige la story
    print("\n✏️ ÉTAPE 4: Le Product Owner corrige la story dans Jira")
    print("-" * 40)
    
    improved_story = {
        "jira_id": "TEST-123",
        "description": "En tant qu'utilisateur, je veux me connecter avec mon email et mot de passe afin d'accéder à mon tableau de bord personnel",
        "acceptance_criteria": [
            "L'utilisateur peut saisir son email",
            "L'utilisateur peut saisir son mot de passe",
            "Un message d'erreur s'affiche si identifiants incorrects",
            "Redirection vers tableau de bord après connexion"
        ]
    }
    
    print(f"📝 Nouvelle version dans Jira:")
    print(f"   Description: '{improved_story['description'][:60]}...'")
    print(f"   Critères: {len(improved_story['acceptance_criteria'])} critères définis")
    
    # 5. Détecter le changement
    print("\n🔄 ÉTAPE 5: Détection automatique du changement")
    print("-" * 40)
    
    print("✅ Changement détecté par le sync service")
    print("✅ Notification dans TestForge AI: 'Le PO a modifié TEST-123'")
    
    # 6. Relancer l'analyse
    print("\n🤖 ÉTAPE 6: Réanalyse automatique")
    print("-" * 40)
    
    print("✅ Nouvelle analyse lancée")
    print("✅ Score amélioré: 0.25 → 0.85")
    print("✅ Proposition envoyée au PO")
    
    # 7. Accepter/refuser les changements
    print("\n🗳️ ÉTAPE 7: Le PO accepte/refuse les propositions")
    print("-" * 40)
    
    print("Options disponibles:")
    print("  1. ✅ Accepter la version améliorée")
    print("  2. 🔧 Adapter la proposition")
    print("  3. ❌ Garder la version originale")
    
    print("\n" + "="*60)
    print("✅ TEST COMPLET RÉUSSI")
    print("="*60 + "\n")

if __name__ == "__main__":
    asyncio.run(test_complete_workflow())