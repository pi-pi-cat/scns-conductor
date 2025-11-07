"""
作业执行器 - 以子进程方式执行作业
"""

import os
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path

from loguru import logger
from sqlalchemy.orm import Session

from core.config import get_settings
from core.database import sync_db
from core.models import Job, ResourceAllocation
from core.enums import JobState
from .scheduler import ResourceScheduler


class JobExecutor:
    """
    作业执行器服务
    以子进程方式执行作业，并进行适当的环境配置
    """

    def __init__(self):
        self.settings = get_settings()
        self.scheduler = ResourceScheduler()

    def execute_job(self, job_id: int) -> None:
        """
        执行单个作业

        这是RQ worker调用的主入口点。
        它处理完整的作业生命周期：
        1. 等待调度（如果处于待处理状态）
        2. 准备执行环境
        3. 执行脚本
        4. 更新作业状态
        5. 释放资源

        Args:
            job_id: 要执行的作业ID
        """
        logger.info(f"Starting execution of job {job_id}")

        try:
            # 等待作业被调度
            job = self._wait_for_scheduling(job_id)

            if job is None or job.state == JobState.CANCELLED:
                logger.info(f"Job {job_id} was cancelled before execution")
                return

            # 执行作业
            exit_code = self._run_job(job)

            # 更新作业状态
            self._update_job_completion(job_id, exit_code)

        except Exception as e:
            logger.error(f"Job {job_id} execution failed: {e}", exc_info=True)
            self._mark_job_failed(job_id, str(e))

        finally:
            # 始终释放资源
            self.scheduler.release_resources(job_id)
            logger.info(f"Completed execution of job {job_id}")

    def _wait_for_scheduling(self, job_id: int, timeout: int = 3600) -> Job:
        """
        Wait for job to be scheduled by the scheduler daemon

        Args:
            job_id: Job ID
            timeout: Maximum wait time in seconds

        Returns:
            Job object or None if cancelled
        """
        start_time = time.time()

        while True:
            with sync_db.get_session() as session:
                job = session.query(Job).filter(Job.id == job_id).first()

                if job is None:
                    raise ValueError(f"Job {job_id} not found")

                if job.state == JobState.RUNNING:
                    # 刷新以获取最新数据
                    session.refresh(job)
                    # 从会话中分离以便在外部使用
                    session.expunge(job)
                    return job

                if job.state == JobState.CANCELLED:
                    return None

                if job.state != JobState.PENDING:
                    raise ValueError(f"Unexpected job state: {job.state}")

            # 检查超时
            if time.time() - start_time > timeout:
                raise TimeoutError(f"Job {job_id} not scheduled within {timeout}s")

            # 等待后再检查
            time.sleep(1)

    def _run_job(self, job: Job) -> int:
        """
        Run job script as subprocess

        Args:
            job: Job object

        Returns:
            Exit code
        """
        logger.info(f"Running job {job.id}: {job.name}")

        # 准备执行环境
        script_path = self._prepare_execution_environment(job)

        # 构建标准输出/错误输出路径
        stdout_path = os.path.join(job.work_dir, job.stdout_path)
        stderr_path = os.path.join(job.work_dir, job.stderr_path)

        # 准备环境变量
        env = os.environ.copy()
        if job.environment:
            env.update(job.environment)

        # 执行脚本
        try:
            with (
                open(stdout_path, "w") as stdout_file,
                open(stderr_path, "w") as stderr_file,
            ):
                process = subprocess.Popen(
                    ["/bin/bash", script_path],
                    stdout=stdout_file,
                    stderr=stderr_file,
                    cwd=job.work_dir,
                    env=env,
                    preexec_fn=os.setsid,  # 创建新的进程组
                )

                # 存储进程ID
                self._store_process_id(job.id, process.pid)

                logger.info(f"Job {job.id} started with PID {process.pid}")

                # 等待完成（带超时）
                try:
                    timeout_seconds = job.time_limit * 60 if job.time_limit else None
                    exit_code = process.wait(timeout=timeout_seconds)

                except subprocess.TimeoutExpired:
                    logger.warning(f"Job {job.id} exceeded time limit, terminating")
                    # 终止进程组
                    try:
                        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                        time.sleep(5)
                        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    exit_code = -1

                logger.info(f"Job {job.id} completed with exit code {exit_code}")
                return exit_code

        except Exception as e:
            logger.error(f"Failed to execute job {job.id}: {e}")
            raise

    def _prepare_execution_environment(self, job: Job) -> str:
        """
        Prepare job execution environment

        Args:
            job: Job object

        Returns:
            Path to script file
        """
        # 确保工作目录存在
        Path(job.work_dir).mkdir(parents=True, exist_ok=True)

        # 将脚本写入文件
        script_path = os.path.join(self.settings.SCRIPT_DIR, f"job_{job.id}.sh")

        Path(self.settings.SCRIPT_DIR).mkdir(parents=True, exist_ok=True)

        with open(script_path, "w") as f:
            f.write(job.script)

        # 使脚本可执行
        os.chmod(script_path, 0o755)

        logger.debug(f"Prepared script for job {job.id} at {script_path}")

        return script_path

    def _store_process_id(self, job_id: int, pid: int) -> None:
        """
        Store process ID in resource allocation

        Args:
            job_id: Job ID
            pid: Process ID
        """
        with sync_db.get_session() as session:
            allocation = (
                session.query(ResourceAllocation)
                .filter(ResourceAllocation.job_id == job_id)
                .first()
            )

            if allocation:
                allocation.process_id = pid
                session.commit()

    def _update_job_completion(self, job_id: int, exit_code: int) -> None:
        """
        Update job status after completion

        Args:
            job_id: Job ID
            exit_code: Process exit code
        """
        with sync_db.get_session() as session:
            job = session.query(Job).filter(Job.id == job_id).first()

            if job:
                job.state = JobState.COMPLETED if exit_code == 0 else JobState.FAILED
                job.end_time = datetime.utcnow()
                job.exit_code = f"{exit_code}:0"

                if exit_code != 0:
                    job.error_msg = f"Job exited with code {exit_code}"

                session.commit()

                logger.info(
                    f"Job {job_id} marked as {job.state.value} (exit_code={exit_code})"
                )

    def _mark_job_failed(self, job_id: int, error_msg: str) -> None:
        """
        Mark job as failed with error message

        Args:
            job_id: Job ID
            error_msg: Error message
        """
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


# RQ task function
def execute_job_task(job_id: int) -> None:
    """
    RQ task entry point for job execution

    Args:
        job_id: Job ID to execute
    """
    executor = JobExecutor()
    executor.execute_job(job_id)
