# test_iterations.py
import asyncio
import time
from app.ai_agents_v2.user_story_refinement.agent import get_pipeline
import app.ai_agents_v2.user_story_refinement.config as config

async def test_with_iterations(iterations: int, story: str, ac: list):
    print(f"\n{'='*80}")
    print(f"🧪 TEST AVEC {iterations} ITÉRATION(S)")
    print(f"{'='*80}")
    
    # Sauvegarder et modifier la config
    original_iterations = config.MAX_ITERATIONS
    config.MAX_ITERATIONS = iterations
    
    try:
        start_time = time.time()
        agent = get_pipeline()
        result = await agent.run(
            story=story,
            acceptance_criteria=ac,
            language="en",
            jira_id=f"TEST-{iterations}"
        )
        duration = time.time() - start_time
        
        # Afficher les résultats détaillés
        print(f"\n📊 RÉSULTATS DÉTAILLÉS:")
        print(f"  ⏱️  Durée: {duration:.2f}s")
        print(f"  📈 Initial score: {result.get('initial_score', 0):.3f}")
        print(f"  📈 Final score: {result.get('final_score', 0):.3f}")
        print(f"  📊 Testability score: {result.get('testability_score', 0):.3f}")
        print(f"  📈 Amélioration: {(result.get('final_score', 0) - result.get('initial_score', 0)):+.3f}")
        print(f"  🎯 Is testable: {result.get('is_testable', False)}")
        print(f"  🔄 Itérations réelles: {result.get('iterations', 0)}")
        print(f"  ✅ Status: {result.get('agent_status', 'unknown')}")
        print(f"  📝 Similarité: {result.get('similarity', 0):.3f}")
        print(f"  🔧 Story améliorée: {'✅ Oui' if result.get('is_improved', False) else '❌ Non'}")
        
        # Estimer les tokens (approximatif)
        approx_tokens = len(story) * 2 + sum(len(a) * 2 for a in ac)
        print(f"  📦 Tokens estimés: ~{approx_tokens}")
        
        return result, duration
        
    finally:
        config.MAX_ITERATIONS = original_iterations

async def main():
    print("=" * 80)
    print("🧪 TEST COMPARATIF DES ITÉRATIONS")
    print("=" * 80)
    
    # Story de test
    story = "As a user, I want to login to the application"
    ac = [
        "User can enter email",
        "User can enter password", 
        "User can click login button"
    ]
    
    print(f"\n📝 STORY DE TEST:")
    print(f"  📖 Story: {story}")
    print(f"  📋 AC count: {len(ac)}")
    print(f"  📏 Longueur: {len(story)} caractères")
    
    # Tester avec 1 itération
    result1, duration1 = await test_with_iterations(1, story, ac)
    
    # Tester avec 2 itérations
    result2, duration2 = await test_with_iterations(2, story, ac)
    
    # Comparaison détaillée
    print(f"\n{'='*80}")
    print(f"📊 COMPARAISON FINALE")
    print(f"{'='*80}")
    print(f"┌─────────────────────┬─────────────┬──────────────┐")
    print(f"│ Critère             │ 1 itération │ 2 itérations │")
    print(f"├─────────────────────┼─────────────┼──────────────┤")
    print(f"│ Score final         │    {result1.get('final_score', 0):.3f}     │     {result2.get('final_score', 0):.3f}      │")
    print(f"│ Amélioration        │   {result1.get('final_score', 0) - result1.get('initial_score', 0):+.3f}     │    {result2.get('final_score', 0) - result2.get('initial_score', 0):+.3f}      │")
    print(f"│ Testabilité         │    {result1.get('testability_score', 0):.3f}     │     {result2.get('testability_score', 0):.3f}      │")
    print(f"│ Is testable         │    {str(result1.get('is_testable', False)):<5} │    {str(result2.get('is_testable', False)):<5}   │")
    print(f"│ Durée (secondes)    │    {duration1:.1f}      │     {duration2:.1f}       │")
    print(f"│ Story améliorée     │    {str(result1.get('is_improved', False)):<5} │    {str(result2.get('is_improved', False)):<5}   │")
    print(f"└─────────────────────┴─────────────┴──────────────┘")
    
    # Recommandation
    print(f"\n💡 RECOMMANDATION:")
    if result1.get('final_score', 0) >= result2.get('final_score', 0):
        print(f"   ✅ 1 itération est suffisante (score {result1.get('final_score', 0):.3f} ≥ {result2.get('final_score', 0):.3f})")
        print(f"   🚀 Plus rapide: {duration1:.1f}s vs {duration2:.1f}s")
    else:
        print(f"   ⚠️ 2 itérations donnent un meilleur score ({result2.get('final_score', 0):.3f} > {result1.get('final_score', 0):.3f})")
        print(f"   ⏱️  Mais plus lent: {duration2:.1f}s vs {duration1:.1f}s")
    
    print(f"\n📌 CONFIGURATION RECOMMANDÉE:")
    print(f"   MAX_ITERATIONS = {1 if result1.get('final_score', 0) >= result2.get('final_score', 0) else 2}")

if __name__ == "__main__":
    asyncio.run(main())