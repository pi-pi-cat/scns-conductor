# 清理策略系统 V4.0 - 完整优化版

## 🎉 特性总览

V4.0 实现了**所有优化方案**：

1. ✅ **装饰器模式** - 策略元数据配置（优先级、依赖、标签）
2. ✅ **钩子方法** - 前置/后置处理和错误处理
3. ✅ **观察者模式** - 策略执行监控（指标、告警等）
4. ✅ **配置驱动** - 从 YAML 配置文件加载

---

## 📋 核心特性详解

### 1. 装饰器模式 - 策略元数据

使用装饰器声明策略的元数据，而不是在代码中硬编码：

```python
@strategy_metadata(
    priority=1,                    # 执行优先级（数字越小越先执行）
    depends_on=[],                # 依赖的策略名称列表
    tags=['critical', 'resource'], # 标签列表
    timeout=60,                    # 超时时间（秒）
    retry_on_failure=False,       # 失败是否重试
    enabled_by_default=True,       # 默认是否启用
)
class CompletedJobCleanupStrategy(BaseCleanupStrategy):
    """已完成作业清理（最高优先级）"""
    pass
```

**优势**：
- ✅ 声明式配置，更清晰
- ✅ 自动排序和依赖管理
- ✅ 标签过滤支持

---

### 2. 钩子方法 - 生命周期管理

策略可以定义前置、后置和错误处理钩子：

```python
class MyStrategy(BaseCleanupStrategy):
    def before_execute(self, session: Session) -> bool:
        """执行前检查，返回 False 跳过执行"""
        count = self._count_items_to_clean(session)
        if count == 0:
            return False
        logger.info(f"Found {count} items to clean")
        return True
    
    def _do_cleanup(self, session: Session) -> int:
        """清理逻辑"""
        # 具体实现
        return count
    
    def after_execute(self, session: Session, result: CleanupResult):
        """执行后处理，如发送通知"""
        if result.items_cleaned > 10:
            self._send_alert(f"Cleaned {result.items_cleaned} items")
    
    def on_error(self, session: Session, error: Exception):
        """错误处理"""
        logger.error(f"Strategy failed: {error}")
        # 可以发送错误通知等
```

**优势**：
- ✅ 灵活的条件执行
- ✅ 统一的扩展点
- ✅ 增强日志和监控

---

### 3. 观察者模式 - 执行监控

策略执行结果可以被多个系统监听：

```python
from scheduler.cleanup_strategies import (
    CleanupStrategyManager,
    MetricsObserver,
    LoggingObserver,
)

# 创建管理器时注入观察者
manager = CleanupStrategyManager(
    observers=[
        LoggingObserver(),  # 日志观察者（默认）
        MetricsObserver(),  # 指标收集观察者
        # 可以添加更多观察者（如 PrometheusObserver、AlertObserver）
    ]
)

# 执行策略时，所有观察者会自动收到通知
results = manager.execute_due_strategies(current_time)
```

**自定义观察者**：

```python
from scheduler.cleanup_strategies import StrategyObserver, CleanupResult

class PrometheusObserver(StrategyObserver):
    """Prometheus 指标观察者"""
    
    def on_strategy_executed(self, result: CleanupResult):
        # 记录 Prometheus 指标
        prometheus_counter.labels(
            strategy=result.strategy_name,
            status='success'
        ).inc(result.items_cleaned)
    
    def on_strategy_failed(self, result: CleanupResult):
        # 记录失败指标
        prometheus_counter.labels(
            strategy=result.strategy_name,
            status='failure'
        ).inc()

# 使用
manager.add_observer(PrometheusObserver())
```

**优势**：
- ✅ 解耦监控逻辑
- ✅ 支持多监控系统
- ✅ 易于测试

---

### 4. 配置驱动 - YAML 配置

策略配置可以从 YAML 文件加载：

```yaml
# config/cleanup_strategies.yaml
strategies:
  completed_job_cleanup:
    enabled: true
    interval_seconds: 5
  
  stale_reservation_cleanup:
    enabled: true
    interval_seconds: 120
    max_age_minutes: 10
  
  stuck_job_cleanup:
    enabled: true
    interval_seconds: 3600
    max_age_hours: 48
```

