"""
Job executor - executes jobs as subprocesses
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
    Job executor service
    Executes jobs as subprocess with proper environment setup
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.scheduler = ResourceScheduler()
    
    def execute_job(self, job_id: int) -> None:
        """
        Execute a single job
        
        This is the main entry point called by RQ worker.
        It handles the complete job lifecycle:
        1. Wait for scheduling (if pending)
        2. Prepare execution environment
        3. Execute script
        4. Update job status
        5. Release resources
        
        Args:
            job_id: Job ID to execute
        """
        logger.info(f"Starting execution of job {job_id}")
        
        try:
            # Wait for job to be scheduled
            job = self._wait_for_scheduling(job_id)
            
            if job is None or job.state == JobState.CANCELLED:
                logger.info(f"Job {job_id} was cancelled before execution")
                return
            
            # Execute the job
            exit_code = self._run_job(job)
            
            # Update job status
            self._update_job_completion(job_id, exit_code)
            
        except Exception as e:
            logger.error(f"Job {job_id} execution failed: {e}", exc_info=True)
            self._mark_job_failed(job_id, str(e))
        
        finally:
            # Always release resources
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
                    # Refresh to get latest data
                    session.refresh(job)
                    # Detach from session to use outside context
                    session.expunge(job)
                    return job
                
                if job.state == JobState.CANCELLED:
                    return None
                
                if job.state != JobState.PENDING:
                    raise ValueError(f"Unexpected job state: {job.state}")
            
            # Check timeout
            if time.time() - start_time > timeout:
                raise TimeoutError(f"Job {job_id} not scheduled within {timeout}s")
            
            # Wait before checking again
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
        
        # Prepare environment
        script_path = self._prepare_execution_environment(job)
        
        # Construct paths for stdout/stderr
        stdout_path = os.path.join(job.work_dir, job.stdout_path)
        stderr_path = os.path.join(job.work_dir, job.stderr_path)
        
        # Prepare environment variables
        env = os.environ.copy()
        if job.environment:
            env.update(job.environment)
        
        # Execute script
        try:
            with open(stdout_path, 'w') as stdout_file, \
                 open(stderr_path, 'w') as stderr_file:
                
                process = subprocess.Popen(
                    ['/bin/bash', script_path],
                    stdout=stdout_file,
                    stderr=stderr_file,
                    cwd=job.work_dir,
                    env=env,
                    preexec_fn=os.setsid,  # Create new process group
                )
                
                # Store process ID
                self._store_process_id(job.id, process.pid)
                
                logger.info(f"Job {job.id} started with PID {process.pid}")
                
                # Wait for completion with timeout
                try:
                    timeout_seconds = job.time_limit * 60 if job.time_limit else None
                    exit_code = process.wait(timeout=timeout_seconds)
                    
                except subprocess.TimeoutExpired:
                    logger.warning(f"Job {job.id} exceeded time limit, terminating")
                    # Kill process group
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
        # Ensure work directory exists
        Path(job.work_dir).mkdir(parents=True, exist_ok=True)
        
        # Write script to file
        script_path = os.path.join(
            self.settings.SCRIPT_DIR,
            f"job_{job.id}.sh"
        )
        
        Path(self.settings.SCRIPT_DIR).mkdir(parents=True, exist_ok=True)
        
        with open(script_path, 'w') as f:
            f.write(job.script)
        
        # Make script executable
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
            allocation = session.query(ResourceAllocation).filter(
                ResourceAllocation.job_id == job_id
            ).first()
            
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
                    f"Job {job_id} marked as {job.state.value} "
                    f"(exit_code={exit_code})"
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

