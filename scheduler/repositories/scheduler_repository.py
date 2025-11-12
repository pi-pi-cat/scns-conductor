"""
调度器数据库操作仓储

集中管理所有调度器相关的数据库查询和更新操作
"""

from datetime import datetime
from typing import List

from loguru import logger
from sqlalchemy.orm import Session

from core.models import Job, ResourceAllocation
from core.enums import JobState, ResourceStatus


class SchedulerRepository:
    """
    调度器数据库操作仓储

    职责：
    - 集中管理所有调度相关的数据库查询
    - 提供作业查询和资源分配操作
    - 封装事务逻辑
    """

    # ========== 作业查询相关 ==========

    @staticmethod
    def get_pending_jobs(session: Session) -> List[Job]:
        """
        获取所有 PENDING 状态的作业（按提交时间排序）

        Args:
            session: 数据库会话

        Returns:
            PENDING 状态的作业列表（按提交时间升序）
        """
        return (
            session.query(Job)
            .filter(Job.state == JobState.PENDING)
            .order_by(Job.submit_time)
            .all()
        )

    # ========== 资源分配相关 ==========

    @staticmethod
    def create_resource_allocation(
        session: Session,
        job_id: int,
        allocated_cpus: int,
        node_name: str,
        status: ResourceStatus = ResourceStatus.RESERVED,
    ) -> ResourceAllocation:
        """
        创建资源分配记录

        Args:
            session: 数据库会话
            job_id: 作业ID
            allocated_cpus: 分配的CPU数量
            node_name: 节点名称
            status: 资源状态（默认为 RESERVED）

        Returns:
            创建的资源分配对象
        """
        allocation = ResourceAllocation(
            job_id=job_id,
            allocated_cpus=allocated_cpus,
            node_name=node_name,
            allocation_time=datetime.utcnow(),
            status=status,
        )
        session.add(allocation)
        session.flush()  # 确保获取ID
        logger.debug(
            f"资源分配已创建: job_id={job_id}, cpus={allocated_cpus}, status={status}"
        )
        return allocation

    # ========== 作业状态更新相关 ==========

    @staticmethod
    def update_job_to_running(
        session: Session,
        job: Job,
        node_name: str,
    ) -> None:
        """
        更新作业状态为 RUNNING

        更新字段：
        - state: RUNNING
        - start_time: 当前时间
        - node_list: 节点名称

        Args:
            session: 数据库会话
            job: 作业对象
            node_name: 节点名称
        """
        job.state = JobState.RUNNING
        job.start_time = datetime.utcnow()
        job.node_list = node_name
        logger.debug(f"作业状态已更新为 RUNNING: job_id={job.id}")
