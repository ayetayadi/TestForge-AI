import re
from typing import Dict, Optional
from app.ai_agents.user_stories.utils.text_quality_utils import detect_language

class TemplateEngine:

    def parse(self, story: str) -> Dict:
        text = story.strip()
        lower = text.lower()

        return {
            "role": self._extract_role(lower),
            "action": self._extract_action(lower),
            "benefit": self._extract_benefit(lower),
        }

    def build(self, role: str, action: str, benefit: Optional[str], lang="en") -> str:
        # sécuriser les valeurs
        role = role or ("utilisateur" if lang == "fr" else "user")
        action = action or ""

        if lang == "fr":
            if benefit:
                return f"En tant que {role}, je veux {action}, afin de {benefit}."
            return f"En tant que {role}, je veux {action}."

        else:
            if benefit:
                return f"As a {role}, I want {action}, so that {benefit}."
            return f"As a {role}, I want {action}."

    def normalize(self, story: str) -> str:
        parsed = self.parse(story)
        lang = detect_language(story)

        return self.build(
            parsed.get("role"),
            parsed.get("action"),
            parsed.get("benefit"),
            lang
        )

    # ======================
    # Extraction
    # ======================

    def _extract_role(self, text: str) -> Optional[str]:
        # EN
        match = re.search(r"as a[n]? ([^,\n]+?)(?:,| i want|$)", text)
        if match:
            return match.group(1).strip()

        # FR
        match = re.search(r"en tant qu[e']? ([^,\n]+?)(?:,| je veux|$)", text)
        if match:
            return match.group(1).strip()

        # fallback intelligent
        if "administrateur" in text:
            return "administrateur"

        if "admin" in text:
            return "admin"

        if "utilisateur" in text:
            return "utilisateur"

        if "user" in text:
            return "user"

        return None

    def _extract_action(self, text: str) -> Optional[str]:
        # EN
        match = re.search(r"i want (.*?)(, so that| so that|$)", text)
        if match:
            return match.group(1).strip()

        # FR
        match = re.search(r"je veux (.*?)( afin d[e']?| pour que|$)", text)
        if match:
            return match.group(1).strip()

        # fallback minimal
        match = re.search(r"(login|connect|create|delete|update|créer|supprimer)", text)
        if match:
            return match.group(0)

        return None

    def _extract_benefit(self, text: str) -> Optional[str]:
        # EN
        match = re.search(r"so that (.*?)\.?$", text)
        if match:
            return match.group(1).strip()

        # FR
        match = re.search(r"(afin d[e']?|pour que) (.*?)\.?$", text)
        if match:
            return match.group(2).strip()

        return None


# Singleton
template_engine = TemplateEngine()