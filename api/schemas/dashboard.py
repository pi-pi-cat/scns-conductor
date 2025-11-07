"""
Dashboard 相关的响应模型
"""

from typing import List
from pydantic import BaseModel, Field


class JobStats(BaseModel):
    """作业统计"""

    total: int = Field(description="总作业数")
    running: int = Field(description="运行中的作业数")
    pending: int = Field(description="排队中的作业数")
    completed: int = Field(description="已完成的作业数")
    failed: int = Field(description="失败的作业数")
    cancelled: int = Field(description="已取消的作业数")


class ResourceStats(BaseModel):
    """资源统计"""

    total_cpus: int = Field(description="总CPU核心数")
    allocated_cpus: int = Field(description="已分配的CPU核心数")
    available_cpus: int = Field(description="可用的CPU核心数")
    utilization_rate: float = Field(description="CPU利用率（百分比）")


class NodeInfo(BaseModel):
    """节点信息"""

    node_name: str = Field(description="节点名称")
    partition: str = Field(description="分区名称")
    total_cpus: int = Field(description="总CPU核心数")
    allocated_cpus: int = Field(description="已分配CPU核心数")
    available_cpus: int = Field(description="可用CPU核心数")
    available: bool = Field(description="节点是否可用")
    utilization_rate: float = Field(description="利用率（百分比）")


class JobSummary(BaseModel):
    """作业概要信息"""

    job_id: int = Field(description="作业ID")
    name: str = Field(description="作业名称")
    account: str = Field(description="账户名称")
    state: str = Field(description="作业状态")
    allocated_cpus: int = Field(description="分配的CPU数")
    submit_time: str = Field(description="提交时间")
    start_time: str | None = Field(default=None, description="开始时间")


class DashboardResponse(BaseModel):
    """Dashboard 总览响应"""

    job_stats: JobStats = Field(description="作业统计")
    resource_stats: ResourceStats = Field(description="资源统计")
    node_info: List[NodeInfo] = Field(description="节点信息列表")
    running_jobs: List[JobSummary] = Field(description="运行中的作业列表")
    pending_jobs: List[JobSummary] = Field(description="排队中的作业列表")

