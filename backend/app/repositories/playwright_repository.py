import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, desc

from app.models.test_case import TestCase
from app.models.playwright_script_version import PlaywrightScriptVersion
from app.models.test_run import TestRun
from app.models.test_result import TestResult
from app.models.test_step_result import TestStepResult
from app.models.enums import (
    ScriptSource, ScriptValidationStatus,
    TestRunStatus, TestResultStatus, StepType, StepStatus
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
    """Récupère le prochain numéro de version pour un test case."""
    result = await db.execute(
        select(PlaywrightScriptVersion.version_number)
        .where(PlaywrightScriptVersion.test_case_id == test_case_id)
        .order_by(desc(PlaywrightScriptVersion.version_number))
        .limit(1)
    )
    last_version = result.scalar_one_or_none()
    return (last_version or 0) + 1


async def deactivate_all_scripts(db: AsyncSession, test_case_id: str) -> None:
    """Désactive toutes les versions de script pour un test case."""
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
    """Sauvegarde une nouvelle version de script."""
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
    
    logger.info(
        f"Script saved: test_case={test_case_id}, "
        f"version={next_version}, source={source.value}, "
        f"placeholders={placeholder_count}"
    )
    
    return script_version


async def get_active_script(db: AsyncSession, test_case_id: str) -> Optional[PlaywrightScriptVersion]:
    """Récupère la version active du script."""
    result = await db.execute(
        select(PlaywrightScriptVersion)
        .where(PlaywrightScriptVersion.test_case_id == test_case_id)
        .where(PlaywrightScriptVersion.is_active == True)
    )
    return result.scalar_one_or_none()


async def get_script_version(db: AsyncSession, script_version_id: str) -> Optional[PlaywrightScriptVersion]:
    """Récupère une version spécifique de script."""
    result = await db.execute(
        select(PlaywrightScriptVersion)
        .where(PlaywrightScriptVersion.id == script_version_id)
    )
    return result.scalar_one_or_none()


async def get_all_scripts(db: AsyncSession, test_case_id: str, limit: int = 50) -> List[PlaywrightScriptVersion]:
    """Récupère toutes les versions d'un script."""
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
    """Met à jour le statut de validation d'un script."""
    await db.execute(
        update(PlaywrightScriptVersion)
        .where(PlaywrightScriptVersion.id == script_version_id)
        .values(
            validation_status=validation_status,
            validation_error=validation_error
        )
    )
    await db.flush()


# ============================================================
# TEST RUN
# ============================================================

async def create_test_run(
    db: AsyncSession,
    script_version_id: str,
    base_url: str,
    browser: str = "chromium",
    viewport: str = "1920x1080",
    timeout_ms: int = 30000,
    headless: bool = True,
    record_video: bool = False,
    capture_screenshots_on_failure: bool = True
) -> TestRun:
    """Crée un nouveau TestRun."""
    test_run = TestRun(
        script_version_id=script_version_id,
        base_url=base_url,
        browser=browser,
        viewport=viewport,
        timeout_ms=timeout_ms,
        headless=headless,
        record_video=record_video,
        capture_screenshots_on_failure=capture_screenshots_on_failure,
        status=TestRunStatus.RUNNING,
        started_at=datetime.utcnow()
    )
    
    db.add(test_run)
    await db.flush()
    
    logger.info(f"TestRun created: {test_run.id} for script {script_version_id}")
    return test_run


async def update_test_run(
    db: AsyncSession,
    test_run_id: str,
    status: Optional[TestRunStatus] = None,
    duration: Optional[float] = None,
    completed_at: Optional[datetime] = None
) -> None:
    """Met à jour un TestRun."""
    values = {}
    if status is not None:
        values["status"] = status
    if duration is not None:
        values["duration"] = duration
    if completed_at is not None:
        values["completed_at"] = completed_at
    elif status is not None and status != TestRunStatus.RUNNING:
        values["completed_at"] = datetime.utcnow()
    
    if values:
        await db.execute(
            update(TestRun)
            .where(TestRun.id == test_run_id)
            .values(**values)
        )
        await db.flush()
        logger.info(f"TestRun {test_run_id} updated: {values}")


async def get_test_run(db: AsyncSession, test_run_id: str) -> Optional[TestRun]:
    """Récupère un TestRun avec ses relations."""
    result = await db.execute(
        select(TestRun)
        .where(TestRun.id == test_run_id)
    )
    return result.scalar_one_or_none()


async def get_test_runs_by_script(
    db: AsyncSession,
    script_version_id: str,
    limit: int = 20
) -> List[TestRun]:
    """Récupère tous les runs pour un script."""
    result = await db.execute(
        select(TestRun)
        .where(TestRun.script_version_id == script_version_id)
        .order_by(desc(TestRun.started_at))
        .limit(limit)
    )
    return result.scalars().all()


# ============================================================
# TEST STEPS
# ============================================================

async def add_step(
    db: AsyncSession,
    test_run_id: str,
    step_order: int,
    step_type: StepType,
    content: str,
    tool_name: Optional[str] = None,
    tool_args: Optional[dict] = None,
    tool_result: Optional[dict] = None,
    status: StepStatus = StepStatus.SUCCESS,
    duration: Optional[float] = None,
    screenshot_b64: Optional[str] = None
) -> TestStepResult:
    """Ajoute un step (think/act/observe) au TestRun."""
    step = TestStepResult(
        test_run_id=test_run_id,
        step_order=step_order,
        step_type=step_type,
        content=content,
        tool_name=tool_name,
        tool_args=tool_args,
        tool_result=tool_result,
        status=status,
        duration=duration,
        screenshot_b64=screenshot_b64
    )
    
    db.add(step)
    await db.flush()
    
    return step


async def add_steps_batch(
    db: AsyncSession,
    test_run_id: str,
    steps: List[Dict[str, Any]]
) -> List[TestStepResult]:
    """Ajoute plusieurs steps en batch."""
    step_objects = []
    for step_data in steps:
        step = TestStepResult(
            test_run_id=test_run_id,
            **step_data
        )
        db.add(step)
        step_objects.append(step)
    
    await db.flush()
    logger.info(f"Added {len(steps)} steps to test_run {test_run_id}")
    return step_objects


async def get_steps(db: AsyncSession, test_run_id: str) -> List[TestStepResult]:
    """Récupère tous les steps d'un TestRun."""
    result = await db.execute(
        select(TestStepResult)
        .where(TestStepResult.test_run_id == test_run_id)
        .order_by(TestStepResult.step_order)
    )
    return result.scalars().all()


# ============================================================
# TEST RESULT
# ============================================================

async def save_test_result(
    db: AsyncSession,
    test_run_id: str,
    status: TestResultStatus,
    justification: Optional[str] = None,
    error_message: Optional[str] = None,
    screenshot_b64: Optional[str] = None,
    duration: Optional[float] = None,
    step_count: Optional[int] = None
) -> TestResult:
    """Sauvegarde le résultat final d'un TestRun."""
    test_result = TestResult(
        test_run_id=test_run_id,
        status=status,
        justification=justification,
        error_message=error_message,
        screenshot_b64=screenshot_b64,
        duration=duration,
        step_count=step_count,
        completed_at=datetime.utcnow()
    )
    
    db.add(test_result)
    await db.flush()
    
    logger.info(f"TestResult saved: {test_run_id} → {status.value}")
    return test_result


async def get_test_result(db: AsyncSession, test_run_id: str) -> Optional[TestResult]:
    """Récupère le résultat d'un TestRun."""
    result = await db.execute(
        select(TestResult)
        .where(TestResult.test_run_id == test_run_id)
    )
    return result.scalar_one_or_none()


# ============================================================
# TRANSACTIONS
# ============================================================

async def commit(db: AsyncSession) -> None:
    """Commit la transaction courante."""
    await db.commit()


async def rollback(db: AsyncSession) -> None:
    """Rollback la transaction courante."""
    await db.rollback()