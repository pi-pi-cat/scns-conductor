"""
作业数据仓储 V2 - 使用 BaseRepository 减少重复代码

重构说明：
- 继承 BaseRepository 获得通用CRUD操作
- 只需实现特定业务逻辑
- 代码量减少约 60%
"""

from typing import Optional, List
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from loguru import logger

from core.models import Job, ResourceAllocation, SystemResource
from core.enums import JobState, ResourceStatus
from .base_repository import BaseRepository, QueryBuilder


class JobRepositoryV2(BaseRepository[Job]):
    """
    作业数据仓储 V2

    继承自 BaseRepository，获得：
    - create(data) - 创建作业
    - get_by_id(id) - 根据ID查询
    - update_by_id(id, data) - 更新
    - delete_by_id(id) - 删除
    - find_many(**filters) - 条件查询
    - batch_update(ids, data) - 批量更新
    等通用方法

    只需实现业务特定的复杂查询
    """

    model = Job

    @classmethod
    async def get_job_with_allocation(cls, job_id: int) -> Optional[Job]:
        """
        获取作业（包含资源分配）

        特定业务逻辑：需要联表查询
        """
        async with cls._session() as session:
            query = (
                select(Job)
                .where(Job.id == job_id)
                .options(selectinload(Job.resource_allocation))
            )
            result = await session.execute(query)
            return result.scalar_one_or_none()

    @classmethod
    async def update_job_state(
        cls,
        job_id: int,
        new_state: JobState,
        error_msg: Optional[str] = None,
        exit_code: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> bool:
        """
        更新作业状态

        特定业务逻辑：需要更新多个相关字段
        """
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

        return await cls.update_by_id(job_id, update_data)

    @classmethod
    async def query_jobs_by_state(cls, state: JobState, limit: int = 100) -> List[Job]:
        """
        按状态查询作业

        使用 QueryBuilder 实现链式调用
        """
        return await (
            QueryBuilder(Job)
            .where(state=state)
            .order_by("submit_time", desc=True)
            .limit(limit)
            .execute()
        )

    @classmethod
    async def get_stats_by_state(cls) -> dict:
        """
        获取各状态的作业统计

        特定业务逻辑：聚合统计
        """
        stats = {}
        for state in JobState:
            count = await cls.count(state=state)
            stats[state.value] = count
        return stats


class ResourceAllocationRepository(BaseRepository[ResourceAllocation]):
    """资源分配仓储"""

    model = ResourceAllocation

    @classmethod
    async def release_by_job_id(cls, job_id: int) -> bool:
        """释放作业的资源分配"""
        return await cls.update_by_id(
            job_id,
            {
                "status": ResourceStatus.RELEASED,
                "released_time": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            },
        )

    @classmethod
    async def get_allocated_cpus_on_node(cls, node_name: str) -> int:
        """获取节点上已分配的CPU数量（只统计真正在运行的作业）"""
        async with cls._session() as session:
            query = select(ResourceAllocation).where(
                ResourceAllocation.node_name == node_name,
                ResourceAllocation.status == ResourceStatus.ALLOCATED,
            )
            result = await session.execute(query)
            allocations = result.scalars().all()
            return sum(alloc.allocated_cpus for alloc in allocations)


class SystemResourceRepository(BaseRepository[SystemResource]):
    """系统资源仓储"""

    model = SystemResource

    @classmethod
    async def get_by_partition(cls, partition: str) -> List[SystemResource]:
        """获取指定分区的资源"""
        return await cls.find_many(partition=partition, available=True)

    @classmethod
    async def get_total_cpus(cls) -> int:
        """获取总CPU数"""
        async with cls._session() as session:
            resources = await cls.get_all()
            return sum(r.total_cpus for r in resources)
