"""
FastAPI application main entry point
"""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from core.config import get_settings
from core.database import async_db
from core.utils.logger import setup_logger
from .routers import jobs_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Application lifespan manager
    Handles startup and shutdown events
    """
    # Startup
    settings = get_settings()

    # Setup logging
    setup_logger(settings.LOG_LEVEL, settings.LOG_FILE)
    logger.info("Starting SCNS-Conductor API service")

    # Ensure required directories exist
    settings.ensure_directories()

    # Initialize database
    async_db.init()
    logger.info("Database initialized")

    logger.info(f"API service started on {settings.API_HOST}:{settings.API_PORT}")

    yield

    # Shutdown
    logger.info("Shutting down SCNS-Conductor API service")
    await async_db.close()
    logger.info("API service stopped")


# Create FastAPI application
app = FastAPI(
    title="SCNS-Conductor",
    description="Job Scheduling and Management System - REST API",
    version="1.0.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(jobs_router)


@app.get("/", status_code=status.HTTP_200_OK)
async def root():
    """Root endpoint - API information"""
    return {
        "service": "SCNS-Conductor API",
        "version": "1.0.0",
        "status": "running",
    }


@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check():
    """Health check endpoint"""
    try:
        # Could add database connectivity check here
        return {
            "status": "healthy",
            "service": "scns-conductor-api",
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unhealthy",
                "error": str(e),
            },
        )


# Exception handlers
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Internal server error",
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
