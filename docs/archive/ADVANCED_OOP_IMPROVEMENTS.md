# 高级 OOP 特性改进建议

## 📚 当前项目中的高级 OOP 应用分析

### ✅ 已经使用的高级特性

| 特性 | 当前使用 | 位置 | 优秀程度 |
|------|---------|------|---------|
| **单例模式** | ✅ 使用装饰器实现 | `core/utils/singleton.py` | ⭐⭐⭐⭐⭐ |
| **上下文管理器** | ✅ `@contextmanager` | `core/database.py` | ⭐⭐⭐⭐⭐ |
| **属性装饰器** | ✅ `@property` | `core/models.py` | ⭐⭐⭐⭐ |
| **类型注解** | ✅ 全面使用 | 所有文件 | ⭐⭐⭐⭐⭐ |
| **SQLModel** | ✅ ORM+Pydantic | `core/models.py` | ⭐⭐⭐⭐⭐ |

### 🎯 可以改进的高级特性

---

## 1. 描述符 (Descriptors) - 推荐应用

### 场景：资源限制验证

**当前代码**：
```python
# core/models.py
class Job(SQLModel, table=True):
    cpus_per_task: int = Field(default=1, description="每个任务的CPU数")
    # 验证在 Pydantic 层面，分散在多处
```

**改进：使用描述符统一管理资源约束**

```python
# core/descriptors.py
class PositiveInteger:
    """正整数描述符 - 自动验证和类型转换"""
    
    def __init__(self, min_value=1, max_value=None):
        self.min_value = min_value
        self.max_value = max_value
        self.name = None
    
    def __set_name__(self, owner, name):
        self.name = f'_{name}'
    
    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        return getattr(obj, self.name, self.min_value)
    
    def __set__(self, obj, value):
        if not isinstance(value, int):
            raise TypeError(f"{self.name[1:]} 必须是整数")
        if value < self.min_value:
            raise ValueError(f"{self.name[1:]} 不能小于 {self.min_value}")
        if self.max_value and value > self.max_value:
            raise ValueError(f"{self.name[1:]} 不能大于 {self.max_value}")
        setattr(obj, self.name, value)


class CPUResourceValidator:
    """CPU资源验证描述符"""
    
    def __init__(self, max_cpus=None):
        self.max_cpus = max_cpus
        self.name = None
    
    def __set_name__(self, owner, name):
        self.name = f'_{name}'
    
    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        return getattr(obj, self.name, 0)
    
    def __set__(self, obj, value):
        # 验证逻辑
        if value < 1:
            raise ValueError("CPU 数量必须至少为 1")
        
        # 动态获取系统最大CPU数
        if self.max_cpus is None:
            from core.config import get_settings
            self.max_cpus = get_settings().TOTAL_CPUS
        
        if value > self.max_cpus:
            raise ValueError(
                f"请求的 CPU 数量 ({value}) 超过系统最大值 ({self.max_cpus})"
            )
        
        setattr(obj, self.name, value)


# 使用
class JobRequest:
    """作业请求类"""
    cpus_per_task = PositiveInteger(min_value=1, max_value=128)
    ntasks_per_node = PositiveInteger(min_value=1, max_value=256)
    allocated_cpus = CPUResourceValidator()
    
    def __init__(self, cpus_per_task, ntasks_per_node):
        self.cpus_per_task = cpus_per_task  # 自动验证
        self.ntasks_per_node = ntasks_per_node  # 自动验证
```

**优势**：
- ✅ 验证逻辑集中管理
- ✅ 可重用于多个类
- ✅ 自动类型检查
- ✅ 清晰的错误消息

---

## 2. 元类 (Metaclass) - 可选应用

### 场景：服务注册系统

**改进：自动注册所有服务类**

