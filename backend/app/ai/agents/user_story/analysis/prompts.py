ANALYSIS_PROMPT = """You are a Product Owner. Evaluate this user story against INVEST criteria.
 
LANGUAGE RULE: The story is written in {language}. You MUST write ALL output (justification, issues, suggestions) in {language}. No exceptions.
 
RULES: Only analyze. Do NOT rewrite, generate AC, or change scope.
 
CONTEXT: {context}
 
STORY: {story}
 
Score using INVEST (Independent, Negotiable, Valuable, Estimable, Small, Testable):
- 1.0 = all criteria met, clear role/action/benefit
- 0.8 = 4-5 criteria met, minor gaps
- 0.6 = 3-4 criteria met, noticeable gaps
- 0.4 = 2-3 criteria met, major problems
- 0.2 = 1-2 criteria met
- 0.0 = invalid story
 
If story has clear role/action/benefit and is testable → score ≥ 0.9, suggestions must be [].
 
Return ONLY this JSON, nothing else:
{{"llm_score": float, "llm_issues": ["which INVEST criteria failed"], "llm_suggestions": ["improvement if score < 0.9"], "justification": "why this score"}}"""
 