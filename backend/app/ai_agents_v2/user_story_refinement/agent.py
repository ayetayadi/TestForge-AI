# ============================================================
# ai_agents_v2/user_story/agent.py (FINAL - AVEC INITIAL SCORE)
# ============================================================

import logging
import json
from typing import Dict, Any, List

from langgraph.prebuilt import create_react_agent
from langsmith import traceable

from app.llm.llm_control import create_llm
from app.ai_agents_v2.user_story_refinement.utils.debugger import create_debugger
from app.ai_agents_v2.user_story_refinement.utils.text_processing import clean_story_text, compare_similarity, extract_actor_from_story, is_improvement_valid, verify_language_consistency, verify_role_preserved
from .tools import TOOLS
from .prompts import SYSTEM_PROMPT, AGENT_INSTRUCTIONS
from .config import LLM_MODEL, LLM_TEMPERATURE

logger = logging.getLogger(__name__)


# ============================================================
# REACT AGENT CLASS
# ============================================================
class UserStoryReActAgent:
    """
    ReAct Agent for User Story Improvement using OpenRouter.
    """
    
    def __init__(self, temperature: float = LLM_TEMPERATURE):
        logger.info("Initializing ReAct Agent...")
        
        self.llm = create_llm(temperature=temperature)
        
        self.graph = create_react_agent(
            model=self.llm,
            tools=TOOLS,
            prompt=SYSTEM_PROMPT,
        )
        
        logger.info("✓ ReAct Agent initialized successfully")
        logger.info(f"  - Tools: {len(TOOLS)}")

    @traceable(name="user_story_react_agent")
    async def run(
        self,
        story: str,
        acceptance_criteria: List[str] = None,
        language: str = "en",
        jira_id: str = "?"
    ) -> Dict[str, Any]:
        """Execute the ReAct Agent on a user story."""
        
        acceptance_criteria = acceptance_criteria or []
        debugger = create_debugger(jira_id)
        debugger.log_input(story, acceptance_criteria, language)
        
        print(f"\n{'='*80}")
        print(f"[🚀 ReAct Agent] Starting Story Improvement")
        print(f"{'='*80}")
        print(f"[INFO] Jira ID: {jira_id}")
        print(f"[INFO] Input Story: {story[:100]}...")
        print(f"[INFO] Input AC: {len(acceptance_criteria)} items")
        print(f"{'='*80}\n")
        
        logger.info(f"Agent starting for {jira_id}")
        
        original_actor = None
        
        try:
            # Clean story
            clean_story = clean_story_text(story)
            original_actor = extract_actor_from_story(clean_story)
            logger.info(f"✓ Story cleaned, actor: {original_actor}")
            
            # Build agent message
            user_message = AGENT_INSTRUCTIONS.format(
                story=clean_story,
                acceptance_criteria=(
                    "\n".join(f"- {ac}" for ac in acceptance_criteria)
                    if acceptance_criteria
                    else "None"
                ),
            )
            
            inputs = {"messages": [("user", user_message)]}
            
            # Run agent
            logger.info("[STEP 3] Running ReAct Agent...")
            print(f"\n[🔄 AGENT] Invoking ReAct Agent via OpenRouter\n")
            
            debugger.log_llm_call(
                messages=[("system", SYSTEM_PROMPT), ("user", user_message)],
                model=LLM_MODEL,
            )
            
            final_state = await self.graph.ainvoke(inputs)
            
            print(f"\n{'='*80}\n")
            
            # Debug tool calls
            messages = final_state.get("messages", [])
            for msg in messages:
                msg_type = type(msg).__name__
                if msg_type == "AIMessage":
                    debugger.log_llm_response(msg)
                elif hasattr(msg, "type") and msg.type == "tool":
                    tool_name = getattr(msg, "name", "unknown")
                    try:
                        result = json.loads(msg.content) if isinstance(msg.content, str) else msg.content
                        success = result.get("status") != "error"
                    except:
                        result = {"raw": str(msg.content)}
                        success = True
                    debugger.log_tool_result(tool_name, result, success)
            
            # Process result
            result = await self._process_agent_result(
                final_state,
                clean_story,
                acceptance_criteria,
                original_actor
            )
            
            result["jira_id"] = jira_id

            model_used = LLM_MODEL
            prompt_tokens = 0
            completion_tokens = 0

            # Si il ya accès aux métriques de l'API
            if hasattr(self.llm, 'last_usage'):
                prompt_tokens = self.llm.last_usage.get('prompt_tokens', 0)
                completion_tokens = self.llm.last_usage.get('completion_tokens', 0)
            
            # Print results
            print(f"{'='*80}")
            print(f"[✅ RESULT SUMMARY]")
            print(f"{'='*80}")
            print(f"[SCORE] Initial: {result.get('initial_score', 0.0):.3f}")
            print(f"[SCORE] Final: {result.get('final_score', 0.0):.3f}")
            print(f"[SCORE] Delta: {result.get('final_score', 0.0) - result.get('initial_score', 0.0):+.3f}")
            print(f"[SCORE] Testability: {result.get('testability_score', 0.0):.3f} ⭐ PRIMARY")
            print(f"[STATUS] Improved: {result.get('is_improved', False)}")
            print(f"[INFO] Iterations: {result.get('iterations', 0)}")
            print(f"[INFO] Prompt Tokens: {result.get('prompt_tokens', 0)}")
            print(f"[INFO] Completion Tokens: {result.get('completion_tokens', 0)}")
            print(f"{'='*80}\n")
            
            debugger.log_final_result(result)
            debugger.save()
            debugger.save_mermaid()
            
            return result
        
        except Exception as e:
            logger.error(f"Agent failed: {e}", exc_info=True)
            print(f"\n[❌ ERROR] {e}\n")
            
            debugger.log_error(e, {
                "jira_id": jira_id,
                "story_length": len(story),
                "ac_count": len(acceptance_criteria),
                "language": language
            })
            debugger.save()
            
            return {
                "improved_story": story,
                "acceptance_criteria": acceptance_criteria,
                "is_improved": False,
                "initial_score": 0.0,
                "final_score": 0.0,
                "testability_score": 0.0,
                "is_testable": False,
                "error": str(e),
                "iterations": 0,
                "valid": False,
                "similarity": 1.0,
                "language_consistent": False,
                "role_preserved": False,
                "original_actor": original_actor or "",
                "improved_actor": "",
                "agent_status": "error",
                "violations": [],
                "model_used": LLM_MODEL,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            }
    
    async def _process_agent_result(
        self,
        final_state: Dict,
        original_story: str,
        original_ac: List[str],
        original_actor: str
    ) -> Dict[str, Any]:
        """Process final agent result with validations."""
        
        logger.info("[PROCESS] Starting result processing...")
        
        messages = final_state.get("messages", [])
        if not messages:
            logger.warning("No messages in final state")
            return self._create_empty_result(original_story, original_ac, original_actor)
        
        last_message = messages[-1]
        response_text = (
            last_message.content
            if hasattr(last_message, "content")
            else str(last_message)
        )
        
        # Parse JSON
        improved_story = original_story
        acceptance_criteria = original_ac
        testability_issues_fixed = []
        violations = []
        agent_status = "unknown"
        
        try:
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            
            if json_start >= 0 and json_end > json_start:
                json_str = response_text[json_start:json_end]
                parsed_json = json.loads(json_str)
                
                improved_story = parsed_json.get("improved_story", original_story)
                acceptance_criteria = parsed_json.get("acceptance_criteria", original_ac)
                testability_issues_fixed = parsed_json.get("testability_issues_fixed", [])
                violations = parsed_json.get("violations", [])
                agent_status = parsed_json.get("status", "unknown")
                
                logger.info(f"✓ JSON parsed successfully")
        except json.JSONDecodeError as e:
            logger.warning(f"JSON decode error: {e}")
        
        # Validations
        is_valid = is_improvement_valid(original_story, improved_story, min_similarity=0.65)
        similarity = compare_similarity(original_story, improved_story)
        language_consistent = verify_language_consistency(original_story, improved_story)
        role_preserved = verify_role_preserved(original_story, improved_story)
        improved_actor = extract_actor_from_story(improved_story)
        
        logger.info(f"  ✓ Similarity: {similarity:.3f}")
        
        # ✅ Extraire scores INITIAL et FINAL
        initial_score, final_score, testability_score, is_testable, testability_issues, iterations = (
            self._extract_all_scores_from_tool_calls(final_state)
        )
        
        logger.info(f"  ✓ Initial Score: {initial_score:.3f}")
        logger.info(f"  ✓ Final Score: {final_score:.3f}")
        logger.info(f"  ✓ Delta: {final_score - initial_score:+.3f}")
        logger.info(f"  ✓ Testability: {testability_score:.3f}")
        logger.info(f"  ✓ Iterations: {iterations}")
        
        if violations:
            is_valid = False
            logger.warning(f"Violations reported: {violations}")
        
        is_improved = (
            (improved_story != original_story or acceptance_criteria != original_ac)
            and is_valid
            and language_consistent
            and role_preserved
        )
        
        logger.info(f"✓ Final decision: is_improved={is_improved}")
        
        return {
            "improved_story": improved_story or original_story,
            "acceptance_criteria": acceptance_criteria or original_ac,
            "is_improved": is_improved,
            "valid": is_valid,
            "score": round(final_score, 3),
            "initial_score": round(initial_score, 3),       # ✅ Score INITIAL
            "final_score": round(final_score, 3),           # ✅ Score FINAL
            "testability_score": round(testability_score, 3),
            "is_testable": is_testable,
            "testability_issues": testability_issues,
            "testability_issues_fixed": testability_issues_fixed,
            "similarity": round(similarity, 3),
            "language_consistent": language_consistent,
            "role_preserved": role_preserved,
            "original_actor": original_actor,
            "improved_actor": improved_actor,
            "iterations": iterations,
            "agent_status": agent_status,
            "violations": violations,
        }
    
    def _extract_all_scores_from_tool_calls(self, state: Dict) -> tuple:
        """
        Extract INITIAL and FINAL scores from tool calls across all iterations.

        Iterative refinement produces N score_story calls:
          - call 1        = initial score (before any improvement)
          - calls 2..N    = one score per improvement iteration

        Returns: (initial_score, final_score, testability_score, is_testable, testability_issues, iterations)
          where iterations = number of improvement cycles (= total score calls - 1)
        """
        messages = state.get("messages", [])
        
        initial_score = 0.0
        final_score = 0.0
        testability_score = 0.0
        is_testable = False
        testability_issues = []
        total_score_calls = 0

        score_results = []

        # Collect all score_story results in chronological order
        for msg in messages:
            if hasattr(msg, "type") and msg.type == "tool":
                if hasattr(msg, "name") and msg.name == "score_story":
                    try:
                        content = msg.content if hasattr(msg, "content") else str(msg)
                        result = json.loads(content) if isinstance(content, str) else content
                        score_results.append(result)
                    except Exception as e:
                        logger.warning(f"Failed to parse score_story result: {e}")
        
        total_score_calls = len(score_results)

        if total_score_calls == 0:
            return 0.0, 0.0, 0.0, False, [], 0

        # First call = initial evaluation (before any improvement)
        initial_score = float(score_results[0].get("final_score", 0.0))
        logger.info(f"✓ Initial score: {initial_score:.3f}")

        # Last call = best result after all improvement iterations
        last = score_results[-1]
        final_score = float(last.get("final_score", 0.0))
        testability_score = float(last.get("testability_score", 0.0))
        is_testable = last.get("is_testable", False)
        testability_issues = last.get("testability_issues", [])
        logger.info(f"✓ Final score: {final_score:.3f} after {total_score_calls - 1} improvement iteration(s)")

        # improvement iterations = total score calls minus the initial evaluation
        improvement_iterations = max(0, total_score_calls - 1)

        return initial_score, final_score, testability_score, is_testable, testability_issues, improvement_iterations
    
    def _create_empty_result(self, story: str, ac: List[str], actor: str) -> Dict[str, Any]:
        """Create empty result for error cases"""
        return {
            "improved_story": story,
            "acceptance_criteria": ac,
            "is_improved": False,
            "initial_score": 0.0,
            "final_score": 0.0,
            "testability_score": 0.0,
            "is_testable": False,
            "testability_issues": [],
            "testability_issues_fixed": [],
            "valid": False,
            "similarity": 1.0,
            "language_consistent": False,
            "role_preserved": False,
            "original_actor": actor,
            "improved_actor": "",
            "iterations": 0,
            "agent_status": "error",
            "violations": [],
        }


# ============================================================
# SINGLETON
# ============================================================

_agent_instance = None


def get_agent(temperature: float = LLM_TEMPERATURE) -> UserStoryReActAgent:
    """Get or create singleton agent instance"""
    global _agent_instance
    
    if _agent_instance is None:
        logger.info("Creating agent singleton...")
        _agent_instance = UserStoryReActAgent(temperature=temperature)
        logger.info("✓ Agent singleton created")
    
    return _agent_instance


def reset_agent():
    """Reset singleton"""
    global _agent_instance
    _agent_instance = None
    logger.info("Agent singleton reset")