"""
FastAPI dependencies for dependency injection
"""
from typing import AsyncIterator
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import async_db


async def get_db() -> AsyncIterator[AsyncSession]:
    """
    Dependency for getting async database session
    
    Usage:
        @router.get("/endpoint")
        async def endpoint(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with async_db.get_session() as session:
        yield session

