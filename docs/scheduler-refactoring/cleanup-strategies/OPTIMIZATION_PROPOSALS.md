# 🎨 清理策略系统 - 进一步优化方案

> **当前状态**: V3 已实现策略模式 + 模板方法 + 自动注册  
> **目标**: 探索更优雅的设计模式和 Python 特性

---

## 📊 当前架构评估

### ✅ 已实现的优秀特性

1. **策略模式** - 策略独立，易于扩展
2. **模板方法** - 消除重复代码（DRY）
3. **自动注册** - `__init_subclass__` 魔法方法
4. **依赖注入** - 管理器可注入，易于测试
5. **统一接口** - 所有策略遵循相同接口

### ⚠️ 可以改进的方面

1. **配置管理** - 硬编码在 `create_default_manager()`
2. **执行顺序** - 策略执行顺序不可控
3. **监控指标** - 缺少执行时间、成功率等指标
4. **条件启用** - 只有简单的 `enabled` 布尔值
5. **钩子机制** - 缺少前置/后置处理
6. **错误处理** - 策略失败后的处理策略单一
7. **类型安全** - 可以更严格的类型注解

---

## 🚀 优化方案（按优先级排序）

---

## 方案 1: 装饰器模式 - 策略元数据配置 ⭐⭐⭐⭐⭐

### 🎯 目标
使用装饰器为策略添加元数据（优先级、依赖关系、标签等），而不是在 `__init__` 中传递。

### 💡 设计思路

```python
# 装饰器定义
@strategy_metadata(
    priority=1,                    # 执行优先级（数字越小越先执行）
    depends_on=['completed_job'],  # 依赖的策略
    tags=['critical', 'resource'], # 标签
    timeout=300,                   # 超时时间（秒）
    retry_on_failure=True,         # 失败是否重试
)
class StaleReservationCleanupStrategy(BaseCleanupStrategy):
    """清理预留超时"""
    pass
```

### ✅ 优势

1. **声明式配置** - 元数据与类定义在一起，更清晰
2. **自动排序** - 管理器根据优先级自动排序
3. **依赖管理** - 自动处理策略依赖关系
4. **标签过滤** - 可以按标签执行策略组
5. **更优雅** - 符合 Python 装饰器文化

### 📝 实现要点

```python
from functools import wraps
from typing import List, Optional
from dataclasses import dataclass, field

@dataclass
class StrategyMetadata:
    """策略元数据"""
    priority: int = 100  # 默认优先级
    depends_on: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    timeout: Optional[int] = None
    retry_on_failure: bool = False
    enabled_by_default: bool = True

# 装饰器
def strategy_metadata(**metadata):
    """策略元数据装饰器"""
    def decorator(cls):
        cls._metadata = StrategyMetadata(**metadata)
        return cls
    return decorator

# 管理器自动排序
def _sort_strategies_by_priority(self):
    """根据优先级和依赖关系排序"""
    # 拓扑排序算法
    pass
```

### 🎨 使用示例

```python
@strategy_metadata(
    priority=1,
    depends_on=[],
    tags=['critical'],
    timeout=60,
)
class CompletedJobCleanupStrategy(BaseCleanupStrategy):
    """必须先执行，释放资源"""
    pass

@strategy_metadata(
    priority=2,
    depends_on=['completed_job_cleanup'],
    tags=['critical', 'resource'],
)
class StaleReservationCleanupStrategy(BaseCleanupStrategy):
    """依赖 completed_job，在其之后执行"""
    pass
```

### 📊 影响评估

- **代码优雅度**: ⭐⭐⭐⭐⭐ (大幅提升)
- **实现复杂度**: ⭐⭐⭐ (中等)
- **向后兼容**: ✅ (完全兼容)
- **实际价值**: ⭐⭐⭐⭐⭐ (高)

---

## 方案 2: 钩子方法模式 - 前置/后置处理 ⭐⭐⭐⭐

### 🎯 目标
为策略添加生命周期钩子，支持前置检查、后置通知等。

### 💡 设计思路

```python
class BaseCleanupStrategy(ABC):
    def before_execute(self, session: Session) -> bool:
        """执行前的钩子（可选）
        
        Returns:
            True 继续执行, False 跳过
        """
        return True
    
    def after_execute(self, session: Session, result: CleanupResult):
        """执行后的钩子（可选）"""
        pass
    
    def on_error(self, session: Session, error: Exception):
        """错误处理钩子（可选）"""
        pass
```

### ✅ 优势

