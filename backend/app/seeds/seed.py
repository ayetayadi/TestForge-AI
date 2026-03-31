from app.core.database import SessionLocal
from app.models.user import User
from app.models.jira_connection import JiraConnection
from app.seeds.fake_data import fake_users, fake_connections
import os


def seed():
    db = SessionLocal()

    if not os.getenv("JIRA_API_TOKEN"):
        raise ValueError("JIRA_API_TOKEN missing")

    # USERS
    for u in fake_users:
        db.merge(User(**u))

    db.flush()  

    # CONNECTIONS
    for c in fake_connections:
        db.merge(JiraConnection(**c))

    db.flush()

    db.commit()
    db.close()


if __name__ == "__main__":
    seed()