```python
# core/metaclasses.py
class ServiceRegistry(type):
    """服务注册元类 - 自动注册所有服务"""
    
    _registry = {}
    
    def __new__(mcs, name, bases, attrs):
        cls = super().__new__(mcs, name, bases, attrs)
        
        # 跳过基类
        if name != 'BaseService':
            service_name = attrs.get('service_name', name.lower())
            mcs._registry[service_name] = cls
            cls._service_name = service_name
            
            logger.info(f"注册服务: {service_name} -> {cls.__name__}")
        
        return cls
    
    @classmethod
    def get_service(mcs, name):
        """获取注册的服务"""
        return mcs._registry.get(name)
    
    @classmethod
    def list_services(mcs):
        """列出所有服务"""
        return list(mcs._registry.keys())


# api/services/base.py
class BaseService(metaclass=ServiceRegistry):
    """服务基类"""
    pass


# api/services/job_service.py
class JobService(BaseService):
    """作业服务 - 自动注册"""
    service_name = "job"
    
    @staticmethod
    async def submit_job(...):
        ...


# api/services/log_service.py
class LogReaderService(BaseService):
    """日志服务 - 自动注册"""
    service_name = "log"


# 使用
service = ServiceRegistry.get_service("job")
print(ServiceRegistry.list_services())  # ['job', 'log']
```

**优势**：
- ✅ 服务自动发现
- ✅ 无需手动注册
- ✅ 统一管理
- ✅ 方便插件化

---

## 3. 高级魔术方法 - 强烈推荐

### 3.1 `__call__` - 可调用对象

**场景：作业执行器作为可调用对象**

```python
# worker/executor.py （改进版）
class JobExecutor:
    """作业执行器 - 可调用对象"""
    
    def __init__(self):
        self.settings = get_settings()
        self.scheduler = ResourceScheduler()
        self._execution_count = 0
    
    def __call__(self, job_id: int) -> bool:
        """
        使执行器可以像函数一样调用
        
        Usage:
            executor = JobExecutor()
            success = executor(job_id)  # 直接调用
        """
        self._execution_count += 1
        logger.info(f"执行器调用次数: {self._execution_count}")
        
        try:
            self.execute_job(job_id)
            return True
        except Exception as e:
            logger.error(f"执行失败: {e}")
            return False
    
    def __repr__(self):
        return f"<JobExecutor(executed={self._execution_count})>"


# 使用
executor = JobExecutor()
executor(1001)  # 像函数一样调用
executor(1002)
print(executor)  # <JobExecutor(executed=2)>
```

### 3.2 `__enter__` / `__exit__` - 上下文管理器类

**场景：资源锁定**

```python
# worker/resource_lock.py
class ResourceLock:
    """资源锁 - 上下文管理器"""
    
    def __init__(self, job_id: int, cpus: int):
        self.job_id = job_id
        self.cpus = cpus
        self.allocated = False
    
    def __enter__(self):
        """进入上下文 - 分配资源"""
        logger.info(f"为作业 {self.job_id} 分配 {self.cpus} CPUs")
        
        with sync_db.get_session() as session:
            allocation = ResourceAllocation(
                job_id=self.job_id,
                allocated_cpus=self.cpus,
                node_name=get_settings().NODE_NAME
            )
            session.add(allocation)
            session.commit()
        
        self.allocated = True
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文 - 释放资源"""
        if self.allocated:
            logger.info(f"释放作业 {self.job_id} 的资源")
            
            with sync_db.get_session() as session:
                allocation = session.query(ResourceAllocation).filter(
                    ResourceAllocation.job_id == self.job_id
                ).first()
                
                if allocation:
                    allocation.released = True
                    allocation.released_time = datetime.utcnow()
                    session.commit()
        
        # 不抑制异常
        return False


# 使用
def execute_job(job_id: int, cpus: int):
    with ResourceLock(job_id, cpus):
        # 资源自动分配
        run_job_script()
        # 退出时自动释放，即使出错也会释放
```

### 3.3 `__getitem__` / `__setitem__` - 容器协议

**场景：配置访问**