**使用配置加载**：

```python
from pathlib import Path
from scheduler.cleanup_strategies import create_manager_from_config

# 从配置文件创建管理器
config_path = Path("config/cleanup_strategies.yaml")
manager = create_manager_from_config(config_path)
```

**优势**：
- ✅ 配置与代码分离
- ✅ 环境差异化配置
- ✅ 运维友好

---

## 🎨 完整使用示例

### 示例 1: 使用默认配置

```python
from scheduler.cleanup_strategies import create_default_manager

# 创建默认管理器
manager = create_default_manager()

# 执行所有到期的策略
import time
current_time = int(time.time())
results = manager.execute_due_strategies(current_time)

# 查看结果
for result in results:
    print(f"{result.strategy_name}: {result.items_cleaned} items, "
          f"success={result.success}, time={result.execution_time:.2f}s")
```

### 示例 2: 使用配置文件

```python
from pathlib import Path
from scheduler.cleanup_strategies import (
    create_manager_from_config,
    MetricsObserver,
)

# 创建自定义观察者
metrics_observer = MetricsObserver()

# 从配置文件加载
config_path = Path("config/cleanup_strategies.yaml")
manager = create_manager_from_config(
    config_path=config_path,
    observers=[metrics_observer],
)

# 执行策略
results = manager.execute_due_strategies(int(time.time()))

# 查看指标
print(metrics_observer.get_metrics())
```

### 示例 3: 手动执行单个策略

```python
# 手动执行指定策略
result = manager.execute_strategy("stale_reservation_cleanup")

if result:
    print(f"Cleaned {result.items_cleaned} items")
    print(f"Execution time: {result.execution_time:.2f}s")
```

### 示例 4: 查看所有策略

```python
# 列出所有策略（按优先级排序）
strategies = manager.list_strategies()

for strategy in strategies:
    metadata = strategy._get_metadata()
    print(f"{strategy.name}:")
    print(f"  Priority: {metadata.priority}")
    print(f"  Depends on: {metadata.depends_on}")
    print(f"  Tags: {metadata.tags}")
    print(f"  Enabled: {strategy.enabled}")
```

---

## 🔧 新增策略示例

### 定义新策略

```python
from scheduler.cleanup_strategies import (
    BaseCleanupStrategy,
    strategy_metadata,
    Session,
    CleanupResult,
)

@strategy_metadata(
    priority=5,
    depends_on=['completed_job_cleanup'],
    tags=['maintenance', 'optional'],
    timeout=300,
)
class DiskCleanupStrategy(BaseCleanupStrategy):
    """清理磁盘空间"""
    
    def __init__(self, interval_seconds=3600, threshold_gb=10):
        super().__init__(interval_seconds)
        self.threshold_gb = threshold_gb
    
    @property
    def name(self) -> str:
        return "disk_cleanup"
    
    @property
    def description(self) -> str:
        return f"清理磁盘，保留 {self.threshold_gb}GB"
    
    def before_execute(self, session: Session) -> bool:
        """检查磁盘使用率"""
        disk_usage = self._get_disk_usage()
        if disk_usage < self.threshold_gb:
            logger.debug("Disk usage OK, skipping cleanup")
            return False
        return True
    
    def _do_cleanup(self, session: Session) -> int:
        """清理旧日志文件"""
        cleaned_files = self._clean_old_logs()
        return len(cleaned_files)
    
    def after_execute(self, session: Session, result: CleanupResult):
        """记录清理统计"""
        if result.items_cleaned > 0:
            logger.info(f"Cleaned {result.items_cleaned} files")
    
    def _get_disk_usage(self) -> float:
        """获取磁盘使用率（示例）"""
        # 实际实现
        return 0.0
    
    def _clean_old_logs(self) -> List[str]:
        """清理旧日志（示例）"""
        # 实际实现
        return []
```

**完成！** 策略已自动注册，无需手动调用 `register()`。

---

## 📊 策略执行流程

