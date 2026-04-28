from datetime import datetime
import json
import re
from typing import List, Union, Tuple

from app.utils.story_utils import extract_ac_lines, remove_emojis


# =========================================================
# DATE
# =========================================================
def parse_date(date_str):
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except Exception:
        return None


# =========================================================
# SPLIT DESCRIPTION / AC (NO LOSS)
# =========================================================
def split_description_and_ac(text: str) -> Tuple[str, List[str]]:
    """
    Sépare description et AC sans supprimer de contenu.
    """
    if not text:
        return "", []

    parts = re.split(
        r"(crit[èe]res?\s+d['’]acceptation\s*:?\s*|acceptance\s+criteria\s*:?\s*)",
        text,
        flags=re.IGNORECASE
    )

    if len(parts) >= 3:
        description = parts[0].strip()
        ac_block = parts[2].strip()

        ac_lines = extract_ac_lines(ac_block)
        return description, ac_lines

    return text.strip(), []


# =========================================================
# PARSE AC FIELD (NO LOSS)
# =========================================================
def parse_ac_field(ac_field) -> Union[List[str], None]:
    if not ac_field:
        return None

    if isinstance(ac_field, list):
        return ac_field

    if isinstance(ac_field, str):
        try:
            fixed = ac_field.replace('""', '"')
            parsed = json.loads(fixed)

            if isinstance(parsed, list):
                return parsed

            return [str(parsed)]

        except Exception:
            return [ac_field]

    return None


# =========================================================
# CLEAN AC (SYNTAX ONLY — NO DELETION)
# =========================================================
def clean_ac_list(ac_list: List[str]) -> List[str]:
    cleaned = []

    for ac in ac_list:
        if ac is None:
            continue

        ac = remove_emojis(ac)

        # supprimer uniquement les headers techniques
        ac = re.sub(
            r"(crit[èe]res?\s+d['’]acceptation\s*:?\s*|acceptance\s+criteria\s*:?\s*)",
            "",
            ac,
            flags=re.IGNORECASE
        )

        # nettoyer bullets uniquement (structure)
        ac = ac.lstrip("-*• ").strip()

        # normaliser espaces
        ac = re.sub(r"\s+", " ", ac).strip()

        # ❗ ON GARDE TOUT LE CONTENU
        cleaned.append(ac)

    return cleaned


# =========================================================
# ADF → TEXT
# =========================================================
def extract_text_from_adf(adf):

    if not adf or "content" not in adf:
        return ""

    lines = []

    def walk(node):
        if isinstance(node, dict):

            node_type = node.get("type")

            if node_type == "text":
                return node.get("text", "") + " "

            elif node_type in ["paragraph", "heading"]:
                content = "".join(walk(child) for child in node.get("content", []))
                if content.strip():
                    lines.append(content.strip())

            elif node_type == "bulletList":
                for item in node.get("content", []):
                    walk(item)

            elif node_type == "listItem":
                content = "".join(walk(child) for child in node.get("content", []))
                if content.strip():
                    lines.append(f"- {content.strip()}")

            else:
                for child in node.get("content", []):
                    walk(child)

        elif isinstance(node, list):
            for item in node:
                walk(item)

        return ""

    walk(adf)

    return "\n".join(lines)


# =========================================================
# MAIN MAPPING (IMPORT CLEAN)
# =========================================================
def map_jira_issue(issue: dict) -> dict:
    # =========================
    # RAW
    # =========================
    raw_description = issue.get("description", "")
    if isinstance(raw_description, dict):
        raw_description = extract_text_from_adf(raw_description)

    raw_title = issue.get("summary", "")
    raw_ac_field = issue.get("acceptance_criteria")

    # =========================
    # CLEAN BASIC
    # =========================
    title = remove_emojis(raw_title or "").strip()
    description_clean = remove_emojis(raw_description or "").strip()

    # =========================
    # SPLIT DESCRIPTION / AC
    # =========================
    description, ac_from_description = split_description_and_ac(description_clean)

    # =========================
    # PARSE AC FIELD
    # =========================
    parsed_ac_field = parse_ac_field(raw_ac_field)

    ac_list: List[str] = []

    if isinstance(parsed_ac_field, list):
        ac_list.extend(parsed_ac_field)

    elif isinstance(parsed_ac_field, str):
        ac_list.extend(extract_ac_lines(parsed_ac_field))

    # ajouter AC depuis description
    if ac_from_description:
        ac_list.extend(ac_from_description)

    # =========================
    # CLEAN AC (NO LOSS)
    # =========================
    cleaned_ac = clean_ac_list(ac_list)

    # =========================
    # FINAL
    # =========================
    return {
        "issue_key": issue.get("key"),

        "title": title,
        "description": description,
        "acceptance_criteria": cleaned_ac,

        "issue_type": issue.get("issue_type"),
        "priority": issue.get("priority"),
        "status": issue.get("status"),
        "story_points": issue.get("story_points"),

        "assignee": issue.get("assignee"),
        "reporter": issue.get("reporter"),

        "epic_key": issue.get("epic"),
        "epic_name": issue.get("epic_name"),
        "sprint": issue.get("sprint"),

        "labels": issue.get("labels", []),
        "components": issue.get("components", []),

        "fix_version": (
            issue.get("fix_versions")[0]
            if issue.get("fix_versions") else None
        ),

        "jira_created_at": parse_date(issue.get("created")),
        "jira_updated_at": parse_date(issue.get("updated")),
    }