# test_agent.py
import asyncio
import time
from app.ai_agents_v2.user_story_refinement.agent import get_pipeline

async def test():
    print("=" * 80)
    print("🧪 TEST AGENT USER STORY REFINEMENT")
    print("=" * 80)
    
    start_time = time.time()
    
    agent = get_pipeline()
    
    result = await agent.run(
        story="As a user, I want to login to the application",
        acceptance_criteria=["User can enter email", "User can enter password", "User can click login"],
        language="en",
        jira_id="TEST-001"
    )
    
    duration = time.time() - start_time
    
    print("\n" + "=" * 80)
    print("📊 RÉSULTATS DÉTAILLÉS")
    print("=" * 80)
    print(f"⏱️  Durée totale: {duration:.2f} secondes")
    print(f"📈 Score initial: {result.get('initial_score', 0):.3f}")
    print(f"📈 Score final: {result.get('final_score', 0):.3f}")
    print(f"📊 Testabilité: {result.get('testability_score', 0):.3f}")
    print(f"🎯 Is testable: {result.get('is_testable', False)}")
    print(f"🔄 Itérations: {result.get('iterations', 0)}")
    print(f"✅ Status: {result.get('agent_status', 'unknown')}")
    print(f"📝 Similarité: {result.get('similarity', 0):.3f}")
    print(f"🌐 Langue cohérente: {result.get('language_consistent', False)}")
    print(f"👤 Rôle préservé: {result.get('role_preserved', False)}")
    print(f"🔧 Amélioration: {'✅ Oui' if result.get('is_improved', False) else '❌ Non'}")
    
    print("\n" + "=" * 80)
    print("📝 STORY AMÉLIORÉE")
    print("=" * 80)
    print(f"{result.get('improved_story', 'N/A')}")
    
    print("\n" + "=" * 80)
    print("📋 CRITÈRES D'ACCEPTATION")
    print("=" * 80)
    for i, ac in enumerate(result.get('acceptance_criteria', []), 1):
        print(f"  {i}. {ac}")
    
    if result.get('testability_issues'):
        print("\n" + "=" * 80)
        print("⚠️ PROBLÈMES DE TESTABILITÉ")
        print("=" * 80)
        for issue in result.get('testability_issues', []):
            print(f"  • {issue}")
    
    if result.get('violations'):
        print("\n" + "=" * 80)
        print("🚨 VIOLATIONS")
        print("=" * 80)
        for violation in result.get('violations', []):
            print(f"  • {violation}")
    
    print("\n" + "=" * 80)
    print(f"🏁 FIN - {duration:.2f} secondes")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(test())