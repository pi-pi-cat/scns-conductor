"""
Logging Middleware - 日志记录中间件

记录执行过程中的关键事件
"""

from loguru import logger

from .base import BaseExecutionMiddleware, middleware_metadata
from worker.execution import JobExecutionContext


@middleware_metadata(
    name="LoggingMiddleware",
    description="Logs execution stages and errors",
    priority=100,  # 高优先级，先执行
)
class LoggingMiddleware(BaseExecutionMiddleware):
    """日志记录中间件"""
    
    def on_stage(self, stage: str, context: JobExecutionContext) -> JobExecutionContext:
        """记录阶段转换"""
        logger.debug(f"Job {context.job_id} entered stage: {stage}")
        return context
    
    def on_error(self, context: JobExecutionContext, error: Exception):
        """记录错误详情"""
        logger.error(
            f"Job {context.job_id} error: {error.__class__.__name__}: {error}"
        )

