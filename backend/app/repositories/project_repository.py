from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.jira_project import JiraProject
from app.models.user_story import UserStory
from app.repositories.jira_connection_repository import get_default_connection


def get_all_projects(db: Session):
    return db.query(JiraProject).all()


def get_project_by_key(db: Session, project_key: str):
    return db.query(JiraProject).filter(
        JiraProject.project_key == project_key
    ).first()


def create_project(db: Session, project_key: str, project_name: str):

    connection = get_default_connection(db)
    #connection = get_connection_by_user(db, user_id)

    if not connection:
        raise Exception("No active Jira connection found")

    project = JiraProject(
        project_key=project_key,
        project_name=project_name,
        jira_connection_id=connection.id 
    )

    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def get_projects_with_story_count(db: Session):
    return (
        db.query(
            JiraProject.id,
            JiraProject.project_key,
            JiraProject.project_name,
            func.count(UserStory.id).label("story_count")
        )
        .outerjoin(UserStory, UserStory.jira_project_id == JiraProject.id)
        .group_by(JiraProject.id)
        .all()
    )