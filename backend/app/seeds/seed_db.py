import asyncio
from app.core.database import SessionLocal, engine, Base
from app.models.user import User
from app.models.jira_connection import JiraConnection
from app.seeds.fake_data import fake_users, fake_connections


async def seed():

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as session:

        print("Seeding users...")

        for u in fake_users:
            existing = await session.get(User, u["id"])
            if not existing:
                session.add(User(**u))

        await session.flush()

        print("Seeding connections...")

        for c in fake_connections:
            existing = await session.get(JiraConnection, c["id"])
            if not existing:
                session.add(JiraConnection(**c))

        await session.commit()

    print("Seeding done.")


if __name__ == "__main__":
    asyncio.run(seed())