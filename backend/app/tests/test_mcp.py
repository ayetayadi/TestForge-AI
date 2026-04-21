import asyncio
import logging

logging.basicConfig(level=logging.DEBUG)

from app.ai_agents_v2.playwright_e2e.tools import PlaywrightMCPClient

async def test():
    print("🔍 DEBUG: Starting test...")
    async with PlaywrightMCPClient() as mcp:
        print(f"🔍 DEBUG: Tools loaded: {len(mcp.tools)}")
        for t in mcp.tools:
            print(f"  - {t.name}")

if __name__ == "__main__":
    asyncio.run(test())