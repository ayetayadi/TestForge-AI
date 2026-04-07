import asyncio
from .dataset import DATASET
from .runner import run_full_evaluation


async def compare_versions():
    print("\n===== VERSION A (avec LLM evaluate) =====")
    results_A = await run_full_evaluation(DATASET)

    # 👉 ici désactive LLM dans evaluate
    input("\n👉 Désactive LLM dans evaluate puis appuie sur ENTER...\n")

    print("\n===== VERSION B (sans LLM evaluate) =====")
    results_B = await run_full_evaluation(DATASET)

    print("\n===== COMPARISON =====")
    for a, b in zip(results_A, results_B):
        print(f"\nCase: {a['id']}")
        print(f"A score: {a['final_score']} | B score: {b['final_score']}")
        print(f"A calls: {a['llm_calls']} | B calls: {b['llm_calls']}")
        print(f"A duration: {a['duration']} | B duration: {b['duration']}")


if __name__ == "__main__":
    asyncio.run(compare_versions())