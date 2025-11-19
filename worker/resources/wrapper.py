"""
Resource Manager Wrapper - 资源管理器包装器

确保资源正确分配和释放，防止资源泄漏
"""

from contextlib import contextmanager
from typing import Dict, Optional

from loguru import logger

from core.services import ResourceManager


class ResourceAllocationError(Exception):
    """资源分配错误"""

    pass


class ResourceManagerWrapper:
    """
    资源管理器包装器

    职责：
    - 跟踪每个作业的资源分配
    - 确保资源正确释放
    - 防止资源泄漏
    - 提供上下文管理器接口
    """

    def __init__(self, resource_manager: ResourceManager):
        """
        初始化资源管理器包装器

        Args:
            resource_manager: 底层资源管理器
        """
        self.resource_manager = resource_manager
        self._allocated_resources: Dict[int, int] = {}  # job_id -> cpus

    @contextmanager
    def allocate_for_job(self, job_id: int, cpus: int):
        """
        为作业分配资源（上下文管理器）

        使用示例：
            with resource_wrapper.allocate_for_job(job_id, cpus):
                # 执行作业
                ...
            # 自动释放资源

        Args:
            job_id: 作业ID
            cpus: 需要的CPU数量

        Yields:
            无

        Raises:
            ResourceAllocationError: 如果资源分配失败
        """
        try:
            # 分配资源
            self._allocate(job_id, cpus)
            yield
        finally:
            # 确保释放资源
            self._release(job_id)

    def _allocate(self, job_id: int, cpus: int):
        """
        分配资源

        Args:
            job_id: 作业ID
            cpus: CPU数量

        Raises:
            ResourceAllocationError: 如果作业已有资源分配或分配失败
        """
        if job_id in self._allocated_resources:
            raise ResourceAllocationError(
                f"Job {job_id} already has allocated resources "
                f"({self._allocated_resources[job_id]} CPUs)"
            )

        # 调用底层资源管理器分配资源
        if not self.resource_manager.allocate(cpus):
            raise ResourceAllocationError(
                f"Failed to allocate {cpus} CPUs for job {job_id}"
            )

        self._allocated_resources[job_id] = cpus
        logger.debug(f"Allocated {cpus} CPUs for job {job_id}")

    def _release(self, job_id: int):
        """
        释放资源

        Args:
            job_id: 作业ID
        """
        if job_id in self._allocated_resources:
            cpus = self._allocated_resources.pop(job_id)
            self.resource_manager.release(cpus)
            logger.debug(f"Released {cpus} CPUs for job {job_id}")
        else:
            logger.warning(
                f"No allocated resources found for job {job_id} "
                f"(may have been released already)"
            )

    def has_allocation(self, job_id: int) -> bool:
        """
        检查作业是否有资源分配

        Args:
            job_id: 作业ID

        Returns:
            True 如果作业有资源分配
        """
        return job_id in self._allocated_resources

    def get_allocated_cpus(self, job_id: int) -> Optional[int]:
        """
        获取作业已分配的CPU数量

        Args:
            job_id: 作业ID

        Returns:
            已分配的CPU数量，如果没有分配则返回None
        """
        return self._allocated_resources.get(job_id)

    def force_release(self, job_id: int) -> bool:
        """
        强制释放资源（即使不在跟踪列表中）

        用于异常情况下的资源清理

        Args:
            job_id: 作业ID

        Returns:
            True 如果释放成功
        """
        if job_id in self._allocated_resources:
            self._release(job_id)
            return True
        return False
