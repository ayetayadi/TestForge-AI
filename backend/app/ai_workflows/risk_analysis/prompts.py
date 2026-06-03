"""
Compact ISTQB risk prompt — optimized for structured output with Groq.

Token budget:
  - Template ≈ 200 tokens
  - Story + ACs ≈ 150-400 tokens (variable)
  - Output ≈ 150-300 tokens (flat ints + two short strings per scenario)
  Total: well within 800 max_tokens.

P = round(avg(story_complexity, ac_complexity, dependencies, clarity))
I = round(avg(users_affected, revenue, safety, reputation))
Computed in Python — LLM only provides the raw 1-5 ratings.
"""

RISK_ANALYSIS_PROMPT = """You are a QA risk analyst. Identify 1-2 DISTINCT risk scenarios for this user story.

STORY: {story}

ACCEPTANCE CRITERIA:
{acceptance_criteria}

Rate each factor 1-5 (use the FULL range — not everything is a 3):
Probability factors:
  story_complexity : 1=trivial CRUD  3=some rules  5=complex logic
  ac_complexity    : 1=1-2 simple ACs  3=3-5 detailed  5=6+ with edge cases
  dependencies     : 1=standalone  3=one system  5=many systems
  clarity          : 1=crystal clear  3=some vague terms  5=unclear/missing

Impact factors:
  users_affected : 1=admin only  3=department  5=all users
  revenue        : 1=no impact  3=indirect  5=direct money
  safety         : 1=cosmetic  3=data loss risk  5=security breach
  reputation     : 1=internal  3=some clients  5=public

description : what fails and when — specific, ≤20 words
mitigation  : verb + what to test — specific, ≤15 words

Rules:
- 1 scenario for simple stories, 2 for complex ones with independent risks
- Each scenario must be a DIFFERENT type of failure (not the same risk rephrased)
- Scenarios like "Payment fails" and "Checkout broken" are NOT distinct — pick one
"""