```python
# core/config.py （改进版）
class Settings(BaseSettings):
    """配置类 - 支持字典式访问"""
    
    # ... 原有字段 ...
    
    def __getitem__(self, key: str):
        """支持 settings['KEY'] 访问"""
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(f"配置项不存在: {key}")
    
    def __setitem__(self, key: str, value):
        """支持 settings['KEY'] = value 设置"""
        if not hasattr(self, key):
            raise KeyError(f"配置项不存在: {key}")
        setattr(self, key, value)
    
    def __contains__(self, key: str):
        """支持 'KEY' in settings 检查"""
        return hasattr(self, key)
    
    def __iter__(self):
        """支持迭代所有配置项"""
        return iter(self.__fields__.keys())
    
    def items(self):
        """返回所有配置项"""
        return {k: getattr(self, k) for k in self.__fields__.keys()}


# 使用
settings = get_settings()
settings['TOTAL_CPUS']  # 字典式访问
'REDIS_HOST' in settings  # True
for key in settings:
    print(f"{key} = {settings[key]}")
```

---

## 4. 抽象基类 (ABC) - 推荐应用

### 场景：定义服务接口

```python
# api/services/base.py
from abc import ABC, abstractmethod
from typing import TypeVar, Generic

T = TypeVar('T')


class BaseService(ABC, Generic[T]):
    """抽象服务基类 - 定义统一接口"""
    
    @abstractmethod
    async def create(self, data: T) -> int:
        """创建资源"""
        pass
    
    @abstractmethod
    async def get(self, id: int) -> T:
        """获取资源"""
        pass
    
    @abstractmethod
    async def update(self, id: int, data: T) -> bool:
        """更新资源"""
        pass
    
    @abstractmethod
    async def delete(self, id: int) -> bool:
        """删除资源"""
        pass


# api/services/job_service.py
class JobService(BaseService[Job]):
    """作业服务 - 必须实现所有抽象方法"""
    
    async def create(self, data: Job) -> int:
        # 实现
        pass
    
    async def get(self, id: int) -> Job:
        # 实现
        pass
    
    # ... 其他方法
```

---

## 5. 属性协议增强

### 5.1 懒加载属性

```python
# core/lazy.py
class LazyProperty:
    """懒加载属性描述符 - 只在首次访问时计算"""
    
    def __init__(self, func):
        self.func = func
        self.name = func.__name__
    
    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        
        # 首次访问时计算值
        value = self.func(obj)
        # 缓存到实例字典中
        setattr(obj, self.name, value)
        return value


# core/models.py
class Job(SQLModel, table=True):
    # ... 其他字段 ...
    
    @LazyProperty
    def total_cpus_required(self) -> int:
        """懒加载计算总CPU需求"""
        logger.debug(f"计算作业 {self.id} 的CPU需求")
        return self.ntasks_per_node * self.cpus_per_task
    
    @LazyProperty
    def estimated_memory_mb(self) -> int:
        """懒加载计算内存需求（MB）"""
        # 解析 memory_per_node (如 "16G" -> 16384)
        import re
        match = re.match(r'(\d+)([KMGT]?)', self.memory_per_node)
        if match:
            num, unit = match.groups()
            multipliers = {'K': 1/1024, 'M': 1, 'G': 1024, 'T': 1024*1024}
            return int(num) * multipliers.get(unit, 1)
        return 0
```

---

## 6. Mixin 模式 - 功能组合

