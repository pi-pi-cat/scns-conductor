"""
作业数据仓储 (Job Repository)

封装所有作业相关的数据库操作，管理会话生命周期
每个方法内部创建短生命周期会话，用完即释放
"""

from typing import Optional, List
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from loguru import logger

from core.database import async_db
from core.models import Job, ResourceAllocation, SystemResource
from core.enums import JobState, ResourceStatus


class JobRepository:
    """
    作业数据仓储

    所有方法都是独立的数据库事务，自动管理会话生命周期
    """

    @staticmethod
    async def create_job(job_data: dict) -> Job:
        """
        创建作业记录

        Args:
            job_data: 作业数据字典

        Returns:
            创建的作业对象（包含分配的ID）
        """
        async with async_db.get_session() as session:
            job = Job(**job_data)
            session.add(job)
            await session.flush()  # 获取自动生成的 ID
            await session.refresh(job)  # 确保所有字段都加载

            logger.debug(f"作业已创建: id={job.id}")
            return job

    @staticmethod
    async def get_job_by_id(
        job_id: int, with_allocation: bool = False
    ) -> Optional[Job]:
        """
        根据ID获取作业

        Args:
            job_id: 作业ID
            with_allocation: 是否同时加载资源分配信息

        Returns:
            作业对象，不存在则返回None
        """
        async with async_db.get_session() as session:
            query = select(Job).where(Job.id == job_id)

            if with_allocation:
                query = query.options(selectinload(Job.resource_allocation))

            result = await session.execute(query)
            job = result.scalar_one_or_none()

            return job

    @staticmethod
    async def update_job_state(
        job_id: int,
        new_state: JobState,
        error_msg: Optional[str] = None,
        exit_code: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> bool:
        """
        更新作业状态

        Args:
            job_id: 作业ID
            new_state: 新状态
            error_msg: 错误信息（可选）
            exit_code: 退出码（可选）
            start_time: 开始时间（可选）
            end_time: 结束时间（可选）

        Returns:
            是否更新成功
        """
        async with async_db.get_session() as session:
            update_data = {
                "state": new_state,
                "updated_at": datetime.utcnow(),
            }

            if error_msg is not None:
                update_data["error_msg"] = error_msg
            if exit_code is not None:
                update_data["exit_code"] = exit_code
            if start_time is not None:
                update_data["start_time"] = start_time
            if end_time is not None:
                update_data["end_time"] = end_time

            stmt = update(Job).where(Job.id == job_id).values(**update_data)

            result = await session.execute(stmt)
            success = result.rowcount > 0

            if success:
                logger.debug(f"作业状态已更新: id={job_id}, state={new_state}")

            return success

    @staticmethod
    async def query_jobs(
        account: Optional[str] = None,
        state: Optional[JobState] = None,
        partition: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Job]:
        """
        查询作业列表

        Args:
            account: 账户过滤（可选）
            state: 状态过滤（可选）
            partition: 分区过滤（可选）
            limit: 返回数量限制
            offset: 偏移量

        Returns:
            作业列表
        """
        async with async_db.get_session() as session:
            query = select(Job)

            if account:
                query = query.where(Job.account == account)
            if state:
                query = query.where(Job.state == state)
            if partition:
                query = query.where(Job.partition == partition)

            query = query.order_by(Job.submit_time.desc()).limit(limit).offset(offset)

            result = await session.execute(query)
            jobs = result.scalars().all()

            return list(jobs)

    @staticmethod
    async def create_resource_allocation(allocation_data: dict) -> ResourceAllocation:
        """
        创建资源分配记录

        Args:
            allocation_data: 资源分配数据

        Returns:
            创建的资源分配对象
        """
        async with async_db.get_session() as session:
            allocation = ResourceAllocation(**allocation_data)
            session.add(allocation)
            await session.flush()
            await session.refresh(allocation)

            logger.debug(f"资源分配已创建: job_id={allocation.job_id}")
            return allocation

    @staticmethod
    async def release_resource_allocation(job_id: int) -> bool:
        """
        释放资源分配

        更新状态为 released

        Args:
            job_id: 作业ID

        Returns:
            是否释放成功
        """
        async with async_db.get_session() as session:
            stmt = (
                update(ResourceAllocation)
                .where(ResourceAllocation.job_id == job_id)
                .values(
                    status=ResourceStatus.RELEASED,
                    released_time=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
            )

            result = await session.execute(stmt)
            success = result.rowcount > 0

            if success:
                logger.debug(f"资源已释放: job_id={job_id}")

            return success

    @staticmethod
    async def get_available_resources(partition: str) -> List[SystemResource]:
        """
        获取指定分区的可用资源

        Args:
            partition: 分区名称

        Returns:
            可用资源列表
        """
        async with async_db.get_session() as session:
            query = select(SystemResource).where(
                SystemResource.partition == partition,
                SystemResource.available == True,
            )

            result = await session.execute(query)
            resources = result.scalars().all()

            return list(resources)

    @staticmethod
    async def get_allocated_cpus_on_node(node_name: str) -> int:
        """
        获取节点上已分配的CPU数量

        只统计 status='allocated' 的资源（真正在运行的作业）

        Args:
            node_name: 节点名称

        Returns:
            已分配的CPU数量
        """
        async with async_db.get_session() as session:
            # 查询该节点上所有已分配（真正运行）的资源
            query = select(ResourceAllocation).where(
                ResourceAllocation.node_name == node_name,
                ResourceAllocation.status == ResourceStatus.ALLOCATED,
            )

            result = await session.execute(query)
            allocations = result.scalars().all()

            total_cpus = sum(alloc.allocated_cpus for alloc in allocations)
            return total_cpus

    @staticmethod
    async def delete_job(job_id: int) -> bool:
        """
        删除作业（通常不建议使用，推荐软删除）

        Args:
            job_id: 作业ID

        Returns:
            是否删除成功
        """
        async with async_db.get_session() as session:
            job = await session.get(Job, job_id)
            if not job:
                return False

            await session.delete(job)
            logger.debug(f"作业已删除: id={job_id}")

            return True

    @staticmethod
    async def batch_update_job_states(
        job_ids: List[int],
        new_state: JobState,
        error_msg: Optional[str] = None,
    ) -> int:
        """
        批量更新作业状态（用于批量操作，如系统关闭时）

        Args:
            job_ids: 作业ID列表
            new_state: 新状态
            error_msg: 错误信息（可选）

        Returns:
            更新的作业数量
        """
        if not job_ids:
            return 0

        async with async_db.get_session() as session:
            update_data = {
                "state": new_state,
                "updated_at": datetime.utcnow(),
            }

            if error_msg is not None:
                update_data["error_msg"] = error_msg

            stmt = update(Job).where(Job.id.in_(job_ids)).values(**update_data)

            result = await session.execute(stmt)
            count = result.rowcount

            logger.debug(f"批量更新了 {count} 个作业状态: state={new_state}")

            return count
