"""
Job Executor - 作业执行器

负责执行作业脚本并管理作业生命周期
"""

import os
import subprocess
from pathlib import Path
from typing import Optional

from loguru import logger

from core.config import get_settings
from core.database import sync_db
from core.models import Job
from core.enums import JobState, ResourceStatus
from core.services import ResourceManager

from worker.execution import JobExecutionContext, ExecutionStage
from worker.middleware import MiddlewareManager, create_default_manager
from worker.monitoring import ProcessMonitor
from worker.process import store_pid, kill_process_tree
from worker.repositories import WorkerRepository
from worker.resources import ResourceManagerWrapper


class JobExecutor:
    """
    作业执行器

    架构说明：
    - 使用 JobExecutionContext 统一管理执行状态
    - 使用 ResourceManagerWrapper 确保资源正确释放
    - 使用 ExecutionStage 划分执行阶段
    - 使用 ExecutionMiddleware 提供可扩展的处理机制
    - 使用 ProcessMonitor 监控进程状态
    - 使用 WorkerRepository 封装数据库操作
    - 遵循单一职责原则和关注点分离
    - 支持依赖注入，便于测试
    """

    def __init__(
        self,
        resource_manager: Optional[ResourceManager] = None,
        middleware_manager: Optional[MiddlewareManager] = None,
        process_monitor: Optional[ProcessMonitor] = None,
        worker_repository: Optional[WorkerRepository] = None,
        settings=None,
    ):
        """
        初始化执行器

        Args:
            resource_manager: 资源管理器（可选，用于依赖注入）
            middleware_manager: 中间件管理器（可选，用于依赖注入）
            process_monitor: 进程监控器（可选，用于依赖注入）
            worker_repository: Worker 仓储（可选，用于依赖注入）
            settings: 配置对象（可选，用于依赖注入）
        """
        self.settings = settings or get_settings()
        base_resource_manager = resource_manager or ResourceManager()
        self.resource_wrapper = ResourceManagerWrapper(base_resource_manager)
        self.middleware_manager = middleware_manager or create_default_manager()
        self.process_monitor = process_monitor or ProcessMonitor()
        self.worker_repository = worker_repository or WorkerRepository

    def execute(self, job_id: int):
        """
        执行作业

        使用执行上下文统一管理状态，使用资源管理器包装器确保资源正确释放。
        支持执行阶段和中间件机制。

        Args:
            job_id: 作业 ID
        """
        logger.info(f"🚀 Executing job {job_id}")

        # 创建执行上下文
        context = JobExecutionContext(job_id=job_id)

        # 阶段 1: 初始化
        self._on_stage(ExecutionStage.INITIALIZED, context)

        # 执行前中间件
        context = self.middleware_manager.execute_before(context)

        try:
            # 阶段 2: 加载作业
            context.job = self._load_job(job_id)
            self._on_stage(ExecutionStage.LOADED, context)

            # 验证状态
            if context.job.state != JobState.RUNNING:
                logger.error(
                    f"Job {job_id} state is {context.job.state.value}, expected RUNNING"
                )
                return

            # 阶段 3: 资源分配
            # 重要：在真正开始执行前，将资源状态从 reserved 更新为 allocated
            self._mark_resources_allocated(job_id, context.job.allocated_cpus)
            self._on_stage(ExecutionStage.RESOURCES_ALLOCATED, context)

            # 阶段 4: 环境准备
            self._prepare_environment(context)
            self._on_stage(ExecutionStage.PREPARED, context)

            # 使用资源管理器包装器确保资源正确释放
            with self.resource_wrapper.allocate_for_job(
                job_id, context.job.allocated_cpus
            ):
                # 阶段 5: 执行作业
                self._on_stage(ExecutionStage.RUNNING, context)
                context.exit_code = self._run(context)

                # 阶段 6: 执行完成
                self._on_stage(ExecutionStage.COMPLETED, context)

        except Exception as e:
            logger.error(f"❌ Job {job_id} failed: {e}", exc_info=True)
            context.error = e
            self._on_stage(ExecutionStage.FAILED, context)

            # 错误处理中间件
            self.middleware_manager.execute_on_error(context, e)

        finally:
            # 阶段 7: 清理
            self._cleanup(context)
            self._on_stage(ExecutionStage.CLEANED_UP, context)

            # 执行后中间件
            context = self.middleware_manager.execute_after(context)

            logger.info(
                f"✅ Job {job_id} finished (elapsed: {context.elapsed_time():.2f}s)"
            )

    def _on_stage(self, stage: ExecutionStage, context: JobExecutionContext):
        """
        阶段钩子方法

        可以被子类重写或通过中间件扩展

        Args:
            stage: 执行阶段
            context: 执行上下文
        """
        logger.debug(f"Job {context.job_id} entered stage: {stage.value}")

        # 调用中间件的阶段钩子
        context = self.middleware_manager.execute_on_stage(stage.value, context)

    def _load_job(self, job_id: int) -> Job:
        """加载作业信息"""
        with sync_db.get_session() as session:
            job = self.worker_repository.get_job_by_id(session, job_id)
            if not job:
                raise ValueError(f"Job {job_id} not found")
            return job

    def _prepare_environment(self, context: JobExecutionContext):
        """
        准备执行环境

        Args:
            context: 执行上下文
        """
        job = context.job
        context.script_path = self._prepare_script(job)
        context.stdout_path = Path(job.work_dir) / job.stdout_path
        context.stderr_path = Path(job.work_dir) / job.stderr_path

        # 准备环境变量
        context.env = os.environ.copy()
        if job.environment:
            context.env.update(job.environment)

    def _run(self, context: JobExecutionContext) -> int:
        """
        运行作业脚本

        Args:
            context: 执行上下文

        Returns:
            退出码
        """
        job = context.job
        logger.info(f"Running job {job.id}: {job.name}")

        # 执行脚本
        try:
            with (
                open(context.stdout_path, "w") as stdout,
                open(context.stderr_path, "w") as stderr,
            ):
                context.process = subprocess.Popen(
                    ["/bin/bash", context.script_path],
                    stdout=stdout,
                    stderr=stderr,
                    cwd=job.work_dir,
                    env=context.env,
                    preexec_fn=os.setsid,
                )

                # 记录进程信息
                context.process_id = context.process.pid
                store_pid(job.id, context.process_id)
                logger.info(f"Job {job.id} started, PID: {context.process_id}")

                # 开始监控进程
                self.process_monitor.start_monitoring(job.id, context)

                # 等待完成（支持超时）
                try:
                    timeout = job.time_limit * 60 if job.time_limit else None
                    exit_code = context.process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    logger.warning(f"Job {job.id} timeout, terminating...")
                    kill_process_tree(context.process_id, timeout=5)
                    exit_code = -1
                finally:
                    # 停止监控进程
                    self.process_monitor.stop_monitoring(job.id)

                logger.info(f"Job {job.id} finished, exit code: {exit_code}")
                return exit_code

        except Exception as e:
            logger.error(f"Failed to run job {job.id}: {e}")
            # 确保停止监控
            self.process_monitor.stop_monitoring(job.id)
            raise

    def _prepare_script(self, job: Job) -> str:
        """准备脚本文件"""
        # 确保目录存在
        Path(job.work_dir).mkdir(parents=True, exist_ok=True)

        # 写入脚本
        script_path = Path(self.settings.SCRIPT_DIR) / f"job_{job.id}.sh"
        script_path.parent.mkdir(parents=True, exist_ok=True)

        script_path.write_text(job.script)
        script_path.chmod(0o755)

        return str(script_path)

    def _cleanup(self, context: JobExecutionContext):
        """
        清理资源

        Args:
            context: 执行上下文
        """
        # 释放数据库中的资源分配（更新状态为 released）
        self._release_resources(context.job_id)

        # 更新最终状态
        if context.has_error():
            self._mark_failed(context.job_id, str(context.error))
        elif context.exit_code is not None:
            self._update_completion(context.job_id, context.exit_code)

    def _update_completion(self, job_id: int, exit_code: int):
        """更新作业完成状态"""
        with sync_db.get_session() as session:
            if self.worker_repository.update_job_completion(session, job_id, exit_code):
                session.commit()
                state = JobState.COMPLETED if exit_code == 0 else JobState.FAILED
                logger.info(f"Job {job_id} marked as {state.value}")

    def _mark_failed(self, job_id: int, error_msg: str):
        """标记作业失败"""
        try:
            with sync_db.get_session() as session:
                if self.worker_repository.update_job_failed(session, job_id, error_msg):
                    session.commit()
        except Exception as e:
            logger.error(f"Failed to mark job {job_id} as failed: {e}")

    def _mark_resources_allocated(self, job_id: int, cpus: int):
        """
        将资源状态从 reserved 更新为 allocated

        这是资源真正被占用的时刻，只有在 Worker 真正开始执行作业时才调用。
        这样可以避免作业被调度但未实际运行导致的资源泄漏问题。

        Args:
            job_id: 作业 ID
            cpus: CPU 数量
        """
        with sync_db.get_session() as session:
            allocation = self.worker_repository.update_allocation_to_allocated(
                session, job_id
            )

            if allocation:
                session.commit()

                # 注意：资源管理由 ResourceManagerWrapper 负责
                # 这里只更新数据库状态，缓存更新由包装器处理

                logger.info(
                    f"✅ Resources allocated for job {job_id}: {cpus} CPUs "
                    f"(status: reserved -> allocated)"
                )
            else:
                logger.warning(
                    f"⚠️  No resource allocation found for job {job_id}, "
                    f"creating new allocation"
                )
                # 如果没有预留记录（异常情况），直接创建 allocated 记录
                self.worker_repository.create_allocation_as_allocated(
                    session=session,
                    job_id=job_id,
                    allocated_cpus=cpus,
                    node_name=self.settings.NODE_NAME,
                )
                session.commit()
                # 注意：资源管理由 ResourceManagerWrapper 负责
                # 这里只更新数据库状态，缓存更新由包装器处理

    def _release_resources(self, job_id: int):
        """
        释放资源（更新数据库 + Redis 缓存）

        更新状态为 released，并回收资源到可用池

        Args:
            job_id: 作业 ID
        """
        with sync_db.get_session() as session:
            result = self.worker_repository.release_allocation(session, job_id)

            if result:
                allocation, old_status = result
                cpus = allocation.allocated_cpus

                session.commit()

                # 注意：Redis 缓存的释放由 ResourceManagerWrapper 负责
                # 这里只更新数据库状态
                if old_status == ResourceStatus.ALLOCATED:
                    logger.info(
                        f"♻️  Released {cpus} CPUs for job {job_id} "
                        f"(status: allocated -> released)"
                    )
                else:
                    logger.info(
                        f"♻️  Released reservation for job {job_id} "
                        f"(status: {old_status} -> released)"
                    )
            else:
                logger.warning(f"⚠️  No unreleased allocation found for job {job_id}")


# RQ 任务入口
def execute_job(job_id: int):
    """
    RQ 任务函数

    Args:
        job_id: 作业 ID
    """
    executor = JobExecutor()
    executor.execute(job_id)
