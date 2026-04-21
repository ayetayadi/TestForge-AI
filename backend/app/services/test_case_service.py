import logging
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import test_case_repository as repo
from app.models.test_case import TestCase
from app.models.user_story_version import UserStoryVersion
from app.models.enums import StoryDecision
from app.models.user_story import UserStory

logger = logging.getLogger(__name__)


async def get_all_test_cases(
    db: AsyncSession,
    project_id: Optional[str] = None,
    search: Optional[str] = None,
    status: Optional[List[str]] = None,
    priority: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    has_script: Optional[bool] = None
) -> List[Dict[str, Any]]:  # ← Changement: retourne List, pas Dict
    """
    Récupère tous les test cases avec filtres.
    Retourne une LISTE, pas un objet paginé.
    """
    
    # Récupérer tous les items (sans pagination)
    items = await repo.get_all_test_cases(
        db,
        project_id=project_id,
        search=search,
        status=status,
        priority=priority,
        tags=tags,
        has_script=has_script,
        limit=1000,  # ← Prendre beaucoup d'items
        offset=0
    )
    
    # Formater chaque item
    formatted_items = []
    for item in items:
        formatted = await format_for_frontend(item, db)
        formatted_items.append(formatted)
    
    # ✅ Retourner directement la liste
    return formatted_items

async def get_test_case_by_id(db: AsyncSession, test_case_id: str) -> Optional[TestCase]:
    """Récupère un test case par son ID."""
    return await repo.get_test_case_by_id(db, test_case_id)


async def get_test_case_by_code(db: AsyncSession, tc_code: str) -> Optional[TestCase]:
    """Récupère un test case par son code."""
    return await repo.get_test_case_by_code(db, tc_code)


async def get_test_cases_by_user_story(db: AsyncSession, user_story_id: str) -> List[TestCase]:
    """Récupère tous les test cases d'une user story."""
    return await repo.get_test_cases_by_user_story_id(db, user_story_id)


async def create_test_case(db: AsyncSession, data: Dict[str, Any]) -> TestCase:
    """Crée un nouveau test case."""
    if not data.get("tc_code"):
        raise ValueError("tc_code est requis")
    if not data.get("title"):
        raise ValueError("title est requis")
    
    # Validation : soit user_story_id soit user_story_version_id
    if not data.get("user_story_id") and not data.get("user_story_version_id"):
        raise ValueError("Soit user_story_id soit user_story_version_id est requis")
    
    # Si on utilise une version, vérifier qu'elle est approuvée
    if data.get("user_story_version_id"):
        version = await db.get(UserStoryVersion, data["user_story_version_id"])
        if not version:
            raise ValueError("UserStoryVersion non trouvée")
        if version.decision_status != StoryDecision.APPROVED:
            raise ValueError("Seules les versions approuvées peuvent être utilisées pour créer des tests")
    
    return await repo.create_test_case(db, data)


async def update_test_case(db: AsyncSession, test_case_id: str, data: Dict[str, Any]) -> Optional[TestCase]:
    """Met à jour un test case."""
    return await repo.update_test_case(db, test_case_id, data)


async def delete_test_case(db: AsyncSession, test_case_id: str) -> bool:
    """Supprime (soft delete) un test case."""
    return await repo.delete_test_case(db, test_case_id)


async def get_source_user_story_info(db: AsyncSession, test_case: TestCase) -> Dict[str, Any]:
    """Récupère la user story source (directe ou via version) avec infos projet."""
    
    result = {
        "user_story_id": None,
        "issue_key": None,
        "title": None,
        "version_id": None,
        "version_number": None,
        "is_refined": False,
        "project_id": None,
        "project_name": None
    }
    
    if test_case.user_story_version_id:
        # Cas refinement: récupérer la user story parente via la version
        version = await db.get(UserStoryVersion, test_case.user_story_version_id)
        if version:
            user_story = version.user_story
            result["user_story_id"] = user_story.id if user_story else None
            result["issue_key"] = user_story.issue_key if user_story else None
            result["title"] = user_story.title if user_story else None
            result["version_id"] = test_case.user_story_version_id
            result["version_number"] = version.version_number if hasattr(version, 'version_number') else None
            result["is_refined"] = True
            
            # Récupérer le projet
            if user_story and user_story.project_id:
                from app.repositories import project_repository
                project = await project_repository.get_project_by_id(db, user_story.project_id)
                result["project_id"] = project.id if project else None
                result["project_name"] = project.project_name if project else None
                
    elif test_case.user_story_id:
        # Cas direct: user story classique
        user_story = await db.get(UserStory, test_case.user_story_id)
        if user_story:
            result["user_story_id"] = user_story.id
            result["issue_key"] = user_story.issue_key if user_story else None
            result["title"] = user_story.title
            result["version_id"] = None
            result["version_number"] = None
            result["is_refined"] = False
            
            # Récupérer le projet
            if user_story.project_id:
                from app.repositories import project_repository
                project = await project_repository.get_project_by_id(db, user_story.project_id)
                result["project_id"] = project.id if project else None
                result["project_name"] = project.project_name if project else None
    
    return result


async def format_for_frontend(test_case: TestCase, db: AsyncSession) -> Dict[str, Any]:
    """Formate un test case pour l'envoi au frontend avec infos user story."""
    
    # Récupérer les infos de la user story source
    user_story_info = await get_source_user_story_info(db, test_case)
    
    return {
        "id": test_case.id,
        "tc_code": test_case.tc_code,
        "title": test_case.title,
        "description": test_case.description,
        "priority": test_case.priority,
        "user_story_id": test_case.user_story_id,
        "user_story_version_id": test_case.user_story_version_id,
        # Infos User Story enrichies
        "issue_key": user_story_info.get("issue_key"),
        "user_story_title": user_story_info.get("title"),
        "project_id": user_story_info.get("project_id"),
        "project_name": user_story_info.get("project_name"),
        # Contenu structuré
        "tags": test_case.tags,
        "preconditions": test_case.preconditions,
        "postconditions": test_case.postconditions,
        "steps": test_case.steps,
        "gherkin_source": test_case.gherkin_source,
        "test_data": test_case.test_data,
        "expected_results": test_case.expected_results,
        "locators": test_case.locators,
        "is_active": test_case.is_active,
        "created_at": test_case.created_at.isoformat() if test_case.created_at else None,
        "updated_at": test_case.updated_at.isoformat() if test_case.updated_at else None,
    }