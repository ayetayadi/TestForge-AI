from typing import List
from app.utils.ac_utils import normalize_ac
from app.ai_agents.user_stories.utils.text_quality_utils import is_testable_ac


class ACService:

    @staticmethod
    def normalize(ac_list: List[str]) -> List[str]:
        if not ac_list:
            return []
        return normalize_ac(ac_list)

    @staticmethod
    def filter_testable(ac_list):
        return [
            ac for ac in ac_list
            if is_testable_ac(ac) or len(ac.split()) >= 4
        ]

    @staticmethod
    def compute_score(ac_list: List[str]) -> float:
        if not ac_list:
            return 0.0

        testable = ACService.filter_testable(ac_list)

        if not testable:
            return 0.0

        ratio = len(testable) / len(ac_list)

        # bonus léger seulement
        detailed = [ac for ac in testable if len(ac.split()) > 6]
        bonus = min(0.2, len(detailed) / max(len(testable), 1) * 0.2)

        score = ratio + bonus

        return round(min(1.0, score), 3)

    @staticmethod
    def deduplicate(ac_list: List[str]) -> List[str]:
        seen = set()
        result = []

        for ac in ac_list:
            norm = " ".join(ac.lower().split())
            if norm not in seen:
                seen.add(norm)
                result.append(ac.strip())

        return result

    @staticmethod
    def get_best(
        ac_list: List[str],
        min_length: int = 5,
        max_count: int = 5
    ) -> List[str]:

        testable = ACService.filter_testable(ac_list)

        sorted_ac = sorted(
            testable,
            key=lambda x: len(x.split()),
            reverse=True
        )

        return [
            ac for ac in sorted_ac
            if len(ac.split()) >= min_length
        ][:max_count]


ac_service = ACService()