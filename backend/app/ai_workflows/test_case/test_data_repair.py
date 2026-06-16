"""
Deterministic post-generation repair of test_data values.

Runs AFTER the LLM returns the test cases — pure Python, NO LLM call, negligible
cost (microseconds). It fixes two recurring problems where the generated
test_data contradicts the acceptance criteria:

  1. Enum values mistranslated to English  (e.g. 'Planning'  → 'Planification')
  2. Date fields set in the past on a positive test when an AC requires the date
     not to be in the past (e.g. a deadline / échéance >= today).

Both repairs are conservative: a value is only changed when we are confident it
violates a constraint that is *explicitly written in an acceptance criterion*.
Unrelated fields are never touched.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Values enumerated inside {...} in an acceptance criterion (e.g. "{Basse, Moyenne, Haute}")
_BRACE_RE = re.compile(r"\{([^{}]+)\}")
_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")

# English (and common variants) → canonical French domain values.
# A replacement is applied ONLY when the French target is actually present in an
# AC enum set for this story, so an unrelated field can never be corrupted.
_SYNONYMS = {
    "planning": "Planification",
    "in progress": "En cours",
    "ongoing": "En cours",
    "to do": "À faire",
    "todo": "À faire",
    "done": "Terminé",
    "complete": "Terminé",
    "completed": "Terminé",
    "finished": "Terminé",
    "paused": "En pause",
    "on hold": "En pause",
    "low": "Basse",
    "medium": "Moyenne",
    "high": "Haute",
}

# An AC carries a "date must not be in the past" constraint when it mentions one of these (FR + EN).
_DATE_CONSTRAINT_HINTS = (
    "passé", "antérieure", "date du jour", "aujourd'hui", "future", "futur",
    "in the past", "not be in the past", "future date", "today or later",
    "no earlier than", "on or after",
)
# test_data keys that plausibly hold a deadline-style date.
_DATE_KEY_HINTS = ("date", "deadline", "echeance", "échéance", "due", "ech")

# Replacement positive date = today + this many days.
_FUTURE_OFFSET_DAYS = 30


# ── Boundary-value (BVA) eligibility ──────────────────────────────────────────
# An AC is BVA-eligible ONLY when it defines a real bound: a numeric/length range,
# a min/max limit, an explicit character/digit count, a comparison symbol, or a
# date threshold. ACs that merely require a field, pick an enum value, or describe
# a plain action have NO boundary and MUST NOT receive a boundary test.
_BOUND_KEYWORDS = (
    "minimum", "maximum", "at least", "at most", "no more than", "no fewer than",
    "no less than", "greater than", "less than", "up to ", "between ", " range",
    "exceed", "exceeds", "longer than", "shorter than", "min length", "max length",
    "au moins", "au plus", "au minimum", "au maximum", "ne doit pas dépasser",
    "ne dépasse pas", "supérieur", "superieur", "inférieur", "inferieur",
    "entre ", "compris entre", "plage", "borne", "limite", "longueur",
    "length", "caractères", "caracteres", "characters",
)
_BOUND_SYMBOL_RE = re.compile(r"(?:[<>]=?|≤|≥)\s*\d|\d\s*(?:[<>]=?|≤|≥)")
_BOUND_COUNT_RE = re.compile(
    r"\d+\s*(?:caract|caracter|character|char\b|chiffre|digit|lettre|letter|mot\b|word)",
    re.IGNORECASE,
)


def _ac_has_bounds(ac: str) -> bool:
    """True when the acceptance criterion defines an actual bound eligible for BVA."""
    if not ac:
        return False
    low = ac.lower()
    if any(kw in low for kw in _BOUND_KEYWORDS):
        return True
    if _BOUND_COUNT_RE.search(ac):
        return True
    if _BOUND_SYMBOL_RE.search(ac):
        return True
    if any(h in low for h in _DATE_CONSTRAINT_HINTS):
        return True
    return False


def bva_eligible_indices(acceptance_criteria: List[str]) -> set:
    """0-based indices of ACs that define a real bound (numeric/length range,
    min/max, explicit count, comparison symbol, or date threshold). ONLY these
    ACs may receive a boundary-value test — all others have no boundary."""
    return {
        i for i, ac in enumerate(acceptance_criteria or [])
        if _ac_has_bounds(ac)
    }


# ── Optional-field hallucination guard ────────────────────────────────────────
# An AC declares a field optional with phrasings like "X peuvent être omis" /
# "X can be omitted" / "X is optional". A negative test must NEVER claim such a
# field is "required" — that contradicts the AC (classic optional→required bug).
_OPTIONAL_FIELD_RE = [
    re.compile(r"champs?\s+(.+?)\s+(?:peuvent|peut)\s+(?:être|etre)\s+omis", re.IGNORECASE),
    re.compile(r"(.+?)\s+(?:can be omitted|are optional|is optional)", re.IGNORECASE),
]
# FR / EN field tokens → canonical key, so a French AC matches an English test case.
_FIELD_SYNONYMS = {
    "téléphone": "phone", "telephone": "phone", "phone": "phone", "tél": "phone",
    "société": "company", "societe": "company", "society": "company", "company": "company", "entreprise": "company",
    "email": "email", "e-mail": "email", "courriel": "email", "mail": "email",
    "description": "description",
    "statut": "status", "status": "status",
    "échéance": "duedate", "echeance": "duedate", "due date": "duedate", "deadline": "duedate",
    "couleur": "color", "color": "color", "colour": "color",
}
_REQUIRED_MARKERS = (
    "is required", "are required", "required field", "is mandatory", "mandatory",
    "est requis", "sont requis", "obligatoire",
)


def _canon_field(token: str) -> Optional[str]:
    return _FIELD_SYNONYMS.get(token.strip().lower().strip("'\""))


def _extract_optional_fields(acceptance_criteria: List[str]) -> set:
    """Canonical names of fields the ACs declare optional (can be omitted)."""
    optional: set = set()
    for ac in acceptance_criteria or []:
        for rx in _OPTIONAL_FIELD_RE:
            for m in rx.finditer(ac or ""):
                for part in re.split(r",|\bet\b|\band\b", m.group(1)):
                    canon = _canon_field(part)
                    if canon:
                        optional.add(canon)
    return optional


def drop_optional_field_negatives(
    test_cases: List[Dict[str, Any]],
    acceptance_criteria: List[str],
) -> List[Dict[str, Any]]:
    """Remove negative TCs that assert an OPTIONAL field is required — a hallucination
    that contradicts the acceptance criteria. Language-robust (FR AC vs EN test case)."""
    optional = _extract_optional_fields(acceptance_criteria)
    if not optional or not test_cases:
        return test_cases

    kept: List[Dict[str, Any]] = []
    for tc in test_cases:
        text = (tc.get("title", "") + " " + " ".join(tc.get("expected_results", []))).lower()
        if any(mark in text for mark in _REQUIRED_MARKERS):
            referenced = {canon for token, canon in _FIELD_SYNONYMS.items() if token in text}
            if referenced & optional:
                logger.info(
                    "[TC GUARD] dropped negative claiming required on optional field(s) %s: %r",
                    referenced & optional, tc.get("title"),
                )
                continue
        kept.append(tc)
    return kept


def _extract_allowed_values(acceptance_criteria: List[str]) -> set:
    """Collect every value listed inside {...} braces across all ACs."""
    allowed: set = set()
    for ac in acceptance_criteria or []:
        for group in _BRACE_RE.findall(ac or ""):
            for part in group.split(","):
                v = part.strip()
                if v:
                    allowed.add(v)
    return allowed


def _has_future_date_constraint(acceptance_criteria: List[str]) -> bool:
    for ac in acceptance_criteria or []:
        low = (ac or "").lower()
        if any(h in low for h in _DATE_CONSTRAINT_HINTS):
            return True
    return False


def _repair_enum_value(value: str, allowed: set) -> Optional[str]:
    """Return a corrected value if `value` is an English variant of an allowed
    French enum value; otherwise None (leave unchanged)."""
    if not allowed or not isinstance(value, str):
        return None
    if value in allowed:
        return None  # already valid — do not touch
    mapped = _SYNONYMS.get(value.strip().lower())
    if mapped and mapped in allowed:
        return mapped
    return None


def repair_test_data(
    test_cases: List[Dict[str, Any]],
    acceptance_criteria: List[str],
    today: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """Mutate and return `test_cases` so their test_data respects the AC enums and
    date constraints. Pure-Python, no LLM call."""
    if not test_cases:
        return test_cases

    allowed = _extract_allowed_values(acceptance_criteria)
    date_constraint = _has_future_date_constraint(acceptance_criteria)

    # Nothing to enforce for this story → skip entirely.
    if not allowed and not date_constraint:
        return test_cases

    today = today or date.today()
    future = (today + timedelta(days=_FUTURE_OFFSET_DAYS)).isoformat()

    for tc in test_cases:
        data = tc.get("test_data")
        if not isinstance(data, dict):
            continue
        is_positive = tc.get("test_type", "").lower().strip() == "positive"

        for key, value in list(data.items()):
            if not isinstance(value, str):
                continue

            # --- enum conformance (any test type) ---
            fixed = _repair_enum_value(value, allowed)
            if fixed is not None:
                logger.info(
                    "[TC REPAIR] enum %r=%r → %r (AC-allowed value)",
                    key, value, fixed,
                )
                data[key] = fixed
                value = fixed

            # --- past date on a positive test (deadline-style field) ---
            if date_constraint and is_positive and any(h in key.lower() for h in _DATE_KEY_HINTS):
                m = _DATE_RE.search(value)
                if m:
                    try:
                        d = datetime.strptime(m.group(1), "%Y-%m-%d").date()
                    except ValueError:
                        d = None
                    if d and d < today:
                        new_value = value.replace(m.group(1), future)
                        logger.info(
                            "[TC REPAIR] past date %r=%r → %r (AC requires date >= today)",
                            key, value, new_value,
                        )
                        data[key] = new_value

    return test_cases
