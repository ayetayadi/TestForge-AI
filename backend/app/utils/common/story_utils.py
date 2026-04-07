import re
from dataclasses import dataclass
from typing import Optional, List
from app.utils.common.html_parser import extract_ac_from_html, clean_html

AC_MARKERS = [
    r"crit[eè]res?\s+d['’]acceptation\s*:?",
    r"acceptance\s+criteria\s*:?",
    r"conditions?\s+d['’]acceptation\s*:?",
    r"\bac\s*:",
]

AC_PATTERN = re.compile("|".join(AC_MARKERS), flags=re.IGNORECASE)


@dataclass
class ParsedStory:
    clean_story: str
    existing_ac: Optional[List[str]]
    source: str


def is_html_content(text: str) -> bool:
    return bool(re.search(r"<[^>]+>", text or ""))


def ensure_string(value):
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    return str(value or "")

def parse_story(description: Optional[str], acceptance_criteria: Optional[str]) -> ParsedStory:

    description = ensure_string(description)
    acceptance_criteria = ensure_string(acceptance_criteria).strip() or None

    is_html = is_html_content(description) or (
        acceptance_criteria and is_html_content(acceptance_criteria)
    )

    # =========================
    # HTML MODE
    # =========================
    if is_html:
        description_clean = clean_html(description)

        if acceptance_criteria:
            existing_ac = extract_ac_from_html(acceptance_criteria)
        else:
            existing_ac = extract_ac_from_html(description)

        # fallback si vide
        if not existing_ac:
            existing_ac = extract_ac_lines(description_clean)

        return ParsedStory(description_clean, existing_ac, "html")

    # =========================
    # TEXT MODE
    # =========================
    ac_match = AC_PATTERN.search(description)

    if not acceptance_criteria and not ac_match:
        fallback_ac = extract_ac_lines(description)
        return ParsedStory(description, fallback_ac or None, "description_only")

    if acceptance_criteria and not ac_match:
        return ParsedStory(
            description,
            extract_ac_lines(acceptance_criteria),
            "separate_field"
        )

    story_part = _clean_story_part(description[: ac_match.start()])

    if acceptance_criteria:
        return ParsedStory(
            story_part,
            extract_ac_lines(acceptance_criteria),
            "duplicate"
        )

    ac_in_desc = extract_ac_lines(description[ac_match.start():])

    return ParsedStory(
        story_part,
        ac_in_desc or extract_ac_lines(description),
        "mixed",
    )


def _clean_story_part(text: str) -> str:
    lines = text.split("\n")

    clean_lines = [
        l.strip()
        for l in lines
        if l.strip() and not AC_PATTERN.search(l)
    ]

    return " ".join(clean_lines).strip()


def extract_ac_lines(text: str) -> List[str]:
    lines = re.split(r"\n|<br>|<li>|</li>", text)

    content = []
    current_section = None

    for line in lines:
        l = re.sub(r"<.*?>", "", line).strip()

        if not l:
            continue

        if ":" in l and len(l.split()) < 5:
            current_section = l.replace(":", "")
            continue

        l = l.lstrip("- •").strip()

        if current_section:
            content.append(f"{current_section} - {l}")
        else:
            content.append(l)

    return content


def ensure_string(value: object) -> str:
    if isinstance(value, list):
        return " ".join(map(str, value))
    return str(value or "")