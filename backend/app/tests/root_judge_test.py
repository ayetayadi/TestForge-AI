from root import RootSignals
import os
from dotenv import load_dotenv

load_dotenv()
client = RootSignals(api_key=os.getenv("ROOTSIGNALS_API_KEY"))

# === Test 1 : Évaluateur intégré (avec request + response) ===
print("=== Test 1 : Évaluateur intégré ===")
try:
    result = client.evaluators.Politeness(
        request="Is this response polite?",
        response="Bonjour, comment puis-je vous aider ?"
    )
    print(f"✅ Score : {result.score}")
    print(f"   Justification : {result.justification}")
except Exception as e:
    print(f"❌ Erreur : {e}")

# === Test 2 : RootJudge ===
print("\n=== Test 2 : RootJudge ===")
try:
    ev = client.evaluators.create(
        name="test_rootjudge_v2",
        intent="Tester si RootJudge fonctionne",
        predicate="Évalue si ce texte est clair et concis : {{response}}",
        model="gpt-4o",
    )
    result = ev.run(
        request="texte original",
        response="Le système répond en moins de 2 secondes."
    )
    print(f"✅ RootJudge fonctionne ! Score : {result.score}")
    print(f"   Justification : {result.justification}")
except Exception as e:
    print(f"❌ RootJudge échoue : {e}")