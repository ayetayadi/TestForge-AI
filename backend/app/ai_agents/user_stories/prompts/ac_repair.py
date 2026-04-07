AC_REPAIR_PROMPT = """Rewrite acceptance criteria to be testable. Keep same feature and intent.
 
CRITICAL: Write ALL acceptance criteria in {language}. No other language allowed.
 
STORY: {story}
 
EXISTING AC TO REPAIR: {ac}
 
RULES:
- Each AC must test what the STORY describes — not a related or opposite feature.
- If the story is about logout, ACs must be about logout. Not login.
- If the story is about export, ACs must be about export. Not import.
- Preserve the TOPICS of the existing AC. Improve wording only.
 
Each AC must be:
- Written in {language}
- A string with: clear condition (when/if) + observable result + measurable element when possible
- No vague terms. No new functionality.
 
Return ONLY this JSON, nothing else:
{{"acceptance_criteria": ["testable AC in {language}", "testable AC in {language}"]}}"""
