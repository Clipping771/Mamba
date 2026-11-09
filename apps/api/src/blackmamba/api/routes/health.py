"""Health endpoints — the only routes (with login) that do not require auth."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from blackmamba import __version__
from blackmamba.core.db import get_session
from blackmamba.schemas.health import HealthResponse, ReadinessResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness: the process is up. Does not touch dependencies."""
    return HealthResponse(status="ok", version=__version__)


@router.get("/health/ready", response_model=ReadinessResponse)
async def ready(
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReadinessResponse:
    """Readiness: can we reach PostgreSQL?"""
    try:
        await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(status="degraded", database="unavailable")
    return ReadinessResponse(status="ok", database="ok")
