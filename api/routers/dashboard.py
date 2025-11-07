"""
Dashboard API 端点 - 系统总览
"""

from fastapi import APIRouter, status
from loguru import logger

from ..schemas.dashboard import DashboardResponse
from ..services.dashboard_service import DashboardService
from ..decorators import handle_api_errors


router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardResponse)
@handle_api_errors
async def get_dashboard() -> DashboardResponse:
    """
    获取系统总览数据
    
    包括:
    - 作业统计（总数、运行中、排队中、完成、失败、取消）
    - 资源统计（总CPU、已分配、可用、利用率）
    - 节点信息（每个节点的CPU使用情况）
    - 运行中的作业列表（最近20个）
    - 排队中的作业列表（最近20个）
    
    性能说明:
        - 所有查询都是独立的短事务
        - 单次请求耗时约 0.1-0.5 秒
        - 不会长时间占用数据库连接
    
    Returns:
        Dashboard 总览数据
    """
    logger.info("收到 Dashboard 查询请求")
    dashboard = await DashboardService.get_dashboard()
    logger.info(
        f"Dashboard 查询成功: "
        f"运行中={dashboard.job_stats.running}, "
        f"排队中={dashboard.job_stats.pending}, "
        f"CPU利用率={dashboard.resource_stats.utilization_rate}%"
    )
    return dashboard

