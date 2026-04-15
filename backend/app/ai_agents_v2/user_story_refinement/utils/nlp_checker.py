import re
from typing import Dict

class NLPChecker:

    def analyze(self, story: str) -> Dict:
        issues = []
        suggestions = []
        score = 1.0

        text = story.lower()

        # 1. Ambiguïté (FR + EN)
        vague_words = [
            "quickly", "easily", "efficiently", "fast", "better",
            "rapidement", "facilement", "efficacement", "simple", "intuitif",
        ]
        found_vague = [w for w in vague_words if w in text]

        if found_vague:
            issues.append(f"Ambiguous terms detected: {', '.join(found_vague)}")
            suggestions.append("Replace vague terms with measurable criteria")
            score -= 0.15

        # 2. Non testable
        non_testable_patterns = [
            r"works well",
            r"perform(s)? better",
            r"improve(s)?",
            r"optimize(s)?",
            r"handle(s)? errors",
            r"bonne performance",
            r"améliorer",
            r"optimiser",
        ]
        for pattern in non_testable_patterns:
            if re.search(pattern, text):
                issues.append("Non-testable requirement detected")
                suggestions.append(
                    "Use measurable acceptance criteria (e.g., response time, success rate)"
                )
                score -= 0.2
                break

        # 3. Voix passive
        passive_patterns = [
            r"\bis (created|updated|deleted|processed)\b",
            r"\bare (created|updated|deleted|processed)\b",
            r"\best (créé|mis à jour|supprimé)\b",
            r"\bsont (créés|mis à jour|supprimés)\b",
        ]
        for pattern in passive_patterns:
            if re.search(pattern, text):
                issues.append("Passive voice detected")
                suggestions.append("Use active voice (e.g., 'user creates account')")
                score -= 0.1
                break

        # 4. Absence de critères mesurables
        if self._implies_performance(text) and not self._has_measurable_elements(text):
            issues.append("Lack of measurable acceptance criteria")
            suggestions.append(
                "Include measurable conditions (e.g., time, success rate, limits)"
            )
            score -= 0.15

        # 5. Expressions floues métier
        vague_business = [
            "user-friendly",
            "intuitive",
            "simple to use",
            "bonne expérience",
            "facile à utiliser",
        ]
        found_business = [w for w in vague_business if w in text]

        if found_business:
            issues.append(f"Vague business requirement: {', '.join(found_business)}")
            suggestions.append(
                "Define UX requirements with concrete metrics or behaviors"
            )
            score -= 0.1

        # 6. Clamp
        score = max(0.0, min(1.0, score))

        return {
            "nlp_score": round(score, 2),
            "nlp_issues": issues,
            "nlp_suggestions": suggestions,
        }

    # ======================
    # Helpers
    # ======================

    def _has_measurable_elements(self, text: str) -> bool:
        measurable_patterns = [
            r"\d+ ?(ms|seconds|sec|%)",
            r"within \d+",
            r"less than \d+",
            r"greater than \d+",
            r"au moins \d+",
            r"moins de \d+",
            r"plus de \d+",
        ]
        return any(re.search(p, text) for p in measurable_patterns)

    def _implies_performance(self, text: str) -> bool:
        perf_keywords = [
            r"\bfast\b", r"\bspeed\b", r"\bperformance\b",
            r"\bresponse time\b", r"\bload\b", r"\brapide\b",
            r"\bperformant\b", r"\btemps de réponse\b",
        ]
        return any(re.search(kw, text) for kw in perf_keywords)


# Singleton
nlp_checker = NLPChecker()