"""
作业查询相关数据结构
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from core.enums import JobState


class TimeInfo(BaseModel):
    """作业时间信息"""

    submit_time: datetime = Field(..., description="作业提交时间")
    start_time: Optional[datetime] = Field(None, description="作业开始时间")
    end_time: Optional[datetime] = Field(None, description="作业结束时间")
    eligible_time: datetime = Field(..., description="作业进入可调度队列的时间")
    elapsed_time: str = Field(..., description="已运行时间，格式如 '天-时:分:秒'")
    limit_time: str = Field(
        ..., description="作业最大运行时限，格式如 '时:分:秒' 或 '天-时:分:秒'"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "submit_time": "2025-11-07T10:20:30Z",
                "start_time": "2025-11-07T10:25:40Z",
                "end_time": None,
                "eligible_time": "2025-11-07T10:20:30Z",
                "elapsed_time": "0-00:39:20",
                "limit_time": "2:00:00",
            }
        }


class JobLog(BaseModel):
    """作业日志文件内容"""

    stderr: str = Field(..., description="标准错误输出内容")
    stdout: str = Field(..., description="标准输出内容")

    class Config:
        json_schema_extra = {
            "example": {
                "stderr": "",
                "stdout": "Starting simulation...\nProcessing data...\nDone.",
            }
        }


class JobDetail(BaseModel):
    """作业详细信息"""

    job_name: str = Field(..., description="作业名称")
    user: str = Field(..., description="用户/账号名")
    partition: str = Field(..., description="分区名称")
    allocated_cpus: int = Field(..., description="分配的 CPU 数")
    allocated_nodes: int = Field(..., description="分配的节点数")
    node_list: Optional[str] = Field(None, description="分配的节点列表")
    exit_code: str = Field(..., description="退出码（格式：ExitCode:Signal）")
    work_dir: str = Field(..., description="作业工作目录")
    data_source: str = Field(..., description="作业来源（API、CLI、WEB）")
    account: str = Field(..., description="账户名")

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
                "account": "project_alpha",
            }
        }


class JobQueryResponse(BaseModel):
    """作业查询响应"""

    job_id: str = Field(..., description="作业ID")
    state: JobState = Field(..., description="作业当前状态")
    error_msg: Optional[str] = Field(None, description="失败时的错误信息")
    time: TimeInfo = Field(..., description="作业时间相关信息")
    job_log: JobLog = Field(..., description="作业日志信息")
    detail: JobDetail = Field(..., description="作业详细描述信息")

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
                    "limit_time": "2:00:00",
                },
                "job_log": {"stderr": "", "stdout": "Starting simulation..."},
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
                    "account": "project_alpha",
                },
            }
        }
