"""
Test Suite Organization Pipeline.

4 steps:
  1. group(test_cases, strategy)  → divide test cases into logical groups
  2. LLM call                     → generate professional titles and descriptions
  3. compute_coverage             → calculate Risk Coverage for the TestSuite
  4. finalize(suites)             → assign execution_order, build records
"""

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

from langsmith import traceable
from pydantic import BaseModel, Field

from app.ai_workflows.test_suite.suite_organizer import (
    group_by_test_type,
    assign_suite_order,
    build_suite_record,
)
from app.ai_workflows.test_suite.test_suite_coverage import (
    compute_suite_coverage,
)
from app.ai_workflows.test_suite.prompts import BUSINESS_FLOW_ORDERING_PROMPT, TEST_SUITE_NAMING_PROMPT
from app.llm.llm_control import create_llm
from .config import (
    LLM_TEMPERATURE, LLM_MODEL, LLM_MAX_TOKENS, LLM_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)


# ============================================================
# LLM OUTPUT SCHEMAS
# ============================================================

class SuiteNameOutput(BaseModel):
    """Schéma pour le naming des suites."""
    group_key: str = Field(description="The group key this name applies to")
    title: str = Field(description="Professional suite title, max 80 chars")
    description: str = Field(description="1-2 sentences describing the suite purpose")
    suite_type: str = Field(description="postive | negative | boundary | feature")
    priority: str = Field(description="critical | high | medium | low")


class SuiteNamingBatch(BaseModel):
    """Batch de noms de suites."""
    suites: List[SuiteNameOutput] = Field(description="One entry per group")


class FlowOrderItem(BaseModel):
    """Un flux métier avec son rang et sa raison."""
    flow: str = Field(description="Business flow name (authentication, dashboard, crud, etc.)")
    rank: int = Field(description="Execution rank (1 = first, higher = later)")
    reason: str = Field(description="Why this flow has this rank in THIS project")


class TCClassification(BaseModel):
    """Classification d'un TC par le LLM."""
    tc_code: str = Field(description="Test case code (e.g., TC-001)")
    business_flow: str = Field(description="Business flow determined by LLM")
    risk_level: str = Field(description="Risk level: critical | high | medium | low")
    reasoning: str = Field(description="Why this TC belongs to this flow and risk")


class FlowOrderItem(BaseModel):
    """Un flux métier avec son rang, raison et détails."""
    flow: str = Field(description="Business flow name")
    rank: int = Field(description="Execution rank (1 = first)")
    reason: str = Field(description="Why this flow has this rank in THIS project")
    tc_count: int = Field(default=0, description="Number of TCs in this flow")
    risk_breakdown: Dict[str, int] = Field(default_factory=dict, description="Risk distribution in this flow")


class BusinessFlowOrderingOutput(BaseModel):
    """Output complet du LLM : classification + ordering."""
    tc_classifications: List[TCClassification] = Field(
        default_factory=list,
        description="Classification of each test case"
    )
    flow_order: List[FlowOrderItem] = Field(
        default_factory=list,
        description="Ordered list of business flows"
    )
    reasoning: str = Field(
        default="",
        description="Overall reasoning for the determined order"
    )
    project_context_summary: str = Field(
        default="",
        description="Brief summary of project context analyzed"
    )

# ============================================================
# STRATEGY DISPATCHER
# ============================================================

_STRATEGY_MAP = {
    "test_type": group_by_test_type,
}

# ── Mots-clés pour la détection des flux ──
_FLOW_KEYWORDS: Dict[str, List[str]] = {
    "authentication": ["auth", "login", "token", "session", "password", "credential", "jwt", "oauth", "sso", "2fa"],
    "session_cleanup": ["logout", "logoff", "signout", "sign-out"],
    "dashboard": ["dashboard", "home", "overview", "landing", "display", "view", "welcome", "portal"],
    "crud": ["create", "update", "delete", "edit", "add", "remove", "save", "crud", "form", "submit"],
    "search": ["search", "filter", "sort", "query", "find", "browse", "lookup"],
    "reporting": ["report", "export", "log", "audit", "analytics", "metrics", "statistics"],
    "error_handling": ["error", "invalid", "fail", "reject", "wrong", "validation", "message"],
    "monitoring": ["monitor", "health", "alert", "track", "activity", "logging"],
    "notifications": ["notification", "alert", "email", "message", "push", "reminder"],
    "settings": ["setting", "config", "preference", "profile", "account", "permission", "role"],
    "api": ["api", "endpoint", "swagger", "documentation", "rest", "curl", "integration"],
    "testing": ["test", "automated", "coverage", "ci/cd", "jest", "playwright", "pipeline"],
}


