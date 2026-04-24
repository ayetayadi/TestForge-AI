from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import List, Optional, Dict, Any

from app.core.database import get_db
from app.services import test_case_service as test_case_service

router = APIRouter(prefix="/test-cases", tags=["Test Cases"])


# ============================================================
# SCHEMAS
# ============================================================

class TestCaseResponse(BaseModel):
    id: str
    tc_code: str
    title: str
    description: Optional[str] = None
    priority: Optional[str] = None
    user_story_id: Optional[str] = None
    user_story_version_id: Optional[str] = None
    issue_key: Optional[str] = None
    user_story_title: Optional[str] = None
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    tags: Optional[List[str]] = None
    preconditions: Optional[List[str]] = None
    postconditions: Optional[List[str]] = None
    steps: Optional[List[Dict]] = None
    gherkin_source: Optional[str] = None
    test_data: Optional[Dict] = None
    expected_results: Optional[List[str]] = None
    locators: Optional[List[Dict]] = None
    is_active: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class CreateTestCaseRequest(BaseModel):
    tc_code: str
    title: str
    description: Optional[str] = None
    priority: Optional[str] = None
    user_story_id: Optional[str] = None
    user_story_version_id: Optional[str] = None
    tags: Optional[List[str]] = []
    preconditions: Optional[List[str]] = []
    postconditions: Optional[List[str]] = []
    steps: Optional[List[Dict]] = []
    gherkin_source: Optional[str] = None
    test_data: Optional[Dict] = None
    expected_results: Optional[List[str]] = []
    locators: Optional[List[Dict]] = None


class UpdateTestCaseRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    user_story_id: Optional[str] = None
    user_story_version_id: Optional[str] = None
    tags: Optional[List[str]] = None
    preconditions: Optional[List[str]] = None
    postconditions: Optional[List[str]] = None
    steps: Optional[List[Dict]] = None
    gherkin_source: Optional[str] = None
    test_data: Optional[Dict] = None
    expected_results: Optional[List[str]] = None
    locators: Optional[List[Dict]] = None
    is_active: Optional[bool] = None


# ============================================================
# ENDPOINTS
# ============================================================

@router.get("/", response_model=List[TestCaseResponse])
async def get_all_test_cases_endpoint(
    db: AsyncSession = Depends(get_db),
    project_id: Optional[str] = Query(None, description="Filtrer par ID du projet"),
    user_story_id: Optional[str] = Query(None, description="Filtrer par ID de la user story"),
    search: Optional[str] = Query(None, description="Rechercher dans le titre ou le code"),
    status: Optional[List[str]] = Query(None, description="Filtrer par statut (active/archived)"),
    priority: Optional[List[str]] = Query(None, description="Filtrer par priorité"),
    tags: Optional[List[str]] = Query(None, description="Filtrer par tags"),
    has_script: Optional[bool] = Query(None, description="Avoir un script associé")
):
    """
    Récupère tous les test cases avec filtres.
    Retourne une liste simple (sans pagination).
    """
    try:
        result = await test_case_service.get_all_test_cases(
            db,
            project_id=project_id,
            user_story_id=user_story_id,
            search=search,
            status=status,
            priority=priority,
            tags=tags,
            has_script=has_script
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    

@router.get("/{test_case_id}", response_model=TestCaseResponse)
async def get_test_case_by_id_endpoint(
    test_case_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Récupère un test case par son ID.
    """
    try:
        test_case = await test_case_service.get_test_case_by_id(db, test_case_id)
        
        if not test_case:
            raise HTTPException(status_code=404, detail="Test case not found")
        
        return await test_case_service.format_for_frontend(test_case, db)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/by-code/{tc_code}", response_model=TestCaseResponse)
async def get_test_case_by_code_endpoint(
    tc_code: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Récupère un test case par son code (ex: TC-AUTH-001).
    """
    try:
        test_case = await test_case_service.get_test_case_by_code(db, tc_code)
        
        if not test_case:
            raise HTTPException(status_code=404, detail="Test case not found")
        
        return await test_case_service.format_for_frontend(test_case, db)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/user-story/{user_story_id}", response_model=List[TestCaseResponse])
async def get_test_cases_by_user_story_endpoint(
    user_story_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Récupère tous les test cases d'une user story.
    """
    try:
        test_cases = await test_case_service.get_test_cases_by_user_story(db, user_story_id)
        
        formatted_cases = []
        for tc in test_cases:
            formatted = await test_case_service.format_for_frontend(tc, db)
            formatted_cases.append(formatted)
        
        return formatted_cases
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/", response_model=TestCaseResponse)
async def create_test_case_endpoint(
    request: CreateTestCaseRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Crée un nouveau test case.
    """
    try:
        test_case = await test_case_service.create_test_case(db, request.model_dump())
        await db.commit()
        await db.refresh(test_case)
        
        return await test_case_service.format_for_frontend(test_case, db)
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{test_case_id}", response_model=TestCaseResponse)
async def update_test_case_endpoint(
    test_case_id: str,
    request: UpdateTestCaseRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Met à jour un test case existant.
    """
    try:
        test_case = await test_case_service.update_test_case(
            db,
            test_case_id, 
            request.model_dump(exclude_none=True)
        )
        
        if not test_case:
            raise HTTPException(status_code=404, detail="Test case not found")
        
        await db.commit()
        await db.refresh(test_case)
        
        return await test_case_service.format_for_frontend(test_case, db)
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{test_case_id}")
async def delete_test_case_endpoint(
    test_case_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Supprime (soft delete) un test case.
    """
    try:
        success = await test_case_service.delete_test_case(db, test_case_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="Test case not found")
        
        await db.commit()
        return {"message": "Test case deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))