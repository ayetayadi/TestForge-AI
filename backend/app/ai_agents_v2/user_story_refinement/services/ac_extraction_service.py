# services/ac_extraction_service.py

"""
Service centralisé pour l'extraction des AC.
Point d'entrée UNIQUE pour tout le pipeline.
"""

import re
from typing import List, Optional
from dataclasses import dataclass
from app.utils.story_utils import (
    parse_story,
    extract_ac_lines,
    extract_ac_from_html,
    is_html_content,
    remove_emojis
)
from app.ai_agents_v2.user_story_refinement.services.ac_service import ac_service


# ============================================================
# BLACKLIST HEADERS (CRITIQUE)
# ============================================================
AC_HEADER_BLACKLIST = [
    "acceptance criteria",
    "acceptance",
    "criteria",
    "ac",
    "critère d'acceptation",
    "critères d’acceptation",
    "critères",
    "conditions",
    "definition of done",
    "done criteria",
    "success criteria"
]


@dataclass
class ExtractionResult:
    story_clean: str
    acceptance_criteria: List[str]
    source: str
    original_story: str


class ACExtractionService:

    def extract(
        self,
        description: str,
        acceptance_criteria_field: Optional[str] = None,
        jira_id: str = "?"
    ) -> ExtractionResult:

        original = description or ""

        # ====================================================
        # 1. JIRA FIELD (PRIORITÉ MAX)
        # ====================================================
        if acceptance_criteria_field and acceptance_criteria_field.strip():

            if is_html_content(acceptance_criteria_field):
                ac_list = extract_ac_from_html(acceptance_criteria_field)
            else:
                ac_list = extract_ac_lines(acceptance_criteria_field)

            ac_list = self._normalize_and_filter(ac_list)


            return ExtractionResult(
                    story_clean=self._clean_story(description),
                    acceptance_criteria=ac_list,
                    source="jira_field",
                    original_story=original,
                )

        # ====================================================
        # 2. PARSE STORY (SECTION EMBARQUÉE)
        # ====================================================
        parsed = parse_story(description, acceptance_criteria_field)

        if parsed.existing_ac:
            ac_list = self._normalize_and_filter(parsed.existing_ac)

            if ac_list:
                return ExtractionResult(
                    story_clean=parsed.clean_story,
                    acceptance_criteria=ac_list,
                    source=parsed.source,
                    original_story=original,
                )

        # ====================================================
        # 3. EXTRACTION SIMPLE (PATTERNS)
        # ====================================================
        ac_list = extract_ac_lines(description)
        ac_list = self._normalize_and_filter(ac_list)

        if ac_list:
            return ExtractionResult(
                story_clean=self._clean_story(description),
                acceptance_criteria=ac_list,
                source="embedded",
                original_story=original,
            )

        # ====================================================
        # 4. FALLBACK (NONE)
        # ====================================================
        return ExtractionResult(
            story_clean=self._clean_story(description),
            acceptance_criteria=[],
            source="none",
            original_story=original,
        )

    @staticmethod
    def safe_filter(original: List[str], filtered: List[str]) -> List[str]:
        if len(filtered) < max(1, len(original) // 2):
            return original
        return filtered
    
    # ============================================================
    # NORMALISATION + FILTRAGE (CRITIQUE)
    # ============================================================
    def _normalize_and_filter(self, ac_list: List[str]) -> List[str]:
        if not ac_list:
            return []
    
        ac_list = ac_service.normalize(ac_list)
        ac_list = ac_service.deduplicate(ac_list)
        original_ac = list(ac_list)
    
        cleaned = []
    
        for ac in ac_list:
            if not ac:
                continue
    
            # 1. remove emojis
            ac = remove_emojis(ac).strip()
    
            # 2. supprimer header inline
            ac = re.sub(
                r"^(crit[èe]res?\s+d['’]acceptation\s*[-:]*\s*)",
                "",
                ac,
                flags=re.IGNORECASE
            )
    
            ac = re.sub(
                r"^(acceptance\s+criteria\s*[-:]*\s*)",
                "",
                ac,
                flags=re.IGNORECASE
            )
    
            # 3. nettoyer bullets
            ac = ac.lstrip("-*• ").strip()

            # 4. nettoyage structurel
            ac = re.sub(r"\s*-\s*", " ", ac)  # supprime " - "
            ac = re.sub(r"\s+", " ", ac)     # normalise espaces
            ac = ac.strip()

            # ❌ ligne invalide
            if ac.endswith("-") or ac.strip() == "":
                continue
                
            lower = ac.lower()
    
            # ❌ ligne vide après nettoyage
            if not lower:
                continue
    
            # ❌ trop court
            #if len(lower.split()) < 2:
            #    continue
        
            # juste ignorer si c’est EXACTEMENT une user story
            if lower.startswith("en tant que") or lower.startswith("as a "):
                # skip uniquement si c’est une vraie user story complète
                if "afin de" in lower or "so that" in lower:
                    continue
    
            # ❌ bruit simple
            if lower in {"ok", "done", "validé"}:
                continue
    
            # ❌ header seul
            if lower in AC_HEADER_BLACKLIST:
                continue
    
            cleaned.append(ac)

        cleaned = self.safe_filter(original_ac, cleaned)
        print("---- AC DEBUG ----")
        print("Original:", len(original_ac))
        print("After clean:", len(cleaned))

        return cleaned
   
    # ============================================================
    # CLEAN STORY (SUPPRESSION SECTION AC)
    # ============================================================
    def _clean_story(self, text: str) -> str:
        if not text:
            return ""

        pattern = re.compile(
            r"(?:[^\w\s]*\s*)?"
            r"(?:crit[èe]res?\s+d['’]acceptation|acceptance\s+criteria|"
            r"conditions?\s+d['’]acceptation|\bac\s*:)"
            r".*$",
            re.IGNORECASE | re.DOTALL
        )

        cleaned = pattern.sub("", text).strip()

        return cleaned if cleaned else text.strip()


# Singleton
ac_extraction_service = ACExtractionService()