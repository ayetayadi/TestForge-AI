import datetime
from app.utils.common.ac_utils import normalize_ac
import re

def parse_date(date_str):
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except:
        return None

def map_jira_issue(issue: dict) -> dict:    
    description = issue.get("description", "")

    # AC extraction
    ac_list = extract_acceptance_criteria(description)
    if not ac_list:
        ac_list = extract_implicit_ac(description)

    return {
        "issue_key": issue.get("key"),

        # contenu
        "title": issue.get("summary", ""),
        "description": description,
        "acceptance_criteria": normalize_ac(ac_list),

        # metadata
        "issue_type": issue.get("issue_type"),
        "priority": issue.get("priority"),
        "status": issue.get("status"),
        "story_points": issue.get("story_points"),

        # people
        "assignee": issue.get("assignee"),
        "reporter": issue.get("reporter"),

        # agile
        "epic_key": issue.get("epic"),
        "epic_name": issue.get("epic"),
        "sprint": issue.get("sprint"),
        "labels": issue.get("labels", []),
        "components": issue.get("components", []),

        # versioning
        "fix_version": (
            issue.get("fix_versions")[0]
            if issue.get("fix_versions") else None
        ),

        # dates
        "jira_created_at": parse_date(issue.get("created")),
        "jira_updated_at": parse_date(issue.get("updated")),
    }
    
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