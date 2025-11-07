"""
作业提交相关数据模型
"""

from typing import Dict
from pydantic import BaseModel, Field, field_validator, RootModel

from core.utils.validators import validate_memory_format
from core.utils.time_utils import parse_time_limit


class JobEnvironment(RootModel[Dict[str, str]]):
    """
    作业环境变量（Pydantic v2）
    支持任意键值对作为环境变量
    """

    root: Dict[str, str] = Field(default_factory=dict)

    def dict(self, **kwargs):
        """重载dict方法，直接返回根字典"""
        return self.root

    def __iter__(self):
        return iter(self.root)

    def __getitem__(self, item):
        return self.root[item]


class JobSpec(BaseModel):
    """作业规格"""

    account: str = Field(
        ..., description="作业所属账号或项目名称", min_length=1, max_length=255
    )

    environment: Dict[str, str] = Field(
        default_factory=dict, description="作业环境变量"
    )

    current_working_directory: str = Field(
        ...,
        alias="current_working_directory",
        description="作业执行的工作目录",
        min_length=1,
        max_length=1024,
    )

    standard_output: str = Field(
        ...,
        alias="standard_output",
        description="标准输出文件路径（相对工作目录）",
        min_length=1,
        max_length=512,
    )

    standard_error: str = Field(
        ...,
        alias="standard_error",
        description="标准错误输出文件路径（相对工作目录）",
        min_length=1,
        max_length=512,
    )

    ntasks_per_node: int = Field(default=1, ge=1, description="每个节点分配的任务数")

    cpus_per_task: int = Field(default=1, ge=1, description="每个任务分配的CPU核数")

    memory_per_node: str = Field(
        default="1G", description="每节点分配的内存（例如：'16G', '1024M'）"
    )

    name: str = Field(..., description="作业名称", min_length=1, max_length=255)

    time_limit: str = Field(..., description="作业运行时限（分钟），如'30'或'120'")

    partition: str = Field(..., description="分区名称", min_length=1, max_length=100)

    exclusive: bool = Field(default=False, description="是否请求节点独占")

    @field_validator("memory_per_node")
    @classmethod
    def validate_memory(cls, v: str) -> str:
        """校验内存格式"""
        validate_memory_format(v)
        return v

    @field_validator("time_limit")
    @classmethod
    def validate_time_limit(cls, v: str) -> str:
        """校验作业时限格式"""
        # 解析时限以确保有效，但保持原字符串
        parse_time_limit(v)
        return v

    def get_time_limit_minutes(self) -> int:
        """获取时限（分钟）"""
        return parse_time_limit(self.time_limit)

    def get_total_cpus(self) -> int:
        """计算所需CPU总数"""
        return self.ntasks_per_node * self.cpus_per_task

    class Config:
        populate_by_name = True


class JobSubmitRequest(BaseModel):
    """作业提交请求"""

    job: JobSpec = Field(..., description="作业规格")
    script: str = Field(..., description="作业脚本内容", min_length=1)

    @field_validator("script")
    @classmethod
    def validate_script(cls, v: str) -> str:
        """校验脚本内容非空"""
        if not v.strip():
            raise ValueError("脚本内容不能为空或仅包含空白字符")
        return v


class JobSubmitResponse(BaseModel):
    """作业提交响应"""

    job_id: str = Field(..., description="作业唯一ID")

    class Config:
        json_schema_extra = {"example": {"job_id": "1001"}}
