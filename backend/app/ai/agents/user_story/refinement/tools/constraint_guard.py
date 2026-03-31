import re
from typing import Dict, List, Tuple
from app.core.ac_config import (
    ALLOWED_STANDARD_TERMS,
    ENGLISH_STEMS,
    HALLUCINATION_PATTERNS,
    MAX_NEW_DOMAIN_TERMS,
    FRENCH_STEMS,
    SAFE_TERMS
)
from app.utils.common.text_quality_utils import detect_language


class ConstraintGuard:

    def validate(self, original: str, improved: str, acceptance_criteria: List[str] = None) -> Dict:
        issues = []
        critical_issues = []

        original_lower = (original or "").lower()
        improved_lower = (improved or "").lower()

        # 1. Verbosity
        if len(improved.split()) > len(original.split()) * 1.8:
            issues.append("Refined story is too verbose")

        # 2. Capability drift
        new_caps = self._detect_capability_drift(original_lower, improved_lower)
        if new_caps:
            issues.append(f"New terms introduced: {new_caps[:3]}")

        # 3. Constraint loss
        lost = self._detect_constraint_loss(original_lower, improved_lower)
        if lost:
            issues.append(f"Constraints possibly lost: {lost}")

        # 4. Forbidden domain shift
        forbidden_keywords = ["login", "payment", "billing", "invoice", "analytics"]
        for keyword in forbidden_keywords:
            if keyword in improved_lower and keyword not in original_lower:
                critical_issues.append(f"Forbidden domain shift: {keyword}")

        # 5. Role change
        if self._extract_role(original_lower) != self._extract_role(improved_lower):
            issues.append("Role changed")

        # 6. Intent preservation
        if not self._preserves_intent(original_lower, improved_lower):
            issues.append("Intent may have shifted (low word overlap)")

        # 7. Domain overlap
        domain_sim = self._domain_overlap(original_lower, improved_lower)
        if domain_sim < 0.4:
            critical_issues.append(f"Domain drift detected (sim={round(domain_sim,2)})")

        # 8. Generic output
        if self._is_generic_story(improved_lower):
            issues.append("Generic output")

        # 9. Structure
        if not self._has_valid_structure(improved_lower):
            issues.append("Structure not ideal")

        # 10. AC validation
        if acceptance_criteria:
            issues.extend(self._validate_ac(acceptance_criteria, original_lower))

            _, rejected = self.validate_ac_provenance(
                acceptance_criteria,
                original
            )

            for r in rejected:
                issues.append(f"Rejected AC ({r['reason']}): {r['ac'][:50]}...")

        return {
            "guard_issues": issues,
            "critical_issues": critical_issues,
            "is_safe": len(critical_issues) == 0,
        }

    # =========================
    # HELPERS
    # =========================

    def _preserves_intent(self, original: str, improved: str) -> bool:
        o = set(original.split())
        i = set(improved.split())
        return (len(o & i) / max(len(o), 1)) >= 0.5

    def _domain_overlap(self, original: str, improved: str) -> float:
        o = set(original.split())
        i = set(improved.split())
        return len(o & i) / max(len(o), 1)

    def _detect_capability_drift(self, original: str, improved: str):
        return list(set(improved.split()) - set(original.split()))

    def _detect_constraint_loss(self, original: str, improved: str):
        keywords = ["token", "limit", "retry", "sécurité"]
        return [k for k in keywords if k in original and k not in improved]

    def _extract_role(self, text: str) -> str:
        m = re.search(r"(?:as a|en tant que?)\s+([^,]+?)(?:,|\s+(?:i want|je veux))", text)
        return m.group(1).strip() if m else ""

    def _validate_ac(self, ac_list: List[str], original_lower: str) -> List[str]:
        issues = []

        observable_keywords = [
            "display", "show", "error", "message",
            "affiche", "erreur", "message"
        ]

        for ac in ac_list:
            ac_lower = ac.lower()

            if len(ac.split()) < 4:
                issues.append(f"AC too short: {ac}")
                continue

            if not any(k in ac_lower for k in observable_keywords):
                if "doit" in ac_lower or "must" in ac_lower:
                    continue
                issues.append(f"Possibly weak AC: {ac}")

        return issues

    def _is_generic_story(self, text: str):
        return len(set(text.split())) < 5

    def _has_valid_structure(self, text: str):
        return (
            ("as a" in text and "i want" in text) or
            ("en tant que" in text and "je veux" in text)
        )

    def validate_ac_provenance(
        self,
        ac_list: List[str],
        original_story: str,
        language: str = None
    ) -> Tuple[List[str], List[Dict]]:

        if not ac_list:
            return [], []

        original_lower = original_story.lower()
        original_tokens = set(re.findall(r'\b\w{3,}\b', original_lower))
        lang = (language or detect_language(original_story) or "").lower()
        if lang in ["fr", "french", "français"]:
            lang_key = "fr"
        elif lang in ["en", "english"]:
            lang_key = "en"
        else:
            lang_key = "fr"

        original_tokens = self._expand_tokens_with_stems(original_tokens, lang_key)
        allowed_terms = {t.lower() for t in ALLOWED_STANDARD_TERMS.get(lang_key, set())}
        safe_terms = {t.lower() for t in SAFE_TERMS}

        # Merge all allowed terms into a single set for filtering
        all_allowed = allowed_terms | safe_terms

        valid = []
        rejected = []

        for ac in ac_list:
            ac_lower = ac.lower()
            rejection_reason = None

            # --- Language consistency check ---
            ac_lang = detect_language(ac)
            ac_lang_key = "fr" if ac_lang in ["fr", "french", "français"] else "en"

            if ac_lang_key != lang_key:
                rejected.append({
                    "ac": ac,
                    "reason": f"language_mismatch:expected={lang_key},got={ac_lang_key}"
                })
                continue
            
            if self._is_opposite_action_ac(ac_lower, original_lower):
                rejected.append({
                    "ac": ac,
                    "reason": "opposite_action_drift"
                })
                continue

            # --- Hallucination pattern check ---
            for pattern in HALLUCINATION_PATTERNS:
                if re.search(pattern, ac_lower) and not re.search(pattern, original_lower):
                    rejection_reason = f"hallucinated_feature:{pattern}"
                    break

            if rejection_reason:
                rejected.append({"ac": ac, "reason": rejection_reason})
                continue

            # --- New concept check ---
            ac_tokens = set(re.findall(r'\b\w{3,}\b', ac_lower))
            ac_tokens_expanded = self._expand_tokens_with_stems(ac_tokens, lang_key)
            new_tokens = ac_tokens_expanded - original_tokens - all_allowed
            domain_tokens = {t for t in new_tokens if len(t) > 5}

            if len(domain_tokens) > MAX_NEW_DOMAIN_TERMS:
                rejected.append({
                    "ac": ac,
                    "reason": f"new_concepts:{list(domain_tokens)[:3]}"
                })
                continue

            valid.append(ac)

        return valid, rejected

    def _expand_tokens_with_stems(self, tokens: set, language: str) -> set:
        expanded = set(tokens)

        language = language.lower()
        if language in ["fr", "french", "français"]:
            stems_dict = FRENCH_STEMS
        elif language in ["en", "english"]:
            stems_dict = ENGLISH_STEMS
        else:
            return tokens

        for token in tokens:
            token_lower = token.lower()
            for stem, variations in stems_dict.items():
                if token_lower in variations or token_lower.startswith(stem):
                    expanded.update(variations)

        return expanded
    

     
    def _is_opposite_action_ac(self, ac_lower: str, story_lower: str) -> bool:
        # Each tuple: (story_must_contain, story_must_NOT_contain, ac_blocked_terms)
        opposite_rules = [
            # French logout vs login
            (
                ["déconnexion", "déconnecter", "se déconnecter"],
                ["connexion sécurisée", "connexion et déconnexion"],
                ["se connecter", "connexion avec", "identifiants",
                 "mot de passe", "saisit un email", "email et un mot de passe",
                 "identifiants invalides", "identifiants sont invalides",
                 "tentative de connexion"]
            ),
            # English logout vs login
            (
                ["log out", "logout", "sign out", "disconnect"],
                ["login and logout", "sign in and sign out"],
                ["log in", "login", "sign in", "credentials",
                 "enters email", "enters password", "invalid credentials",
                 "authentication attempt"]
            ),
            # French export vs import
            (
                ["export", "exporter", "exportation"],
                ["import et export", "import/export"],
                ["importer", "importation", "import de", "import des"]
            ),
            # French import vs export
            (
                ["import", "importer", "importation"],
                ["import et export", "import/export"],
                ["exporter", "exportation", "export de", "export des"]
            ),
            # French delete vs create
            (
                ["supprimer", "suppression"],
                ["créer et supprimer"],
                ["créer", "création", "ajouter", "ajout"]
            ),
            # French create vs delete
            (
                ["créer", "création"],
                ["créer et supprimer"],
                ["supprimer", "suppression", "effacer"]
            ),
        ]
 
        for story_keywords, story_exceptions, ac_blocked in opposite_rules:
            # Check if story is about this action
            story_matches = any(kw in story_lower for kw in story_keywords)
            if not story_matches:
                continue
 
            # Check if story has an exception (e.g. story covers both actions)
            has_exception = any(exc in story_lower for exc in story_exceptions)
            if has_exception:
                continue
 
            # Check if AC contains blocked opposite-action terms
            for blocked in ac_blocked:
                if blocked in ac_lower:
                    return True
 
        return False


constraint_guard = ConstraintGuard()