# ============================================================
# PIPELINE
# ============================================================
class TestSuitePipeline:
    def __init__(self, temperature: float = LLM_TEMPERATURE, model: str = LLM_MODEL):
        logger.info("[TEST SUITE] Initializing pipeline...")
        
        # LLM pour le naming des suites
        llm = create_llm(temperature=temperature, model=model, max_tokens=LLM_MAX_TOKENS)
        self._llm = llm.with_structured_output(SuiteNamingBatch)
        
        # LLM pour l'ordering des flux métier
        ordering_llm = create_llm(temperature=0.2, model=model, max_tokens=2000)
        self._ordering_llm = ordering_llm.with_structured_output(BusinessFlowOrderingOutput)
        
        logger.info("[TEST SUITE] Ready")
    
    async def _emit(self, callback: Optional[Callable], event_type: str, data: dict) -> None:
        if callback is None:
            return
        try:
            await callback(event_type, data)
        except Exception:
            pass

    def _detect_flow_from_tc(self, tc: Dict) -> str:
        """Détecte le flux métier d'un TC dict basé sur les mots-clés."""
        text = " ".join([
            (tc.get("title", "") or "").lower()
        ])
        for flow, keywords in _FLOW_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                return flow
        return "other"
    
    def _get_default_flow_order(self) -> Dict[str, int]:
        """Fallback si le LLM échoue."""
        return {
            "authentication": 1, "authorization": 2, "crud": 3,
            "dashboard": 4, "search": 5, "error_handling": 6,
            "reporting": 7, "monitoring": 8, "notifications": 9,
            "settings": 10, "api": 11, "testing": 12, "other": 99,
        }
    
    def _get_default_classifications(self, test_cases: List[Dict]) -> Dict[str, Any]:
        """Fallback : classification par mots-clés."""
        tc_classifications = {}
        flow_order = self._get_default_flow_order()
        
        for tc in test_cases:
            flow = self._detect_flow_from_tc(tc)
            tc_classifications[tc["tc_code"]] = {
                "business_flow": flow,
                "risk_level": tc.get("priority", "medium"),
                "reasoning": "Auto-classified by keyword detection (LLM unavailable)",
            }
        
        # Construire flow_details
        flow_details = {}
        for tc_code, c in tc_classifications.items():
            flow = c["business_flow"]
            if flow not in flow_details:
                flow_details[flow] = {"tc_count": 0, "risk_breakdown": {}, "reason": "Default"}
            flow_details[flow]["tc_count"] += 1
            risk = c["risk_level"]
            flow_details[flow]["risk_breakdown"][risk] = flow_details[flow]["risk_breakdown"].get(risk, 0) + 1
        
        return {
            "tc_classifications": tc_classifications,
            "flow_order": flow_order,
            "flow_details": flow_details,
            "reasoning": "Default order (LLM unavailable)",
            "project_context_summary": "N/A",
        }
    
    async def _determine_business_flow_order(
        self,
        test_cases: List[Dict],
        user_stories: List[Dict],
        project_name: str
    ) -> Dict[str, Any]:
        """
        Le LLM classifie CHAQUE TC et détermine l'ordre des flux.
        
        Returns:
            {
                "tc_classifications": {tc_code: {flow, risk_level, reasoning}},
                "flow_order": {flow: rank},
                "flow_details": {flow: {tc_count, risk_breakdown}},
                "reasoning": str
            }
        """
        
        # ── Résumer pour le prompt ──
        us_with_tests = [u for u in user_stories if u.get('has_tests')]
        us_without_tests = [u for u in user_stories if not u.get('has_tests')]
        
        us_summary = "USER STORIES WITH TEST CASES:\n"
        us_summary += "\n".join(
            f"- {us.get('issue_key', '?')}: {us.get('title', '')[:120]}"
            for us in us_with_tests[:15]
        )
        
        if us_without_tests:
            us_summary += "\n\nUSER STORIES WITHOUT TEST CASES (for context):\n"
            us_summary += "\n".join(
                f"- {us.get('issue_key', '?')}: {us.get('title', '')[:120]}"
                for us in us_without_tests[:10]
            )
        
        # Lister TOUS les TCs avec leur code pour le LLM
        tc_summary = "\n".join(
            f"{i+1}. {tc.get('tc_code', '?')}: {tc.get('title', '')[:100]} "
            f"[type: {tc.get('test_type', '?')}, priority: {tc.get('priority', '?')}]"
            for i, tc in enumerate(test_cases)
        )
        
        prompt = BUSINESS_FLOW_ORDERING_PROMPT.format(
            project_name=project_name,
            user_stories_summary=us_summary,
            test_cases_summary=tc_summary,
        )
        
        try:
            result: BusinessFlowOrderingOutput = await self._ordering_llm.ainvoke(prompt)
            
            # ── Extraire les classifications par TC ──
            tc_classifications = {}
            for item in result.tc_classifications:
                tc_classifications[item.tc_code] = {
                    "business_flow": item.business_flow,
                    "risk_level": item.risk_level,
                    "reasoning": item.reasoning,
                }
            
            # ── Extraire l'ordre des flux ──
            flow_order = {}
            flow_details = {}
            for item in result.flow_order:
                flow_order[item.flow] = item.rank
                flow_details[item.flow] = {
                    "tc_count": item.tc_count,
                    "risk_breakdown": item.risk_breakdown,
                    "reason": item.reason,
                }
            
            # ── VÉRIFIER que tous les TCs sont classifiés ──
            all_tc_codes = {tc.get("tc_code") for tc in test_cases}
            classified_codes = set(tc_classifications.keys())
            missing = all_tc_codes - classified_codes
            
            if missing:
                logger.warning(f"[FLOW ORDER] LLM missed {len(missing)} TCs: {missing}")
                # Ajouter les TCs manquants avec "other"/"medium"
                for tc_code in missing:
                    tc_classifications[tc_code] = {
                        "business_flow": "other",
                        "risk_level": "medium",
                        "reasoning": "Auto-assigned (LLM missed this TC)",
                    }
                    logger.info(f"[FLOW ORDER] Auto-assigned {tc_code} → other/medium")
            
            # ── VÉRIFIER que tous les flux sont dans l'ordre ──
            all_flows = {c["business_flow"] for c in tc_classifications.values()}
            ordered_flows = set(flow_order.keys())
            missing_flows = all_flows - ordered_flows
            
            if missing_flows:
                logger.warning(f"[FLOW ORDER] LLM missed flows in order: {missing_flows}")
                next_rank = max(flow_order.values()) + 1 if flow_order else 99
                for flow in sorted(missing_flows):
                    flow_order[flow] = next_rank
                    flow_details[flow] = {
                        "tc_count": sum(1 for c in tc_classifications.values() if c["business_flow"] == flow),
                        "risk_breakdown": {},
                        "reason": "Auto-assigned (LLM missed this flow in order)",
                    }
                    next_rank += 1
            
            logger.info(f"[FLOW ORDER] Classified {len(tc_classifications)} TCs into {len(flow_order)} flows")
            logger.info(f"[FLOW ORDER] Flow order: {flow_order}")
            logger.info(f"[FLOW ORDER] Reasoning: {result.reasoning}")
            logger.info(f"[FLOW ORDER] Context: {result.project_context_summary}")
            
            return {
                "tc_classifications": tc_classifications,
                "flow_order": flow_order,
                "flow_details": flow_details,
                "reasoning": result.reasoning,
                "project_context_summary": result.project_context_summary,
            }
            
        except Exception as e:
            logger.warning(f"[FLOW ORDER] LLM failed: {e}")
            return self._get_default_classifications(test_cases)
    

    @traceable(name="test_suite_pipeline")
    async def run(
        self,
        test_cases: List[Dict[str, Any]],
        test_plan_id: str,
        project_name: str = "",
        strategy: str = "test_type",
        accepted_risk_ids: List[str] = None,
        progress_callback: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """
        Organise les TCs en suites par type de scénario: positive → negative → boundary.
        """
        strategy = "test_type"
        accepted_risk_ids = accepted_risk_ids or []
        
        logger.info(
            f"[TEST SUITE] Starting: plan={test_plan_id} "
            f"tc_count={len(test_cases)} strategy={strategy} "
            f"risks={len(accepted_risk_ids)}"
        )

        if not test_cases:
            return {
                "suites": [], "count": 0, "strategy": strategy,
                "risk_coverage": None, "workflow_status": "success",
                "note": "No test cases provided",
            }

        try:
            # STEP 1: GROUP
            await self._emit(progress_callback, "phase", {
                "phase": "grouping",
                "message": f"Grouping {len(test_cases)} test cases by '{strategy}'...",
            })

            group_fn = _STRATEGY_MAP.get(strategy, group_by_test_type)
            groups = group_fn(test_cases)

            logger.info(f"[TEST SUITE] Groups: {[(k, len(v)) for k, v in groups.items()]}")

            # STEP 2: LLM NAMING
            await self._emit(progress_callback, "phase", {
                "phase": "naming",
                "message": f"Generating titles for {len(groups)} suites...",
            })

            try:
                naming = await asyncio.wait_for(
                    self._call_llm(groups, project_name, strategy),
                    timeout=LLM_TIMEOUT_SECONDS,
                )
                names_by_key = {n.group_key: n for n in naming.suites}
            except Exception as e:
                logger.warning(f"[TEST SUITE] LLM naming failed: {e}")
                names_by_key = {}

            # STEP 3: COMPUTE RISK COVERAGE
            await self._emit(progress_callback, "phase", {
                "phase": "coverage",
                "message": "Calculating Risk Coverage...",
            })

            risk_coverage = compute_suite_coverage(
                test_cases=test_cases,
                accepted_risk_ids=accepted_risk_ids,
            )

            logger.info(
                f"[TEST SUITE] Risk Coverage: {risk_coverage['risk_coverage_pct']:.0%} "
                f"({risk_coverage['covered_risks']}/{risk_coverage['total_risks']})"
            )

            # STEP 4: FINALIZE
            await self._emit(progress_callback, "phase", {
                "phase": "finalizing",
                "message": "Assigning execution order...",
            })

            raw_suites = []
            for group_key, tcs in groups.items():
                name_info = names_by_key.get(group_key)
                record = build_suite_record(
                    group_key=group_key,
                    test_cases=tcs,
                    test_plan_id=test_plan_id,
                    title=name_info.title if name_info else "",
                    description=name_info.description if name_info else "",
                    suite_type=name_info.suite_type if name_info else None,
                    priority=name_info.priority if name_info else None,
                )
                raw_suites.append(record)

            ordered_suites = assign_suite_order(raw_suites)

            await self._emit(progress_callback, "phase", {
                "phase": "done",
                "message": f"Created {len(ordered_suites)} test suites.",
                "count": len(ordered_suites),
                "risk_coverage": risk_coverage,
            })

            self._log_summary(test_plan_id, ordered_suites, risk_coverage)

            return {
                "suites": ordered_suites,
                "count": len(ordered_suites),
                "strategy": strategy,
                "risk_coverage": risk_coverage,
                "workflow_status": "success",
            }

        except Exception as exc:
            logger.error(f"[TEST SUITE] Fatal error: {exc}", exc_info=True)
            return {
                "suites": [], "count": 0, "strategy": strategy,
                "risk_coverage": None, "workflow_status": "error",
                "error": str(exc),
            }

    async def _call_llm(
        self,
        groups: Dict[str, List[Dict[str, Any]]],
        project_name: str,
        strategy: str,
    ) -> SuiteNamingBatch:
        """Appelle le LLM pour nommer les suites."""
        groups_text_lines = []
        for key, tcs in groups.items():
            sample_titles = [tc.get("title", "")[:60] for tc in tcs[:3]]
            groups_text_lines.append(
                f'- group_key: "{key}" | {len(tcs)} test cases\n'
                f'  Sample tests: {"; ".join(sample_titles)}'
            )
        groups_text = "\n".join(groups_text_lines)

        prompt = TEST_SUITE_NAMING_PROMPT.format(
            project_name=project_name or "Project",
            strategy=strategy,
            suite_groups=groups_text,
        )
        return await self._llm.ainvoke(prompt)

    def _log_summary(
        self, 
        test_plan_id: str, 
        suites: List[Dict[str, Any]],
        risk_coverage: Dict[str, Any] = None,
    ) -> None:
        """Log le résumé de la génération."""
        for s in suites:
            logger.info(
                f"[RESULT] plan={test_plan_id} suite='{s['title']}' "
                f"type={s['suite_type']} order={s['execution_order']} "
                f"tc_count={s['_tc_count']}"
            )
        
        if risk_coverage:
            logger.info(
                f"[RESULT] plan={test_plan_id} "
                f"Risk Coverage={risk_coverage['risk_coverage_pct']:.0%} "
                f"({risk_coverage['mitigation_status']})"
            )    
# ============================================================
# SINGLETON
# ============================================================

_instances: dict[str, TestSuitePipeline] = {}


def get_pipeline(temperature: float = LLM_TEMPERATURE) -> TestSuitePipeline:
    from app.llm.llm_control import get_worker_api_key
    api_key = get_worker_api_key() or "default"
    if api_key not in _instances:
        logger.info(f"[TEST SUITE] Creating pipeline instance for key: {api_key[:12]}...")
        _instances[api_key] = TestSuitePipeline(temperature=temperature)
    return _instances[api_key]


def reset_pipeline() -> None:
    _instances.clear()
    logger.info("[TEST SUITE] All pipeline instances reset")