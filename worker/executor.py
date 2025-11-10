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

        这是被RQ worker调用的主入口。
        它包含作业的完整生命周期：
        1. 等待调度（如果处于待处理状态）
        2. 准备执行环境
        3. 执行脚本
        4. 更新作业状态
        5. 释放资源

        参数:
            job_id: 要执行的作业ID
        """
        logger.info(f"开始执行作业 {job_id}")

        try:
            # 等待作业被调度
            job = self._wait_for_scheduling(job_id)

            if job is None or job.state == JobState.CANCELLED:
                logger.info(f"作业 {job_id} 在执行前被取消")
                return

            # 执行作业
            exit_code = self._run_job(job)

            # 更新作业状态
            self._update_job_completion(job_id, exit_code)

        except Exception as e:
            logger.error(f"作业 {job_id} 执行失败: {e}", exc_info=True)
            self._mark_job_failed(job_id, str(e))

        finally:
            # 始终释放资源
            self.scheduler.release_resources(job_id)
            logger.info(f"已完成作业 {job_id} 的执行")

    def _wait_for_scheduling(self, job_id: int, timeout: int = 3600) -> Job:
        """
        等待调度器守护进程调度作业

        参数:
            job_id: 作业ID
            timeout: 最大等待时间（秒）

        返回:
            作业对象 或 None（被取消时）
        """
        start_time = time.time()

        while True:
            with sync_db.get_session() as session:
                job = session.query(Job).filter(Job.id == job_id).first()

                if job is None:
                    raise ValueError(f"未找到作业 {job_id}")

                if job.state == JobState.RUNNING:
                    # 刷新以获取最新数据
                    session.refresh(job)
                    # 从会话中分离以便在外部使用
                    session.expunge(job)
                    return job

                if job.state == JobState.CANCELLED:
                    return None

                if job.state != JobState.PENDING:
                    raise ValueError(f"作业状态异常: {job.state}")

            # 检查超时
            if time.time() - start_time > timeout:
                raise TimeoutError(f"作业 {job_id} 超过 {timeout} 秒未被调度")

            # 等待1秒后重试
            time.sleep(1)

    def _run_job(self, job: Job) -> int:
        """
        以子进程方式运行作业脚本

        参数:
            job: 作业对象

        返回:
            脚本退出码
        """
        logger.info(f"运行作业 {job.id}: {job.name}")

        # 准备执行环境
        script_path = self._prepare_execution_environment(job)

        # 构建标准输出/错误输出路径
        stdout_path = os.path.join(job.work_dir, job.stdout_path)
        stderr_path = os.path.join(job.work_dir, job.stderr_path)

        # 准备环境变量
        env = os.environ.copy()
        if job.environment:
            env.update(job.environment)

        # 执行脚本文件
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

                # 记录进程ID
                self._store_process_id(job.id, process.pid)

                logger.info(f"作业 {job.id} 启动，PID 为 {process.pid}")

                # 等待完成（支持超时）
                try:
                    timeout_seconds = job.time_limit * 60 if job.time_limit else None
                    exit_code = process.wait(timeout=timeout_seconds)

                except subprocess.TimeoutExpired:
                    logger.warning(f"作业 {job.id} 超过运行时限，正在终止")
                    # 终止进程组
                    try:
                        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                        time.sleep(5)
                        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    exit_code = -1

                logger.info(f"作业 {job.id} 执行完成，退出码 {exit_code}")
                return exit_code

        except Exception as e:
            logger.error(f"执行作业 {job.id} 失败: {e}")
            raise

    def _prepare_execution_environment(self, job: Job) -> str:
        """
        准备作业的执行环境

        参数:
            job: 作业对象

        返回:
            脚本文件路径
        """
        # 确保工作目录存在
        Path(job.work_dir).mkdir(parents=True, exist_ok=True)

        # 将脚本写入文件
        script_path = os.path.join(self.settings.SCRIPT_DIR, f"job_{job.id}.sh")

        Path(self.settings.SCRIPT_DIR).mkdir(parents=True, exist_ok=True)

        with open(script_path, "w") as f:
            f.write(job.script)

        # 设置脚本为可执行
        os.chmod(script_path, 0o755)

        logger.debug(f"已为作业 {job.id} 准备脚本：{script_path}")

        return script_path

    def _store_process_id(self, job_id: int, pid: int) -> None:
        """
        在资源分配记录中存储进程ID

        参数:
            job_id: 作业ID
            pid: 进程ID
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
        作业完成后更新其状态

        参数:
            job_id: 作业ID
            exit_code: 进程退出码
        """
        with sync_db.get_session() as session:
            job = session.query(Job).filter(Job.id == job_id).first()

            if job:
                job.state = JobState.COMPLETED if exit_code == 0 else JobState.FAILED
                job.end_time = datetime.utcnow()
                job.exit_code = f"{exit_code}:0"

                if exit_code != 0:
                    job.error_msg = f"作业以退出码 {exit_code} 终止"

                session.commit()

                logger.info(
                    f"作业 {job_id} 标记为 {job.state.value}（exit_code={exit_code}）"
                )

    def _mark_job_failed(self, job_id: int, error_msg: str) -> None:
        """
        标记作业为失败并记录错误信息

        参数:
            job_id: 作业ID
            error_msg: 错误信息
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
            logger.error(f"标记作业 {job_id} 失败状态出错: {e}")


# RQ任务函数
def execute_job_task(job_id: int) -> None:
    """
    RQ任务：作业执行的入口函数

    参数:
        job_id: 要执行的作业ID
    """
    executor = JobExecutor()
    executor.execute_job(job_id)
