"""
核心作业管理服务

重构说明：
- 移除了对数据库会话的依赖注入
- 所有数据库操作通过 JobRepository 进行
- Repository 内部管理会话生命周期（按需创建，用完即释放）
- Service 层只关注业务逻辑，不关心数据库连接管理
"""

import os
import signal
from datetime import datetime

from loguru import logger

from core.models import Job
from core.enums import JobState, DataSource
from core.exceptions import JobNotFoundException
from core.redis_client import redis_manager
from core.utils.time_utils import (
    format_elapsed_time,
    format_limit_time,
)

from ..repositories import JobRepository
from ..schemas.job_submit import JobSubmitRequest
from ..schemas.job_query import JobQueryResponse, TimeInfo, JobLog, JobDetail
from .log_reader import LogReaderService


class JobService:
    """作业操作的核心服务"""

    @staticmethod
    async def submit_job(request: JobSubmitRequest) -> int:
        """
        向系统提交新作业

        参数:
            request: 作业提交请求

        返回:
            作业ID

        说明:
            1. 创建作业记录（短事务，立即释放连接）
            2. 执行队列操作（不占用数据库连接）
            3. 如需更新状态，再次获取连接（短事务）
        """
        job_spec = request.job
        script = request.script

        # 计算所需的总CPU数
        total_cpus = job_spec.get_total_cpus()
        time_limit_minutes = job_spec.get_time_limit_minutes()

        # 准备作业数据
        job_data = {
            "account": job_spec.account,
            "name": job_spec.name,
            "partition": job_spec.partition,
            "state": JobState.PENDING,
            "allocated_cpus": total_cpus,
            "allocated_nodes": 1,
            "ntasks_per_node": job_spec.ntasks_per_node,
            "cpus_per_task": job_spec.cpus_per_task,
            "memory_per_node": job_spec.memory_per_node,
            "time_limit": time_limit_minutes,
            "exclusive": job_spec.exclusive,
            "script": script,
            "work_dir": job_spec.current_working_directory,
            "stdout_path": job_spec.standard_output,
            "stderr_path": job_spec.standard_error,
            "environment": job_spec.environment,
            "data_source": DataSource.API,
            "exit_code": "",
        }

        # ✅ 短事务1：创建作业记录（会话自动管理，用完即释放）
        job = await JobRepository.create_job(job_data)
        job_id = job.id

        logger.info(
            f"作业已提交: id={job_id}, name={job_spec.name}, "
            f"cpus={total_cpus}, account={job_spec.account}"
        )

        # ⚡ 队列操作（不占用数据库连接）
        try:
            queue = redis_manager.get_queue()
            rq_job = queue.enqueue(
                "worker.executor.execute_job_task",
                job_id,
                job_timeout=3600 * 24,  # 24小时超时
            )
            logger.info(f"作业 {job_id} 已入队至RQ: {rq_job.id}")
        except Exception as e:
            logger.error(f"作业 {job_id} 入队失败: {e}")

            # ✅ 短事务2：更新失败状态（独立的短连接）
            await JobRepository.update_job_state(
                job_id=job_id,
                new_state=JobState.FAILED,
                error_msg=f"作业入队失败: {e}",
            )
            raise

        return job_id

    @staticmethod
    async def query_job(job_id: int) -> JobQueryResponse:
        """
        查询作业信息

        参数:
            job_id: 作业ID

        返回:
            作业查询响应

        异常:
            JobNotFoundException: 未找到对应作业时抛出

        说明:
            单次查询操作，短事务，快速释放连接
        """
        # ✅ 短事务：查询作业（会话自动管理）
        job = await JobRepository.get_job_by_id(job_id, with_allocation=True)

        if job is None:
            raise JobNotFoundException(job_id)

        # 计算时间信息（纯计算，不占用连接）
        time_info = JobService._build_time_info(job)

        # 读取日志文件内容（文件I/O，不占用数据库连接）
        stdout_content, stderr_content = await LogReaderService.get_job_logs(job)
        job_log = JobLog(stdout=stdout_content, stderr=stderr_content)

        # 构建作业详细信息
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

        # 构建响应体
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
    async def cancel_job(job_id: int) -> None:
        """
        取消作业（幂等操作）

        参数:
            job_id: 作业ID

        异常:
            JobNotFoundException: 未找到作业时抛出

        说明:
            1. 查询作业状态（短事务）
            2. 终止进程（系统调用，不占用连接）
            3. 更新状态和释放资源（短事务）
        """
        # ✅ 短事务1：查询作业
        job = await JobRepository.get_job_by_id(job_id, with_allocation=True)

        if job is None:
            raise JobNotFoundException(job_id)

        # 检查作业状态，已终止无需重复取消
        if job.state in [JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED]:
            # 幂等：已在终止状态
            logger.info(f"作业 {job_id} 已经处于终止状态: {job.state}")
            return

        # 如果作业正在运行，尝试终止作业进程
        if job.state == JobState.RUNNING:
            await JobService._kill_job_process(job)

        # ✅ 短事务2：更新作业状态为已取消
        await JobRepository.update_job_state(
            job_id=job_id,
            new_state=JobState.CANCELLED,
            end_time=datetime.utcnow(),
            exit_code=job.exit_code or "-1:15",  # SIGTERM信号
        )

        # ✅ 短事务3：释放资源分配
        await JobRepository.release_resource_allocation(job_id)

        logger.info(f"作业 {job_id} 取消成功")

    @staticmethod
    async def _kill_job_process(job: Job) -> None:
        """
        杀死正在运行的作业进程

        参数:
            job: 作业对象（已加载 resource_allocation 关系）

        说明:
            纯系统调用，不占用数据库连接
        """
        # 从已加载的关系中获取资源分配
        allocation = job.resource_allocation

        if allocation and allocation.process_id:
            try:
                # 向进程组发送SIGTERM信号以终止作业
                os.killpg(os.getpgid(allocation.process_id), signal.SIGTERM)
                logger.info(
                    f"已向作业 {job.id} 发送SIGTERM信号 (PID: {allocation.process_id})"
                )
            except ProcessLookupError:
                logger.warning(
                    f"未找到作业 {job.id} 对应的进程 {allocation.process_id}"
                )
            except Exception as e:
                logger.error(f"终止作业 {job.id} 进程失败: {e}")

    @staticmethod
    def _build_time_info(job: Job) -> TimeInfo:
        """
        构建作业时间信息

        参数:
            job: Job模型实例

        返回:
            TimeInfo 对象
        """
        # 计算作业已运行时间
        if job.start_time:
            end_time = job.end_time or datetime.utcnow()
            elapsed_time = format_elapsed_time(job.start_time, end_time)
        else:
            elapsed_time = "0-00:00:00"

        # 格式化时间限制信息
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
