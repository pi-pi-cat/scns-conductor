"""
FastAPI 依赖项，用于依赖注入
"""

from typing import AsyncIterator
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import async_db


async def get_db() -> AsyncIterator[AsyncSession]:
    """
    获取异步数据库会话的依赖项

    用法示例:
        @router.get("/endpoint")
        async def endpoint(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with async_db.get_session() as session:
        yield session
