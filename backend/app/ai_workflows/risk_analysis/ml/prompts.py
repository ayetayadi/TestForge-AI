"""
Prompts LLM pour l'analyse de risque.
"""

RBT_EXPLANATION_PROMPT = """You are a risk-based testing expert. A user story has been analyzed and received the following scores:

- Probability of failure (P): {probability}/5
- Impact if it fails (I): {impact}/5
- Risk Score: {risk_score}/25
- Priority: {priority}

User Story:
{user_story}

Acceptance Criteria:
{acceptance_criteria}

Based on these scores, provide:
1. A concise description of the risk (2-3 sentences)
2. Concrete mitigation strategy: describe which END-TO-END (E2E) test scenarios
   to automate to cover this risk. The project ONLY runs automated E2E tests
   (executed via Playwright) — do NOT mention unit, integration, load, or manual
   tests. Express the mitigation as the critical user journeys and edge cases to
   cover by E2E tests.
3. Brief reasoning explaining why P={probability} and I={impact}
4. probability_factors: rate each sub-factor 1-5 — story_complexity, ac_complexity, dependencies, clarity
5. impact_factors: rate each sub-factor 1-5 — users_affected, revenue, safety, reputation
6. probability_reasoning: one sentence justifying the probability factors
7. impact_reasoning: one sentence justifying the impact factors

The scores P={probability} and I={impact} are fixed (predicted by a model); your factor
ratings must be consistent with them. Respond in the same language as the user story."""

RISK_ANALYSIS_PROMPT_FALLBACK = """You are a risk-based testing expert. Analyze this user story and estimate:
- probability (1=very low, 5=very high chance of defect)
- impact (1=negligible, 5=critical business impact)

User Story: {story}

Acceptance Criteria:
{acceptance_criteria}

Return only probability and impact as integers 1-5."""
