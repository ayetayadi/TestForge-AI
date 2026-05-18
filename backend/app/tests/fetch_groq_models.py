"""
fetch_groq_models.py
Récupère la liste des modèles Groq disponibles avec gestion d'erreurs.
"""

import os
import json
import requests
import sys
from dotenv import load_dotenv 

load_dotenv()
# ============================================================
# 1. VÉRIFICATION DE LA CLÉ API
# ============================================================

api_key = os.environ.get("GROQ_API_KEY_5")

if not api_key:
    print("❌ ERREUR : GROQ_API_KEY_5 non trouvée !")
    print("\nSolutions :")
    print("  1. Vérifiez le nom de la variable (GROQ_API_KEY_5 ?)")
    print("  2. Essayez GROQ_API_KEY (sans le _5)")
    print("  3. Dans PowerShell : $env:GROQ_API_KEY_5='votre_clé'")
    print("  4. Dans CMD : set GROQ_API_KEY_5=votre_clé")
    sys.exit(1)

print(f"🔑 Clé API utilisée : {api_key[:10]}...{api_key[-4:]}")
print(f"   Longueur : {len(api_key)} caractères")

# ============================================================
# 2. APPEL DE L'API AVEC DEBUG
# ============================================================

url = "https://api.groq.com/openai/v1/models"
headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}

print(f"\n📡 Appel à : {url}")
print(f"   Headers : {headers}")

try:
    response = requests.get(url, headers=headers)
    
    # Afficher le statut complet
    print(f"\n📊 Statut HTTP : {response.status_code}")
    print(f"   Content-Type : {response.headers.get('Content-Type', 'N/A')}")
    
    # Si erreur, afficher le contenu complet
    if response.status_code != 200:
        print(f"\n❌ ERREUR HTTP {response.status_code}")
        print(f"   Réponse brute : {response.text}")
        
        # Suggestions selon le code d'erreur
        if response.status_code == 403:
            print("\n🔍 CAUSE PROBABLE : Clé API invalide ou expirée")
            print("\nSolutions :")
            print("  1. Générez une nouvelle clé sur https://console.groq.com/keys")
            print("  2. Vérifiez que vous avez bien copié la clé complète")
            print("  3. La clé doit commencer par 'gsk_'")
            print("  4. Vérifiez vos crédits sur https://console.groq.com/settings")
            
        elif response.status_code == 401:
            print("\n🔍 CAUSE PROBABLE : Clé API manquante ou mal formatée")
            
        elif response.status_code == 429:
            print("\n🔍 CAUSE PROBABLE : Rate limit dépassé")
            
        sys.exit(1)
    
    # Succès
    data = response.json()
    
    print(f"\n✅ Réponse reçue")
    print(f"   Type : {type(data)}")
    
    # Debug : afficher les clés de la réponse
    if isinstance(data, dict):
        print(f"   Clés disponibles : {list(data.keys())}")
    
    # Extraire les modèles
    models = data.get("data", [])
    
    if not models:
        print("\n⚠️  Aucun modèle trouvé dans data['data']")
        print(f"   Structure complète : {json.dumps(data, indent=2)[:500]}...")
    
    # ============================================================
    # 3. AFFICHAGE DES MODÈLES
    # ============================================================
    
    print("\n" + "="*80)
    print("MODÈLES DISPONIBLES SUR GROQ")
    print("="*80)
    
    for i, model in enumerate(models, 1):
        model_id = model.get("id", "N/A")
        owned_by = model.get("owned_by", "N/A")
        context = model.get("context_window", "N/A")
        
        print(f"\n📦 Modèle {i}/{len(models)}")
        print(f"   ID : {model_id}")
        print(f"   Propriétaire : {owned_by}")
        print(f"   Contexte max : {context} tokens")
        
        # Afficher toutes les autres infos disponibles
        for key, value in model.items():
            if key not in ["id", "owned_by", "context_window"]:
                print(f"   {key} : {value}")
    
    print(f"\n✅ Total : {len(models)} modèles disponibles")
    
    # ============================================================
    # 4. SAUVEGARDE
    # ============================================================
    
    output = {
        "fetch_date": requests.utils.datetime.now().isoformat() if hasattr(requests.utils, 'datetime') else "unknown",
        "total_models": len(models),
        "models": models
    }
    
    with open("groq_models_list.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print("\n💾 Liste sauvegardée dans groq_models_list.json")
    
except requests.exceptions.ConnectionError:
    print("\n❌ Erreur de connexion : Impossible d'atteindre l'API Groq")
    print("   Vérifiez votre connexion internet et le proxy éventuel")
    
except requests.exceptions.Timeout:
    print("\n❌ Timeout : L'API Groq ne répond pas")
    
except json.JSONDecodeError:
    print(f"\n❌ Réponse non-JSON reçue : {response.text[:500]}")
    
except Exception as e:
    print(f"\n❌ Erreur inattendue : {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()