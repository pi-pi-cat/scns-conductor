"""
请求ID追踪中间件
"""
import uuid
import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from loguru import logger


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    请求ID追踪中间件
    
    功能:
        1. 为每个请求生成唯一的追踪ID
        2. 将ID添加到请求上下文和响应头
        3. 在日志中记录请求信息和执行时间
        4. 支持从客户端传入Request ID（通过X-Request-ID头）
    
    使用:
        app.add_middleware(RequestIDMiddleware)
    
    优势:
        - 分布式系统中追踪请求链路
        - 方便调试和问题定位
        - 性能监控（请求耗时）
    """
    
    async def dispatch(self, request: Request, call_next):
        # 生成请求ID（优先使用客户端传入的ID）
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        
        # 添加到请求状态（可在endpoint中访问 request.state.request_id）
        request.state.request_id = request_id
        
        # 记录请求开始
        start_time = time.time()
        logger.info(
            f"→ Request started: {request.method} {request.url.path}",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "client": request.client.host if request.client else "unknown",
            }
        )
        
        # 执行请求
        try:
            response: Response = await call_next(request)
        except Exception as e:
            # 记录异常
            duration = time.time() - start_time
            logger.error(
                f"✗ Request failed: {request.method} {request.url.path} "
                f"- Error: {e} - Duration: {duration:.3f}s",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "duration": duration,
                },
                exc_info=True,
            )
            raise
        
        # 记录请求完成
        duration = time.time() - start_time
        status_emoji = "✓" if 200 <= response.status_code < 400 else "✗"
        logger.info(
            f"{status_emoji} Request completed: {request.method} {request.url.path} "
            f"- Status: {response.status_code} - Duration: {duration:.3f}s",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration": duration,
            }
        )
        
        # 添加响应头
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = f"{duration:.3f}"
        
        return response

