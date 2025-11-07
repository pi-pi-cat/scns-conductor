"""
SQLModel 数据库模型
结合了 SQLAlchemy ORM 和 Pydantic 的优势
"""
from datetime import datetime
from typing import Optional, Dict

from sqlmodel import Field, SQLModel, Relationship, Column, Index
from sqlalchemy import Text, BigInteger, text
from sqlalchemy.dialects.postgresql import JSONB

from .enums import JobState, DataSource


class Job(SQLModel, table=True):
    """作业表 - 存储所有作业信息"""
    
    __tablename__ = "jobs"
    
    # 主键
    id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
        description="作业ID"
    )
    
    # 作业标识信息
    account: str = Field(max_length=255, description="账户/项目名称")
    name: str = Field(max_length=255, description="作业名称")
    partition: str = Field(max_length=100, description="分区名称")
    data_source: str = Field(
        default=DataSource.API,
        max_length=50,
        description="数据来源（API、CLI、WEB）"
    )
    
    # 作业状态和执行信息
    state: JobState = Field(
        default=JobState.PENDING,
        description="作业状态",
        index=True
    )
    error_msg: Optional[str] = Field(
        default=None,
        sa_column=Column(Text),
        description="失败时的错误信息"
    )
    exit_code: Optional[str] = Field(
        default=None,
        max_length=20,
        description="退出码，格式为 'code:signal'"
    )
    
    # 资源分配
    allocated_cpus: int = Field(description="已分配的CPU核心数")
    allocated_nodes: int = Field(default=1, description="已分配的节点数")
    node_list: Optional[str] = Field(
        default=None,
        sa_column=Column(Text),
        description="已分配节点列表（逗号分隔）"
    )
    
    # 资源需求
    ntasks_per_node: int = Field(default=1, description="每个节点的任务数")
    cpus_per_task: int = Field(default=1, description="每个任务的CPU数")
    memory_per_node: str = Field(default="1G", max_length=20, description="每个节点的内存")
    time_limit: Optional[int] = Field(default=None, description="时间限制（分钟）")
    exclusive: bool = Field(default=False, description="是否独占节点")
    
    # 作业内容
    script: str = Field(sa_column=Column(Text, nullable=False), description="作业脚本内容")
    work_dir: str = Field(max_length=1024, description="工作目录")
    stdout_path: str = Field(max_length=512, description="标准输出文件路径")
    stderr_path: str = Field(max_length=512, description="标准错误文件路径")
    environment: Optional[Dict[str, str]] = Field(
        default=None,
        sa_column=Column(JSONB),
        description="环境变量"
    )
    
    # 时间追踪
    submit_time: datetime = Field(
        default_factory=datetime.utcnow,
        description="作业提交时间",
        index=True
    )
    eligible_time: datetime = Field(
        default_factory=datetime.utcnow,
        description="作业变为可调度状态的时间"
    )
    start_time: Optional[datetime] = Field(default=None, description="作业开始时间")
    end_time: Optional[datetime] = Field(default=None, description="作业结束时间")
    
    # 元数据
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="记录创建时间"
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="记录更新时间"
    )
    
    # 关系
    resource_allocation: Optional["ResourceAllocation"] = Relationship(
        back_populates="job",
        sa_relationship_kwargs={"uselist": False, "cascade": "all, delete-orphan"}
    )
    
    # 索引（通过 __table_args__ 添加）
    __table_args__ = (
        Index("idx_job_state", "state"),
        Index("idx_job_submit_time", "submit_time"),
        Index("idx_job_partition", "partition"),
        Index("idx_job_account", "account"),
    )
    
    @property
    def total_cpus_required(self) -> int:
        """计算所需的总CPU核心数"""
        return self.ntasks_per_node * self.cpus_per_task
    
    class Config:
        arbitrary_types_allowed = True


class ResourceAllocation(SQLModel, table=True):
    """资源分配表 - 追踪作业的资源分配情况，用于调度和资源管理"""
    
    __tablename__ = "resource_allocations"
    
    id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
        description="主键ID"
    )
    job_id: int = Field(
        sa_column=Column(
            BigInteger,
            nullable=False,
            unique=True  # 每个作业只有一个资源分配
        ),
        foreign_key="jobs.id",
        description="作业ID"
    )
    
    # 资源详情
    allocated_cpus: int = Field(description="已分配的CPU数量")
    node_name: str = Field(max_length=255, description="分配的节点名称")
    
    # 进程追踪
    process_id: Optional[int] = Field(default=None, description="操作系统进程ID")
    
    # 分配生命周期
    allocation_time: datetime = Field(
        default_factory=datetime.utcnow,
        description="资源分配时间"
    )
    released: bool = Field(
        default=False,
        index=True,
        description="资源是否已释放"
    )
    released_time: Optional[datetime] = Field(
        default=None,
        description="资源释放时间"
    )
    
    # 元数据
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="记录创建时间"
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="记录更新时间"
    )
    
    # 关系
    job: Optional[Job] = Relationship(back_populates="resource_allocation")
    
    # 索引
    __table_args__ = (
        Index("idx_resource_allocation_released", "released"),
        Index("idx_resource_allocation_node", "node_name"),
    )
    
    class Config:
        arbitrary_types_allowed = True


class SystemResource(SQLModel, table=True):
    """系统资源表 - 定义可用的计算资源，代表物理或虚拟计算节点"""
    
    __tablename__ = "system_resources"
    
    id: Optional[int] = Field(default=None, primary_key=True, description="主键ID")
    node_name: str = Field(
        max_length=255,
        unique=True,
        index=True,
        description="节点主机名"
    )
    
    # 资源容量
    total_cpus: int = Field(description="节点上的总CPU核心数")
    partition: str = Field(max_length=100, description="节点所属的分区")
    
    # 节点状态
    available: bool = Field(
        default=True,
        index=True,
        description="节点是否可用于调度"
    )
    
    # 元数据
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="记录创建时间"
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="记录更新时间"
    )
    
    # 索引
    __table_args__ = (
        Index("idx_system_resource_available", "available"),
        Index("idx_system_resource_partition", "partition"),
    )
    
    class Config:
        arbitrary_types_allowed = True

