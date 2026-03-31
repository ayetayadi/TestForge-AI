from datetime import datetime
from app.utils.common.ac_utils import normalize_ac
import re


def map_jira_issue(issue):
    fields = issue.get("fields", {})

    description_adf = fields.get("description")
    description = extract_text_from_adf(description_adf)

    # AC extraction
    ac_list = extract_acceptance_criteria(description)
    if not ac_list:
        ac_list = extract_implicit_ac(description)

    # Sprint (nested object)
    sprint_field = fields.get("sprint")
    sprint_name = None
    if isinstance(sprint_field, dict):
        sprint_name = sprint_field.get("name")
    elif isinstance(sprint_field, list) and sprint_field:
        sprint_name = sprint_field[-1].get("name") if isinstance(sprint_field[-1], dict) else str(sprint_field[-1])

    # Fix version
    fix_versions = fields.get("fixVersions") or []
    fix_version = fix_versions[0].get("name") if fix_versions else None

    # Epic
    epic_key = fields.get("epic", {}).get("key") if isinstance(fields.get("epic"), dict) else fields.get("customfield_10014")
    epic_name = fields.get("epic", {}).get("name") if isinstance(fields.get("epic"), dict) else fields.get("customfield_10015")

    # Components
    components = [c.get("name") for c in (fields.get("components") or []) if c.get("name")]

    # Labels
    labels = fields.get("labels") or []

    # Dates
    jira_created = _parse_jira_date(fields.get("created"))
    jira_updated = _parse_jira_date(fields.get("updated"))

    return {
        "issue_key": issue.get("key"),
        "title": fields.get("summary", ""),
        "description": description,
        "acceptance_criteria": normalize_ac(ac_list),

        # Metadata
        "issue_type": (fields.get("issuetype") or {}).get("name"),
        "priority": (fields.get("priority") or {}).get("name"),
        "status": (fields.get("status") or {}).get("name"),
        "story_points": fields.get("story_points") or fields.get("customfield_10028"),

        # People
        "assignee": (fields.get("assignee") or {}).get("displayName"),
        "reporter": (fields.get("reporter") or {}).get("displayName"),

        # Agile
        "epic_key": epic_key,
        "epic_name": epic_name,
        "sprint": sprint_name,
        "labels": labels,
        "components": components,

        # Versioning
        "fix_version": fix_version,

        # Dates
        "jira_created_at": jira_created,
        "jira_updated_at": jira_updated,
    }


def _parse_jira_date(date_str):
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    
# ─────────────────────────────────────────
# ADF → TEXT
# ─────────────────────────────────────────
def extract_text_from_adf(adf):

    if not adf or "content" not in adf:
        return ""

    lines = []

    def walk(node):

        if isinstance(node, dict):

            node_type = node.get("type")

            # TEXT (IMPORTANT → espace ajouté)
            if node_type == "text":
                return node.get("text", "") + " "

            # PARAGRAPH / HEADING
            elif node_type in ["paragraph", "heading"]:
                content = "".join(walk(child) for child in node.get("content", []))
                if content.strip():
                    lines.append(content.strip())

            # BULLET LIST
            elif node_type == "bulletList":
                for item in node.get("content", []):
                    walk(item)

            # LIST ITEM
            elif node_type == "listItem":
                content = "".join(walk(child) for child in node.get("content", []))
                if content.strip():
                    lines.append(f"- {content.strip()}")

            # AUTRES CAS
            else:
                for child in node.get("content", []):
                    walk(child)

        elif isinstance(node, list):
            for item in node:
                walk(item)

        return ""

    walk(adf)

    return "\n".join(lines)

# ─────────────────────────────────────────
# EXTRACTION AC (EXPLICITE)
# ─────────────────────────────────────────

AC_SECTION_KEYWORDS = [
    "acceptance criteria",
    "acceptance",
    "criteria",
    "ac",
    "critère d'acceptation",
    "critères",
    "conditions",
    "definition of done",
    "done criteria",
    "success criteria"
]

def extract_implicit_ac(text):
    if not text:
        return []

    lines = text.split("\n")
    patterns = ["doit", "must", "should", "shall"]
    ac = []

    for line in lines:
        if any(p in line.lower() for p in patterns):
            ac.append(line.strip())

    return ac[:5]

def extract_acceptance_criteria(text):
    if not text:
        return []

    lines = text.split("\n")
    ac = []
    capture = False

    for line in lines:
        clean = line.strip()
        lower = clean.lower()

        # 1. detect section header
        if any(k in lower.replace(":", "").replace("✅", "").strip() for k in AC_SECTION_KEYWORDS):
            capture = True
            continue

        if capture:
            if not clean:
                break

            # bullet
            if clean.startswith(("-", "*", "•")):
                ac.append(clean[1:].strip())
                continue

            # numbered
            if re.match(r"^\d+[\.\)]\s+", clean):
                ac.append(re.sub(r"^\d+[\.\)]\s+", "", clean))
                continue

            # given/when/then
            if lower.startswith(("given", "when", "then", "and")):
                ac.append(clean)
                continue

            # semicolon split
            if ";" in clean:
                ac.extend([p.strip() for p in clean.split(";") if p.strip()])
                continue

            # catch-all: any non-empty line in the AC section
            ac.append(clean)

    if not ac:
        ac = extract_implicit_ac(text)

    return ac