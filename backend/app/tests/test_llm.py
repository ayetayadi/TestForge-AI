# test_tokens.py
import asyncio
from langchain_openrouter import ChatOpenRouter
from app.core.config import settings

async def test_token_extraction():
    print("=" * 60)
    print("TEST: Token extraction from OpenRouter")
    print("=" * 60)
    
    llm = ChatOpenRouter(
        model="openai/gpt-oss-20b",
        temperature=0.3,
        api_key=settings.OPENROUTER_API_KEY,
    )
    
    print("\n[1] Calling LLM...")
    response = await llm.ainvoke("Hello, say just one word: 'test'")
    
    print("\n[2] Response Analysis:")
    print(f"  - Response type: {type(response)}")
    print(f"  - Response content: {response.content[:100]}...")
    
    print("\n[3] Checking for token usage:")
    print(f"  - Has response_metadata: {hasattr(response, 'response_metadata')}")
    if hasattr(response, 'response_metadata'):
        print(f"  - response_metadata: {response.response_metadata}")
    
    print(f"  - Has usage_metadata: {hasattr(response, 'usage_metadata')}")
    if hasattr(response, 'usage_metadata'):
        print(f"  - usage_metadata: {response.usage_metadata}")
    
    print(f"  - Has llm_output: {hasattr(response, 'llm_output')}")
    if hasattr(response, 'llm_output'):
        print(f"  - llm_output: {response.llm_output}")
    
    # Vérifier tous les attributs disponibles
    print("\n[4] All attributes (non-private):")
    attrs = [a for a in dir(response) if not a.startswith('_')]
    for attr in attrs:
        if 'usage' in attr.lower() or 'token' in attr.lower() or 'meta' in attr.lower():
            try:
                value = getattr(response, attr)
                print(f"  - {attr}: {value}")
            except:
                print(f"  - {attr}: <error>")
    
    print("\n" + "=" * 60)

if __name__ == "__main__":
    asyncio.run(test_token_extraction())