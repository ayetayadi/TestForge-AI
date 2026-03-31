import os

fake_users = [
    {
        "id": "user-1",
        "email": "test@test.com",
        "username": "test",
        "hashed_password": "hashed"
    }
]

fake_connections = [
    {
        "id": "conn-1",
        "user_id": "user-1",
        "jira_url": os.getenv("JIRA_URL"),
        "jira_email": os.getenv("JIRA_EMAIL"),
        "jira_api_token": os.getenv("JIRA_API_TOKEN")
    }
]
