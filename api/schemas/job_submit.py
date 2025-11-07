"""
Schemas for job submission
"""
from typing import Dict
from pydantic import BaseModel, Field, field_validator

from core.utils.validators import validate_memory_format
from core.utils.time_utils import parse_time_limit


class JobEnvironment(BaseModel):
    """
    Job environment variables
    Accepts any key-value pairs as environment variables
    """
    __root__: Dict[str, str] = Field(default_factory=dict)
    
    def dict(self, **kwargs):
        """Override dict to return the root dictionary"""
        return self.__root__
    
    def __iter__(self):
        return iter(self.__root__)
    
    def __getitem__(self, item):
        return self.__root__[item]


class JobSpec(BaseModel):
    """Job specification"""
    
    account: str = Field(
        ...,
        description="Account or project name for the job",
        min_length=1,
        max_length=255
    )
    
    environment: Dict[str, str] = Field(
        default_factory=dict,
        description="Environment variables for the job"
    )
    
    current_working_directory: str = Field(
        ...,
        alias="current_working_directory",
        description="Working directory for job execution",
        min_length=1,
        max_length=1024
    )
    
    standard_output: str = Field(
        ...,
        alias="standard_output",
        description="Standard output file path (relative to working directory)",
        min_length=1,
        max_length=512
    )
    
    standard_error: str = Field(
        ...,
        alias="standard_error",
        description="Standard error file path (relative to working directory)",
        min_length=1,
        max_length=512
    )
    
    ntasks_per_node: int = Field(
        default=1,
        ge=1,
        description="Number of tasks per node"
    )
    
    cpus_per_task: int = Field(
        default=1,
        ge=1,
        description="Number of CPU cores per task"
    )
    
    memory_per_node: str = Field(
        default="1G",
        description="Memory per node (e.g., '16G', '1024M')"
    )
    
    name: str = Field(
        ...,
        description="Job name",
        min_length=1,
        max_length=255
    )
    
    time_limit: str = Field(
        ...,
        description="Time limit in minutes (e.g., '30', '120')"
    )
    
    partition: str = Field(
        ...,
        description="Partition name",
        min_length=1,
        max_length=100
    )
    
    exclusive: bool = Field(
        default=False,
        description="Whether to request exclusive node access"
    )
    
    @field_validator("memory_per_node")
    @classmethod
    def validate_memory(cls, v: str) -> str:
        """Validate memory format"""
        validate_memory_format(v)
        return v
    
    @field_validator("time_limit")
    @classmethod
    def validate_time_limit(cls, v: str) -> str:
        """Validate time limit format"""
        # Parse to ensure it's valid, but keep original string
        parse_time_limit(v)
        return v
    
    def get_time_limit_minutes(self) -> int:
        """Get time limit in minutes"""
        return parse_time_limit(self.time_limit)
    
    def get_total_cpus(self) -> int:
        """Calculate total CPU cores required"""
        return self.ntasks_per_node * self.cpus_per_task
    
    class Config:
        populate_by_name = True


class JobSubmitRequest(BaseModel):
    """Job submission request"""
    
    job: JobSpec = Field(..., description="Job specification")
    script: str = Field(
        ...,
        description="Job script content",
        min_length=1
    )
    
    @field_validator("script")
    @classmethod
    def validate_script(cls, v: str) -> str:
        """Validate script content"""
        if not v.strip():
            raise ValueError("Script cannot be empty or whitespace only")
        return v


class JobSubmitResponse(BaseModel):
    """Job submission response"""
    
    job_id: str = Field(..., description="Unique job ID")
    
    class Config:
        json_schema_extra = {
            "example": {
                "job_id": "1001"
            }
        }

