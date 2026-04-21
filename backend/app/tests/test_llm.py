# test_github.py
import asyncio
from app.llm.llm_control import create_llm

async def test():
    llm = create_llm(model="openai/gpt-oss-120b")
    response = await llm.ainvoke("Say hello in one word")
    print(f"Response: {response.content}")

asyncio.run(test())