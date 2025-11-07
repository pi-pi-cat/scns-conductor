"""
FastAPI 主入口
"""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from core.config import get_settings
from core.database import async_db
from core.redis_client import redis_manager
from core.utils.logger import setup_logger
from .routers import jobs_router, dashboard_router
from .middleware import RequestIDMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    应用生命周期管理器（启动与关闭事件）
    """
    # 启动阶段
    settings = get_settings()

    # 初始化日志
    setup_logger(settings.LOG_LEVEL, settings.LOG_FILE)
    logger.info("启动 SCNS-Conductor API 服务")

    # 确保所需目录存在
    settings.ensure_directories()

    # 初始化数据库
    async_db.init()
    logger.info("数据库已初始化")

    # 初始化Redis连接（用于任务队列）
    try:
        redis_manager.init()
        if not redis_manager.ping():
            raise ConnectionError("无法连接到 Redis")
        logger.info("Redis已初始化")
    except Exception as e:
        logger.error(f"Redis初始化失败: {e}")
        raise

    logger.info(f"API 服务已启动，监听 {settings.API_HOST}:{settings.API_PORT}")

    yield

    # 关闭阶段
    logger.info("正在关闭 SCNS-Conductor API 服务")
    await async_db.close()
    redis_manager.close()
    logger.info("API 服务已停止")


# 创建 FastAPI 应用
app = FastAPI(
    title="SCNS-Conductor",
    description="作业调度与管理系统 - REST API",
    version="1.0.0",
    lifespan=lifespan,
)

# 添加中间件（顺序重要：最后添加的最先执行）
# 1. 请求 ID 追踪（最内层）
app.add_middleware(RequestIDMiddleware)

# 2. 跨域请求 CORS（最外层）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境需合理配置
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(jobs_router)
app.include_router(dashboard_router)


@app.get("/", status_code=status.HTTP_200_OK)
async def root():
    """根接口 - 返回 API 信息"""
    return {
        "service": "SCNS-Conductor API",
        "version": "1.0.0",
        "status": "running",
    }


@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check():
    """健康检查接口"""
    try:
        # 此处可添加数据库连通性检查
        return {
            "status": "healthy",
            "service": "scns-conductor-api",
        }
    except Exception as e:
        logger.error(f"健康检查失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unhealthy",
                "error": str(e),
            },
        )


# 全局异常处理器
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """全局异常处理"""
    logger.error(f"未处理的异常: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "服务器内部错误",
        },
    )


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "api.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        workers=settings.API_WORKERS,
        log_level=settings.LOG_LEVEL.lower(),
    )
