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
from core.enums import JobState

from shared.resource_manager import ResourceManager
from shared.process_utils import store_pid, kill_process_tree


class JobExecutor:
    """作业执行器"""

    def __init__(self):
        self.settings = get_settings()
        self.resource_manager = ResourceManager()

    def execute(self, job_id: int):
        """
        执行作业

        Args:
            job_id: 作业 ID
        """
        logger.info(f"🚀 Executing job {job_id}")

        try:
            # 加载作业
            job = self._load_job(job_id)

            # 验证状态
            if job.state != JobState.RUNNING:
                logger.error(
                    f"Job {job_id} state is {job.state.value}, expected RUNNING"
                )
                return

            # 执行作业
            exit_code = self._run(job)

            # 更新状态
            self._update_completion(job_id, exit_code)

        except Exception as e:
            logger.error(f"❌ Job {job_id} failed: {e}", exc_info=True)
            self._mark_failed(job_id, str(e))

        finally:
            # 释放资源
            self._release_resources(job_id)
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

    def _release_resources(self, job_id: int):
        """释放资源"""
        with sync_db.get_session() as session:
            allocation = (
                session.query(ResourceAllocation)
                .filter(
                    ResourceAllocation.job_id == job_id,
                    ResourceAllocation.released == False,
                )
                .first()
            )

            if allocation:
                allocation.released = True
                allocation.released_time = datetime.utcnow()
                self.resource_manager.release(allocation.allocated_cpus)
                session.commit()

                logger.info(
                    f"♻️  Released {allocation.allocated_cpus} CPUs for job {job_id}"
                )
            else:
                logger.warning(f"⚠️  No allocation found for job {job_id}")


# RQ 任务入口
def execute_job(job_id: int):
    """
    RQ 任务函数

    Args:
        job_id: 作业 ID
    """
    executor = JobExecutor()
    executor.execute(job_id)