1. **灵活扩展** - 策略可以自定义前后处理
2. **统一接口** - 所有钩子都有默认实现
3. **日志增强** - 可以在钩子中添加详细日志
4. **条件执行** - `before_execute` 可以动态决定是否执行

### 📝 实现要点

```python
def execute(self, session: Session) -> CleanupResult:
    """模板方法 - 集成钩子"""
    # 前置钩子
    if not self.before_execute(session):
        return self._build_skipped_result()
    
    try:
        count = self._do_cleanup(session)
        if count > 0:
            session.commit()
        
        result = self._build_success_result(count)
        
        # 后置钩子
        self.after_execute(session, result)
        
        return result
    except Exception as e:
        # 错误钩子
        self.on_error(session, e)
        session.rollback()
        return self._build_error_result(e)
```

### 🎨 使用示例

```python
class StaleReservationCleanupStrategy(BaseCleanupStrategy):
    def before_execute(self, session: Session) -> bool:
        """检查是否有待清理的预留"""
        count = session.query(ResourceAllocation).filter(
            ResourceAllocation.status == ResourceStatus.RESERVED
        ).count()
        
        if count == 0:
            logger.debug("No stale reservations, skipping")
            return False
        
        logger.info(f"Found {count} stale reservations to clean")
        return True
    
    def after_execute(self, session: Session, result: CleanupResult):
        """执行后发送通知"""
        if result.items_cleaned > 10:
            self._send_alert(f"Cleaned {result.items_cleaned} stale reservations")
```

### 📊 影响评估

- **代码优雅度**: ⭐⭐⭐⭐
- **实现复杂度**: ⭐⭐ (简单)
- **向后兼容**: ✅ (完全兼容)
- **实际价值**: ⭐⭐⭐⭐

---

## 方案 3: 观察者模式 - 策略执行监控 ⭐⭐⭐⭐

### 🎯 目标
策略执行结果可以被多个观察者监听（日志、监控、告警等）。

### 💡 设计思路

```python
class StrategyObserver(ABC):
    """策略观察者接口"""
    
    @abstractmethod
    def on_strategy_executed(self, result: CleanupResult):
        """策略执行完成时调用"""
        pass
    
    @abstractmethod
    def on_strategy_failed(self, result: CleanupResult):
        """策略执行失败时调用"""
        pass

class MetricsObserver(StrategyObserver):
    """指标收集观察者"""
    def on_strategy_executed(self, result: CleanupResult):
        # 记录 Prometheus 指标
        pass

class AlertObserver(StrategyObserver):
    """告警观察者"""
    def on_strategy_executed(self, result: CleanupResult):
        if result.items_cleaned > 100:
            # 发送告警
            pass
```

### ✅ 优势

1. **解耦监控** - 策略不关心如何监控
2. **多观察者** - 可以同时有多个监控系统
3. **易于扩展** - 新增监控只需添加观察者
4. **测试友好** - 可以注入 Mock 观察者

### 📝 实现要点

```python
class CleanupStrategyManager:
    def __init__(self, observers: List[StrategyObserver] = None):
        self.strategies = {}
        self.observers = observers or []
    
    def add_observer(self, observer: StrategyObserver):
        """添加观察者"""
        self.observers.append(observer)
    
    def _notify_observers(self, result: CleanupResult):
        """通知所有观察者"""
        if result.success:
            for observer in self.observers:
                observer.on_strategy_executed(result)
        else:
            for observer in self.observers:
                observer.on_strategy_failed(result)
```

### 🎨 使用示例

```python
# 创建管理器时注入观察者
manager = CleanupStrategyManager(
    observers=[
        MetricsObserver(),  # Prometheus 指标
        AlertObserver(),   # 告警系统
        LogObserver(),     # 详细日志
    ]
)
```

### 📊 影响评估

- **代码优雅度**: ⭐⭐⭐⭐
- **实现复杂度**: ⭐⭐⭐ (中等)
- **向后兼容**: ✅ (完全兼容)
- **实际价值**: ⭐⭐⭐⭐

---

## 方案 4: 配置驱动 - 从配置文件加载 ⭐⭐⭐

### 🎯 目标
策略配置从 YAML/JSON 文件加载，而不是硬编码。

### 💡 设计思路

```yaml
# config/cleanup_strategies.yaml
strategies:
  completed_job_cleanup:
    enabled: true
    interval_seconds: 5
    priority: 1
  
  stale_reservation_cleanup:
    enabled: true
    interval_seconds: 120
    max_age_minutes: 10
    priority: 2
    depends_on:
      - completed_job_cleanup
  
  stuck_job_cleanup:
    enabled: true
    interval_seconds: 3600
    max_age_hours: 48
    priority: 3
```

