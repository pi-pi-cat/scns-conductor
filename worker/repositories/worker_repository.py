"""
Worker 数据库操作仓储

集中管理所有 Worker 相关的数据库查询和更新操作
"""

from datetime import datetime
from typing import Optional, Tuple

from loguru import logger
from sqlalchemy.orm import Session

from core.models import Job, ResourceAllocation
from core.enums import JobState, ResourceStatus


class WorkerRepository:
    """
    Worker 数据库操作仓储

    职责：
    - 集中管理所有 Worker 相关的数据库查询
    - 提供作业状态更新和资源分配操作
    - 封装事务逻辑
    """

    # ========== 作业查询相关 ==========

    @staticmethod
    def get_job_by_id(session: Session, job_id: int) -> Optional[Job]:
        """
        根据 ID 获取作业

        Args:
            session: 数据库会话
            job_id: 作业ID

        Returns:
            作业对象，不存在则返回 None
        """
        job = session.query(Job).filter(Job.id == job_id).first()
        if job:
            session.expunge(job)  # 从会话中分离，允许在会话外使用
        return job

    # ========== 作业状态更新相关 ==========

    @staticmethod
    def update_job_completion(
        session: Session,
        job_id: int,
        exit_code: int,
    ) -> bool:
        """
        更新作业完成状态

        Args:
            session: 数据库会话
            job_id: 作业ID
            exit_code: 退出码

        Returns:
            是否更新成功
        """
        job = session.query(Job).filter(Job.id == job_id).first()
        if not job:
            logger.warning(f"Job {job_id} not found for completion update")
            return False

        job.state = JobState.COMPLETED if exit_code == 0 else JobState.FAILED
        job.end_time = datetime.utcnow()
        job.exit_code = f"{exit_code}:0"

        if exit_code != 0:
            job.error_msg = f"Exited with code {exit_code}"

        logger.debug(f"Job {job_id} marked as {job.state.value}")
        return True

    @staticmethod
    def update_job_failed(
        session: Session,
        job_id: int,
        error_msg: str,
        exit_code: str = "-1:0",
    ) -> bool:
        """
        标记作业失败

        Args:
            session: 数据库会话
            job_id: 作业ID
            error_msg: 错误消息
            exit_code: 退出码（默认为 "-1:0"）

        Returns:
            是否更新成功
        """
        job = session.query(Job).filter(Job.id == job_id).first()
        if not job:
            logger.warning(f"Job {job_id} not found for failure update")
            return False

        job.state = JobState.FAILED
        job.end_time = datetime.utcnow()
        job.error_msg = error_msg
        job.exit_code = exit_code

        logger.debug(f"Job {job_id} marked as FAILED")
        return True

    # ========== 资源分配相关 ==========

    @staticmethod
    def get_unreleased_allocation(
        session: Session,
        job_id: int,
    ) -> Optional[ResourceAllocation]:
        """
        获取未释放的资源分配记录

        Args:
            session: 数据库会话
            job_id: 作业ID

        Returns:
            资源分配对象，不存在则返回 None
        """
        return (
            session.query(ResourceAllocation)
            .filter(
                ResourceAllocation.job_id == job_id,
                ResourceAllocation.status != ResourceStatus.RELEASED,
            )
            .first()
        )

    @staticmethod
    def update_allocation_to_allocated(
        session: Session,
        job_id: int,
    ) -> Optional[ResourceAllocation]:
        """
        将资源分配状态从 reserved 更新为 allocated

        这是资源真正被占用的时刻，只有在 Worker 真正开始执行作业时才调用。

        Args:
            session: 数据库会话
            job_id: 作业ID

        Returns:
            更新后的资源分配对象，不存在则返回 None
        """
        allocation = (
            session.query(ResourceAllocation)
            .filter(ResourceAllocation.job_id == job_id)
            .first()
        )

        if allocation:
            allocation.status = ResourceStatus.ALLOCATED
            logger.debug(
                f"Resource allocation updated to ALLOCATED for job {job_id}"
            )
            return allocation
        else:
            logger.warning(
                f"No resource allocation found for job {job_id}"
            )
            return None

    @staticmethod
    def create_allocation_as_allocated(
        session: Session,
        job_id: int,
        allocated_cpus: int,
        node_name: str,
    ) -> ResourceAllocation:
        """
        创建资源分配记录（状态为 allocated）

        用于异常情况：如果没有预留记录，直接创建 allocated 记录。

        Args:
            session: 数据库会话
            job_id: 作业ID
            allocated_cpus: 分配的CPU数量
            node_name: 节点名称

        Returns:
            创建的资源分配对象
        """
        allocation = ResourceAllocation(
            job_id=job_id,
            allocated_cpus=allocated_cpus,
            node_name=node_name,
            allocation_time=datetime.utcnow(),
            status=ResourceStatus.ALLOCATED,
        )
        session.add(allocation)
        session.flush()
        logger.debug(
            f"Created new resource allocation (ALLOCATED) for job {job_id}"
        )
        return allocation

    @staticmethod
    def release_allocation(
        session: Session,
        job_id: int,
    ) -> Optional[Tuple[ResourceAllocation, ResourceStatus]]:
        """
        释放资源分配（更新状态为 released）

        Args:
            session: 数据库会话
            job_id: 作业ID

        Returns:
            (资源分配对象, 旧状态) 元组，不存在则返回 None
        """
        allocation = (
            session.query(ResourceAllocation)
            .filter(
                ResourceAllocation.job_id == job_id,
                ResourceAllocation.status != ResourceStatus.RELEASED,
            )
            .first()
        )

        if allocation:
            # 保存旧状态用于后续判断
            old_status = allocation.status

            allocation.status = ResourceStatus.RELEASED
            allocation.released_time = datetime.utcnow()

            logger.debug(
                f"Resource allocation released for job {job_id} "
                f"(status: {old_status} -> released)"
            )

            return (allocation, old_status)
        else:
            logger.warning(
                f"No unreleased allocation found for job {job_id}"
            )
            return None

    @staticmethod
    def update_process_id(
        session: Session,
        job_id: int,
        process_id: int,
    ) -> bool:
        """
        更新资源分配记录中的进程 ID

        Args:
            session: 数据库会话
            job_id: 作业ID
            process_id: 进程ID

        Returns:
            是否更新成功
        """
        allocation = (
            session.query(ResourceAllocation)
            .filter(
                ResourceAllocation.job_id == job_id,
                ResourceAllocation.status != ResourceStatus.RELEASED,
            )
            .first()
        )

        if allocation:
            allocation.process_id = process_id
            logger.debug(f"Process ID {process_id} stored for job {job_id}")
            return True
        else:
            logger.warning(
                f"No unreleased allocation found for job {job_id}, "
                f"PID not stored"
            )
            return False

