import asyncio
from app.core.database import async_session_maker, engine, Base
from app.models.user import User
from app.models.jira_connection import JiraConnection
from app.seeds.fake_data import fake_users


async def seed():

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Use correct session maker
    async with async_session_maker() as session:

        print("Seeding users...")

        for u in fake_users:
            existing = await session.get(User, u["id"])
            if not existing:
                session.add(User(**u))

        await session.commit()

    print("Seeding done.")


if __name__ == "__main__":
    asyncio.run(seed())