from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.jira_connection import JiraConnection
from app.services.jira_service import refresh_access_token
from app.services.jira_client import JiraClient


class JiraSessionManager:
    """
    Owns the lifecycle of a user's Jira OAuth session.

    Responsibilities:
    - Load the JiraConnection from the DB.
    - Proactively refresh the access token before it expires.
    - Force-refresh on demand (e.g. after an Atlassian 401).
    - Vend a fully-wired JiraClient with a refresh callback baked in.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    async def get_connection(self, user_id: str) -> JiraConnection:
        result = await self.db.execute(
            select(JiraConnection).where(JiraConnection.user_id == user_id)
        )
        conn = result.scalar_one_or_none()

        if not conn or not conn.is_active:
            raise HTTPException(404, "Jira not connected")

        return conn

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    async def force_refresh(self, conn: JiraConnection) -> str:
        """
        Unconditionally refresh the Jira OAuth token and persist it.
        Returns the new access token.
        """
        if not conn.refresh_token:
            raise HTTPException(
                400,
                "No refresh token available. Please reconnect Jira."
            )

        try:
            new_tokens = await refresh_access_token(conn.refresh_token)

            conn.access_token = new_tokens["access_token"]

            if "refresh_token" in new_tokens:
                conn.refresh_token = new_tokens["refresh_token"]

            expires_in = new_tokens.get("expires_in", 3600)
            conn.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

            await self.db.commit()
            return conn.access_token

        except HTTPException:
            await self.db.rollback()
            raise

        except Exception:
            await self.db.rollback()
            raise HTTPException(400, "Jira session expired. Please reconnect Jira.")

    async def ensure_valid_token(self, conn: JiraConnection) -> str:
        """
        Return a valid access token.
        Refreshes proactively when expiry is within 5 minutes.
        Falls back to the stored token if expiry is unknown (old connections).
        """
        if conn.token_expires_at and conn.refresh_token:
            if datetime.utcnow() >= conn.token_expires_at - timedelta(minutes=5):
                return await self.force_refresh(conn)

        return conn.access_token

    # ------------------------------------------------------------------
    # Client factory
    # ------------------------------------------------------------------

    async def get_client(self, conn: JiraConnection) -> JiraClient:
        """
        Build a JiraClient with a fresh token and a refresh callback wired in.

        The callback lets JiraClient self-heal on Atlassian 401s without any
        extra logic in the calling code.
        """
        token = await self.ensure_valid_token(conn)

        async def _refresher() -> str:
            return await self.force_refresh(conn)

        return JiraClient(token, conn.cloud_id, token_refresher=_refresher)
