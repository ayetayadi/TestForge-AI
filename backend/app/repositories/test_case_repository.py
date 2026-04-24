from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import Integer, select, or_, func, case
from typing import List, Optional
from sqlalchemy.orm import joinedload
from app.models.test_case import TestCase
from app.models.user_story import UserStory
from app.models.user_story_version import UserStoryVersion

async def get_all_test_cases(
    db: AsyncSession,
    project_id: Optional[str] = None,
    user_story_id: Optional[str] = None,
    search: Optional[str] = None,
    status: Optional[List[str]] = None,
    priority: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    has_script: Optional[bool] = None,
    order_by: str = "created_at",
    order_direction: str = "desc",
    limit: int = 100,
    offset: int = 0
) -> List[TestCase]:
    """Récupère les test cases avec filtres optionnels et tri.
    
    Args:
        order_by: Champ de tri (created_at, updated_at, tc_code, title)
        order_direction: Direction du tri (asc, desc)
    """
    
    from sqlalchemy.orm import joinedload
    from sqlalchemy import func
    
    query = select(TestCase).where(TestCase.is_active == True)
    
    # Joindre UserStory pour pouvoir filtrer par projet
    query = query.outerjoin(
        UserStory, 
        TestCase.user_story_id == UserStory.id
    ).options(
        joinedload(TestCase.user_story)
    )
    
    # Filtre par project_id
    if project_id:
        query = query.where(UserStory.project_id == project_id)

    # Filtre par user_story_id
    if user_story_id:
        query = query.where(TestCase.user_story_id == user_story_id)

    # Filtre search
    if search:
        query = query.where(
            or_(
                TestCase.title.ilike(f"%{search}%"),
                TestCase.tc_code.ilike(f"%{search}%")
            )
        )
    
    # Filtre status
    if status:
        active_filter = False
        archived_filter = False
        for s in status:
            if s == 'active':
                active_filter = True
            elif s == 'archived':
                archived_filter = True
        
        if active_filter and not archived_filter:
            query = query.where(TestCase.is_active == True)
        elif archived_filter and not active_filter:
            query = query.where(TestCase.is_active == False)
    
    # Filtre priority (via priority column)
    if priority:
        query = query.where(TestCase.priority.in_([p.lower() for p in priority]))
    
    # Filtre tags
    if tags:
        tag_conditions = []
        for tag in tags:
            tag_conditions.append(TestCase.tags.contains([tag]))
        if tag_conditions:
            query = query.where(or_(*tag_conditions))
    
    # ============================================================
    # TRI (ORDER BY)
    # ============================================================
    
    if order_by == "tc_code":
        # Pour trier TC-AUTH-001, TC-AUTH-002, TC-LOGIN-001, etc.
        # On extrait le préfixe (lettres) et le numéro
        # Exemple: TC-AUTH-001 → prefix = 'AUTH', number = 1
        
        if order_direction.lower() == "asc":
            query = query.order_by(
                # Extraire le préfixe (les lettres entre TC- et -)
                func.substring(TestCase.tc_code, 4, func.length(TestCase.tc_code) - 7).asc(),
                # Extraire le numéro à la fin et le convertir en entier
                func.cast(
                    func.substring(TestCase.tc_code, 
                                  func.length(TestCase.tc_code) - 2, 
                                  3),
                    Integer
                ).asc()
            )
        else:
            query = query.order_by(
                func.substring(TestCase.tc_code, 4, func.length(TestCase.tc_code) - 7).desc(),
                func.cast(
                    func.substring(TestCase.tc_code, 
                                  func.length(TestCase.tc_code) - 2, 
                                  3),
                    Integer
                ).desc()
            )
    else:
        # Mapping des champs de tri standards
        order_mapping = {
            "created_at": TestCase.created_at,
            "updated_at": TestCase.updated_at,
            "title": TestCase.title,
            "is_active": TestCase.is_active,
        }
        
        order_column = order_mapping.get(order_by, TestCase.created_at)
        
        if order_direction.lower() == "asc":
            query = query.order_by(order_column.asc())
        else:
            query = query.order_by(order_column.desc())
        
        # Tri secondaire pour éviter les résultats aléatoires
        if order_by != "created_at":
            query = query.order_by(TestCase.created_at.desc())
    
    # Pagination
    query = query.limit(limit).offset(offset)
    
    result = await db.execute(query)
    return result.unique().scalars().all()

