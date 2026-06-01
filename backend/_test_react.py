"""Standalone smoke test for the new ReAct verification agent.
Loads the real failing TC from the DB and runs run_react() against the live app.
No persistence — just validates the agent logic + script_v2 reconstruction.
"""
import asyncio
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from app.core.database import async_session_maker
from app.repositories import playwright_repository as repo
from app.ai_agents_v2.playwright_e2e.tools import PlaywrightMCPClient
from app.ai_agents_v2.playwright_e2e.agent import PlaywrightReActAgent

TC_ID = "c12d981d-313a-45de-80d6-e68b9cfdec37"   # TC-016 — the one that failed
APP_URL = "http://localhost:3010"


async def main():
    async with async_session_maker() as db:
        tc = await repo.get_test_case(db, TC_ID)
        if not tc:
            print("TC not found"); return
        tc_for_agent = {
            "title": tc.title,
            "description": tc.description,
            "preconditions": tc.preconditions,
            "postconditions": tc.postconditions,
            "steps": tc.steps,
            "gherkin_source": tc.gherkin_source,
            "test_data": tc.test_data,
            "expected_results": tc.expected_results,
            "locators": tc.locators,
        }

    print("\n" + "=" * 70)
    print("TEST CASE:", tc_for_agent["title"])
    print("=" * 70)

    agent = PlaywrightReActAgent()
    async with PlaywrightMCPClient(headless=True, browser="chromium") as mcp:
        tools = {t.name: t for t in mcp.tools}
        res = await agent.run_react(
            tools,
            test_case=tc_for_agent,
            app_url=APP_URL,
            test_case_id="manual-react-test",
        )

    print("\n" + "=" * 70)
    print("RESULT")
    print("=" * 70)
    print("execution_status :", res["execution_status"])
    print("steps_passed     :", res["steps_passed"])
    print("steps_failed     :", res["steps_failed"])
    print("screenshot       :", "YES" if res.get("screenshot") else "NO")
    print("error/justif     :", res.get("error"))
    print("\n--- STEP DETAILS ---")
    for s in res["step_details"]:
        mark = "OK " if s["status"] == "passed" else "XX "
        print(f"  {mark} {s['step'][:90]}")
    print("\n--- SCRIPT V2 (reconstructed) ---")
    print(res["script_v2"])


if __name__ == "__main__":
    asyncio.run(main())
