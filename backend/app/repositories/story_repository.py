from sqlalchemy.orm import Session
from app.models.user_story import UserStory


def get_all_stories(db: Session):
    return db.query(UserStory).all()

def get_story_by_issue_key(db: Session, issue_key):
    return db.query(UserStory).filter_by(issue_key=issue_key).first()


def get_stories_by_project_id(db: Session, project_id):
    return db.query(UserStory).filter_by(jira_project_id=project_id).all()


def story_exists(db: Session, issue_key):
    return db.query(UserStory).filter_by(issue_key=issue_key).first() is not None


def create_story(db: Session, data):
    story = UserStory(**data)
    db.add(story)
    return story