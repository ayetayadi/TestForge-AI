from sqlalchemy.orm import Session
from app.models.jira_connection import JiraConnection


# 🔹 Récupérer toutes les connections
def get_all_connections(db: Session):
    return db.query(JiraConnection).all()


# 🔹 Récupérer une connection par ID
def get_connection_by_id(db: Session, connection_id: str):
    return db.query(JiraConnection).filter(
        JiraConnection.id == connection_id
    ).first()


# 🔹 Récupérer la connection d’un user (si 1 seule)
def get_connection_by_user(db: Session, user_id: str):
    return db.query(JiraConnection).filter(
        JiraConnection.user_id == user_id
    ).first()


# 🔹 Récupérer la connection active (ton cas actuel)
def get_default_connection(db: Session):
    return db.query(JiraConnection).filter(
        JiraConnection.is_active == True
    ).first()


# 🔹 Créer une nouvelle connection
def create_connection(
    db: Session,
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
        jira_api_token=jira_api_token,  # 🔐 encrypt via setter
        cloud_id=cloud_id,
        is_active=True
    )

    db.add(connection)
    db.commit()
    db.refresh(connection)

    return connection


# 🔹 Mettre à jour le token (important pour ton cas)
def update_connection_token(db: Session, connection_id: str, new_token: str):
    connection = get_connection_by_id(db, connection_id)

    if not connection:
        return None

    connection.jira_api_token = new_token  # 🔐 encrypt auto
    db.commit()
    db.refresh(connection)

    return connection


# 🔹 Désactiver une connection
def deactivate_connection(db: Session, connection_id: str):
    connection = get_connection_by_id(db, connection_id)

    if not connection:
        return None

    connection.is_active = False
    db.commit()

    return connection


# 🔹 Supprimer une connection
def delete_connection(db: Session, connection_id: str):
    connection = get_connection_by_id(db, connection_id)

    if not connection:
        return False

    db.delete(connection)
    db.commit()

    return True