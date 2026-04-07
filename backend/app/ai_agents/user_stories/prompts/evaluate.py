EVALUATE_PROMPT = """
You are a Product Owner re-evaluating a user story AFTER refinement.

LANGUAGE RULE: The story is written in {language}. You MUST write ALL output in {language}.

PREVIOUS SCORE: {previous_score}
PREVIOUS ISSUES:
{previous_issues}

CURRENT STORY:
{story}

TASK:
- Re-evaluate using INVEST criteria
- Compare with previous evaluation
- Identify improvements and remaining gaps

SCORING RULES:
- 1.0 = perfect INVEST
- 0.8 = minor gaps
- 0.6 = moderate issues
- 0.4 = major issues
- 0.2 = weak
- 0.0 = invalid

IMPORTANT:
- Focus on what improved vs what remains
- Do NOT invent new features
- Do NOT rewrite the story

Return ONLY JSON:
{{
  "llm_score": float,
  "llm_issues": [],
  "llm_suggestions": [],
  "justification": "include comparison with previous"
}}
"""