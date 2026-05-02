"""
LLM prompt for ISTQB risk analysis — Easy English version.
"""

RISK_ANALYSIS_PROMPT = """You are a test manager. You analyze risks in user stories.

For each story, give two numbers:
- P (Probability): How likely is a bug in this story? (0.1 = very unlikely → 0.9 = almost certain)
- I (Impact): How bad if the bug reaches users? (1 = small problem → 5 = very serious)

USER STORY:
{story}

ACCEPTANCE CRITERIA:
{acceptance_criteria}

JIRA CONTEXT:
- Issue key : {issue_key}
- Priority  : {jira_priority}
- Story points: {story_points}
- Components: {components}
- Labels    : {labels}
- Epic      : {epic}

WHEN TO INCREASE PROBABILITY (P):
  • The feature has complex logic
  • There are many acceptance criteria
  • It involves login, payments, or user data
  • Story points are high (8 or more)
  • Many components work together
  • Jira priority is High or Critical
  • This is a new feature (never tested before)

WHEN TO INCREASE IMPACT (I):
  • All users need this feature
  • A bug could lose data or money
  • A bug could break security
  • There is no backup plan if it fails
  • It blocks other features from working

RULES:
- P must be a number between 0.1 and 0.9 (like 0.3, 0.6, 0.8)
- I must be a whole number between 1 and 5

- description: One short sentence. Simple words. Maximum 15 words.
  Say what can go wrong.
  Good example: "Weak login may let hackers access user accounts."
  Good example: "Wrong price may cause company to lose money."
  Bad example: "The implementation of the authentication mechanism..." (too long)

- mitigation: One short sentence. Maximum 12 words. Start with an action word.
  Say how to test it.
  Good example: "Test login with correct, wrong, and empty passwords."
  Good example: "Test price with discounts, taxes, and large orders."
  Bad example: "Perform thorough testing of the authentication workflow..." (too long)

- reasoning: Exactly 3 short bullet points. One sentence each.
  Bullet 1: Why this P?
  Bullet 2: Why this I?
  Bullet 3: The calculation result.
  
  Example:
  • P=0.6 because there are many validation rules and conditions
  • I=3 because wrong price loses money but there is a manual fix
  • Score = 0.6 × 3 = 1.80 (MEDIUM)
"""