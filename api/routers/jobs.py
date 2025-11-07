"""
作业管理 API 端点
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from core.exceptions import JobNotFoundException, JobStateException
from ..dependencies import get_db
from ..schemas import (
    JobSubmitRequest,
    JobSubmitResponse,
    JobQueryResponse,
    JobCancelResponse,
)
from ..services import JobService


router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post(
    "/submit", response_model=JobSubmitResponse, status_code=status.HTTP_201_CREATED
)
async def submit_job(
    request: JobSubmitRequest, db: AsyncSession = Depends(get_db)
) -> JobSubmitResponse:
    """
    提交新作业执行

    在数据库中创建作业记录并排队等待调度。
    立即返回唯一的作业 ID。

    Args:
        request: 包含作业规格和脚本的提交请求
        db: 数据库会话

    Returns:
        作业 ID
    """
    try:
        job_id = await JobService.submit_job(request, db)
        logger.info(f"Job {job_id} submitted successfully")
        return JobSubmitResponse(job_id=str(job_id))

    except ValueError as e:
        logger.error(f"Validation error during job submission: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    except Exception as e:
        logger.error(f"Failed to submit job: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to submit job",
        )


@router.get("/query/{job_id}", response_model=JobQueryResponse)
async def query_job(
    job_id: int, db: AsyncSession = Depends(get_db)
) -> JobQueryResponse:
    """
    查询作业状态和信息

    检索作业的完整信息，包括：
    - 当前状态和执行时间
    - 资源分配详情
    - 日志文件内容（stdout/stderr）

    Args:
        job_id: 唯一作业标识符
        db: 数据库会话

    Returns:
        完整的作业信息

    Raises:
        404: 作业未找到
    """
    try:
        response = await JobService.query_job(job_id, db)
        return response

    except JobNotFoundException as e:
        logger.warning(f"Job not found: {job_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Job {job_id} not found"
        )

    except Exception as e:
        logger.error(f"Failed to query job {job_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to query job",
        )


@router.post("/cancel/{job_id}", response_model=JobCancelResponse)
async def cancel_job(
    job_id: int, db: AsyncSession = Depends(get_db)
) -> JobCancelResponse:
    """
    取消正在运行或等待中的作业

    尝试终止当前正在运行或等待的作业。
    此操作是幂等的 - 取消已经取消的作业不会报错。

    Args:
        job_id: 唯一作业标识符
        db: 数据库会话

    Returns:
        取消确认

    Raises:
        404: 作业未找到
    """
    try:
        await JobService.cancel_job(job_id, db)
        logger.info(f"Job {job_id} cancelled successfully")
        return JobCancelResponse(msg="取消成功")

    except JobNotFoundException as e:
        logger.warning(f"Job not found: {job_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Job {job_id} not found"
        )

    except JobStateException as e:
        logger.warning(f"Invalid job state transition: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    except Exception as e:
        logger.error(f"Failed to cancel job {job_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cancel job",
        )
