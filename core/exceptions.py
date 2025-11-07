"""
作业调度系统的自定义异常
"""


class SCNSConductorException(Exception):
    """SCNS-Conductor 基础异常类"""
    pass


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


class ResourceAllocationException(SCNSConductorException):
    """资源分配失败异常"""
    pass


class ConfigurationException(SCNSConductorException):
    """配置无效异常"""
    pass


class DatabaseException(SCNSConductorException):
    """数据库操作失败异常"""
    pass

