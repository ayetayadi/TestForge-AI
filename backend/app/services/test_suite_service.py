"""TestSuite service — full QA lifecycle context: traceability matrix, dependency graph, prioritization."""

import logging
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.test_suite import TestSuite
from app.models.test_case import TestCase
from app.models.risk import Risk
from app.models.user_story import UserStory
from app.models.test_case_dependency import TestCaseDependency
from app.models.test_plan import TestPlan
from app.repositories.test_suite_repository import TestSuiteRepository
from app.repositories.test_case_repository import get_test_cases_by_test_plan_id
from app.repositories.test_plan_repository import TestPlanRepository
from app.schemas.test_suite_schema import (
    DependencyEdge,
    DependencyGraphSchema,
    DependencyNode,
    EmbeddedRiskSchema,
    EmbeddedTestCaseSchema,
    EmbeddedTestPlanSchema,
    PriorityReasoningSchema,
    SuiteCoverageSchema,
    TestSuiteDetailSchema,
    TestSuiteListItemSchema,
    TestSuiteListResponse,
    TraceabilityACRow,
    TraceabilityMatrixSchema,
    TraceabilityStoryRow,
)
from app.ai_workflows.test_suite.pipeline import get_pipeline as get_suite_pipeline

logger = logging.getLogger(__name__)

# Risk level → numeric weight for prioritization (higher = more urgent)
_RISK_WEIGHT: Dict[str, int] = {
    "critical": 1000,
    "high": 700,
    "medium": 400,
    "low": 100,
}

# Test case priority → weight
_PRIORITY_WEIGHT: Dict[str, int] = {
    "critical": 800,
    "high": 600,
    "medium": 300,
    "low": 100,
}


