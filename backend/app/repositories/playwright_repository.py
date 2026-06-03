import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, desc, func as sql_func

from app.models.test_case import TestCase
from app.models.playwright_script_version import PlaywrightScriptVersion
from app.models.test_execution import TestExecution
from app.models.test_case_result import TestCaseResult
from app.models.enums import (
    ScriptSource, ScriptValidationStatus,
    TestExecutionStatus, TestCaseResultStatus,
)

logger = logging.getLogger(__name__)


# ============================================================
# TEST CASE
# ============================================================

async def get_test_case(db: AsyncSession, test_case_id: str) -> Optional[TestCase]:
    """Récupère un test case par son ID."""
    result = await db.execute(
        select(TestCase).where(TestCase.id == test_case_id)
    )
    return result.scalar_one_or_none()


async def update_test_case_after_execution(
    db: AsyncSession,
    test_case_id: str,
    active_script_id: str,
    locator_mapping: Dict[str, str],
) -> None:
    """
    After a successful execution, pin the active script on the TestCase and
    persist the discovered locators so future generation can reuse them.
    """
    locators = [
        {"name": desc, "selector": locator, "reliability": "high"}
        for desc, locator in locator_mapping.items()
        if locator
    ]

    values: Dict[str, Any] = {"active_playwright_script_id": active_script_id}
    if locators:
        values["locators"] = locators

    await db.execute(
        update(TestCase)
        .where(TestCase.id == test_case_id)
        .values(**values)
    )
    await db.flush()
    logger.info(
        f"TestCase {test_case_id} updated: active_script={active_script_id}, "
        f"{len(locators)} locators saved"
    )


async def get_test_case_by_tc_code(db: AsyncSession, tc_code: str) -> Optional[TestCase]:
    """Récupère un test case par son code TC-XXX."""
    result = await db.execute(
        select(TestCase).where(TestCase.tc_code == tc_code)
    )
    return result.scalar_one_or_none()


async def get_test_case_with_active_script(db: AsyncSession, test_case_id: str) -> Optional[Dict[str, Any]]:
    """Récupère un test case avec son script actif."""
    test_case = await get_test_case(db, test_case_id)
    if not test_case:
        return None

    active_script = await get_active_script(db, test_case_id)

    return {
        "test_case": test_case,
        "active_script": active_script
    }


# ============================================================
# SCRIPT VERSIONS
# ============================================================

async def get_next_version_number(db: AsyncSession, test_case_id: str) -> int:
    result = await db.execute(
        select(PlaywrightScriptVersion.version_number)
        .where(PlaywrightScriptVersion.test_case_id == test_case_id)
        .order_by(desc(PlaywrightScriptVersion.version_number))
        .limit(1)
    )
    last_version = result.scalar_one_or_none()
    return (last_version or 0) + 1


async def deactivate_all_scripts(db: AsyncSession, test_case_id: str) -> None:
    await db.execute(
        update(PlaywrightScriptVersion)
        .where(PlaywrightScriptVersion.test_case_id == test_case_id)
        .where(PlaywrightScriptVersion.is_active == True)
        .values(is_active=False)
    )


async def save_script(
    db: AsyncSession,
    test_case_id: str,
    script_content: str,
    source: ScriptSource,
    placeholder_count: int = 0,
    validation_status: ScriptValidationStatus = ScriptValidationStatus.NOT_VALIDATED,
    validation_error: Optional[str] = None,
    is_active: bool = True
) -> PlaywrightScriptVersion:
    next_version = await get_next_version_number(db, test_case_id)

    if is_active:
        await deactivate_all_scripts(db, test_case_id)

    script_version = PlaywrightScriptVersion(
        test_case_id=test_case_id,
        version_number=next_version,
        script_content=script_content,
        is_active=is_active,
        validation_status=validation_status,
        validation_error=validation_error,
        source=source,
        placeholder_count=placeholder_count
    )

    db.add(script_version)
    await db.flush()

    if is_active:
        await db.execute(
            update(TestCase)
            .where(TestCase.id == test_case_id)
            .values(active_playwright_script_id=script_version.id)
        )
        await db.flush()

    logger.info(
        f"Script saved: test_case={test_case_id}, "
        f"version={next_version}, source={source.value}, "
        f"placeholders={placeholder_count}"
    )
    return script_version


async def get_active_script(db: AsyncSession, test_case_id: str) -> Optional[PlaywrightScriptVersion]:
    result = await db.execute(
        select(PlaywrightScriptVersion)
        .where(PlaywrightScriptVersion.test_case_id == test_case_id)
        .where(PlaywrightScriptVersion.is_active == True)
    )
    return result.scalar_one_or_none()


