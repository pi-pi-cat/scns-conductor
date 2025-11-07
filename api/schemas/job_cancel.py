"""
Schemas for job cancellation
"""
from pydantic import BaseModel, Field


class JobCancelResponse(BaseModel):
    """Job cancellation response"""
    
    msg: str = Field(default="取消成功", description="Cancellation status message")
    
    class Config:
        json_schema_extra = {
            "example": {
                "msg": "取消成功"
            }
        }

