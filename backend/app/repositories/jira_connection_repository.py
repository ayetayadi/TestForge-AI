from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.jira_connection import JiraConnection


# 🔹 Récupérer toutes les connections
async def get_all_connections(db: AsyncSession):
    return await db.execute(select(JiraConnection)).scalars().all()


# 🔹 Récupérer une connection par ID
async def get_connection_by_id(db: AsyncSession, connection_id: str):
    result = await db.execute(
        select(JiraConnection).where(JiraConnection.id == connection_id)
    )
    return result.scalar_one_or_none()


# 🔹 Récupérer la connection d’un user (si 1 seule)
def get_connection_by_user(db: AsyncSession, user_id: str):
    return db.query(JiraConnection).filter(
        JiraConnection.user_id == user_id
    ).first()


# 🔹 Récupérer la connection active (ton cas actuel)
async def get_default_connection(db: AsyncSession):
    result = await db.execute(
        select(JiraConnection).where(JiraConnection.is_active == True)
    )
    return result.scalar_one_or_none()


# 🔹 Créer une nouvelle connection
async def create_connection(
    db: AsyncSession,
    user_id: str,
    jira_url: str,
    jira_email: str,
    jira_api_token: str,
    cloud_id: str | None = None
):
    connection = JiraConnection(
        user_id=user_id,
        jira_url=jira_url,
        jira_email=jira_email,
        jira_api_token=jira_api_token, 
        cloud_id=cloud_id,
        is_active=True
    )

    db.add(connection)
    await db.commit()
    await db.refresh(connection)

    return connection


# 🔹 Mettre à jour le token
async def update_connection_token(db: AsyncSession, connection_id: str, new_token: str):
    connection = await get_connection_by_id(db, connection_id)

    if not connection:
        return None

    connection.jira_api_token = new_token
    await db.commit()
    await db.refresh(connection)

    return connection


# 🔹 Désactiver une connection
async def deactivate_connection(db: AsyncSession, connection_id: str):
    connection = await get_connection_by_id(db, connection_id)

    if not connection:
        return None

    connection.is_active = False
    await db.commit()

    return connection


# 🔹 Supprimer une connection
async def delete_connection(db: AsyncSession, connection_id: str):
    connection = await get_connection_by_id(db, connection_id)

    if not connection:
        return False

    db.delete(connection)
    await db.commit()

    return True