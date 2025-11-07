"""
数据库仓储层 (Repository Layer)

职责：
- 封装所有数据库操作
- 管理数据库会话生命周期
- 提供统一的数据访问接口
- 确保会话按需创建、用后即释放

优势：
- 服务层不需要关心数据库会话管理
- 最小化数据库连接占用时间
- 便于测试和mock
- 统一的错误处理
"""

from .job_repository import JobRepository

__all__ = ["JobRepository"]