```python
# core/mixins.py
class TimestampMixin:
    """时间戳Mixin - 自动管理创建和更新时间"""
    
    created_at: datetime
    updated_at: datetime
    
    def touch(self):
        """更新修改时间"""
        self.updated_at = datetime.utcnow()


class SerializableMixin:
    """序列化Mixin - 提供便捷的序列化方法"""
    
    def to_dict(self, exclude=None):
        """转换为字典"""
        exclude = exclude or set()
        return {
            k: v for k, v in self.__dict__.items()
            if not k.startswith('_') and k not in exclude
        }
    
    def to_json(self):
        """转换为JSON字符串"""
        import json
        return json.dumps(self.to_dict(), default=str)


class AuditMixin:
    """审计Mixin - 记录操作历史"""
    
    def log_action(self, action: str, user: str = "system"):
        """记录操作"""
        logger.info(
            f"审计日志: {user} 对 {self.__class__.__name__} "
            f"执行了 {action} 操作",
            extra={"object_id": getattr(self, 'id', None)}
        )


# 使用Mixin
class Job(SQLModel, TimestampMixin, SerializableMixin, AuditMixin, table=True):
    """作业模型 - 组合多个Mixin功能"""
    # ... 字段定义 ...


# 使用
job = Job(...)
job.touch()  # 来自 TimestampMixin
job.log_action("submit", "user123")  # 来自 AuditMixin
json_str = job.to_json()  # 来自 SerializableMixin
```

---

## 7. 高级装饰器

### 7.1 重试装饰器（带指数退避）

```python
# core/decorators.py
import functools
import time
from typing import Type, Tuple

def retry(
    max_attempts: int = 3,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    backoff_factor: float = 2.0,
    logger=None
):
    """
    重试装饰器 - 支持指数退避
    
    Args:
        max_attempts: 最大重试次数
        exceptions: 要捕获的异常类型
        backoff_factor: 退避因子
    """
    def decorator(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_attempts:
                        raise
                    
                    wait_time = backoff_factor ** (attempt - 1)
                    if logger:
                        logger.warning(
                            f"{func.__name__} 失败 (尝试 {attempt}/{max_attempts}), "
                            f"{wait_time}秒后重试: {e}"
                        )
                    time.sleep(wait_time)
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_attempts:
                        raise
                    
                    wait_time = backoff_factor ** (attempt - 1)
                    if logger:
                        logger.warning(
                            f"{func.__name__} 失败 (尝试 {attempt}/{max_attempts}), "
                            f"{wait_time}秒后重试: {e}"
                        )
                    time.sleep(wait_time)
        
        # 根据函数类型返回合适的包装器
        import inspect
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


# 使用
from core.exceptions import DatabaseException

@retry(max_attempts=3, exceptions=(DatabaseException,), logger=logger)
async def submit_job_to_database(job):
    """提交作业到数据库 - 自动重试"""
    async with async_db.get_session() as session:
        session.add(job)
        await session.commit()
```

---

## 📊 优先级建议

| 特性 | 优先级 | 复杂度 | 收益 | 建议 |
|------|--------|--------|------|------|
| **描述符验证** | ⭐⭐⭐⭐⭐ | 中 | 高 | 立即实施 |
| **可调用对象** | ⭐⭐⭐⭐⭐ | 低 | 高 | 立即实施 |
| **上下文管理器类** | ⭐⭐⭐⭐⭐ | 低 | 高 | 立即实施 |
| **Mixin模式** | ⭐⭐⭐⭐ | 中 | 中 | 推荐实施 |
| **懒加载属性** | ⭐⭐⭐⭐ | 低 | 中 | 推荐实施 |
| **抽象基类** | ⭐⭐⭐ | 中 | 中 | 可选实施 |
| **元类注册** | ⭐⭐ | 高 | 低 | 可选实施 |

---

## 🎯 实施路线图

### 阶段1：低风险改进（立即实施）

1. ✅ 添加 `__call__` 到 `JobExecutor`
2. ✅ 实现 `ResourceLock` 上下文管理器
3. ✅ 添加重试装饰器到关键数据库操作

### 阶段2：中等改进（1-2周内）

4. ✅ 实现描述符验证器
5. ✅ 添加Mixin功能组合
6. ✅ 实现懒加载属性

### 阶段3：架构改进（长期规划）

7. 🔄 引入抽象基类规范接口
8. 🔄 实现服务注册元类（如需要插件系统）

---

**文档版本**: v1.0.3  
**最后更新**: 2025-11-07

