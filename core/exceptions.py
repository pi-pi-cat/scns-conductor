"""
作业调度系统的自定义异常
"""
from typing import Optional


class SCNSConductorException(Exception):
    """SCNS-Conductor 基础异常类"""
    pass


# ========== 数据库异常 ==========

class DatabaseException(SCNSConductorException):
    """数据库相关异常基类"""
    pass


class DatabaseNotInitializedException(DatabaseException):
    """数据库未初始化异常"""
    def __init__(self, manager_name: str = "DatabaseManager"):
        super().__init__(
            f"{manager_name} not initialized. Call init() first."
        )


class DatabaseConnectionException(DatabaseException):
    """数据库连接异常"""
    def __init__(self, detail: str):
        super().__init__(f"Database connection error: {detail}")


class DatabaseTimeoutException(DatabaseException):
    """数据库超时异常"""
    def __init__(self, operation: str, timeout: float):
        super().__init__(
            f"Database operation '{operation}' timed out after {timeout}s"
        )


# ========== Redis异常 ==========

class RedisException(SCNSConductorException):
    """Redis相关异常基类"""
    pass


class RedisNotInitializedException(RedisException):
    """Redis未初始化异常"""
    def __init__(self):
        super().__init__(
            "RedisManager not initialized. Call init() first."
        )


class RedisConnectionException(RedisException):
    """Redis连接异常"""
    def __init__(self, detail: str):
        super().__init__(f"Redis connection error: {detail}")


# ========== 配置异常 ==========

class ConfigurationException(SCNSConductorException):
    """配置相关异常基类"""
    pass


class InvalidConfigException(ConfigurationException):
    """无效的配置异常"""
    def __init__(self, key: str, value: any, reason: str):
        super().__init__(
            f"Invalid configuration: {key}={value} - {reason}"
        )


# ========== 作业异常 ==========

class JobNotFoundException(SCNSConductorException):
    """作业未找到异常"""
    def __init__(self, job_id: int):
        self.job_id = job_id
        super().__init__(f"作业 {job_id} 未找到")


class JobStateException(SCNSConductorException):
    """作业状态转换异常"""
    def __init__(self, job_id: int, current_state: str, target_state: str):
        self.job_id = job_id
        self.current_state = current_state
        self.target_state = target_state
        super().__init__(
            f"作业 {job_id} 无法从状态 {current_state} 转换到 {target_state}"
        )