async def get_script_version(db: AsyncSession, script_version_id: str) -> Optional[PlaywrightScriptVersion]:
    result = await db.execute(
        select(PlaywrightScriptVersion)
        .where(PlaywrightScriptVersion.id == script_version_id)
    )
    return result.scalar_one_or_none()


async def get_all_scripts(db: AsyncSession, test_case_id: str, limit: int = 50) -> List[PlaywrightScriptVersion]:
    result = await db.execute(
        select(PlaywrightScriptVersion)
        .where(PlaywrightScriptVersion.test_case_id == test_case_id)
        .order_by(desc(PlaywrightScriptVersion.version_number))
        .limit(limit)
    )
    return result.scalars().all()


async def update_script_validation(
    db: AsyncSession,
    script_version_id: str,
    validation_status: ScriptValidationStatus,
    validation_error: Optional[str] = None
) -> None:
    await db.execute(
        update(PlaywrightScriptVersion)
        .where(PlaywrightScriptVersion.id == script_version_id)
        .values(
            validation_status=validation_status,
            validation_error=validation_error
        )
    )
    await db.flush()


async def delete_script_version(
    db: AsyncSession,
    script_version_id: str,
) -> dict:
    script = await get_script_version(db, script_version_id)
    if not script:
        return {"deleted": False, "reason": "not_found"}

    test_case_id = script.test_case_id
    was_active = script.is_active

    await db.delete(script)
    await db.flush()

    new_active_id = None
    if was_active:
        result = await db.execute(
            select(PlaywrightScriptVersion)
            .where(PlaywrightScriptVersion.test_case_id == test_case_id)
            .order_by(desc(PlaywrightScriptVersion.version_number))
            .limit(1)
        )
        next_version = result.scalar_one_or_none()
        if next_version:
            next_version.is_active = True
            new_active_id = str(next_version.id)

        await db.execute(
            update(TestCase)
            .where(TestCase.id == test_case_id)
            .values(active_playwright_script_id=new_active_id)
        )
        await db.flush()

    return {
        "deleted": True,
        "test_case_id": test_case_id,
        "was_active": was_active,
        "new_active_script_id": new_active_id,
    }


async def delete_all_scripts_for_test_case(
    db: AsyncSession,
    test_case_id: str,
) -> dict:
    result = await db.execute(
        select(PlaywrightScriptVersion)
        .where(PlaywrightScriptVersion.test_case_id == test_case_id)
    )
    versions = result.scalars().all()
    if not versions:
        return {"deleted": False, "reason": "no_scripts"}

    for v in versions:
        await db.delete(v)
    await db.flush()

    await db.execute(
        update(TestCase)
        .where(TestCase.id == test_case_id)
        .values(active_playwright_script_id=None)
    )
    await db.flush()

    return {"deleted": True, "count": len(versions), "test_case_id": test_case_id}


# ============================================================
# TEST EXECUTION  (la session de lancement de suite)
# ============================================================

async def create_test_execution(
    db: AsyncSession,
    suite_id: str,
    app_url: str,
    browser: str = "chromium",
    headless: bool = True,
    stop_on_failure: bool = False,
    model_id: Optional[str] = None,
    triggered_by: Optional[str] = None,
    total_count: int = 0,
) -> TestExecution:
    """Crée une nouvelle TestExecution (statut=running)."""
    execution = TestExecution(
        suite_id=suite_id,
        app_url=app_url,
        browser=browser,
        headless=headless,
        stop_on_failure=stop_on_failure,
        model_id=model_id,
        triggered_by=triggered_by,
        total_count=total_count,
        status=TestExecutionStatus.RUNNING,
        started_at=datetime.utcnow(),
    )
    db.add(execution)
    await db.flush()
    logger.info(f"TestExecution created: {execution.id} for suite {suite_id} ({total_count} TCs)")
    return execution


async def update_test_execution(
    db: AsyncSession,
    execution_id: str,
    *,
    status: Optional[TestExecutionStatus] = None,
    completed_at: Optional[datetime] = None,
    duration: Optional[float] = None,
    passed_count: Optional[int] = None,
    failed_count: Optional[int] = None,
    skipped_count: Optional[int] = None,
    error_count: Optional[int] = None,
) -> None:
    values: Dict[str, Any] = {}
    if status is not None:        values["status"] = status
    if completed_at is not None:  values["completed_at"] = completed_at
    if duration is not None:      values["duration"] = duration
    if passed_count is not None:  values["passed_count"] = passed_count
    if failed_count is not None:  values["failed_count"] = failed_count
    if skipped_count is not None: values["skipped_count"] = skipped_count
    if error_count is not None:   values["error_count"] = error_count

    if values:
        await db.execute(
            update(TestExecution).where(TestExecution.id == execution_id).values(**values)
        )
        await db.flush()


