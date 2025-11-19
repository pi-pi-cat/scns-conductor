"""
Metrics Middleware - 指标收集中间件

收集作业执行的指标，如执行时间等
"""

from datetime import datetime

from loguru import logger

from .base import BaseExecutionMiddleware, middleware_metadata
from worker.execution import JobExecutionContext


@middleware_metadata(
    name="MetricsMiddleware",
    description="Collects execution metrics (duration, exit code, etc.)",
    priority=50,
)
class MetricsMiddleware(BaseExecutionMiddleware):
    """指标收集中间件"""
    
    def before_execution(self, context: JobExecutionContext) -> JobExecutionContext:
        """记录开始时间"""
        context.start_time = datetime.utcnow()
        logger.debug(f"Job {context.job_id} execution started at {context.start_time}")
        return context
    
    def after_execution(self, context: JobExecutionContext) -> JobExecutionContext:
        """记录执行时间和指标"""
        elapsed = context.elapsed_time()
        logger.info(
            f"Job {context.job_id} execution metrics: "
            f"elapsed={elapsed:.2f}s, "
            f"exit_code={context.exit_code}, "
            f"has_error={context.has_error()}"
        )
        return context

