# app/tests/seed_admin.py
import asyncio
import uuid
from app.core.database import async_session_maker, engine, Base
from app.models.user import User
from app.core.security import hash_password

async def seed():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_maker() as session:
        admin = User(
            id=str(uuid.uuid4()),
            email="admin@testforge.com",
            username="admin",                        # ← username, not full_name
            hashed_password=hash_password("change-me-123"),
            is_admin=True,
        )
        session.add(admin)
        await session.commit()
        print(" Admin created: admin@testforge.com / change-me-123")

asyncio.run(seed())