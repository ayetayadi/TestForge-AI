import uuid
import os
from app.core.security import hash_password

fake_users = [
    {
        "id": str(uuid.uuid4()),
        "email": "admin@testforge.com",
        "username": "admin",
        "hashed_password": hash_password("change-me-123"),
        "is_admin": True,
    },
    {
        "id": "user-1",
        "email": "test@test.com",
        "username": "test",
        "hashed_password": hash_password("test123"),
        "is_admin": False,
    }
]

fake_connections = [
    {
        "id": "conn-1",
        "user_id": "user-1",
        "jira_url": os.getenv("JIRA_URL"),
        "jira_email": os.getenv("JIRA_EMAIL"),
        "jira_api_token": os.getenv("JIRA_API_TOKEN"),
    }
]