async def get_test_execution(db: AsyncSession, execution_id: str) -> Optional[TestExecution]:
    result = await db.execute(
        select(TestExecution).where(TestExecution.id == execution_id)
    )
    return result.scalar_one_or_none()


async def delete_test_execution(db: AsyncSession, execution_id: str) -> bool:
    ex = await get_test_execution(db, execution_id)
    if not ex:
        return False
    await db.delete(ex)
    await db.flush()
    return True


async def close_test_execution(
    db: AsyncSession,
    execution_id: str,
    closed_by: Optional[str] = None,
) -> Optional[TestExecution]:
    """Marque une TestExecution comme clôturée."""
    await db.execute(
        update(TestExecution)
        .where(TestExecution.id == execution_id)
        .values(is_closed=True, closed_at=datetime.utcnow(), closed_by=closed_by)
    )
    await db.flush()
    return await get_test_execution(db, execution_id)


async def reopen_test_execution(
    db: AsyncSession,
    execution_id: str,
) -> Optional[TestExecution]:
    """Réouvre une TestExecution clôturée."""
    await db.execute(
        update(TestExecution)
        .where(TestExecution.id == execution_id)
        .values(is_closed=False, closed_at=None, closed_by=None)
    )
    await db.flush()
    return await get_test_execution(db, execution_id)