async def count_all_test_cases(
    db: AsyncSession,
    project_id: Optional[str] = None,
    search: Optional[str] = None,
    status: Optional[List[str]] = None,
    priority: Optional[List[str]] = None,
    tags: Optional[List[str]] = None
) -> int:
    """Compte le nombre total de test cases avec filtres."""
    
    query = select(func.count(TestCase.id)).where(TestCase.is_active == True)
    
    if project_id:
        query = query.outerjoin(
            UserStory, 
            TestCase.user_story_id == UserStory.id
        ).outerjoin(
            UserStoryVersion,
            TestCase.user_story_version_id == UserStoryVersion.id
        ).where(
            or_(
                UserStory.project_id == project_id,
                UserStoryVersion.user_story.has(project_id=project_id)
            )
        )
    
    if search:
        query = query.where(
            or_(
                TestCase.title.ilike(f"%{search}%"),
                TestCase.tc_code.ilike(f"%{search}%")
            )
        )
    
    if status:
        active_filter = False
        archived_filter = False
        for s in status:
            if s == 'active':
                active_filter = True
            elif s == 'archived':
                archived_filter = True
        
        if active_filter and not archived_filter:
            query = query.where(TestCase.is_active == True)
        elif archived_filter and not active_filter:
            query = query.where(TestCase.is_active == False)
    
    if priority:
        query = query.where(TestCase.priority.in_([p.lower() for p in priority]))
    
    if tags:
        tag_conditions = []
        for tag in tags:
            tag_conditions.append(TestCase.tags.contains([tag]))
        if tag_conditions:
            query = query.where(or_(*tag_conditions))
    
    result = await db.execute(query)
    return result.scalar()


async def get_test_case_by_id(db: AsyncSession, test_case_id: str) -> Optional[TestCase]:
    """Récupère un test case par son ID."""
    return await db.get(TestCase, test_case_id)


async def get_test_case_by_code(db: AsyncSession, tc_code: str) -> Optional[TestCase]:
    """Récupère un test case par son code (TC-XXX)."""
    result = await db.execute(
        select(TestCase).where(TestCase.tc_code == tc_code)
    )
    return result.scalar_one_or_none()


async def get_test_cases_by_user_story_id(db: AsyncSession, user_story_id: str) -> List[TestCase]:
    """Récupère tous les test cases liés à une user story."""
    result = await db.execute(
        select(TestCase).where(
            or_(
                TestCase.user_story_id == user_story_id,
                # Pour les versions approuvées
                TestCase.user_story_version.has(user_story_id=user_story_id)
            )
        )
    )
    return result.scalars().all()


async def create_test_case(db: AsyncSession, data: dict) -> TestCase:
    """Crée un nouveau test case."""
    test_case = TestCase(**data)
    db.add(test_case)
    await db.flush()
    return test_case


async def update_test_case(db: AsyncSession, test_case_id: str, data: dict) -> Optional[TestCase]:
    """Met à jour un test case."""
    test_case = await get_test_case_by_id(db, test_case_id)
    if test_case:
        for key, value in data.items():
            if hasattr(test_case, key) and value is not None:
                setattr(test_case, key, value)
        await db.flush()
    return test_case


async def delete_test_case(db: AsyncSession, test_case_id: str) -> bool:
    """Supprime un test case (soft delete)."""
    test_case = await get_test_case_by_id(db, test_case_id)
    if test_case:
        test_case.is_active = False
        await db.flush()
        return True
    return False