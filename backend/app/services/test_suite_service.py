"""TestSuite service — full QA lifecycle context: traceability matrix, dependency graph, prioritization."""

import logging
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4
from collections import deque
import heapq
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.models.test_suite import TestSuite
from app.models.test_case import TestCase
from app.models.risk import Risk
from app.models.user_story import UserStory
from app.models.test_case_dependency import TestCaseDependency
from app.models.test_plan import TestPlan
from app.models.tc_coverage import TcCoverage
from app.ai_workflows.test_case.config import MIN_AC_COVERAGE
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

# ── Business Flow (MÉTIER) hierarchy ────────────────────────────────────────
# Rank 1 = executes first (foundational flow), higher rank = executes later.
# Used as PRIMARY sort key; Risk Level is SECONDARY.
# ISTQB §5.2.4: "Business-critical paths shall be tested before secondary flows."
_BUSINESS_FLOW_KEYWORDS: Dict[str, List[str]] = {
    "authentication": [
        "auth", "login", "logout", "disconnect", "register", "signup", "sign-in",
        "account", "compte", "sign up", "registration", "inscription",
        "password", "credential", "session", "token", "jwt", "oauth", "sso",
        "2fa", "mfa", "verification", "forgot password", "reset password",
    ],
    "dashboard": [
        "dashboard", "home", "overview", "landing", "summary", "main page",
        "welcome", "portal", "workspace",
    ],
    "crud": [
        "create", "update", "delete", "edit", "add", "remove", "save",
        "crud", "form", "submit", "modify", "insert", "record",
    ],
    "search": [
        "search", "filter", "sort", "query", "find", "browse", "lookup",
        "autocomplete", "pagination",
    ],
    "reporting": [
        "report", "export", "log", "audit", "history", "analytics",
        "metrics", "statistics", "chart", "download",
    ],
    "settings": [
        "setting", "config", "preference", "profile", "account",
        "permission", "role", "user management",
    ],
    "notifications": [
        "notification", "alert", "email", "message", "sms", "push",
        "reminder", "broadcast",
    ],
}

_BUSINESS_FLOW_RANK: Dict[str, int] = {
    "authentication": 1,
    "dashboard": 2,
    "crud": 3,
    "search": 4,
    "reporting": 5,
    "settings": 6,
    "notifications": 7,
    "other": 8,
}

# ── Critère 2 : chaîne de dépendances entre entités métier ──────────────────
# Auth(1) → Client(2) → Catégorie(3) → Projet(4) → Tâche(5) → Commentaire(6)
_ENTITY_RANK: Dict[str, int] = {
    "auth":     1,
    "client":   2,
    "category": 3,
    "project":  4,
    "task":     5,
    "comment":  6,
    "other":   99,
}

_ENTITY_KEYWORDS: Dict[str, List[str]] = {
    "auth": [
        "auth", "login", "logout", "disconnect", "connexion", "déconnexion", "compte",
        "account", "register", "inscription", "password", "mot de passe",
        "session", "token", "jwt", "sign in", "sign out", "sign up",
    ],
    "client":   ["client", "customer"],
    "category": ["category", "catégorie", "categorie"],
    "project":  ["project", "projet"],
    "task":     ["task", "tâche", "tache"],
    "comment":  ["comment", "commentaire"],
}

# ── Critère 1 : ordre des actions CRUD ──────────────────────────────────────
# Create(1) → Update(2) → Cancel(3) → Delete(4). Jamais l'inverse.
_ACTION_RANK: Dict[str, int] = {
    "create": 1,
    "update": 2,
    "cancel": 3,
    "delete": 4,
}

_ACTION_KEYWORDS: Dict[str, List[str]] = {
    "create": [
        "créer", "create", "ajouter", "add", "nouveau", "new",
        "register", "inscription", "enregistrer", "ajout", "création",
        "sign up", "s'inscrire", "créer un",
    ],
    "update": [
        "modifier", "update", "edit", "mettre à jour", "changer",
        "modification", "mise à jour", "renommer",
    ],
    "cancel": [
        "annuler", "cancel", "désactiver", "disable", "suspendre", "archiver",
    ],
    "delete": [
        "supprimer", "delete", "remove", "effacer", "suppression",
    ],
}

