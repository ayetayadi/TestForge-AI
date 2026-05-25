from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.models.testomat_connection import TestomatConnection


async def get_connection(db: AsyncSession, user_id: str) -> Optional[TestomatConnection]:
    result = await db.execute(
        select(TestomatConnection).where(TestomatConnection.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def save_connection(db: AsyncSession, user_id: str, api_key: str) -> TestomatConnection:
    existing = await get_connection(db, user_id)
    if existing:
        existing.api_key = api_key
        existing.is_active = True
        await db.flush()
        return existing

    conn = TestomatConnection(user_id=user_id)
    conn.api_key = api_key
    db.add(conn)
    await db.flush()
    return conn


async def delete_connection(db: AsyncSession, user_id: str) -> bool:
    result = await db.execute(
        delete(TestomatConnection).where(TestomatConnection.user_id == user_id)
    )
    return result.rowcount > 0
