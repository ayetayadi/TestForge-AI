"""Standalone smoke test for the ReAct verification agent.

Loads real TCs from the DB and runs run_react() against the live app in ONE
shared browser session (like a real suite). No persistence — just validates the
agent logic + script_v2 reconstruction + the new debug transcript.

Prerequisites before running:
  1. MCP Playwright server:   npx @playwright/mcp@latest --port 8931
  2. Target app running on:   http://localhost:3010
  3. The TC IDs below must exist in the DB.

Run:
  cd backend
  python -m app.tests._test_react
  # for the FULL prompt dump each turn:
  $env:DEBUG="true"; python -m app.tests._test_react
"""
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from app.core.database import async_session_maker
from app.repositories import playwright_repository as repo
from app.ai_agents_v2.playwright_e2e.tools import PlaywrightMCPClient
from app.ai_agents_v2.playwright_e2e.agent import PlaywrightReActAgent

APP_URL = "http://localhost:3010"

# ── TCs to run, IN ORDER ─────────────────────────────────────────────────────
# Login MUST be first: it establishes the session the next TCs reuse (shared
# browser, suite_continuation=True for index > 0 — exactly like a real suite).
# Comment a line out to skip it. Start with ONLY login, then add the rest.
TC_IDS = [
    # ── DIAGNOSTIC: run "Create category" ALONE so suite_continuation=False →
    # the agent auto-logs-in with the REAL configured creds (TEST_USER_EMAIL),
    # NOT the fake test_data. This proves the agent CAN reach a PASSED verdict.
    ("1b0db77e-71f8-487a-9a7e-121c61efa499", "Create category with all fields"),
    # ── Re-enable these later (login needs REAL creds in its test_data first):
    # ("cae6d673-af6d-4464-8053-e21e4d78be0e", "Login with valid credentials"),
    # ("253ab55d-701c-4ac2-b2b8-10a82c8f728d", "Create client with all fields"),
]


def _tc_to_agent(tc) -> dict:
    return {
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


async def main():
    # 1. Fetch all TCs upfront (DB session closed before browser work)
    cases = []
    async with async_session_maker() as db:
        for tc_id, expected_title in TC_IDS:
            tc = await repo.get_test_case(db, tc_id)
            if not tc:
                print(f"⚠️  TC NOT FOUND in DB: {tc_id} ({expected_title}) — skipping")
                continue
            cases.append((tc_id, _tc_to_agent(tc)))

    if not cases:
        print("No runnable TCs — aborting."); return

    print("\n" + "=" * 70)
    print(f"RUNNING {len(cases)} TEST CASE(S) IN ONE SHARED SESSION")
    for i, (_, tc) in enumerate(cases):
        print(f"  {i + 1}. {tc['title']}")
    print("=" * 70)

    # 2. ONE shared browser session for the whole run (mirrors run_suite_smart)
    agent = PlaywrightReActAgent()
    results = []
    async with PlaywrightMCPClient(headless=True, browser="chromium") as mcp:
        tools = {t.name: t for t in mcp.tools}

        for idx, (tc_id, tc_for_agent) in enumerate(cases):
            print("\n" + "█" * 70)
            print(f"█ TC {idx + 1}/{len(cases)}: {tc_for_agent['title']}")
            print(f"█ suite_continuation = {idx > 0}")
            print("█" * 70)

            res = await agent.run_react(
                tools,
                test_case=tc_for_agent,
                app_url=APP_URL,
                test_case_id=f"manual-{tc_id[:8]}",
                suite_continuation=(idx > 0),   # 1st logs in, rest reuse the session
            )
            results.append((tc_for_agent["title"], res))

            print("\n" + "-" * 70)
            print(f"RESULT: {tc_for_agent['title']}")
            print("-" * 70)
            print("execution_status :", res["execution_status"])
            print("steps_passed     :", res["steps_passed"])
            print("steps_failed     :", res["steps_failed"])
            print("screenshot       :", "YES" if res.get("screenshot") else "NO")
            print("error/justif     :", res.get("error"))
            print("--- STEP DETAILS ---")
            for s in res["step_details"]:
                mark = "OK " if s["status"] == "passed" else "XX "
                print(f"  {mark} {s['step'][:90]}")
            print("--- SCRIPT V2 (reconstructed) ---")
            print(res["script_v2"])

    # 3. Final summary across all TCs
    print("\n" + "=" * 70)
    print("SUITE SUMMARY")
    print("=" * 70)
    for title, res in results:
        status = res["execution_status"]
        mark = "✅" if status in ("passed", "completed") else "❌"
        print(f"  {mark} [{status:9}] {title}  "
              f"({res['steps_passed']} passed / {res['steps_failed']} failed)")


if __name__ == "__main__":
    asyncio.run(main())
