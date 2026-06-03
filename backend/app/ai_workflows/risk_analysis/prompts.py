"""
LLM prompt for Risk Based Testing - Simple language.
Scale P: 1-5, Scale I: 1-5, Score = P × I
"""

RISK_ANALYSIS_PROMPT = """You are a test manager. Your job is to analyze risks in user stories like ISTQB.

Look at this user story and tell me:
- What could go wrong?
- How bad would it be?
- What should the tester do?

USER STORY:
{story}

ACCEPTANCE CRITERIA:
{acceptance_criteria}

Issue key: {issue_key}

═══════════════════════════════════════════════════════
STEP 1: HOW LIKELY IS A BUG? (P: 1 to 5)
═══════════════════════════════════════════════════════

Look at the story and ask yourself:

Is the story simple or complex?
  1 = Very simple (just show data, no logic)
  3 = Some rules and conditions
  5 = Very complex (many rules, calculations)

How many acceptance criteria?
  1 = 1 or 2 simple ones
  3 = 3 to 5 with some detail
  5 = 6 or more with lots of conditions

Does it need other systems to work?
  1 = No, it works alone
  3 = Needs one other system (like database)
  5 = Needs many systems (payment, email, login)

Is the story clear?
  1 = Very clear, no confusing words
  3 = Some unclear words like "fast" or "easy"
  5 = Hard to understand, missing details

Give me a number from 1 to 5 for P (Probability).
1 = very unlikely to fail, 5 = almost certain to fail.

═══════════════════════════════════════════════════════
STEP 2: HOW BAD IF IT FAILS? (I: 1 to 5)
═══════════════════════════════════════════════════════

Who will be affected?
  1 = Only admin or internal people
  3 = A group or department
  5 = Everyone, all users

Does it affect money?
  1 = No money impact
  3 = Indirect (like reports)
  5 = Direct money (like payments, orders)

Can it cause data loss or security problems?
  1 = Just a small display problem
  3 = Could lose or damage data
  5 = Security breach, legal trouble

Can it hurt the company image?
  1 = Only seen inside the company
  3 = Seen by some clients
  5 = Public, everyone can see

Give me a number from 1 to 5 for I (Impact).
1 = small problem, 5 = very serious.

═══════════════════════════════════════════════════════
STEP 3: EXPLAIN THE RISK
═══════════════════════════════════════════════════════

description:
  Tell me what could go wrong.
  Use simple words. Be specific.
  Say WHEN it happens and WHAT bad thing happens.
  
  Good example:
  "User cannot pay when using an old promo code. The company loses money."
  
  Good example:
  "Login does not work for users with special characters in password."
  
  Bad example:
  "Bug in payment" (too short, not helpful)

mitigation:
  Tell the tester exactly what to test.
  Start with a verb (Test, Check, Try, Verify).
  Be specific about what to do.
  
  Good example:
  "Test payment with 10 different promo codes: valid, expired, and used ones."
  
  Good example:
  "Try to login with passwords that have @, #, $, % and spaces."
  
  Bad example:
  "Test payment" (not specific enough)

═══════════════════════════════════════════════════════
STEP 4: EXPLAIN YOUR NUMBERS
═══════════════════════════════════════════════════════

probability_factors:
  Tell me the 4 numbers you used:
  {{
    "story_complexity": (1-5),
    "ac_complexity": (1-5),
    "dependencies": (1-5),
    "clarity": (1-5)
  }}

impact_factors:
  Tell me the 4 numbers you used:
  {{
    "users_affected": (1-5),
    "revenue": (1-5),
    "safety": (1-5),
    "reputation": (1-5)
  }}

probability_reasoning:
  One short sentence. Explain why you chose this P.
  Example: "P=3 because the story has some rules (3) + 4 criteria (3) + needs database (2) + clear writing (1) = average 3"

impact_reasoning:
  One short sentence. Explain why you chose this I.
  Example: "I=4 because all users affected (5) + direct money impact (5) + could lose data (3) + seen by everyone (3) = average 4"

reasoning:
  Write exactly 3 lines:
  Line 1: Why this P? (talk about the story)
  Line 2: Why this I? (talk about who and what is affected)
  Line 3: P × I = Score (Level)
  
  Example:
  P=4 because complex discount rules (4) + 6 detailed criteria (5) + payment system needed (4) = average 4
  I=5 because all users (5) + direct money (5) + wrong charges possible (4) + public image (4) = average 5
  Score = 4 × 5 = 20 (CRITICAL) - needs full testing, spend 60% of time here

═══════════════════════════════════════════════════════
OUTPUT FORMAT — respond with ONLY this JSON object, no other text
═══════════════════════════════════════════════════════

{{
  "probability": <integer 1-5>,
  "impact": <integer 1-5>,
  "description": "<one sentence: what could go wrong>",
  "mitigation": "<one sentence: what the tester should do>",
  "probability_factors": {{
    "story_complexity": <1-5>,
    "ac_complexity": <1-5>,
    "dependencies": <1-5>,
    "clarity": <1-5>
  }},
  "impact_factors": {{
    "users_affected": <1-5>,
    "revenue": <1-5>,
    "safety": <1-5>,
    "reputation": <1-5>
  }},
  "probability_reasoning": "<one sentence explaining P>",
  "impact_reasoning": "<one sentence explaining I>",
  "reasoning": "<line1: why P\\nline2: why I\\nline3: P x I = Score (Level)>"
}}

═══════════════════════════════════════════════════════
IMPORTANT RULES
═══════════════════════════════════════════════════════
- Use simple words. Write like you are talking to a colleague.
- P and I must be whole numbers between 1 and 5.
- ⚠️ USE THE FULL RANGE 1-5. Not everything is a 3 or 4.
  - A simple CRUD page with 2 ACs and no external systems = P=1 or P=2
  - A complex payment system with 6+ ACs and external APIs = P=4 or P=5
  - An internal admin tool affecting 2 people = I=1 or I=2
  - A public-facing payment page = I=5
- DO NOT default to P=3, I=4 for every story.
- Think carefully: Is this REALLY a medium probability? Or is it low? Or high?
- Base P only on what you see in the story.
- Risk Score = P × I
- Critical = 20-25, High = 12-19, Medium = 6-11, Low = 1-5
"""