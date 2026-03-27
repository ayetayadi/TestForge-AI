from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.testing.suite.test_reflection import users

from app.core.database import engine, Base
from app.api import auth, admin, jira, users

app = FastAPI(title="TestForge AI")

# CORS must be added FIRST before any routers
origins = ["http://localhost:4200"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=600,
)

@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(jira.router)
app.include_router(users.router)
# Debug route to confirm CORS is active
@app.get("/ping")
async def ping():
    return {"status": "ok"}