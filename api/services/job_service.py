"""
核心作业管理服务
"""

import os
import signal
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from core.models import Job, ResourceAllocation
from core.enums import JobState, DataSource
from core.exceptions import JobNotFoundException, JobStateException
from core.redis_client import redis_manager
from core.utils.time_utils import (
    format_elapsed_time,
    format_limit_time,
    parse_time_limit,
)
from core.config import get_settings

from ..schemas.job_submit import JobSpec, JobSubmitRequest
from ..schemas.job_query import JobQueryResponse, TimeInfo, JobLog, JobDetail
from .log_reader import LogReaderService


class JobService:
    """作业操作的核心服务"""

    @staticmethod
    async def submit_job(request: JobSubmitRequest, db: AsyncSession) -> int:
        """
        向系统提交新作业

        Args:
            request: 作业提交请求
            db: 数据库会话

        Returns:
            作业ID
        """
        job_spec = request.job
        script = request.script

        # 计算所需的总CPU数
        total_cpus = job_spec.get_total_cpus()
        time_limit_minutes = job_spec.get_time_limit_minutes()

        # 创建作业记录
        job = Job(
            account=job_spec.account,
            name=job_spec.name,
            partition=job_spec.partition,
            state=JobState.PENDING,
            allocated_cpus=total_cpus,
            allocated_nodes=1,
            ntasks_per_node=job_spec.ntasks_per_node,
            cpus_per_task=job_spec.cpus_per_task,
            memory_per_node=job_spec.memory_per_node,
            time_limit=time_limit_minutes,
            exclusive=job_spec.exclusive,
            script=script,
            work_dir=job_spec.current_working_directory,
            stdout_path=job_spec.standard_output,
            stderr_path=job_spec.standard_error,
            environment=job_spec.environment,
            data_source=DataSource.API,
            exit_code="",
        )

        # 添加到数据库
        db.add(job)
        await db.flush()  # 刷新以获取作业ID
        await db.refresh(job)

        job_id = job.id

        # 提交事务
        await db.commit()

        logger.info(
            f"Job submitted: id={job_id}, name={job_spec.name}, "
            f"cpus={total_cpus}, account={job_spec.account}"
        )

        # 将作业加入执行队列（由worker的调度守护进程处理）
        # 注意：这将由worker的调度守护进程处理
        # 我们只需将其标记为PENDING，调度器会自动拾取

        return job_id

    @staticmethod
    async def query_job(job_id: int, db: AsyncSession) -> JobQueryResponse:
        """
        Query job information

        Args:
            job_id: Job ID
            db: Database session

        Returns:
            Job query response

        Raises:
            JobNotFoundException: If job not found
        """
        # 查询作业
        stmt = select(Job).where(Job.id == job_id)
        result = await db.execute(stmt)
        job = result.scalar_one_or_none()

        if job is None:
            raise JobNotFoundException(job_id)

        # 计算时间信息
        time_info = JobService._build_time_info(job)

        # 读取日志
        stdout_content, stderr_content = await LogReaderService.get_job_logs(job)
        job_log = JobLog(stdout=stdout_content, stderr=stderr_content)

        # 构建详细信息
        detail = JobDetail(
            job_name=job.name,
            user=job.account,
            partition=job.partition,
            allocated_cpus=job.allocated_cpus,
            allocated_nodes=job.allocated_nodes,
            node_list=job.node_list or "",
            exit_code=job.exit_code or ":",
            work_dir=job.work_dir,
            data_source=job.data_source,
            account=job.account,
        )

        # 构建响应
        response = JobQueryResponse(
            job_id=str(job.id),
            state=job.state,
            error_msg=job.error_msg,
            time=time_info,
            job_log=job_log,
            detail=detail,
        )

        return response

    @staticmethod
    async def cancel_job(job_id: int, db: AsyncSession) -> None:
        """
        Cancel a job (idempotent operation)

        Args:
            job_id: Job ID
            db: Database session

        Raises:
            JobNotFoundException: If job not found
        """
        # 查询作业
        stmt = select(Job).where(Job.id == job_id)
        result = await db.execute(stmt)
        job = result.scalar_one_or_none()

        if job is None:
            raise JobNotFoundException(job_id)

        # 检查作业是否可以取消
        if job.state in [JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED]:
            # 幂等性：已经处于终止状态
            logger.info(f"Job {job_id} already in terminal state: {job.state}")
            return

        # 如果作业正在运行，尝试终止进程
        if job.state == JobState.RUNNING:
            await JobService._kill_job_process(job_id, db)

        # 更新作业状态
        job.state = JobState.CANCELLED
        job.end_time = datetime.utcnow()
        if not job.exit_code:
            job.exit_code = "-1:15"  # SIGTERM

        # 释放资源
        stmt = select(ResourceAllocation).where(
            ResourceAllocation.job_id == job_id, ResourceAllocation.released == False
        )
        result = await db.execute(stmt)
        allocation = result.scalar_one_or_none()

        if allocation:
            allocation.released = True
            allocation.released_time = datetime.utcnow()

        await db.commit()

        logger.info(f"Job {job_id} cancelled successfully")

    @staticmethod
    async def _kill_job_process(job_id: int, db: AsyncSession) -> None:
        """
        Kill running job process

        Args:
            job_id: Job ID
            db: Database session
        """
        # Query process ID from resource allocation
        stmt = select(ResourceAllocation).where(ResourceAllocation.job_id == job_id)
        result = await db.execute(stmt)
        allocation = result.scalar_one_or_none()

        if allocation and allocation.process_id:
            try:
                # 向进程组发送SIGTERM信号
                os.killpg(os.getpgid(allocation.process_id), signal.SIGTERM)
                logger.info(
                    f"Sent SIGTERM to job {job_id} (PID: {allocation.process_id})"
                )
            except ProcessLookupError:
                logger.warning(
                    f"Process {allocation.process_id} for job {job_id} not found"
                )
            except Exception as e:
                logger.error(f"Failed to kill job {job_id} process: {e}")

    @staticmethod
    def _build_time_info(job: Job) -> TimeInfo:
        """
        Build time information for job

        Args:
            job: Job model

        Returns:
            TimeInfo object
        """
        # 计算经过的时间
        if job.start_time:
            end_time = job.end_time or datetime.utcnow()
            elapsed_time = format_elapsed_time(job.start_time, end_time)
        else:
            elapsed_time = "0-00:00:00"

        # 格式化时间限制
        if job.time_limit:
            limit_time = format_limit_time(job.time_limit)
        else:
            limit_time = "UNLIMITED"

        return TimeInfo(
            submit_time=job.submit_time,
            start_time=job.start_time,
            end_time=job.end_time,
            eligible_time=job.eligible_time,
            elapsed_time=elapsed_time,
            limit_time=limit_time,
        )