class TestSuiteService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = TestSuiteRepository(db)

    # ============================================================
    # LIST
    # ============================================================

    async def get_all(
        self,
        plan_id: Optional[str] = None,
        project_id: Optional[str] = None,
        suite_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> TestSuiteListResponse:
        suites = await self.repo.get_all(
            plan_id=plan_id,
            project_id=project_id,
            suite_type=suite_type,
            status=status,
        )
        items = [self._to_list_item(s) for s in suites]
        return TestSuiteListResponse(items=items, total=len(items))

    def _to_list_item(self, suite: TestSuite) -> TestSuiteListItemSchema:
        plan = suite.test_plan
        project = plan.jira_project if plan else None
        coverage = self._compute_coverage(suite, [], [])
        return TestSuiteListItemSchema(
            id=suite.id,
            test_plan_id=suite.test_plan_id,
            title=suite.title,
            description=suite.description,
            suite_type=suite.suite_type,
            priority=suite.priority,
            status=suite.status,
            execution_order=suite.execution_order,
            is_ai_generated=suite.is_ai_generated,
            test_case_count=len(suite.test_cases) if suite.test_cases else 0,
            project_name=project.project_name if project else None,
            project_key=project.project_key if project else None,
            test_plan_title=plan.title if plan else None,
            test_plan_status=plan.status if plan else None,
            coverage=coverage,
            created_at=suite.created_at,
            updated_at=suite.updated_at,
        )

    # ============================================================
    # GENERATE SUITES FROM TEST CASES
    # ============================================================

    async def generate_suites(
        self,
        test_plan_id: str,
        strategy: str = "risk_level",
        project_name: str = "",
    ) -> Dict[str, Any]:
        """Generate test suites from existing test cases."""
        
        # 1. Verify Test Plan exists
        plan_repo = TestPlanRepository(self.db)
        plan = await plan_repo.get_by_id(test_plan_id)
        if not plan:
            raise ValueError(f"Test Plan {test_plan_id} not found")
        
        # 2. Get test cases WITHOUT suite assignment
        result = await self.db.execute(
            select(TestCase).where(
                TestCase.test_plan_id == test_plan_id,
                TestCase.test_suite_id.is_(None)
            )
        )
        test_cases = list(result.scalars().all())
        
        if not test_cases:
            raise ValueError("No unassigned test cases found. All TCs are already in suites.")
        
        # 3. Convert to dicts with metadata
        tc_dicts = []
        for tc in test_cases:
            d = {
                "id": tc.id,
                "tc_code": tc.tc_code,
                "title": tc.title,
                "test_type": tc.test_type or "positive",
                "priority": tc.priority or "medium",
                "tags": tc.tags or [],
                "user_story_id": tc.user_story_id,
            }
            tc_dicts.append(d)
        
        # 4. Run AI pipeline
        pipeline = get_suite_pipeline()
        result = await pipeline.run(
            test_cases=tc_dicts,
            test_plan_id=test_plan_id,
            project_name=project_name or plan.title or "Project",
            strategy=strategy,
        )
        
        if result.get("workflow_status") == "error":
            raise ValueError(f"Suite generation failed: {result.get('error')}")
        
        # 5. Persist suites and link test cases
        created_suites = []
        tc_map = {tc.tc_code: tc for tc in test_cases}
        
        for suite_data in result["suites"]:
            suite = TestSuite(
                id=str(uuid4()),
                test_plan_id=test_plan_id,
                title=suite_data["title"],
                description=suite_data.get("description", ""),
                suite_type=suite_data.get("suite_type", "functional"),
                priority=suite_data.get("priority", "medium"),
                execution_order=suite_data.get("execution_order"),
                is_ai_generated=True,
                status="draft",
            )
            self.db.add(suite)
            await self.db.flush()
            
            linked_count = 0
            for tc_code in suite_data.get("_tc_codes", []):
                tc = tc_map.get(tc_code)
                if tc:
                    tc.test_suite_id = suite.id
                    linked_count += 1
            
            logger.info(f"[SUITE GEN] Suite '{suite.title}' linked to {linked_count} TCs")
            
            created_suites.append({
                "id": suite.id,
                "title": suite.title,
                "execution_order": suite.execution_order,
                "tc_count": linked_count,
            })
        
        await self.db.commit()
        
        # ============================================================
        # CRÉER LES DÉPENDANCES ENTRE TCs
        # ============================================================
        dependency_count = await self._create_dependencies_for_suites(
            result["suites"], tc_map, test_plan_id
        )
        logger.info(f"[SUITE GEN] Created {dependency_count} dependencies between TCs")
        
        return {
            "suites": created_suites,
            "count": len(created_suites),
            "strategy": strategy,
            "workflow_status": "success",
        }
    
    
    # ============================================================
    # CRÉER LES DÉPENDANCES
    # ============================================================
    
    async def _create_dependencies_for_suites(
        self,
        suites_data: List[Dict[str, Any]],
        tc_map: Dict[str, TestCase],
        test_plan_id: str,
    ) -> int:
        """
        Crée des dépendances entre les TCs d'une même suite.
        Logique : 
        - Trier par type (smoke → positive → negative → edge_case)
        - Trier par execution_order
        - Créer des dépendances séquentielles (chaque TC dépend du précédent)
        - Dépendances inter-suites : les TCs d'une suite prioritaire sont prérequis pour la suite suivante
        """
        
        type_order = {"smoke": 0, "positive": 1, "negative": 2, "boundary": 3, "edge_case": 4}
        dep_count = 0
        
        # Trier les suites par execution_order
        sorted_suites = sorted(suites_data, key=lambda s: s.get("execution_order", 99))
        
        previous_suite_last_tc = None
        
        for suite_data in sorted_suites:
            # Récupérer les TCs de cette suite
            suite_tcs = [
                tc_map[tc_code] 
                for tc_code in suite_data.get("_tc_codes", []) 
                if tc_code in tc_map
            ]
            
            if not suite_tcs:
                continue
            
            # Trier par type puis par execution_order
            suite_tcs.sort(key=lambda x: (
                type_order.get((x.test_type or "positive").lower(), 99),
                x.execution_order or 0
            ))
            
            # 1. Créer dépendance inter-suite (si suite précédente existe)
            if previous_suite_last_tc and suite_tcs:
                dep = TestCaseDependency(
                    id=str(uuid4()),
                    test_plan_id=test_plan_id,
                    source_test_case_id=previous_suite_last_tc.id,
                    target_test_case_id=suite_tcs[0].id,
                    dependency_type="requires",
                    is_ai_generated=True,
                )
                self.db.add(dep)
                dep_count += 1
                logger.debug(
                    f"[DEP] Inter-suite: {previous_suite_last_tc.tc_code} → {suite_tcs[0].tc_code}"
                )
            
            # 2. Créer dépendances intra-suite (séquentielles)
            for i in range(1, len(suite_tcs)):
                dep = TestCaseDependency(
                    id=str(uuid4()),
                    test_plan_id=test_plan_id,
                    source_test_case_id=suite_tcs[i-1].id,
                    target_test_case_id=suite_tcs[i].id,
                    dependency_type="requires",
                    is_ai_generated=True,
                )
                self.db.add(dep)
                dep_count += 1
                logger.debug(
                    f"[DEP] Intra-suite: {suite_tcs[i-1].tc_code} → {suite_tcs[i].tc_code}"
                )
            
            # Mémoriser le dernier TC de cette suite pour la liaison inter-suite
            previous_suite_last_tc = suite_tcs[-1]
        
        if dep_count > 0:
            await self.db.commit()
        
        return dep_count

    # ============================================================
    # DETAIL
    # ============================================================

    async def get_detail(self, suite_id: str) -> Optional[TestSuiteDetailSchema]:
        suite = await self.repo.get_by_id(suite_id)
        if not suite:
            return None

        risks, stories, dependencies = await self._fetch_related(suite)

        risk_map: Dict[str, Risk] = {r.id: r for r in risks}
        story_map: Dict[str, UserStory] = {s.id: s for s in stories}

        prioritized_cases = self._prioritize_cases(suite.test_cases, risk_map, story_map)

        plan = suite.test_plan
        project = plan.jira_project if plan else None

        coverage = self._compute_coverage(suite, risks, stories)
        matrix = self._build_traceability_matrix(prioritized_cases, story_map, suite)
        graph = self._build_dependency_graph(suite.test_cases, dependencies)
        lifecycle = self._build_lifecycle(suite, risks)
        priority_reasoning = self._build_priority_reasoning(suite, risk_map, story_map)
        
        # All suites in this plan for comparison
        all_suites = await self.repo.get_all(plan_id=suite.test_plan_id)
        all_suites_order = [
            {
                "id": s.id,
                "title": s.title,
                "execution_order": s.execution_order,
                "priority": s.priority,
                "test_case_count": len(s.test_cases) if s.test_cases else 0,
            }
            for s in sorted(all_suites, key=lambda x: x.execution_order or 99)
        ]

        return TestSuiteDetailSchema(
            id=suite.id,
            test_plan_id=suite.test_plan_id,
            title=suite.title,
            description=suite.description,
            suite_type=suite.suite_type,
            priority=suite.priority,
            status=suite.status,
            execution_order=suite.execution_order,
            is_ai_generated=suite.is_ai_generated,
            created_at=suite.created_at,
            updated_at=suite.updated_at,
            test_plan=self._embed_plan(plan, suite) if plan else None,
            project_id=project.id if project else None,
            project_name=project.project_name if project else None,
            project_key=project.project_key if project else None,
            test_cases=[self._embed_case(tc, risk_map, story_map) for tc in prioritized_cases],
            risks=[self._embed_risk(r) for r in risks],
            coverage=coverage,
            traceability_matrix=matrix,
            dependency_graph=graph,
            lifecycle=lifecycle,
            priority_reasoning=priority_reasoning,
            all_suites_order=all_suites_order,
        )

    # ============================================================
    # ASSIGN TEST CASE TO SUITE (Manual)
    # ============================================================

    async def assign_test_case_to_suite(
        self,
        test_case_id: str,
        suite_id: str,
    ) -> bool:
        """Manually assign a test case to a suite."""
        
        tc = await self.db.get(TestCase, test_case_id)
        suite = await self.db.get(TestSuite, suite_id)
        
        if not tc or not suite:
            return False
        
        tc.test_suite_id = suite_id
        await self.db.commit()
        
        logger.info(f"[SUITE] Assigned {tc.tc_code} to suite '{suite.title}'")
        return True

    async def unassign_test_case_from_suite(
        self,
        test_case_id: str,
    ) -> bool:
        """Remove a test case from its suite."""
        
        tc = await self.db.get(TestCase, test_case_id)
        if not tc:
            return False
        
        tc.test_suite_id = None
        await self.db.commit()
        
        logger.info(f"[SUITE] Unassigned {tc.tc_code} from suite")
        return True

    # ============================================================
    # PRIVATE HELPERS
    # ============================================================

    async def _fetch_related(
        self, suite: TestSuite
    ) -> Tuple[List[Risk], List[UserStory], List[TestCaseDependency]]:
        risks, stories, deps = await _gather(
            self.repo.get_risks_for_suite(suite),
            self.repo.get_user_stories_for_suite(suite),
            self.repo.get_dependencies_for_suite(suite),
        )
        return risks, stories, deps

    def _build_priority_reasoning(
        self,
        suite: TestSuite,
        risk_map: Dict[str, Risk],
        story_map: Dict[str, UserStory],
    ) -> PriorityReasoningSchema:
        """Build explanation of why this suite has its priority and execution order."""
        
        risk_breakdown: Dict[str, int] = {}
        total_risk_weight = 0
        for tc in suite.test_cases:
            if tc.user_story_id:
                # Chercher les risques pour cette US
                for risk in risk_map.values():
                    if risk.user_story_id == tc.user_story_id and risk.level:
                        level = risk.level
                        risk_breakdown[level] = risk_breakdown.get(level, 0) + 1
                        total_risk_weight += _RISK_WEIGHT.get(level, 0)
        
        total_ac = 0
        covered_ac = 0
        for tc in suite.test_cases:
            if tc.user_story_id and tc.user_story_id in story_map:
                story = story_map[tc.user_story_id]
                ac_count = len(story.acceptance_criteria or [])
                total_ac += ac_count
                if tc.is_active:
                    covered_ac += ac_count
        
        exec_order = suite.execution_order or 99
        if suite.suite_type == "smoke":
            order_reason = "Smoke tests always run first"
        elif exec_order == 1:
            order_reason = f"Highest risk weight ({total_risk_weight})"
        elif exec_order <= 3:
            order_reason = f"Moderate risk weight ({total_risk_weight})"
        else:
            order_reason = f"Lower risk weight ({total_risk_weight}) — runs later"
        
        formula = (
            f"Priority Score = Risk Weight ({total_risk_weight}) + "
            f"Priority Bonus ({_PRIORITY_WEIGHT.get(suite.priority or '', 0)}) → "
            f"Order {exec_order}"
        )
        
        return PriorityReasoningSchema(
            risk_weight=total_risk_weight,
            risk_breakdown=risk_breakdown,
            coverage_ac_count=covered_ac,
            coverage_total_ac=total_ac,
            requirement_order=exec_order,
            priority_formula=formula,
            execution_order_reason=order_reason,
        )

    def _prioritize_cases(
        self,
        cases: List[TestCase],
        risk_map: Dict[str, Risk],
        story_map: Dict[str, UserStory],
    ) -> List[TestCase]:
        """Sort test cases: highest risk weight → most AC covered → earliest AC index."""
    
        def _score(tc: TestCase) -> Tuple[int, int, int, int]:
            max_risk_weight = 0
            # ✅ Chercher les risques via l'US
            if tc.user_story_id:
                for risk in risk_map.values():
                    if risk.user_story_id == tc.user_story_id and risk.level:
                        max_risk_weight = max(max_risk_weight, _RISK_WEIGHT.get(risk.level, 0))
    
            priority_weight = _PRIORITY_WEIGHT.get(tc.priority or "", 0)
            ac_count = 0
            min_ac_idx = 9999
            if tc.user_story_id:
                story = story_map.get(tc.user_story_id)
                if story and story.acceptance_criteria:
                    ac_count = len(story.acceptance_criteria)
                    min_ac_idx = 0
    
            return (
                -(max_risk_weight + priority_weight),
                -ac_count,
                min_ac_idx,
                tc.execution_order or 9999,
            )
    
        return sorted(cases, key=_score)

    def _compute_priority_score(
        self,
        tc: TestCase,
        risk_map: Dict[str, Risk],
    ) -> int:
        score = 0
        # ✅ Chercher les risques via l'US
        if tc.user_story_id:
            for risk in risk_map.values():
                if risk.user_story_id == tc.user_story_id and risk.level:
                    score += _RISK_WEIGHT.get(risk.level, 0)
        score += _PRIORITY_WEIGHT.get(tc.priority or "", 0)
        return score

    def _build_traceability_matrix(
        self,
        cases: List[TestCase],
        story_map: Dict[str, UserStory],
        suite: TestSuite,
    ) -> TraceabilityMatrixSchema:
        by_story: Dict[str, List[TestCase]] = defaultdict(list)
        for tc in cases:
            if tc.user_story_id:
                by_story[tc.user_story_id].append(tc)

        rows: List[TraceabilityStoryRow] = []
        total_ac = 0
        covered_ac = 0

        for story_id, story_cases in by_story.items():
            story = story_map.get(story_id)
            if not story:
                continue

            ac_list = story.acceptance_criteria or []
            ac_rows: List[TraceabilityACRow] = []

            for idx, ac_text in enumerate(ac_list):
                covering_codes = [tc.tc_code for tc in story_cases if tc.is_active]
                is_covered = len(covering_codes) > 0

                ac_rows.append(TraceabilityACRow(
                    ac_index=idx,
                    ac_text=ac_text,
                    covered_by=covering_codes,
                    is_covered=is_covered,
                ))

                total_ac += 1
                if is_covered:
                    covered_ac += 1

            covered_cases = sum(1 for tc in story_cases if tc.is_active)
            story_coverage_pct = (covered_ac / total_ac * 100) if total_ac > 0 else 0.0

            rows.append(TraceabilityStoryRow(
                user_story_id=story_id,
                issue_key=story.issue_key,
                title=story.title,
                acceptance_criteria=ac_rows,
                covered_cases=covered_cases,
                total_ac=len(ac_list),
                coverage_pct=round(story_coverage_pct, 1),
            ))

        global_pct = round(covered_ac / total_ac * 100, 1) if total_ac > 0 else 0.0

        matrix = TraceabilityMatrixSchema(
            rows=rows,
            total_stories=len(rows),
            total_ac=total_ac,
            covered_ac=covered_ac,
            global_coverage_pct=global_pct,
        )
        suite.matrix_snapshot = matrix.model_dump()
        return matrix

    def _build_dependency_graph(
        self,
        cases: List[TestCase],
        dependencies: List[TestCaseDependency],
    ) -> DependencyGraphSchema:
        tc_map: Dict[str, TestCase] = {tc.id: tc for tc in cases}

        nodes = [
            DependencyNode(
                id=tc.id,
                tc_code=tc.tc_code,
                title=tc.title,
                priority=tc.priority,
                test_type=tc.test_type,
                execution_order=tc.execution_order,
            )
            for tc in cases
        ]

        edges: List[DependencyEdge] = []
        for dep in dependencies:
            src = tc_map.get(dep.source_test_case_id)
            tgt = tc_map.get(dep.target_test_case_id)
            if src and tgt:
                edges.append(DependencyEdge(
                    source=src.tc_code,
                    target=tgt.tc_code,
                    source_id=dep.source_test_case_id,
                    target_id=dep.target_test_case_id,
                    dependency_type=dep.dependency_type,
                    is_ai_generated=dep.is_ai_generated,
                ))

        execution_order = self._topological_sort(cases, dependencies)

        return DependencyGraphSchema(
            nodes=nodes,
            edges=edges,
            execution_order=execution_order,
        )

    def _topological_sort(
        self,
        cases: List[TestCase],
        dependencies: List[TestCaseDependency],
    ) -> List[str]:
        """Kahn's algorithm — returns tc_codes in safe execution order."""
        tc_map: Dict[str, TestCase] = {tc.id: tc for tc in cases}
        tc_ids = set(tc_map.keys())

        in_degree: Dict[str, int] = {tid: 0 for tid in tc_ids}
        adj: Dict[str, List[str]] = defaultdict(list)

        for dep in dependencies:
            src = dep.source_test_case_id
            tgt = dep.target_test_case_id
            if dep.dependency_type == "requires" and src in tc_ids and tgt in tc_ids:
                adj[src].append(tgt)
                in_degree[tgt] += 1

        queue = [tid for tid, deg in in_degree.items() if deg == 0]
        result: List[str] = []

        while queue:
            node = queue.pop(0)
            tc = tc_map.get(node)
            if tc:
                result.append(tc.tc_code)
            for neighbor in adj[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        remaining = {tid for tid in tc_ids if tc_map[tid].tc_code not in result}
        for tid in remaining:
            tc = tc_map.get(tid)
            if tc:
                result.append(tc.tc_code)

        return result

    def _compute_coverage(
        self,
        suite: TestSuite,
        risks: List[Risk],
        stories: List[UserStory],
    ) -> SuiteCoverageSchema:
        cases = suite.test_cases or []
        active = [c for c in cases if c.is_active]
    
        by_priority: Dict[str, int] = dict(Counter(c.priority for c in active if c.priority))
        by_type: Dict[str, int] = dict(Counter(c.test_type for c in active if c.test_type))
        has_gherkin = sum(1 for c in active if c.gherkin_source)
        has_steps = sum(1 for c in active if c.steps)
    
        # ✅ Couverture des risques via les US
        covered_risk_ids = set()
        risk_map = {r.id: r for r in risks}
        for tc in active:
            if tc.user_story_id:
                for risk in risks:
                    if risk.user_story_id == tc.user_story_id:
                        covered_risk_ids.add(risk.id)
        
        total_risks = len(risks)
        risk_pct = round(len(covered_risk_ids) / total_risks * 100, 1) if total_risks > 0 else 0.0
        total_ac = sum(len(s.acceptance_criteria or []) for s in stories)
        covered_story_ids = {tc.user_story_id for tc in active if tc.user_story_id}
        covered_ac = sum(
            len(s.acceptance_criteria or [])
            for s in stories
            if s.id in covered_story_ids
        )
        ac_pct = round(covered_ac / total_ac * 100, 1) if total_ac > 0 else 0.0

        coverage = SuiteCoverageSchema(
            total_cases=len(cases),
            active_cases=len(active),
            by_priority=by_priority,
            by_type=by_type,
            has_gherkin=has_gherkin,
            has_steps=has_steps,
            risk_coverage_pct=risk_pct,
            ac_coverage_pct=ac_pct,
        )
        suite.coverage_snapshot = coverage.model_dump()
        return coverage

    def _build_lifecycle(self, suite: TestSuite, risks: List[Risk]) -> Dict[str, Any]:
        plan = suite.test_plan
        cases = suite.test_cases or []
        risk_dist = dict(Counter(r.level for r in risks if r.level))

        return {
            "risk_analysis": {
                "total_risks": len(risks),
                "distribution": risk_dist,
                "accepted_count": sum(1 for r in risks if r.is_accepted),
            },
            "test_plan": {
                "id": plan.id if plan else None,
                "title": plan.title if plan else None,
                "status": plan.status if plan else None,
                "approved_at": plan.approved_at.isoformat() if plan and plan.approved_at else None,
                "environment": plan.environment if plan else None,
                "test_types": plan.test_types if plan else [],
                "entry_criteria": plan.entry_criteria if plan else None,
                "exit_criteria": plan.exit_criteria if plan else None,
            },
            "test_suite": {
                "id": suite.id,
                "title": suite.title,
                "type": suite.suite_type,
                "priority": suite.priority,
                "is_ai_generated": suite.is_ai_generated,
                "created_at": suite.created_at.isoformat() if suite.created_at else None,
            },
            "test_cases": {
                "total": len(cases),
                "active": sum(1 for c in cases if c.is_active),
                "with_gherkin": sum(1 for c in cases if c.gherkin_source),
                 "coverage_snapshot": suite.coverage_snapshot if suite.coverage_snapshot else None,
            },
        }

    def _embed_plan(self, plan, suite: TestSuite) -> EmbeddedTestPlanSchema:
        return EmbeddedTestPlanSchema(
            id=plan.id,
            title=plan.title,
            status=plan.status,
            objective=plan.objective,
            in_scope=plan.in_scope,
            out_of_scope=plan.out_of_scope,
            test_types=plan.test_types or [],
            test_levels=plan.test_levels or [],
            environment=plan.environment,
            entry_criteria=plan.entry_criteria,
            exit_criteria=plan.exit_criteria,
            approach=plan.approach,
            start_date=str(plan.start_date) if plan.start_date else None,
            end_date=str(plan.end_date) if plan.end_date else None,
            approved_at=plan.approved_at,
            coverage_snapshot=suite.coverage_snapshot,
            matrix_snapshot=suite.matrix_snapshot,
        )
    
    def _embed_case(
        self,
        tc: TestCase,
        risk_map: Dict[str, Risk],
        story_map: Dict[str, UserStory],
    ) -> EmbeddedTestCaseSchema:
        risk_ids = []
        if tc.user_story_id:
            for risk in risk_map.values():
                if risk.user_story_id == tc.user_story_id:
                    risk_ids.append(risk.id)
        return EmbeddedTestCaseSchema(
            id=tc.id,
            tc_code=tc.tc_code,
            title=tc.title,
            description=tc.description,
            test_type=tc.test_type,
            risk_ids=risk_ids,
            priority=tc.priority,
            tags=tc.tags or [],
            preconditions=tc.preconditions or [],
            postconditions=tc.postconditions or [],
            steps=tc.steps or [],
            gherkin_source=tc.gherkin_source,
            test_data=tc.test_data or {},
            expected_results=tc.expected_results or [],
            execution_order=tc.execution_order,
            user_story_id=tc.user_story_id,
            is_active=tc.is_active,
            created_at=tc.created_at,
            priority_score=self._compute_priority_score(tc, risk_map),
        )

    def _embed_risk(self, risk: Risk) -> EmbeddedRiskSchema:
        return EmbeddedRiskSchema(
            id=risk.id,
            description=risk.description,
            level=risk.level,
            risk_score=risk.risk_score,
            probability=risk.probability,
            impact=risk.impact,
            mitigation=risk.mitigation,
            is_accepted=risk.is_accepted,
        )


# ============================================================
# Gather helper
# ============================================================

async def _gather(coro1, coro2, coro3):
    r1 = await coro1
    r2 = await coro2
    r3 = await coro3
    return r1, r2, r3