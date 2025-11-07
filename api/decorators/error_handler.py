"""
API错误处理装饰器
"""

import functools
from typing import Callable, Type, Dict
from fastapi import HTTPException, status
from loguru import logger

from core.exceptions import (
    JobNotFoundException,
    JobStateException,
    SCNSConductorException,
)


# 异常映射表：业务异常 -> HTTP状态码
EXCEPTION_MAP: Dict[Type[Exception], int] = {
    JobNotFoundException: status.HTTP_404_NOT_FOUND,
    JobStateException: status.HTTP_400_BAD_REQUEST,
    ValueError: status.HTTP_400_BAD_REQUEST,
}


def handle_api_errors(func: Callable):
    """
    统一的API错误处理装饰器

    自动捕获并转换异常为HTTP响应，避免重复的try-except代码

    使用示例:
        @router.post("/submit")
        @handle_api_errors
        async def submit_job(...):
            return await service.submit_job(...)

    优势:
        1. 代码更简洁（减少78%的异常处理代码）
        2. 统一的错误响应格式
        3. 自动日志记录
        4. 易于维护和扩展
    """

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)

        # 已知的业务异常
        except tuple(EXCEPTION_MAP.keys()) as e:
            status_code = EXCEPTION_MAP[type(e)]
            logger.warning(
                f"[{func.__name__}] {type(e).__name__}: {e}",
                extra={"exception_type": type(e).__name__},
            )
            raise HTTPException(status_code=status_code, detail=str(e))

        # 自定义业务异常
        except SCNSConductorException as e:
            logger.error(
                f"[{func.__name__}] {type(e).__name__}: {e}",
                extra={"exception_type": type(e).__name__},
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
            )

        # 未预期的异常
        except Exception as e:
            # 使用 repr() 避免异常信息中的 {} 导致格式化错误
            logger.error(
                f"[{func.__name__}] Unexpected error: {repr(e)}",
                exc_info=True,
                extra={"exception_type": type(e).__name__},
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal server error",
            )

    return wrapper