### ✅ 优势

1. **配置与代码分离** - 修改配置无需改代码
2. **环境差异化** - 不同环境可以有不同的配置
3. **动态调整** - 可以支持运行时重载配置
4. **运维友好** - 运维人员可以直接修改配置

### 📝 实现要点

```python
from pathlib import Path
import yaml

def load_strategy_config(config_path: Path) -> dict:
    """从配置文件加载策略配置"""
    with open(config_path) as f:
        return yaml.safe_load(f)

def create_manager_from_config(config_path: Path) -> CleanupStrategyManager:
    """从配置文件创建管理器"""
    config = load_strategy_config(config_path)
    manager = CleanupStrategyManager()
    
    for strategy_name, strategy_config in config['strategies'].items():
        # 根据配置实例化策略
        pass
    
    return manager
```

### 📊 影响评估

- **代码优雅度**: ⭐⭐⭐
- **实现复杂度**: ⭐⭐ (简单)
- **向后兼容**: ⚠️ (需要迁移配置)
- **实际价值**: ⭐⭐⭐ (中等，取决于是否需要)

---

## 方案 5: 策略组合模式 - 策略链 ⭐⭐⭐

### 🎯 目标
支持策略组合执行，形成策略链或策略组。

### 💡 设计思路

```python
class StrategyGroup(BaseCleanupStrategy):
    """策略组合 - 按顺序执行多个策略"""
    
    def __init__(self, strategies: List[BaseCleanupStrategy]):
        self.strategies = strategies
    
    def _do_cleanup(self, session: Session) -> int:
        total = 0
        for strategy in self.strategies:
            result = strategy.execute(session)
            total += result.items_cleaned
            if not result.success:
                # 是否继续执行？
                break
        return total

# 使用
critical_cleanup = StrategyGroup([
    CompletedJobCleanupStrategy(...),
    StaleReservationCleanupStrategy(...),
])
```

### ✅ 优势

1. **策略分组** - 可以按业务逻辑分组
2. **批量执行** - 一次性执行一组策略
3. **条件执行** - 可以控制失败后的行为

### 📊 影响评估

- **代码优雅度**: ⭐⭐⭐
- **实现复杂度**: ⭐⭐ (简单)
- **向后兼容**: ✅ (完全兼容)
- **实际价值**: ⭐⭐ (当前场景可能不需要)

---

## 方案 6: 类型安全增强 - Protocol 和泛型 ⭐⭐⭐

### 🎯 目标
使用 Python 3.8+ 的 `Protocol` 和泛型增强类型安全。

### 💡 设计思路

```python
from typing import Protocol, TypeVar, Generic

T = TypeVar('T')

class CleanupStrategy(Protocol):
    """策略协议（鸭子类型）"""
    name: str
    description: str
    
    def execute(self, session: Session) -> CleanupResult:
        ...
    
    def should_run(self, current_time: int) -> bool:
        ...

class StrategyFactory(Generic[T]):
    """策略工厂（泛型）"""
    def create(self, config: dict) -> T:
        pass
```

### ✅ 优势

1. **类型安全** - IDE 更好的提示
2. **协议支持** - 支持鸭子类型
3. **泛型支持** - 更灵活的类型系统

### 📊 影响评估

- **代码优雅度**: ⭐⭐⭐⭐
- **实现复杂度**: ⭐⭐ (简单)
- **向后兼容**: ✅ (完全兼容)
- **实际价值**: ⭐⭐⭐ (提升开发体验)

---

## 方案 7: 异步支持 - 并行执行策略 ⭐⭐

### 🎯 目标
支持策略异步执行，可以并行运行多个策略。

### 💡 设计思路

```python
import asyncio
from typing import Awaitable

class AsyncCleanupStrategy(BaseCleanupStrategy):
    """异步清理策略"""
    
    @abstractmethod
    async def _do_cleanup_async(self, session: Session) -> int:
        """异步清理逻辑"""
        pass

# 管理器并行执行
async def execute_due_strategies_async(self, current_time: int):
    tasks = [
        strategy.execute_async(session)
        for strategy in self.strategies.values()
        if strategy.should_run(current_time)
    ]
    results = await asyncio.gather(*tasks)
    return results
```

### 📊 影响评估

