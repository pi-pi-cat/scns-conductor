"""
Job scheduler with FIFO + First Fit resource allocation
"""
from datetime import datetime
from typing import List
from sqlalchemy.orm import Session
from loguru import logger

from core.config import get_settings
from core.database import sync_db
from core.models import Job, ResourceAllocation
from core.enums import JobState
from .resource_tracker import ResourceTracker


class ResourceScheduler:
    """
    Job scheduler implementing FIFO + First Fit algorithm
    Schedules pending jobs based on available CPU resources
    """
    
    def __init__(self):
        self.resource_tracker = ResourceTracker()
        self.settings = get_settings()
    
    def schedule_pending_jobs(self) -> List[int]:
        """
        Schedule pending jobs based on available resources
        
        Returns:
            List of job IDs that were scheduled
        """
        scheduled_jobs = []
        
        with sync_db.get_session() as session:
            # Query pending jobs ordered by submit time (FIFO)
            pending_jobs = session.query(Job).filter(
                Job.state == JobState.PENDING
            ).order_by(Job.submit_time).all()
            
            if not pending_jobs:
                return scheduled_jobs
            
            logger.debug(f"Found {len(pending_jobs)} pending jobs")
            
            # Try to schedule each job
            for job in pending_jobs:
                required_cpus = job.total_cpus_required
                
                # Check if resources are available (First Fit)
                if self.resource_tracker.can_allocate(required_cpus):
                    # Allocate resources
                    if self._allocate_resources(session, job, required_cpus):
                        scheduled_jobs.append(job.id)
                        logger.info(
                            f"Scheduled job {job.id} ({job.name}): "
                            f"cpus={required_cpus}"
                        )
                else:
                    logger.debug(
                        f"Insufficient resources for job {job.id}: "
                        f"required={required_cpus}, "
                        f"available={self.resource_tracker.available_cpus}"
                    )
            
            # Commit all changes
            session.commit()
        
        if scheduled_jobs:
            stats = self.resource_tracker.get_stats()
            logger.info(
                f"Scheduled {len(scheduled_jobs)} jobs. "
                f"Resource utilization: {stats['utilization']:.1f}%"
            )
        
        return scheduled_jobs
    
    def _allocate_resources(
        self,
        session: Session,
        job: Job,
        cpus: int
    ) -> bool:
        """
        Allocate resources to a job
        
        Args:
            session: Database session
            job: Job to allocate resources to
            cpus: Number of CPUs to allocate
        
        Returns:
            True if allocation succeeded
        """
        try:
            # Update resource tracker
            if not self.resource_tracker.allocate(cpus):
                return False
            
            # Create resource allocation record
            allocation = ResourceAllocation(
                job_id=job.id,
                allocated_cpus=cpus,
                node_name=self.settings.NODE_NAME,
                allocation_time=datetime.utcnow(),
                released=False,
            )
            session.add(allocation)
            
            # Update job state
            job.state = JobState.RUNNING
            job.start_time = datetime.utcnow()
            job.node_list = self.settings.NODE_NAME
            
            return True
        
        except Exception as e:
            logger.error(f"Failed to allocate resources for job {job.id}: {e}")
            # Rollback resource tracker
            self.resource_tracker.release(cpus)
            return False
    
    def release_resources(self, job_id: int) -> None:
        """
        Release resources for a completed job
        
        Args:
            job_id: Job ID
        """
        with sync_db.get_session() as session:
            # Find allocation
            allocation = session.query(ResourceAllocation).filter(
                ResourceAllocation.job_id == job_id,
                ResourceAllocation.released == False
            ).first()
            
            if allocation:
                # Mark as released
                allocation.released = True
                allocation.released_time = datetime.utcnow()
                
                # Update resource tracker
                self.resource_tracker.release(allocation.allocated_cpus)
                
                session.commit()
                
                logger.info(
                    f"Released resources for job {job_id}: "
                    f"cpus={allocation.allocated_cpus}"
                )
            else:
                logger.warning(f"No active allocation found for job {job_id}")
    
    def get_resource_stats(self) -> dict:
        """Get current resource statistics"""
        return self.resource_tracker.get_stats()

