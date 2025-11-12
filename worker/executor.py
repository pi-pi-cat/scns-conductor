"""
Job Executor - 作业执行器

负责执行作业脚本并管理作业生命周期
"""

import os
import subprocess
from datetime import datetime
from pathlib import Path

from loguru import logger

from core.config import get_settings
from core.database import sync_db
from core.models import Job, ResourceAllocation
from core.enums import JobState, ResourceStatus
from core.services import ResourceManager

from worker.process_utils import store_pid, kill_process_tree


class JobExecutor:
    """
    作业执行器

    重构说明：
    - 使用 ResourceManager 管理资源释放
    - 遵循 DRY 原则
    """

    def __init__(self, resource_manager: ResourceManager = None):
        """
        初始化执行器

        Args:
            resource_manager: 资源管理器（可选，用于依赖注入）
        """
        self.settings = get_settings()
        self.resource_manager = resource_manager or ResourceManager()

    def execute(self, job_id: int):
        """
        执行作业

        Args:
            job_id: 作业 ID
        """
        logger.info(f"🚀 Executing job {job_id}")

        exit_code = None
        error_occurred = False
        error_msg = None

        try:
            # 加载作业
            job = self._load_job(job_id)

            # 验证状态
            if job.state != JobState.RUNNING:
                logger.error(
                    f"Job {job_id} state is {job.state.value}, expected RUNNING"
                )
                return

            # 重要：在真正开始执行前，将资源状态从 reserved 更新为 allocated
            # 这样才算真正占用资源
            self._mark_resources_allocated(job_id, job.allocated_cpus)

            # 执行作业
            exit_code = self._run(job)

        except Exception as e:
            logger.error(f"❌ Job {job_id} failed: {e}", exc_info=True)
            error_occurred = True
            error_msg = str(e)

        finally:
            # 重要：先释放资源，再更新状态
            # 避免 scheduler 的 release_completed() 抢先释放资源
            self._release_resources(job_id)

            # 更新最终状态
            if error_occurred:
                self._mark_failed(job_id, error_msg)
            elif exit_code is not None:
                self._update_completion(job_id, exit_code)

            logger.info(f"✅ Job {job_id} finished")

    def _load_job(self, job_id: int) -> Job:
        """加载作业信息"""
        with sync_db.get_session() as session:
            job = session.query(Job).filter(Job.id == job_id).first()
            if not job:
                raise ValueError(f"Job {job_id} not found")
            session.expunge(job)
            return job

    def _run(self, job: Job) -> int:
        """运行作业脚本"""
        logger.info(f"Running job {job.id}: {job.name}")

        # 准备环境
        script_path = self._prepare_script(job)
        stdout_path = Path(job.work_dir) / job.stdout_path
        stderr_path = Path(job.work_dir) / job.stderr_path

        # 准备环境变量
        env = os.environ.copy()
        if job.environment:
            env.update(job.environment)

        # 执行脚本
        try:
            with open(stdout_path, "w") as stdout, open(stderr_path, "w") as stderr:
                process = subprocess.Popen(
                    ["/bin/bash", script_path],
                    stdout=stdout,
                    stderr=stderr,
                    cwd=job.work_dir,
                    env=env,
                    preexec_fn=os.setsid,
                )

                # 记录进程 ID
                store_pid(job.id, process.pid)
                logger.info(f"Job {job.id} started, PID: {process.pid}")

                # 等待完成（支持超时）
                try:
                    timeout = job.time_limit * 60 if job.time_limit else None
                    exit_code = process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    logger.warning(f"Job {job.id} timeout, terminating...")
                    kill_process_tree(process.pid, timeout=5)
                    exit_code = -1

                logger.info(f"Job {job.id} finished, exit code: {exit_code}")
                return exit_code

        except Exception as e:
            logger.error(f"Failed to run job {job.id}: {e}")
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

    def _update_completion(self, job_id: int, exit_code: int):
        """更新作业完成状态"""
        with sync_db.get_session() as session:
            job = session.query(Job).filter(Job.id == job_id).first()
            if job:
                job.state = JobState.COMPLETED if exit_code == 0 else JobState.FAILED
                job.end_time = datetime.utcnow()
                job.exit_code = f"{exit_code}:0"

                if exit_code != 0:
                    job.error_msg = f"Exited with code {exit_code}"

                session.commit()
                logger.info(f"Job {job_id} marked as {job.state.value}")

    def _mark_failed(self, job_id: int, error_msg: str):
        """标记作业失败"""
        try:
            with sync_db.get_session() as session:
                job = session.query(Job).filter(Job.id == job_id).first()
                if job:
                    job.state = JobState.FAILED
                    job.end_time = datetime.utcnow()
                    job.error_msg = error_msg
                    job.exit_code = "-1:0"
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
            allocation = (
                session.query(ResourceAllocation)
                .filter(ResourceAllocation.job_id == job_id)
                .first()
            )

            if allocation:
                # 更新状态为 allocated
                allocation.status = ResourceStatus.ALLOCATED
                session.commit()

                # 更新 Redis 缓存（现在资源才真正被占用）
                self.resource_manager.allocate(cpus)

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
                allocation = ResourceAllocation(
                    job_id=job_id,
                    allocated_cpus=cpus,
                    node_name=self.settings.NODE_NAME,
                    allocation_time=datetime.utcnow(),
                    status=ResourceStatus.ALLOCATED,
                )
                session.add(allocation)
                session.commit()
                self.resource_manager.allocate(cpus)

    def _release_resources(self, job_id: int):
        """
        释放资源（更新数据库 + Redis 缓存）
        
        更新状态为 released，并回收资源到可用池

        Args:
            job_id: 作业 ID
        """
        with sync_db.get_session() as session:
            # 查找未释放的资源分配记录（status != released）
            allocation = (
                session.query(ResourceAllocation)
                .filter(
                    ResourceAllocation.job_id == job_id,
                    ResourceAllocation.status != ResourceStatus.RELEASED,
                )
                .first()
            )

            if allocation:
                cpus = allocation.allocated_cpus
                old_status = allocation.status

                # 1. 更新状态为已释放
                allocation.status = ResourceStatus.RELEASED
                allocation.released_time = datetime.utcnow()
                session.commit()

                # 2. 只有在资源实际被分配时（allocated）才需要更新缓存
                # 如果还是 reserved 状态就被释放了，说明从未真正占用，不需要释放缓存
                if old_status == ResourceStatus.ALLOCATED:
                    self.resource_manager.release(cpus)
                    logger.info(
                        f"♻️  Released {cpus} CPUs for job {job_id} "
                        f"(status: allocated -> released)"
                    )
                else:
                    logger.info(
                        f"♻️  Released reservation for job {job_id} "
                        f"(status: {old_status} -> released, no cache update needed)"
                    )
            else:
                logger.warning(
                    f"⚠️  No unreleased allocation found for job {job_id}"
                )


# RQ 任务入口
def execute_job(job_id: int):
    """
    RQ 任务函数

    Args:
        job_id: 作业 ID
    """
    executor = JobExecutor()
    executor.execute(job_id)
