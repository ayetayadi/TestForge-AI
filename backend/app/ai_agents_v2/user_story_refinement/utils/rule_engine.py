import re
from typing import Dict


class RuleEngine:

    def evaluate(self, story: str) -> Dict:
        issues = []
        suggestions = []
        score = 1.0

        story_lower = story.lower()

        # 1. Format user story (FR + EN)
        if not self._has_user_story_format(story_lower):
            issues.append("User story does not follow a standard format")
            suggestions.append(
                "Use format: As a [role], I want [feature], so that [benefit]"
            )
            score -= 0.15

        # 2. Acteur
        if not self._has_actor(story_lower):
            issues.append("Missing or unclear actor")
            suggestions.append("Specify who is performing the action")
            score -= 0.15

        # 3. Action
        if not self._has_action(story_lower):
            issues.append("Missing action or functionality")
            suggestions.append("Clearly describe what the user wants to do")
            score -= 0.15

        # 4. Valeur métier
        if not self._has_value(story_lower):
            issues.append("Missing business value")
            suggestions.append("Explain why this feature is useful")
            score -= 0.15

        # 5. Longueur
        word_count = len(story.split())

        if word_count > 50:
            issues.append("User story is too long")
            suggestions.append("Keep it concise (30-40 words recommended)")
            score -= 0.1

        if word_count < 5:
            issues.append("User story is too short")
            suggestions.append("Provide more meaningful detail")
            score -= 0.1

        # 6. Mots vagues FR + EN
        vague_words = [
            "quickly", "easily", "efficiently", "fast", "user-friendly",
            "rapidement", "facilement", "efficacement", "simple", "intuitif",
        ]
        found_vague = [w for w in vague_words if w in story_lower]

        if found_vague:
            issues.append(f"Contains vague terms: {', '.join(found_vague)}")
            suggestions.append("Use measurable and testable criteria")
            score -= 0.1

        # 7. Clamp
        score = max(0.0, min(1.0, score))

        return {
            "rule_score": round(score, 2),
            "rule_issues": issues,
            "rule_suggestions": suggestions,
        }

    # ======================
    # Helpers
    # ======================

    def _has_user_story_format(self, story: str) -> bool:
        # FIX: suppression de la virgule obligatoire après le rôle
        # "En tant qu'utilisateur Je veux" est valide sans virgule
        has_role = bool(
            re.search(r"\bas a\b", story)
            or re.search(r"\ben tant qu[e\']?\b", story)
        )
        has_action = bool(
            re.search(r"\bi want\b", story)
            or re.search(r"\bje veux\b", story)
            or re.search(r"\bje souhaite\b", story)
            or re.search(r"\bj'aimerais\b", story)
        )
        return has_role and has_action

    def _has_actor(self, story: str) -> bool:
        return bool(
            re.search(r"\bas a\b", story)
            or re.search(r"\ben tant qu[e\']?\b", story)
            or re.search(r"\b(user|admin|client|utilisateur)\b", story)
        )

    def _has_action(self, story: str) -> bool:
        return bool(
            re.search(r"\bi want\b", story)
            or re.search(r"\bje veux\b", story)
            or re.search(r"\b(should be able to|can|peut)\b", story)
            or re.search(r"\bje souhaite\b", story)
            or re.search(r"\bj'aimerais\b", story)
        )

    def _has_value(self, story: str) -> bool:
        return bool(
            re.search(r"\bso that\b", story)
            or re.search(r"\bafin d[e\']?\b", story)
            or re.search(r"\bpour que\b", story)
        )


# Singleton
rule_engine = RuleEngine()