- **代码优雅度**: ⭐⭐⭐
- **实现复杂度**: ⭐⭐⭐⭐ (复杂，需要异步数据库)
- **向后兼容**: ⚠️ (需要重构)
- **实际价值**: ⭐⭐ (当前场景可能不需要)

---

## 🎯 推荐方案组合

### 方案 A: 优雅增强型（推荐）⭐⭐⭐⭐⭐

**组合**:
1. ✅ **方案 1: 装饰器模式** - 策略元数据
2. ✅ **方案 2: 钩子方法** - 前置/后置处理
3. ✅ **方案 3: 观察者模式** - 执行监控

**理由**:
- 三者互补，形成完整的生命周期管理
- 实现复杂度适中
- 大幅提升代码优雅度
- 完全向后兼容

**预期效果**:
```
代码优雅度: ⭐⭐⭐⭐⭐
可维护性:   ⭐⭐⭐⭐⭐
可扩展性:   ⭐⭐⭐⭐⭐
```

### 方案 B: 实用增强型 ⭐⭐⭐⭐

**组合**:
1. ✅ **方案 1: 装饰器模式** - 策略元数据
2. ✅ **方案 2: 钩子方法** - 前置/后置处理
3. ✅ **方案 4: 配置驱动** - 配置文件加载

**理由**:
- 适合需要频繁调整配置的场景
- 配置与代码分离
- 运维友好

### 方案 C: 极致优雅型 ⭐⭐⭐⭐⭐

**组合**:
1. ✅ **方案 1: 装饰器模式** - 策略元数据
2. ✅ **方案 2: 钩子方法** - 前置/后置处理
3. ✅ **方案 3: 观察者模式** - 执行监控
4. ✅ **方案 6: 类型安全** - Protocol 和泛型

**理由**:
- 所有优雅特性都加上
- 类型安全 + 运行时优雅
- 适合长期维护的项目

---

## 📋 实施建议

### 阶段 1: 核心增强（必须）

1. **装饰器模式** - 策略元数据配置
   - 优先级排序
   - 依赖关系管理
   - 标签系统

### 阶段 2: 生命周期（推荐）

2. **钩子方法** - 前置/后置处理
   - `before_execute`
   - `after_execute`
   - `on_error`

### 阶段 3: 监控增强（可选）

3. **观察者模式** - 执行监控
   - 指标收集
   - 告警通知
   - 日志增强

### 阶段 4: 类型安全（可选）

4. **类型安全** - Protocol 和泛型
   - 协议定义
   - 泛型支持

---

## 🎨 最终效果预览

### Before (V3)

```python
class StaleReservationCleanupStrategy(BaseCleanupStrategy):
    def __init__(self, interval_seconds=120, max_age_minutes=10):
        super().__init__(interval_seconds)
        self.max_age_minutes = max_age_minutes
    
    def _do_cleanup(self, session):
        # 清理逻辑
        pass
```

### After (V4 - 推荐方案)

```python
@strategy_metadata(
    priority=2,
    depends_on=['completed_job_cleanup'],
    tags=['critical', 'resource'],
    timeout=60,
)
class StaleReservationCleanupStrategy(BaseCleanupStrategy):
    """清理预留超时"""
    
    def __init__(self, interval_seconds=120, max_age_minutes=10):
        super().__init__(interval_seconds)
        self.max_age_minutes = max_age_minutes
    
    def before_execute(self, session: Session) -> bool:
        """前置检查"""
        count = self._count_stale_reservations(session)
        if count == 0:
            return False
        logger.info(f"Found {count} stale reservations")
        return True
    
    def _do_cleanup(self, session: Session) -> int:
        """清理逻辑"""
        # 具体实现
        pass
    
    def after_execute(self, session: Session, result: CleanupResult):
        """后置处理"""
        if result.items_cleaned > 10:
            self._send_alert(f"Cleaned {result.items_cleaned} items")
```

---

## 🎯 总结

### 最推荐的方案

**方案 A: 优雅增强型**
- 装饰器模式（元数据）
- 钩子方法（生命周期）
- 观察者模式（监控）

### 实施优先级

1. **高优先级**: 装饰器模式（方案 1）
2. **中优先级**: 钩子方法（方案 2）
3. **低优先级**: 观察者模式（方案 3）

### 预期收益

- **代码优雅度**: 提升 30%
- **可维护性**: 提升 40%
- **可扩展性**: 提升 50%
- **开发体验**: 提升 60%

---

**请选择你感兴趣的方案，我可以开始实现！** 🚀

