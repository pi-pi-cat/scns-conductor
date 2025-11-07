"""
Schemas for job query
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from core.enums import JobState


class TimeInfo(BaseModel):
    """Job time information"""
    
    submit_time: datetime = Field(..., description="Job submission time")
    start_time: Optional[datetime] = Field(None, description="Job start time")
    end_time: Optional[datetime] = Field(None, description="Job end time")
    eligible_time: datetime = Field(..., description="Time when job became eligible")
    elapsed_time: str = Field(..., description="Elapsed time in format 'day-HH:MM:SS'")
    limit_time: str = Field(..., description="Time limit in format 'HH:MM:SS' or 'D-HH:MM:SS'")
    
    class Config:
        json_schema_extra = {
            "example": {
                "submit_time": "2025-11-07T10:20:30Z",
                "start_time": "2025-11-07T10:25:40Z",
                "end_time": None,
                "eligible_time": "2025-11-07T10:20:30Z",
                "elapsed_time": "0-00:39:20",
                "limit_time": "2:00:00"
            }
        }


class JobLog(BaseModel):
    """Job log files content"""
    
    stderr: str = Field(..., description="Standard error output")
    stdout: str = Field(..., description="Standard output")
    
    class Config:
        json_schema_extra = {
            "example": {
                "stderr": "",
                "stdout": "Starting simulation...\nProcessing data...\nDone."
            }
        }


class JobDetail(BaseModel):
    """Detailed job information"""
    
    job_name: str = Field(..., description="Job name")
    user: str = Field(..., description="User/Account name")
    partition: str = Field(..., description="Partition name")
    allocated_cpus: int = Field(..., description="Number of allocated CPUs")
    allocated_nodes: int = Field(..., description="Number of allocated nodes")
    node_list: Optional[str] = Field(None, description="List of allocated nodes")
    exit_code: str = Field(..., description="Exit code in format 'ExitCode:Signal'")
    work_dir: str = Field(..., description="Working directory")
    data_source: str = Field(..., description="Data source (API, CLI, WEB)")
    account: str = Field(..., description="Account name")
    
    class Config:
        json_schema_extra = {
            "example": {
                "job_name": "daily_simulation_run",
                "user": "project_alpha",
                "partition": "compute-high-mem",
                "allocated_cpus": 8,
                "allocated_nodes": 1,
                "node_list": "kunpeng-compute-01",
                "exit_code": "0:0",
                "work_dir": "/home/users/project_alpha/runs/exp1",
                "data_source": "API",
                "account": "project_alpha"
            }
        }


class JobQueryResponse(BaseModel):
    """Job query response"""
    
    job_id: str = Field(..., description="Job ID")
    state: JobState = Field(..., description="Current job state")
    error_msg: Optional[str] = Field(None, description="Error message if job failed")
    time: TimeInfo = Field(..., description="Time information")
    job_log: JobLog = Field(..., description="Job logs")
    detail: JobDetail = Field(..., description="Detailed job information")
    
    class Config:
        json_schema_extra = {
            "example": {
                "job_id": "1001",
                "state": "RUNNING",
                "error_msg": None,
                "time": {
                    "submit_time": "2025-11-07T10:20:30Z",
                    "start_time": "2025-11-07T10:25:40Z",
                    "end_time": None,
                    "eligible_time": "2025-11-07T10:20:30Z",
                    "elapsed_time": "0-00:39:20",
                    "limit_time": "2:00:00"
                },
                "job_log": {
                    "stderr": "",
                    "stdout": "Starting simulation..."
                },
                "detail": {
                    "job_name": "daily_simulation_run",
                    "user": "project_alpha",
                    "partition": "compute-high-mem",
                    "allocated_cpus": 8,
                    "allocated_nodes": 1,
                    "node_list": "kunpeng-compute-01",
                    "exit_code": "0:0",
                    "work_dir": "/home/users/project_alpha/runs/exp1",
                    "data_source": "API",
                    "account": "project_alpha"
                }
            }
        }

