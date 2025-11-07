"""
作业取消相关数据结构
"""

from pydantic import BaseModel, Field


class JobCancelResponse(BaseModel):
    """作业取消响应"""

    msg: str = Field(default="取消成功", description="取消状态消息")

    class Config:
        json_schema_extra = {"example": {"msg": "取消成功"}}
