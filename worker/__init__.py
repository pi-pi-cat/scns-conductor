"""
Worker Service - 作业执行服务

职责：
- 从队列获取已调度的作业
- 执行作业脚本
- 更新作业状态
- 释放资源

架构：
- execution/: 执行上下文和阶段
- middleware/: 执行中间件（自动注册）
- monitoring/: 进程监控
- process/: 进程管理工具
- resources/: 资源管理包装器
- repositories/: 数据库操作仓储
"""

__version__ = "2.0.0"

# 导出主要接口
from .executor import JobExecutor, execute_job

__all__ = [
    "JobExecutor",
    "execute_job",
]