# ── Critère 3 : Auth encadre tout ───────────────────────────────────────────
# Création de compte → position 1, Connexion → position 2, Déconnexion → dernière
_ACCOUNT_CREATE_KEYWORDS: List[str] = [
    "create account", "create a new account", "create an account", "new account", "an account",
    "créer compte", "créer un compte", "register",
    "inscription", "sign up", "s'inscrire", "enregistrement",
]

_LOGIN_KEYWORDS: List[str] = [
    "login", "connexion", "sign in", "authenticate", "se connecter",
    "identifiants valides", "mot de passe correct",
]

_LOGOUT_KEYWORDS: List[str] = [
    "logout", "log out", "déconnexion", "sign out", "logoff", "se déconnecter", "déconnecter",
    # English presentation enforced for test cases → titles say "Disconnect ..."
    "disconnect", "disconnection",
]


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
        project_ids=None,
    ) -> TestSuiteListResponse:
        suites = await self.repo.get_all(
            plan_id=plan_id,
            project_id=project_id,
            suite_type=suite_type,
            status=status,
            project_ids=project_ids,
        )
        items = [self._to_list_item(s) for s in suites]
        return TestSuiteListResponse(items=items, total=len(items))

    def _to_list_item(self, suite: TestSuite) -> TestSuiteListItemSchema:
        plan = suite.test_plan
        project = plan.jira_project if plan else None
        risk_coverage = None
        if suite.risk_coverage_pct is not None:
            risk_coverage = {
                "risk_coverage_pct": round(suite.risk_coverage_pct * 100, 1),
                "covered_risks": 0,  # Sera calculé dans le détail
                "total_risks": 0,
                "uncovered_risk_ids": suite.risk_coverage_uncovered or [],
                "mitigation_status": suite.mitigation_status or "not_mitigated",
            }
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
            risk_coverage=risk_coverage,
            created_at=suite.created_at,
            updated_at=suite.updated_at,
        )

    # ============================================================
    # GENERATE SUITES FROM TEST CASES
    # ============================================================

    async def generate_suites(
        self,
        test_plan_id: str,
        strategy: str = "test_type",
        project_name: str = "",
    ) -> Dict[str, Any]:
        """Generate test suites from existing test cases."""
        # Grouping is always by scenario type: positive → negative → boundary
        strategy = "test_type"

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
            raise ValueError("No unassigned test cases found.")
        
        # ── 🔥 RÉCUPÉRER TOUTES LES US DU PLAN (pas seulement celles avec TCs) ──
        all_plan_stories_result = await self.db.execute(
            select(UserStory).where(
                UserStory.project_id == plan.project_id  # Ou via le scope du plan
            )
        )
        all_plan_stories = all_plan_stories_result.scalars().all()
        
        # 3. Convert to dicts with metadata
        tc_dicts = []
        for tc in test_cases:
            tc_dicts.append({
                "id": tc.id,
                "tc_code": tc.tc_code,
                "title": tc.title,
                "test_type": tc.test_type or "positive",
                "risk_level": tc.risk_level or "medium",
                "user_story_id": tc.user_story_id,
            })
        
        # ── 🔥 DÉTERMINER L'ORDRE DES FLUX AVEC TOUTES LES US ──
        pipeline = get_suite_pipeline()
        
        # Collecter TOUTES les US pour le contexte LLM
        us_list = []
        seen_us = set()
        
        # D'abord les US qui ont des TCs
        for tc in test_cases:
            if tc.user_story_id and tc.user_story_id not in seen_us:
                seen_us.add(tc.user_story_id)
                us = tc.user_story
                if us:
                    us_list.append({
                        "issue_key": us.issue_key,
                        "title": us.title or "",
                        "sprint": us.sprint,
                        "has_tests": True,
                    })
        
        # Ensuite les US sans TCs (pour contexte complet)
        for us in all_plan_stories:
            if us.id not in seen_us:
                seen_us.add(us.id)
                us_list.append({
                    "issue_key": us.issue_key,
                    "title": us.title or "",
                    "sprint": us.sprint,
                    "has_tests": False,
                })
        
        logger.info(
            f"[SUITE GEN] Context for LLM: {len(us_list)} US "
            f"({sum(1 for u in us_list if u['has_tests'])} with tests, "
            f"{sum(1 for u in us_list if not u['has_tests'])} without)"
        )
        
        # LLM détermine l'ordre des flux
        flow_order = None
        llm_tc_classifications = None
        try:
            flow_order_data = await pipeline._determine_business_flow_order(
                test_cases=tc_dicts,
                user_stories=us_list,
                project_name=project_name or plan.title or "Project"
            )

            # Extraire les deux parties du résultat LLM
            actual_flow_order = flow_order_data.get("flow_order", {})        # {flow: rank}
            llm_tc_classifications = flow_order_data.get("tc_classifications", {})  # {tc_code: {...}}

            # Vérifier que tous les flux détectés sont dans l'ordre
            detected_flows = set()
            for tc in test_cases:
                detected_flows.add(self._get_business_flow(tc))

            missing_flows = detected_flows - set(actual_flow_order.keys())
            if missing_flows:
                logger.warning(
                    f"[SUITE GEN] LLM missed flows: {missing_flows}. "
                    f"Adding them at the end."
                )
                next_rank = max(actual_flow_order.values(), default=0) + 1
                for flow in sorted(missing_flows):
                    actual_flow_order[flow] = next_rank
                    next_rank += 1

            # Stocker les deux dans le plan
            plan.business_flow_order = actual_flow_order
            plan.tc_classifications = llm_tc_classifications
            await self.db.commit()
            flow_order = actual_flow_order
            logger.info(
                f"[SUITE GEN] ✅ LLM Flow Order saved: {actual_flow_order} "
                f"| Classifications: {len(llm_tc_classifications)} TCs"
            )

        except Exception as e:
            logger.warning(f"[SUITE GEN] LLM flow order failed: {e}")
            flow_order = _BUSINESS_FLOW_RANK
        
        # 4. Run AI pipeline (naming + grouping + business-flow-aware ordering)
        result = await pipeline.run(
            test_cases=tc_dicts,
            test_plan_id=test_plan_id,
            project_name=project_name or plan.title or "Project",
            strategy=strategy,
            tc_classifications=llm_tc_classifications if flow_order else None,
            flow_order=flow_order if flow_order else None,
        )
        
        if result.get("workflow_status") == "error":
            raise ValueError(f"Suite generation failed: {result.get('error')}")

        # 5. Persist suites and link test cases
        created_suites = []
        tc_map = {tc.tc_code: tc for tc in test_cases}

        risk_query = select(Risk).where(
            Risk.user_story_id.in_([tc.user_story_id for tc in test_cases if tc.user_story_id]),
            Risk.is_accepted == True
        )
        risk_result = await self.db.execute(risk_query)
        all_risks = list(risk_result.scalars().all())
        accepted_risk_ids = [r.id for r in all_risks]

        # Build structured title components from the test plan
        _plan_project = project_name or ""
        if not _plan_project and " — " in (plan.title or ""):
            parts = plan.title.split(" — ")
            _plan_project = parts[1].strip() if len(parts) >= 2 else plan.title
        _scope_str = " - ".join(plan.scope_refs) if plan.scope_refs else ""
        _TYPE_LABEL = {
            "positive": "positive",
            "negative": "negative",
            "boundary": "boundary values",
            "edge_case": "boundary values",
            "edge": "boundary values",
        }

        # Collect titles already saved for this plan (to detect regeneration)
        existing_titles_result = await self.db.execute(
            select(TestSuite.title).where(TestSuite.test_plan_id == test_plan_id)
        )
        used_titles: set = {row[0] for row in existing_titles_result.all()}

        for suite_data in result["suites"]:
            group_key = (suite_data.get("_group_key") or suite_data.get("suite_type") or "positive").lower()
            type_label = _TYPE_LABEL.get(group_key, group_key)
            if _scope_str:
                base_title = f"Test Suite - {_plan_project} - {_scope_str} - {type_label}"
            else:
                base_title = f"Test Suite - {_plan_project} - {type_label}"
            structured_title = base_title
            counter = 2
            while structured_title in used_titles:
                structured_title = f"{base_title} - {counter}"
                counter += 1
            used_titles.add(structured_title)

            suite = TestSuite(
                id=str(uuid4()),
                test_plan_id=test_plan_id,
                title=structured_title,
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
            suite_tc_ids = []
            for tc_code in suite_data.get("_tc_codes", []):
                tc = tc_map.get(tc_code)
                if tc:
                    tc.test_suite_id = suite.id
                    linked_count += 1
                    suite_tc_ids.append(tc.id)
            
            
            suite_risk_ids = [
                r.id for r in all_risks 
                if r.user_story_id in [
                    tc.user_story_id 
                    for tc in test_cases 
                    if tc.id in suite_tc_ids and tc.user_story_id
                ]
            ]
            
            suite_covered = len(suite_risk_ids)
            suite_total = len(accepted_risk_ids)
            suite_risk_pct = suite_covered / suite_total if suite_total > 0 else 1.0
            
            suite.risk_coverage_pct = suite_risk_pct
            suite.risk_coverage_uncovered = [
                rid for rid in accepted_risk_ids if rid not in suite_risk_ids
            ]
            
            if suite_risk_pct >= 1.0:
                suite.mitigation_status = "fully_mitigated"
            elif suite_risk_pct >= 0.80:
                suite.mitigation_status = "partially_mitigated"
            else:
                suite.mitigation_status = "not_mitigated"
            
            logger.info(
                f"[SUITE GEN] Suite '{suite.title}' - "
                f"Risk Coverage: {suite_risk_pct:.0%} ({suite.mitigation_status})"
            )
            
            created_suites.append({
                "id": suite.id,
                "title": suite.title,
                "execution_order": suite.execution_order,
                "tc_count": linked_count,
                "risk_coverage_pct": suite_risk_pct,
                "mitigation_status": suite.mitigation_status,
            })
        
        await self.db.commit()
        
        # ============================================================
        # CRÉER LES DÉPENDANCES ENTRE TCs
        # ============================================================
        risk_map = {r.user_story_id: r for r in all_risks}
        dependency_count = await self._create_dependencies_for_suites(
            result["suites"], tc_map, test_plan_id, risk_map,
            flow_order=flow_order,
            tc_classifications=llm_tc_classifications,
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
        risk_map: Dict[str, Risk],
        flow_order: Optional[Dict[str, int]] = None,
        tc_classifications: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Crée des dépendances séquentielles DANS CHAQUE suite (par flux métier + risque).
        1 suite = 1 graphe de dépendances indépendant.
        Résultat: 1 à 3 graphes selon les types de scénarios (positive/negative/boundary).
        """
        dep_count = 0

        # Delete existing AI-generated dependencies for this plan to avoid duplicates on re-run
        await self.db.execute(
            delete(TestCaseDependency).where(
                TestCaseDependency.test_plan_id == test_plan_id,
                TestCaseDependency.is_ai_generated == True,
                TestCaseDependency.is_manual_override == False,
            )
        )
        await self.db.flush()

        # Utiliser directement les paramètres passés (déjà calculés par generate_suites)
        # pas de re-lecture DB — évite les problèmes de timing et de relations non chargées
        _flow_order: Dict[str, int] = flow_order or _BUSINESS_FLOW_RANK
        _tc_classifications: Dict[str, Any] = tc_classifications or {}
        seen_pairs: set = set()

        logger.info(
            f"[DEP] flow_order={_flow_order} | "
            f"classifications={len(_tc_classifications)} TCs"
        )

        def _sort_key(tc: TestCase) -> Tuple[int, int, int]:
            clf = _tc_classifications.get(tc.tc_code, {})
            return self._compute_order_key(tc, clf, _flow_order)

        # Créer les dépendances DANS CHAQUE suite séparément
        for suite_data in suites_data:
            suite_tcs = [
                tc_map[code]
                for code in suite_data.get("_tc_codes", [])
                if code in tc_map
            ]

            if len(suite_tcs) < 2:
                logger.info(
                    f"[DEP] Suite '{suite_data.get('title', '?')}': "
                    f"{len(suite_tcs)} TC(s) — pas de dépendances à créer"
                )
                continue

            sorted_suite_tcs = sorted(suite_tcs, key=_sort_key)

            # Mettre à jour execution_order selon l'ordre flux métier + risk level
            for i, tc in enumerate(sorted_suite_tcs, start=1):
                tc.execution_order = i

            suite_title = suite_data.get("title", "?")
            logger.info(
                f"[DEP] Suite '{suite_title}': "
                f"création de {len(sorted_suite_tcs) - 1} dépendances"
            )
            for i, tc in enumerate(sorted_suite_tcs):
                clf = _tc_classifications.get(tc.tc_code, {})
                flow = clf.get("business_flow") or self._keyword_flow(tc.title or "")
                risk_level = clf.get("risk_level") or tc.risk_level or "medium"
                logger.info(f"  {i + 1}. {tc.tc_code} | flow={flow} | risk={risk_level}")

            for i in range(1, len(sorted_suite_tcs)):
                prev, curr = sorted_suite_tcs[i - 1], sorted_suite_tcs[i]
                pair = (prev.id, curr.id)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                self.db.add(TestCaseDependency(
                    id=str(uuid4()),
                    test_plan_id=test_plan_id,
                    source_test_case_id=prev.id,
                    target_test_case_id=curr.id,
                    dependency_type="requires",
                    is_ai_generated=True,
                ))
                dep_count += 1

        if dep_count > 0:
            await self.db.commit()
            verify = await self.db.execute(
                select(TestCaseDependency).where(TestCaseDependency.test_plan_id == test_plan_id)
            )
            total_in_db = len(verify.scalars().all())
            logger.info(f"[DEP] ✅ Committed {dep_count} dépendances (DB total: {total_in_db})")

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

        prioritized_cases = self._prioritize_cases_by_risk(suite.test_cases, risk_map)

        plan = suite.test_plan
        project = plan.jira_project if plan else None

        risk_coverage = self._compute_coverage(suite, risks, stories)
        us_ac_coverages = await self._compute_us_ac_coverages(suite, stories)
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
            risk_coverage=risk_coverage,
            us_ac_coverages=us_ac_coverages,
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


    def _compute_order_key(
        self,
        tc: "TestCase",
        clf: Dict[str, Any],
        flow_order: Dict[str, int],
    ) -> Tuple[int, int, int]:
        """
        Clé de tri en 3 critères :
          1. Entity rank  — chaîne de dépendances métier
                           (Auth=1 → Client=2 → Catégorie=3 → Projet=4 → Tâche=5 → Commentaire=6)
          2. Action rank  — ordre CRUD : Create=1 → Update=2 → Cancel=3 → Delete=4
          3. Risk weight  — tiebreaker : critical en premier

        Règles spéciales (Critère 3) :
          - Création de compte → (1, 0, 0)    — toujours premier
          - Connexion (login)  → (1, 1, 0)    — toujours deuxième
          - Déconnexion        → (9999, 9999, 0) — toujours dernier
        """
        title = (tc.title or "").lower()

        # Critère 3 : Auth encadre tout
        if any(kw in title for kw in _LOGOUT_KEYWORDS):
            return (9999, 9999, 0)
        if any(kw in title for kw in _ACCOUNT_CREATE_KEYWORDS):
            return (1, 0, 0)
        if any(kw in title for kw in _LOGIN_KEYWORDS):
            return (1, 1, 0)

        # Critère 2 : entité métier (keywords sur le titre en priorité, LLM en fallback)
        entity_rank = None
        for entity, keywords in _ENTITY_KEYWORDS.items():
            if any(kw in title for kw in keywords):
                entity_rank = _ENTITY_RANK[entity]
                break
        if entity_rank is None:
            flow = clf.get("business_flow") or self._keyword_flow(tc.title or "")
            entity_rank = flow_order.get(flow, 99)

        # Critère 1 : type d'action (Create → Update → Cancel → Delete)
        action_rank = 5  # non classifié
        for action, keywords in _ACTION_KEYWORDS.items():
            if any(kw in title for kw in keywords):
                action_rank = _ACTION_RANK[action]
                break

        # Tiebreaker : risk level (critical en premier)
        risk_level = clf.get("risk_level") or tc.risk_level or "medium"
        risk_wt = _RISK_WEIGHT.get(risk_level, 300)

        return (entity_rank, action_rank, -risk_wt)

    def _keyword_flow(self, text: str) -> str:
        """Détection du flux métier par mots-clés dans le titre (fallback pur)."""
        t = text.lower()
        for flow, keywords in _BUSINESS_FLOW_KEYWORDS.items():
            if any(kw in t for kw in keywords):
                return flow
        return "other"

    def _get_business_flow(self, tc: TestCase) -> str:
        """
        Priorité 1 : classification LLM stockée dans le TestPlan (relations chargées).
        Priorité 2 : détection par mots-clés sur le titre.
        """
        if tc.test_suite and tc.test_suite.test_plan:
            plan = tc.test_suite.test_plan
            if plan.tc_classifications and tc.tc_code in plan.tc_classifications:
                llm_flow = plan.tc_classifications[tc.tc_code].get("business_flow")
                if llm_flow:
                    return llm_flow
        return self._keyword_flow(tc.title or "")

    @staticmethod
    def _is_auth_title(title: str) -> bool:
        """A title that unambiguously belongs to authentication (account / login / logout)."""
        t = (title or "").lower()
        return (
            any(kw in t for kw in _LOGOUT_KEYWORDS)
            or any(kw in t for kw in _LOGIN_KEYWORDS)
            or any(kw in t for kw in _ACCOUNT_CREATE_KEYWORDS)
        )

    def _resolve_display_flow(self, tc: TestCase, tc_classifications: Dict[str, Any]) -> str:
        """Business flow used for the dependency graph. Deterministic AUTH override first:
        account creation / login / logout are ALWAYS 'authentication' even if the LLM labelled
        them 'crud' (a 'Create a new account' is auth, not a CRUD create)."""
        if self._is_auth_title(tc.title or ""):
            return "authentication"
        if tc.tc_code in tc_classifications:
            return tc_classifications[tc.tc_code].get("business_flow", "other")
        return self._get_business_flow(tc)

    def _prioritize_cases_by_risk(
        self,
        cases: List[TestCase],
        risk_map: Dict[str, Risk],
    ) -> List[TestCase]:
        """
        Priorise les TCs de manière HIÉRARCHIQUE.
        🔥 Utilise les classifications LLM si disponibles.
        """
        
        # ── Récupérer l'ordre LLM du plan ──
        flow_order = _BUSINESS_FLOW_RANK  # Défaut
        tc_classifications = {}
        
        if cases:
            first_tc = cases[0]
            if first_tc.test_suite and first_tc.test_suite.test_plan:
                plan = first_tc.test_suite.test_plan
                if plan.business_flow_order:
                    flow_order = plan.business_flow_order
                if plan.tc_classifications:
                    tc_classifications = plan.tc_classifications
        
        # ── Fonction de tri ──
        def _sort_key(tc: TestCase) -> Tuple[int, int, int]:
            clf = tc_classifications.get(tc.tc_code, {})
            return self._compute_order_key(tc, clf, flow_order)
        
        return sorted(cases, key=_sort_key)

    def _compute_priority_score(
        self,
        tc: TestCase,
        risk_map: Dict[str, Risk],
    ) -> int:
        """
        Calcule le score de priorité basé UNIQUEMENT sur le risque.
        
        ISTQB §5.2.3 :
            "Priority score = Risk weight of the associated product risk"
        """
        if tc.user_story_id:
            for risk in risk_map.values():
                if risk.user_story_id == tc.user_story_id and risk.level:
                    return _RISK_WEIGHT.get(risk.level, 0)
        
        return _RISK_WEIGHT.get(tc.risk_level or "medium", 300)

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
                active_tcs = [tc for tc in story_cases if tc.is_active]
                n_ac = len(ac_list)
                n_tc = len(active_tcs)
    
                ac_rows: List[TraceabilityACRow] = []
                story_covered_ac = 0
    
                for idx, ac_text in enumerate(ac_list):
                    covering_codes = []
                    for tc in active_tcs:
                        ac_indices = tc._covered_ac_indices or []
                        if idx in ac_indices:
                            covering_codes.append(tc.tc_code)
                    
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
                        story_covered_ac += 1
    
                story_coverage_pct = (story_covered_ac / n_ac * 100) if n_ac > 0 else 0.0
                rows.append(TraceabilityStoryRow(
                    user_story_id=story_id,
                    issue_key=story.issue_key,
                    title=story.title,
                    acceptance_criteria=ac_rows,
                    covered_cases=n_tc,
                    total_ac=n_ac,
                    coverage_pct=round(story_coverage_pct, 1),
                ))
    
            global_pct = round(covered_ac / total_ac * 100, 1) if total_ac > 0 else 0.0
    
            return TraceabilityMatrixSchema(
                rows=rows,
                total_stories=len(rows),
                total_ac=total_ac,
                covered_ac=covered_ac,
                global_coverage_pct=global_pct,
            )



    def _build_dependency_graph(
        self,
        cases: List[TestCase],
        dependencies: List[TestCaseDependency],
    ) -> DependencyGraphSchema:
        """
        Construit le graphe de dépendances.
        🔥 Utilise la classification LLM du plan.
        """
        tc_map: Dict[str, TestCase] = {tc.id: tc for tc in cases}
        
        # ── 🔥 RÉCUPÉRER L'ORDRE LLM ──
        flow_order = _BUSINESS_FLOW_RANK
        tc_classifications = {}
        
        if cases:
            first_tc = cases[0]
            if first_tc.test_suite and first_tc.test_suite.test_plan:
                plan = first_tc.test_suite.test_plan
                if plan.business_flow_order:
                    flow_order = plan.business_flow_order
                if plan.tc_classifications:
                    tc_classifications = plan.tc_classifications
        
        # ── Nœuds avec classification LLM ──
        flow_colors = {
            "authentication": "#FF4444",
            "dashboard": "#FF8C00",
            "crud": "#FFD700",
            "search": "#32CD32",
            "reporting": "#4169E1",
            "settings": "#8A2BE2",
            "notifications": "#FF69B4",
            "error_handling": "#EF4444",
            "monitoring": "#06B6D4",
            "api": "#10B981",
            "testing": "#8B5CF6",
            "other": "#808080",
        }
        
        nodes = []
        for tc in tc_map.values():   # tc_map déduplique par id
            flow = self._resolve_display_flow(tc, tc_classifications)
            risk = tc.risk_level or "medium"
            flow_rank = flow_order.get(flow, 99)
            risk_wt = _RISK_WEIGHT.get(risk, 300)

            nodes.append(DependencyNode(
                id=tc.id,
                tc_code=tc.tc_code,
                title=tc.title,
                priority=risk,
                test_type=tc.test_type,
                execution_order=tc.execution_order,
                test_suite_id=tc.test_suite_id,
                business_flow=flow,  # ← Flow du LLM
                flow_rank=flow_rank,
                risk_weight=risk_wt,
                status_color=flow_colors.get(flow, "#808080"),
            ))
        
        # ── Arêtes ──
        suite_tc_ids = {tc.id for tc in cases}
        edges: List[DependencyEdge] = []
        
        for dep in dependencies:
            if dep.source_test_case_id in suite_tc_ids and dep.target_test_case_id in suite_tc_ids:
                src = tc_map.get(dep.source_test_case_id)
                tgt = tc_map.get(dep.target_test_case_id)
                if src and tgt:
                    edges.append(DependencyEdge(
                        source=src.tc_code,
                        target=tgt.tc_code,
                        source_id=dep.source_test_case_id,
                        target_id=dep.target_test_case_id,
                        dependency_type=dep.dependency_type or "requires",
                        is_ai_generated=dep.is_ai_generated,
                    ))
        
        # ── Ordre d'exécution SIMPLE (pas de tri topologique) ──
        sorted_nodes = sorted(nodes, key=lambda n: (n.flow_rank or 99, -(n.risk_weight or 0)))
        execution_order = [n.tc_code for n in sorted_nodes]
        
        logger.info(
            f"[GRAPH] {len(nodes)} nodes, {len(edges)} edges, "
            f"order: {' → '.join(execution_order[:5])}..."
        )
        
        return DependencyGraphSchema(
            nodes=nodes,
            edges=edges,
            execution_order=execution_order,
        )

    def _compute_coverage(
        self,
        suite: TestSuite,
        risks: List[Risk],
        stories: List[UserStory],
    ) -> Dict[str, Any]:
        """
        Calcule le Risk Coverage pour la TestSuite.
        
        Avec 1 US = 1 Risk :
            Risk Coverage ≡ US Coverage (mathématiquement équivalent)
            On garde le Risk Coverage car c'est la métrique de MITIGATION.
        """
        cases = suite.test_cases or []
        active = [c for c in cases if c.is_active]
    
        by_priority: Dict[str, int] = dict(Counter(c.risk_level for c in active if c.risk_level))
        by_type: Dict[str, int] = dict(Counter(c.test_type for c in active if c.test_type))
        has_gherkin = sum(1 for c in active if c.gherkin_source)
        has_steps = sum(1 for c in active if c.steps)
    
        # ============================================================
        # RISK COVERAGE (seule métrique nécessaire)
        # ============================================================
        total_risks = len(risks)
        
        if total_risks > 0:
            # Récupérer les US qui ont des tests actifs
            covered_us_ids = {tc.user_story_id for tc in active if tc.user_story_id}
            
            # Un risque est couvert si SON US a des tests
            covered_risk_ids = {
                risk.id for risk in risks 
                if risk.user_story_id in covered_us_ids
            }
            
            risk_pct = round(len(covered_risk_ids) / total_risks * 100, 1)
            uncovered = [risk.id for risk in risks if risk.id not in covered_risk_ids]
        else:
            risk_pct = 100.0
            covered_risk_ids = set()
            uncovered = []
    
        # Déterminer le statut de mitigation
        if risk_pct >= 100:
            mitigation_status = "fully_mitigated"
        elif risk_pct >= 80:
            mitigation_status = "partially_mitigated"
        else:
            mitigation_status = "not_mitigated"
    
        # Sauvegarder dans la suite
        suite.risk_coverage_pct = risk_pct / 100  # Stocker en 0.0-1.0
        suite.risk_coverage_uncovered = uncovered
        suite.mitigation_status = mitigation_status
    
        # ✅ Retourner un DICT (pas un objet Pydantic)
        return {
            "risk_coverage_pct": risk_pct,
            "covered_risks": len(covered_risk_ids),
            "total_risks": total_risks,
            "uncovered_risk_ids": uncovered,
            "mitigation_status": mitigation_status,
            # Optionnel : stats supplémentaires
            "total_cases": len(cases),
            "active_cases": len(active),
            "by_priority": by_priority,
            "by_type": by_type,
            "has_gherkin": has_gherkin,
            "has_steps": has_steps,
        }


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
                "with_gherkin": sum(1 for c in cases if c.gherkin_source),            },
        }

    def _embed_plan(self, plan, suite: TestSuite) -> EmbeddedTestPlanSchema:
        return EmbeddedTestPlanSchema(
            id=plan.id,
            title=plan.title,
            status=plan.status,
            objective=plan.objective,
            in_scope=plan.in_scope,
            out_of_scope=plan.out_of_scope,
            environment=plan.environment,
            entry_criteria=plan.entry_criteria,
            exit_criteria=plan.exit_criteria,
            approach=plan.approach,
            start_date=str(plan.start_date) if plan.start_date else None,
            end_date=str(plan.end_date) if plan.end_date else None,
            approved_at=plan.approved_at,
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
            risk_level=tc.risk_level,
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
    
    async def _compute_us_ac_coverages(
        self,
        suite: TestSuite,
        stories: List[UserStory],
    ) -> List[Dict[str, Any]]:
        """
        Récupère l'AC Coverage depuis la table tc_coverages (une ligne par scenario_type).
        On garde la meilleure couverture par US.
        """
        result = await self.db.execute(
            select(TcCoverage).where(TcCoverage.test_plan_id == suite.test_plan_id)
        )
        coverage_rows = result.scalars().all()

        # Garder la meilleure couverture par user_story_id
        cov_by_us: Dict[str, TcCoverage] = {}
        for row in coverage_rows:
            if row.user_story_id not in cov_by_us or row.coverage_pct > cov_by_us[row.user_story_id].coverage_pct:
                cov_by_us[row.user_story_id] = row

        tcs_by_us: Dict[str, List[TestCase]] = defaultdict(list)
        for tc in (suite.test_cases or []):
            if tc.user_story_id:
                tcs_by_us[tc.user_story_id].append(tc)

        us_coverages = []
        for story in stories:
            has_tests = len(tcs_by_us.get(story.id, [])) > 0
            cov = cov_by_us.get(story.id)

            if cov:
                pct = round(cov.coverage_pct * 100, 1)
                covered = cov.covered_count
                total = cov.total_ac_count
                sufficient = cov.coverage_pct >= MIN_AC_COVERAGE
            elif has_tests:
                total = len(story.acceptance_criteria or [])
                covered = total
                pct = 100.0
                sufficient = True
            else:
                total = len(story.acceptance_criteria or [])
                covered = 0
                pct = 0.0
                sufficient = False

            us_coverages.append({
                "user_story_id": story.id,
                "issue_key": story.issue_key,
                "title": story.title,
                "ac_coverage_pct": pct,
                "covered_ac": covered,
                "total_ac": total,
                "uncovered_ac": [],
                "is_sufficient": sufficient,
                "has_tests": has_tests,
            })

        return us_coverages

# ============================================================
# Gather helper
# ============================================================

async def _gather(coro1, coro2, coro3):
    r1 = await coro1
    r2 = await coro2
    r3 = await coro3
    return r1, r2, r3