"""
Resource Monitoring Middleware - 资源监控中间件

监控资源使用情况
"""

from loguru import logger

from .base import BaseExecutionMiddleware, middleware_metadata
from worker.execution import JobExecutionContext


@middleware_metadata(
    name="ResourceMonitoringMiddleware",
    description="Monitors resource allocation and release",
    priority=30,
)
class ResourceMonitoringMiddleware(BaseExecutionMiddleware):
    """资源监控中间件"""
    
    def before_execution(self, context: JobExecutionContext) -> JobExecutionContext:
        """记录资源分配前状态"""
        if context.job:
            logger.debug(
                f"Job {context.job_id} resource allocation: "
                f"{context.job.allocated_cpus} CPUs"
            )
        return context
    
    def after_execution(self, context: JobExecutionContext) -> JobExecutionContext:
        """记录资源释放"""
        if context.job:
            logger.debug(
                f"Job {context.job_id} resources released: "
                f"{context.job.allocated_cpus} CPUs"
            )
        return context

