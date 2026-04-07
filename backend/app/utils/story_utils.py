import re
from dataclasses import dataclass
from typing import Optional, List, Union
from bs4 import BeautifulSoup


AC_MARKERS = [
    r"crit[eè]res?\s+d['’]acceptation\s*:?",
    r"acceptance\s+criteria\s*:?",
    r"conditions?\s+d['’]acceptation\s*:?",
    r"\bac\s*:",
]

AC_PATTERN = re.compile("|".join(AC_MARKERS), flags=re.IGNORECASE)

def clean_html(text: str) -> str:
    if not text:
        return ""

    soup = BeautifulSoup(text, "html.parser")

    for br in soup.find_all("br"):
        br.replace_with("\n")

    return soup.get_text("\n")


def extract_ac_from_html(text: str):
    if not text:
        return []

    soup = BeautifulSoup(text, "html.parser")

    ac_list = []
    current_section = None

    # LIST ITEMS
    for li in soup.find_all("li"):
        content = li.get_text(" ", strip=True)
        if content:
            ac_list.append(content)

    # PARAGRAPHS
    for p in soup.find_all("p"):
        content = p.get_text(" ", strip=True)

        if not content:
            continue

        if ":" in content and len(content.split()) < 5:
            current_section = content.replace(":", "")
            continue

        if current_section:
            ac_list.append(f"{current_section} - {content}")
        else:
            ac_list.append(content)

    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if cells:
                ac_list.append(" | ".join(cells))

    ac_list = [re.sub(r"\s+", " ", a).strip() for a in ac_list if a.strip()]

    return ac_list

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

EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\u2700-\u27BF"
    "\u2600-\u26FF"
    "]+",
    flags=re.UNICODE
)

def remove_emojis(text: Union[str, List[str], None]) -> Union[str, List[str], None]:
    if text is None:
        return None

    # 🔥 cas liste (CRITIQUE pour tes AC)
    if isinstance(text, list):
        return [remove_emojis(t) for t in text if t]

    # 🔥 sécurité type
    if not isinstance(text, str):
        return text

    return EMOJI_PATTERN.sub("", text)