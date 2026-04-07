import asyncio
from typing import List, Dict

from app.ai_agents.user_stories.pipeline.runner import run_user_story_pipeline
from .dataset import DATASET


async def run_eval_case(example: Dict) -> Dict:
    state = {
        "job_id": f"eval_{example['id']}",
        "jira_id": example["id"],
        **example["input"]
    }

    result = await run_user_story_pipeline(state)

    return {
        "id": example["id"],
        "final_score": result.get("final_score", 0),
        "improvement": result.get("score_improvement", 0),
        "llm_calls": result.get("llm_calls", 0),
        "duration": result.get("duration", 0),
        "guard_failed": result.get("guard_failed", False),
        "ac_count": len(result.get("acceptance_criteria", []))
    }


async def run_full_evaluation(dataset: List[Dict]):
    results = []

    for example in dataset:
        res = await run_eval_case(example)
        print(f"✔ {example['id']} → score={res['final_score']}")
        results.append(res)

    return results


if __name__ == "__main__":
    results = asyncio.run(run_full_evaluation(DATASET))
    print("\nFINAL RESULTS:\n", results)