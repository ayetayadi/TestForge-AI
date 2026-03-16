from fastapi import FastAPI
from app.core.database import Base, engine

# import all models so SQLAlchemy knows them
from app.models import User, JiraConnection, JiraProject, UserStory

app = FastAPI(title="TestForge API")


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)


@app.get("/")
def root():
    return {"message": "FastAPI + PostgreSQL is working"}