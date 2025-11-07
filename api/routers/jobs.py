"""
作业管理 API 端点

重构说明：
- 移除了数据库会话依赖注入
- 数据库连接由 Repository 层自动管理
- Router 层只负责请求/响应处理和日志记录
"""

from fastapi import APIRouter, status
from loguru import logger
from ..schemas import (
    JobSubmitRequest,
    JobSubmitResponse,
    JobQueryResponse,
    JobCancelResponse,
)
from ..services import JobService
from ..decorators import handle_api_errors


router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post(
    "/submit", response_model=JobSubmitResponse, status_code=status.HTTP_201_CREATED
)
@handle_api_errors
async def submit_job(request: JobSubmitRequest) -> JobSubmitResponse:
    """
    提交新作业执行

    在数据库中创建作业记录并排队等待调度。
    立即返回唯一的作业 ID。

    Args:
        request: 包含作业规格和脚本的提交请求

    Returns:
        作业 ID

    说明:
        数据库连接由 Repository 层自动管理，
        短事务，用完即释放，不会长时间占用连接
    """
    job_id = await JobService.submit_job(request)
    logger.info(f"Job {job_id} submitted successfully")
    return JobSubmitResponse(job_id=str(job_id))


@router.get("/query/{job_id}", response_model=JobQueryResponse)
@handle_api_errors
async def query_job(job_id: int) -> JobQueryResponse:
    """
    查询作业状态和信息

    检索作业的完整信息，包括：
    - 当前状态和执行时间
    - 资源分配详情
    - 日志文件内容（stdout/stderr）

    Args:
        job_id: 唯一作业标识符

    Returns:
        完整的作业信息

    Raises:
        404: 作业未找到

    说明:
        数据库连接由 Repository 层自动管理，
        单次查询，短事务，快速释放连接
    """
    return await JobService.query_job(job_id)


@router.post("/cancel/{job_id}", response_model=JobCancelResponse)
@handle_api_errors
async def cancel_job(job_id: int) -> JobCancelResponse:
    """
    取消正在运行或等待中的作业

    尝试终止当前正在运行或等待的作业。
    此操作是幂等的 - 取消已经取消的作业不会报错。

    Args:
        job_id: 唯一作业标识符

    Returns:
        取消确认

    Raises:
        404: 作业未找到

    说明:
        数据库连接由 Repository 层自动管理，
        多个短事务，每次操作后立即释放连接
    """
    await JobService.cancel_job(job_id)
    logger.info(f"Job {job_id} cancelled successfully")
    return JobCancelResponse(msg="取消成功")
