from typing import List
from app.utils.ac_utils import normalize_ac
from app.ai_agents_v2.user_story_refinement.utils.text_processing import shares_keywords
from app.ai_agents_v2.user_story_refinement.utils.testability import is_testable_ac


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
            if is_testable_ac(ac) or len(ac.split()) >= 3
        ]

    @staticmethod
    def compute_score(ac_list: List[str]) -> float:
        if not ac_list:
            return 0.0

        testable = ACService.filter_testable(ac_list)

        if not testable:
            return 0.0

        ratio = len(testable) / len(ac_list)

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
    def score_ac(ac: str) -> int:
        score = len(ac.split())

        if is_testable_ac(ac):
            score += 5

        return score

    @staticmethod
    def get_best(
        ac_list: List[str],
        min_length: int = 3,
        max_count: int = 5
    ) -> List[str]:

        if not ac_list:
            return []

        testable = ACService.filter_testable(ac_list)

        if not testable or len(testable) < len(ac_list) * 0.6:
            testable = ac_list

        sorted_ac = sorted(
            testable,
            key=ACService.score_ac,
            reverse=True
        )

        result = [
            ac for ac in sorted_ac
            if len(ac.split()) >= min_length
        ]

        if not result:
            return ac_list[:max_count]

        return result[:max_count]
    
    @staticmethod
    def validate_ac(original_story: str, ac_list: list) -> list:
        if not ac_list:
            return []
    
        valid = []
    
        for ac in ac_list:
            if not is_testable_ac(ac):
                continue
    
            if not shares_keywords(original_story, ac):
                continue
    
            valid.append(ac.strip())
    
        if not valid:
            return ac_list[:3]
    
        return valid[:5]



ac_service = ACService()