```
1. 检查是否到期 (should_run)
   ↓
2. 前置钩子 (before_execute)
   ├─ 返回 False → 跳过执行
   └─ 返回 True → 继续
   ↓
3. 执行清理逻辑 (_do_cleanup)
   ├─ 成功 → 提交事务
   └─ 失败 → 回滚事务
   ↓
4. 后置钩子 (after_execute)
   ↓
5. 通知观察者 (notify_observers)
   ├─ on_strategy_executed (成功)
   └─ on_strategy_failed (失败)
   ↓
6. 返回结果 (CleanupResult)
```

---

## 🎯 策略优先级和依赖

策略按以下规则排序：

1. **依赖关系** - 依赖的策略先执行
2. **优先级** - 相同依赖层级按优先级排序（数字越小越先）

**示例**：

```python
@strategy_metadata(priority=1, depends_on=[])
class StrategyA: pass  # 最先执行

@strategy_metadata(priority=2, depends_on=['strategy_a'])
class StrategyB: pass  # 在 A 之后执行

@strategy_metadata(priority=1, depends_on=['strategy_a'])
class StrategyC: pass  # 在 A 之后，但优先级比 B 高，所以先于 B 执行
```

**执行顺序**: A → C → B

---

## 📈 性能指标

每个策略执行结果包含：

- `strategy_name`: 策略名称
- `items_cleaned`: 清理的记录数
- `success`: 是否成功
- `error_message`: 错误信息（如果有）
- `execution_time`: 执行时间（秒）

**示例**：

```python
result = manager.execute_strategy("completed_job_cleanup")

print(f"Strategy: {result.strategy_name}")
print(f"Items cleaned: {result.items_cleaned}")
print(f"Success: {result.success}")
print(f"Execution time: {result.execution_time:.2f}s")
```

---

## 🔍 调试和监控

### 查看已注册的策略

```python
from scheduler.cleanup_strategies import get_registered_strategies

strategies = get_registered_strategies()
for name, cls in strategies.items():
    print(f"{name}: {cls}")
```

### 查看管理器中的策略

```python
strategies = manager.list_strategies()
for strategy in strategies:
    print(f"{strategy.name}: {strategy.description}")
```

### 获取指标

```python
metrics_observer = MetricsObserver()
manager.add_observer(metrics_observer)

# 执行策略后
metrics = metrics_observer.get_metrics()
print(metrics)
# {
#     'total_executions': 10,
#     'total_success': 9,
#     'total_failures': 1,
#     'total_items_cleaned': 150
# }
```

---

## 🚀 迁移指南

### 从 V3 迁移到 V4

1. **策略类** - 无需修改（向后兼容）
2. **管理器创建** - 可以继续使用 `create_default_manager()`
3. **新增功能** - 可选使用装饰器、钩子、观察者

### 逐步迁移

**阶段 1**: 保持现有代码不变，V4 完全向后兼容

**阶段 2**: 为策略添加装饰器（可选）

```python
# 添加装饰器
@strategy_metadata(priority=1, tags=['critical'])
class MyStrategy(BaseCleanupStrategy):
    # 现有代码不变
    pass
```

**阶段 3**: 添加钩子方法（可选）

```python
class MyStrategy(BaseCleanupStrategy):
    def before_execute(self, session):
        # 添加前置检查
        return True
    
    def after_execute(self, session, result):
        # 添加后置处理
        pass
```

**阶段 4**: 添加观察者（可选）

```python
manager = CleanupStrategyManager(
    observers=[MetricsObserver(), AlertObserver()]
)
```

---

## 📚 相关文档

- **优化方案**: `docs/OPTIMIZATION_PROPOSALS.md`
- **快速指南**: `docs/OPTIMIZATION_QUICK_GUIDE.md`
- **架构说明**: `docs/CLEANUP_STRATEGY_ARCHITECTURE.md`
- **配置文件示例**: `config/cleanup_strategies.yaml.example`

---

## 🎉 总结

V4.0 实现了**所有优化方案**，代码优雅度达到 ⭐⭐⭐⭐⭐！

**核心优势**：
- ✅ 声明式配置（装饰器）
- ✅ 灵活的生命周期管理（钩子）
- ✅ 解耦的监控系统（观察者）
- ✅ 配置与代码分离（YAML）
- ✅ 完全向后兼容

**这就是真正的 Python 高级编程！** 🐍✨

