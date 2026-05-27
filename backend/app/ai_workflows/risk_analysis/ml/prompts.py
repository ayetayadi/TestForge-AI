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
2. Concrete mitigation strategies (testing approaches)
3. Brief reasoning explaining why P={probability} and I={impact}

Respond in the same language as the user story."""

RISK_ANALYSIS_PROMPT_FALLBACK = """You are a risk-based testing expert. Analyze this user story and estimate:
- probability (1=very low, 5=very high chance of defect)
- impact (1=negligible, 5=critical business impact)

User Story: {story}

Acceptance Criteria:
{acceptance_criteria}

Return only probability and impact as integers 1-5."""
