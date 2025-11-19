"""
Process Monitor - 进程监控器

监控作业进程的状态和资源使用情况
"""

import threading
from typing import Dict, Optional

from loguru import logger

from worker.execution import JobExecutionContext


class ProcessMonitor:
    """
    进程监控器
    
    职责：
    - 监控进程状态
    - 检查资源使用情况
    - 检测异常情况
    """
    
    def __init__(self, check_interval: int = 5):
        """
        初始化进程监控器
        
        Args:
            check_interval: 检查间隔（秒）
        """
        self.check_interval = check_interval
        self._monitored_processes: Dict[int, JobExecutionContext] = {}
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
    
    def start_monitoring(self, job_id: int, context: JobExecutionContext):
        """
        开始监控进程
        
        Args:
            job_id: 作业ID
            context: 执行上下文
        """
        with self._lock:
            self._monitored_processes[job_id] = context
            if not self._monitor_thread or not self._monitor_thread.is_alive():
                self._start_monitor_thread()
            logger.debug(f"Started monitoring job {job_id} (PID: {context.process_id})")
    
    def stop_monitoring(self, job_id: int):
        """
        停止监控进程
        
        Args:
            job_id: 作业ID
        """
        with self._lock:
            if job_id in self._monitored_processes:
                context = self._monitored_processes.pop(job_id)
                logger.debug(f"Stopped monitoring job {job_id}")
                return context
        return None
    
    def is_monitoring(self, job_id: int) -> bool:
        """
        检查是否正在监控某个作业
        
        Args:
            job_id: 作业ID
        
        Returns:
            True 如果正在监控
        """
        with self._lock:
            return job_id in self._monitored_processes
    
    def _start_monitor_thread(self):
        """启动监控线程"""
        self._stop_event.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="ProcessMonitor"
        )
        self._monitor_thread.start()
        logger.debug("Process monitor thread started")
    
    def _monitor_loop(self):
        """监控循环"""
        while not self._stop_event.is_set():
            try:
                # 复制当前监控的进程列表，避免在迭代时修改
                with self._lock:
                    processes_to_check = list(self._monitored_processes.items())
                
                for job_id, context in processes_to_check:
                    if context.process:
                        self._check_process(job_id, context)
            
            except Exception as e:
                logger.error(f"Error in process monitor loop: {e}")
            
            # 等待检查间隔
            self._stop_event.wait(self.check_interval)
    
    def _check_process(self, job_id: int, context: JobExecutionContext):
        """
        检查单个进程
        
        Args:
            job_id: 作业ID
            context: 执行上下文
        """
        if not context.process:
            return
        
        # 检查进程是否存活
        poll_result = context.process.poll()
        if poll_result is not None:
            # 进程已结束
            if context.exit_code is None:
                # 进程意外结束，但还未记录退出码
                logger.warning(
                    f"Job {job_id} process ended unexpectedly "
                    f"(PID: {context.process_id}, exit code: {poll_result})"
                )
            self.stop_monitoring(job_id)
        else:
            # 进程仍在运行，检查资源使用
            self._check_resource_usage(job_id, context)
    
    def _check_resource_usage(self, job_id: int, context: JobExecutionContext):
        """
        检查资源使用情况
        
        Args:
            job_id: 作业ID
            context: 执行上下文
        """
        if not context.process_id:
            return
        
        try:
            # 尝试导入 psutil（可选依赖）
            try:
                import psutil
            except ImportError:
                # psutil 未安装，跳过资源检查
                return
            
            process = psutil.Process(context.process_id)
            
            # 检查内存使用
            memory_info = process.memory_info()
            memory_mb = memory_info.rss / 1024 / 1024
            
            # 检查 CPU 使用（非阻塞）
            try:
                cpu_percent = process.cpu_percent(interval=None)
            except Exception:
                cpu_percent = 0.0
            
            # 记录资源使用（仅在调试模式下）
            logger.debug(
                f"Job {job_id} resource usage: "
                f"memory={memory_mb:.2f}MB, "
                f"cpu={cpu_percent:.1f}%"
            )
            
            # 检查内存使用是否过高（超过 10GB）
            if memory_mb > 10240:
                logger.warning(
                    f"Job {job_id} using excessive memory: {memory_mb:.2f} MB"
                )
        
        except psutil.NoSuchProcess:
            # 进程不存在，可能已经结束
            logger.debug(f"Job {job_id} process {context.process_id} no longer exists")
        except Exception as e:
            logger.debug(f"Failed to check resource usage for job {job_id}: {e}")
    
    def stop(self):
        """停止监控器"""
        self._stop_event.set()
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=2)
        logger.debug("Process monitor stopped")
    
    def get_monitored_jobs(self) -> list[int]:
        """
        获取正在监控的作业ID列表
        
        Returns:
            作业ID列表
        """
        with self._lock:
            return list(self._monitored_processes.keys())

