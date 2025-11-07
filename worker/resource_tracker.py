"""
Thread-safe resource tracker for CPU allocation
"""
import threading
from loguru import logger

from core.config import get_settings
from core.database import sync_db
from core.models import ResourceAllocation


class ResourceTracker:
    """
    Thread-safe CPU resource tracker
    Manages available CPU resources for job scheduling
    """
    
    def __init__(self):
        self._lock = threading.Lock()
        settings = get_settings()
        self._total_cpus = settings.TOTAL_CPUS
        self._used_cpus = 0
        self._load_current_usage()
    
    def _load_current_usage(self) -> None:
        """
        Load current resource usage from database
        Called during initialization to recover state
        """
        try:
            with sync_db.get_session() as session:
                # Query all unreleased allocations
                allocations = session.query(ResourceAllocation).filter(
                    ResourceAllocation.released == False
                ).all()
                
                self._used_cpus = sum(a.allocated_cpus for a in allocations)
                
                logger.info(
                    f"Resource tracker initialized: "
                    f"total={self._total_cpus}, used={self._used_cpus}, "
                    f"available={self.available_cpus}"
                )
        
        except Exception as e:
            logger.error(f"Failed to load current resource usage: {e}")
            self._used_cpus = 0
    
    def can_allocate(self, cpus: int) -> bool:
        """
        Check if requested CPUs can be allocated
        
        Args:
            cpus: Number of CPUs requested
        
        Returns:
            True if allocation is possible
        """
        with self._lock:
            return (self._used_cpus + cpus) <= self._total_cpus
    
    def allocate(self, cpus: int) -> bool:
        """
        Attempt to allocate CPUs
        
        Args:
            cpus: Number of CPUs to allocate
        
        Returns:
            True if allocation succeeded, False otherwise
        """
        with self._lock:
            if self.can_allocate(cpus):
                self._used_cpus += cpus
                logger.debug(
                    f"Allocated {cpus} CPUs: "
                    f"used={self._used_cpus}/{self._total_cpus}"
                )
                return True
            return False
    
    def release(self, cpus: int) -> None:
        """
        Release allocated CPUs
        
        Args:
            cpus: Number of CPUs to release
        """
        with self._lock:
            self._used_cpus = max(0, self._used_cpus - cpus)
            logger.debug(
                f"Released {cpus} CPUs: "
                f"used={self._used_cpus}/{self._total_cpus}"
            )
    
    @property
    def available_cpus(self) -> int:
        """Get number of available CPUs"""
        with self._lock:
            return self._total_cpus - self._used_cpus
    
    @property
    def used_cpus(self) -> int:
        """Get number of used CPUs"""
        with self._lock:
            return self._used_cpus
    
    @property
    def total_cpus(self) -> int:
        """Get total CPUs"""
        return self._total_cpus
    
    def get_stats(self) -> dict:
        """
        Get resource statistics
        
        Returns:
            Dictionary with resource stats
        """
        with self._lock:
            return {
                "total_cpus": self._total_cpus,
                "used_cpus": self._used_cpus,
                "available_cpus": self._total_cpus - self._used_cpus,
                "utilization": (self._used_cpus / self._total_cpus * 100) if self._total_cpus > 0 else 0,
            }