async def list_test_executions(
    db: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
    suite_id: Optional[str] = None,
    status: Optional[TestExecutionStatus] = None,
    project_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Liste paginée des TestExecution avec compteurs."""
    from app.models.test_suite import TestSuite
    from app.models.test_plan import TestPlan

    base_query = select(TestExecution).order_by(desc(TestExecution.started_at))
    count_query = select(sql_func.count(TestExecution.id))

    if suite_id:
        base_query  = base_query.where(TestExecution.suite_id == suite_id)
        count_query = count_query.where(TestExecution.suite_id == suite_id)

    if status:
        base_query  = base_query.where(TestExecution.status == status)
        count_query = count_query.where(TestExecution.status == status)

    if project_ids is not None:
        base_query = (
            base_query
            .join(TestSuite, TestExecution.suite_id == TestSuite.id)
            .join(TestPlan, TestSuite.test_plan_id == TestPlan.id)
            .where(TestPlan.project_id.in_(project_ids))
        )
        count_query = (
            count_query
            .join(TestSuite, TestExecution.suite_id == TestSuite.id)
            .join(TestPlan, TestSuite.test_plan_id == TestPlan.id)
            .where(TestPlan.project_id.in_(project_ids))
        )

    total = (await db.execute(count_query)).scalar_one()
    rows = (await db.execute(base_query.limit(limit).offset(offset))).scalars().all()

    return {"items": rows, "total": total}


async def get_execution_global_stats(
    db: AsyncSession,
    project_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Stats globales (toutes executions confondues), filtrées par projets."""
    from app.models.test_suite import TestSuite
    from app.models.test_plan import TestPlan

    q = select(
        sql_func.count(TestExecution.id).label("total"),
        sql_func.sum(TestExecution.passed_count).label("passed"),
        sql_func.sum(TestExecution.failed_count).label("failed"),
        sql_func.sum(TestExecution.skipped_count).label("skipped"),
        sql_func.sum(TestExecution.error_count).label("error"),
        sql_func.avg(TestExecution.duration).label("avg_duration"),
    )
    if project_ids is not None:
        q = (
            q.join(TestSuite, TestExecution.suite_id == TestSuite.id)
             .join(TestPlan, TestSuite.test_plan_id == TestPlan.id)
             .where(TestPlan.project_id.in_(project_ids))
        )
    row = (await db.execute(q)).first()

    running_q = select(sql_func.count(TestExecution.id)).where(
        TestExecution.status == TestExecutionStatus.RUNNING
    )
    if project_ids is not None:
        running_q = (
            running_q.join(TestSuite, TestExecution.suite_id == TestSuite.id)
                     .join(TestPlan, TestSuite.test_plan_id == TestPlan.id)
                     .where(TestPlan.project_id.in_(project_ids))
        )
    running = (await db.execute(running_q)).scalar_one() or 0

    total    = int(row.total or 0)
    passed   = int(row.passed or 0)
    failed   = int(row.failed or 0)
    skipped  = int(row.skipped or 0)
    error    = int(row.error or 0)
    avg_dur  = float(row.avg_duration or 0)
    tc_total = passed + failed + skipped + error

    return {
        "total_runs":   total,
        "running":      running,
        "passed":       passed,
        "failed":       failed,
        "skipped":      skipped,
        "error":        error,
        "pass_rate":    round(passed / max(tc_total, 1) * 100, 1),
        "avg_duration": round(avg_dur, 1),
    }


# ============================================================
# TEST CASE RESULT  (résultat d'UN TC dans UNE TestExecution)
# ============================================================

async def create_tc_result(
    db: AsyncSession,
    execution_id: str,
    test_case_id: str,
    execution_order: int,
    script_version_id: Optional[str] = None,
) -> TestCaseResult:
    """Crée un TestCaseResult (statut=skipped par défaut, à mettre à jour ensuite)."""
    tc_result = TestCaseResult(
        execution_id=execution_id,
        test_case_id=test_case_id,
        script_version_id=script_version_id,
        execution_order=execution_order,
        status=TestCaseResultStatus.SKIPPED,
        steps=[],
        started_at=datetime.utcnow(),
    )
    db.add(tc_result)
    await db.flush()
    return tc_result


async def update_tc_result(
    db: AsyncSession,
    tc_result_id: str,
    *,
    status: Optional[TestCaseResultStatus] = None,
    steps: Optional[List[Dict[str, Any]]] = None,
    steps_passed: Optional[int] = None,
    steps_failed: Optional[int] = None,
    justification: Optional[str] = None,
    error_message: Optional[str] = None,
    screenshot_b64: Optional[str] = None,
    duration: Optional[float] = None,
    completed_at: Optional[datetime] = None,
    script_version_id: Optional[str] = None,
) -> None:
    values: Dict[str, Any] = {}
    if status is not None:            values["status"] = status
    if steps is not None:             values["steps"] = steps
    if steps_passed is not None:      values["steps_passed"] = steps_passed
    if steps_failed is not None:      values["steps_failed"] = steps_failed
    if justification is not None:     values["justification"] = justification
    if error_message is not None:     values["error_message"] = error_message
    if screenshot_b64 is not None:    values["screenshot_b64"] = screenshot_b64
    if duration is not None:          values["duration"] = duration
    if completed_at is not None:      values["completed_at"] = completed_at
    if script_version_id is not None: values["script_version_id"] = script_version_id

    if values:
        await db.execute(
            update(TestCaseResult).where(TestCaseResult.id == tc_result_id).values(**values)
        )
        await db.flush()


async def get_tc_result(db: AsyncSession, tc_result_id: str) -> Optional[TestCaseResult]:
    result = await db.execute(
        select(TestCaseResult).where(TestCaseResult.id == tc_result_id)
    )
    return result.scalar_one_or_none()


async def list_tc_results_for_execution(
    db: AsyncSession,
    execution_id: str,
) -> List[TestCaseResult]:
    """Tous les TestCaseResult d'une exécution, dans l'ordre d'exécution."""
    result = await db.execute(
        select(TestCaseResult)
        .where(TestCaseResult.execution_id == execution_id)
        .order_by(TestCaseResult.execution_order)
    )
    return result.scalars().all()


async def get_latest_tc_result_for_test_case(
    db: AsyncSession,
    test_case_id: str,
) -> Optional[TestCaseResult]:
    """Le dernier résultat connu pour un TC (toutes exécutions confondues)."""
    result = await db.execute(
        select(TestCaseResult)
        .where(TestCaseResult.test_case_id == test_case_id)
        .order_by(desc(TestCaseResult.created_at))
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_tc_results_for_test_case(
    db: AsyncSession,
    test_case_id: str,
    limit: int = 20,
) -> List[TestCaseResult]:
    """Historique des résultats d'un TC, toutes exécutions confondues."""
    result = await db.execute(
        select(TestCaseResult)
        .where(TestCaseResult.test_case_id == test_case_id)
        .order_by(desc(TestCaseResult.created_at))
        .limit(limit)
    )
    return result.scalars().all()


# ============================================================
# TRANSACTIONS
# ============================================================

async def commit(db: AsyncSession) -> None:
    await db.commit()


async def rollback(db: AsyncSession) -> None:
    await db.rollback()
