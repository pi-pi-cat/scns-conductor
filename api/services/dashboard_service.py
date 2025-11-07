"""
Dashboard 服务 - 聚合统计数据
"""

from typing import List

from loguru import logger

from core.models import Job
from core.enums import JobState
from ..repositories.job_repository import JobRepository
from ..schemas.dashboard import (
    DashboardResponse,
    JobStats,
    ResourceStats,
    NodeInfo,
    JobSummary,
)


class DashboardService:
    """Dashboard 服务 - 提供系统总览数据"""

    @staticmethod
    async def get_dashboard() -> DashboardResponse:
        """
        获取 Dashboard 总览数据

        包含:
        - 作业统计
        - 资源统计
        - 节点信息
        - 运行中的作业
        - 排队中的作业

        说明:
            所有查询都是独立的短事务，不会长时间占用连接
        """
        logger.info("开始获取 Dashboard 数据")

        # 并发查询各种统计数据（每个都是独立短事务）
        job_stats = await DashboardService._get_job_stats()
        resource_stats = await DashboardService._get_resource_stats()
        node_info = await DashboardService._get_node_info()
        running_jobs = await DashboardService._get_running_jobs()
        pending_jobs = await DashboardService._get_pending_jobs()

        response = DashboardResponse(
            job_stats=job_stats,
            resource_stats=resource_stats,
            node_info=node_info,
            running_jobs=running_jobs,
            pending_jobs=pending_jobs,
        )

        logger.info("Dashboard 数据获取成功")
        return response

    @staticmethod
    async def _get_job_stats() -> JobStats:
        """获取作业统计（短事务）"""
        # 查询各状态的作业数量
        running_jobs = await JobRepository.query_jobs(
            state=JobState.RUNNING, limit=1000
        )
        pending_jobs = await JobRepository.query_jobs(
            state=JobState.PENDING, limit=1000
        )
        completed_jobs = await JobRepository.query_jobs(
            state=JobState.COMPLETED, limit=1000
        )
        failed_jobs = await JobRepository.query_jobs(state=JobState.FAILED, limit=1000)
        cancelled_jobs = await JobRepository.query_jobs(
            state=JobState.CANCELLED, limit=1000
        )

        total = (
            len(running_jobs)
            + len(pending_jobs)
            + len(completed_jobs)
            + len(failed_jobs)
            + len(cancelled_jobs)
        )

        return JobStats(
            total=total,
            running=len(running_jobs),
            pending=len(pending_jobs),
            completed=len(completed_jobs),
            failed=len(failed_jobs),
            cancelled=len(cancelled_jobs),
        )

    @staticmethod
    async def _get_resource_stats() -> ResourceStats:
        """获取资源统计（短事务）"""
        # 获取所有系统资源
        resources = await JobRepository.get_available_resources("")

        total_cpus = sum(r.total_cpus for r in resources)

        # 计算已分配的CPU
        allocated_cpus = 0
        for resource in resources:
            allocated = await JobRepository.get_allocated_cpus_on_node(
                resource.node_name
            )
            allocated_cpus += allocated

        available_cpus = total_cpus - allocated_cpus
        utilization_rate = (
            (allocated_cpus / total_cpus * 100) if total_cpus > 0 else 0.0
        )

        return ResourceStats(
            total_cpus=total_cpus,
            allocated_cpus=allocated_cpus,
            available_cpus=available_cpus,
            utilization_rate=round(utilization_rate, 2),
        )

    @staticmethod
    async def _get_node_info() -> List[NodeInfo]:
        """获取节点信息（短事务）"""
        resources = await JobRepository.get_available_resources("")

        node_list = []
        for resource in resources:
            allocated = await JobRepository.get_allocated_cpus_on_node(
                resource.node_name
            )
            available = resource.total_cpus - allocated
            utilization = (
                (allocated / resource.total_cpus * 100)
                if resource.total_cpus > 0
                else 0.0
            )

            node_list.append(
                NodeInfo(
                    node_name=resource.node_name,
                    partition=resource.partition,
                    total_cpus=resource.total_cpus,
                    allocated_cpus=allocated,
                    available_cpus=available,
                    available=resource.available,
                    utilization_rate=round(utilization, 2),
                )
            )

        return node_list

    @staticmethod
    async def _get_running_jobs() -> List[JobSummary]:
        """获取运行中的作业列表（短事务）"""
        jobs = await JobRepository.query_jobs(
            state=JobState.RUNNING,
            limit=20,  # 限制返回数量
        )

        return [DashboardService._job_to_summary(job) for job in jobs]

    @staticmethod
    async def _get_pending_jobs() -> List[JobSummary]:
        """获取排队中的作业列表（短事务）"""
        jobs = await JobRepository.query_jobs(
            state=JobState.PENDING,
            limit=20,  # 限制返回数量
        )

        return [DashboardService._job_to_summary(job) for job in jobs]

    @staticmethod
    def _job_to_summary(job: Job) -> JobSummary:
        """将 Job 对象转换为 JobSummary"""
        return JobSummary(
            job_id=job.id,
            name=job.name,
            account=job.account,
            state=job.state.value,
            allocated_cpus=job.allocated_cpus,
            submit_time=job.submit_time.isoformat(),
            start_time=job.start_time.isoformat() if job.start_time else None,
        )
