# 清理策略架构 - 优雅的 OOP 设计

## 🎯 问题背景

**原有设计的问题**：
- ❌ 兜底逻辑散落在多处（`scheduler/daemon.py`、`scripts/cleanup.py`）
- ❌ 代码重复（相同逻辑在多处实现）
- ❌ 硬编码配置（时间间隔等直接写死）
- ❌ 难以扩展（新增策略需要改多个文件）
- ❌ 难以测试（逻辑耦合严重）

**用户反馈**：
> "我觉得这种代码太混乱了，是不是这些兜底策略应该使用高级OOP的方式组织起来"

## ✅ 新架构设计

### 核心概念

使用 **策略模式 + 注册器模式**，将所有清理逻辑统一管理：

```
策略基类 (BaseCleanupStrategy)
    ↓
具体策略 (StaleReservationCleanupStrategy, ...)
    ↓
策略管理器 (CleanupStrategyManager)
    ↓
调度器使用 (Scheduler.execute_cleanup_strategies())
```

### 类图

```
┌──────────────────────────────┐
│  BaseCleanupStrategy (ABC)   │  ← 抽象基类
├──────────────────────────────┤
│ + name: str                  │
│ + description: str           │
│ + interval_seconds: int      │
│ + enabled: bool              │
├──────────────────────────────┤
│ + execute(session) → Result  │  ← 抽象方法
│ + should_run(time) → bool    │
│ + mark_run(time)             │
└──────────────────────────────┘
           ↑
           │ 继承
    ┌──────┴──────────┬──────────────┬──────────────┐
    │                 │              │              │
┌───────┐      ┌─────────┐   ┌──────────┐   ┌──────────┐
│StaleRes│      │Completed│   │StuckJob  │   │OldJob    │
│ervation│      │Job      │   │Cleanup   │   │Cleanup   │
│Cleanup │      │Cleanup  │   │Strategy  │   │Strategy  │
└───────┘      └─────────┘   └──────────┘   └──────────┘

                      ↓ 管理

┌──────────────────────────────┐
│ CleanupStrategyManager       │
├──────────────────────────────┤
│ + strategies: Dict           │
├──────────────────────────────┤
│ + register(strategy)         │
│ + execute_due_strategies()   │
│ + execute_strategy(name)     │
└──────────────────────────────┘
```

## 📋 具体实现

### 1. 策略基类

```python
class BaseCleanupStrategy(ABC):
    """清理策略基类"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """策略名称"""
        pass
    
    @abstractmethod
    def execute(self, session: Session) -> CleanupResult:
        """执行清理逻辑"""
        pass
```

**优势**：
- ✅ 定义统一接口
- ✅ 强制子类实现核心方法
- ✅ 提供通用的时间管理逻辑

### 2. 具体策略

#### 预留超时清理

```python
class StaleReservationCleanupStrategy(BaseCleanupStrategy):
    def __init__(self, interval_seconds=120, max_age_minutes=10):
        super().__init__(interval_seconds)
        self.max_age_minutes = max_age_minutes
    
    @property
    def name(self) -> str:
        return "stale_reservation_cleanup"
    
    def execute(self, session: Session) -> CleanupResult:
        # 具体清理逻辑
        ...
```

**优势**：
- ✅ 封装单一职责
- ✅ 配置参数化
- ✅ 易于测试

#### 已完成作业清理

```python
class CompletedJobCleanupStrategy(BaseCleanupStrategy):
    def __init__(self, interval_seconds=5):
        super().__init__(interval_seconds)
```

#### 卡住作业清理

```python
class StuckJobCleanupStrategy(BaseCleanupStrategy):
    def __init__(self, interval_seconds=3600, max_age_hours=48):
        ...
```

#### 旧作业清理（可选）

```python
class OldJobCleanupStrategy(BaseCleanupStrategy):
    def __init__(self, interval_seconds=86400, max_age_days=30, enabled=False):
        super().__init__(interval_seconds, enabled)  # 默认禁用
```

### 3. 策略管理器

```python
class CleanupStrategyManager:
    def register(self, strategy: BaseCleanupStrategy):
        """注册策略"""
        self.strategies[strategy.name] = strategy
    
    def execute_due_strategies(self, current_time: int):
        """执行所有到期的策略"""
        for strategy in self.strategies.values():
            if strategy.should_run(current_time):
                result = strategy.execute(session)
                strategy.mark_run(current_time)
```

**优势**：
- ✅ 统一管理所有策略
- ✅ 自动调度执行
- ✅ 支持手动执行特定策略

### 4. 默认配置

```python
def create_default_manager() -> CleanupStrategyManager:
    """创建带有默认策略的管理器"""
    manager = CleanupStrategyManager()
    
    # 自动注册所有策略
    manager.register(StaleReservationCleanupStrategy(
        interval_seconds=120,  # 2分钟
        max_age_minutes=10
    ))
    manager.register(CompletedJobCleanupStrategy(
        interval_seconds=5  # 5秒
    ))
    manager.register(StuckJobCleanupStrategy(
        interval_seconds=3600,  # 1小时
        max_age_hours=48
    ))
    manager.register(OldJobCleanupStrategy(
        interval_seconds=86400,  # 1天
        max_age_days=30,
        enabled=False  # 默认禁用
    ))
    
    return manager
```

## 🚀 使用方式

### 在 Scheduler 中使用

```python
class JobScheduler:
    def __init__(self, cleanup_manager=None):
        # 注入策略管理器
        self.cleanup_manager = cleanup_manager or create_default_manager()
    
    def execute_cleanup_strategies(self, current_time: int):
        """执行清理策略"""
        self.cleanup_manager.execute_due_strategies(current_time)


# Daemon 中每次循环调用
def run(self):
    while True:
        current_time = int(time.time())
        
        # 1. 调度作业
        self.scheduler.schedule()
        
        # 2. 执行清理策略（统一管理）
        self.scheduler.execute_cleanup_strategies(current_time)
```

**优势**：
- ✅ 守护进程代码极简
- ✅ 所有策略自动执行
- ✅ 无需关心具体时间间隔

### 命令行工具

```bash
# 列出所有策略
python scripts/cleanup_v2.py --list

# 执行所有策略
python scripts/cleanup_v2.py

# 执行指定策略
python scripts/cleanup_v2.py --strategy stale_reservation_cleanup

# 启用旧作业清理
python scripts/cleanup_v2.py --enable-old-job
```

## 📊 架构优势对比

| 维度 | 旧架构 | 新架构 |
|------|--------|--------|
| **代码组织** | 散落多处 | 集中管理 |
| **新增策略** | 改3-4个文件 | 添加1个类 + 注册 |
| **配置管理** | 硬编码 | 参数化 |
| **时间调度** | 手动管理 | 自动管理 |
| **测试性** | 难测试 | 易测试（独立类） |
| **可维护性** | 低 | 高 |
| **可扩展性** | 差 | 优秀 |

## 🎨 扩展示例

### 新增自定义策略

只需3步：

**1. 创建策略类**

```python
class MyCustomCleanupStrategy(BaseCleanupStrategy):
    def __init__(self, interval_seconds=300):
        super().__init__(interval_seconds)
    
    @property
    def name(self) -> str:
        return "my_custom_cleanup"
    
    @property
    def description(self) -> str:
        return "我的自定义清理策略"
    
    def execute(self, session: Session) -> CleanupResult:
        # 你的清理逻辑
        ...
        return CleanupResult(
            strategy_name=self.name,
            items_cleaned=count,
            success=True
        )
```

**2. 注册策略**

```python
manager = create_default_manager()
manager.register(MyCustomCleanupStrategy(interval_seconds=600))
```

**3. 完成！**

策略会自动执行，无需修改其他代码。

### 禁用某个策略

```python
manager = create_default_manager()
strategy = manager.get_strategy("old_job_cleanup")
strategy.enabled = False
```

### 修改配置

```python
# 修改预留超时阈值
manager = CleanupStrategyManager()
manager.register(StaleReservationCleanupStrategy(
    interval_seconds=60,   # 改为1分钟检查一次
    max_age_minutes=5      # 改为5分钟超时
))
```

## 🧪 测试示例

```python
def test_stale_reservation_cleanup():
    # 创建策略
    strategy = StaleReservationCleanupStrategy(
        interval_seconds=10,
        max_age_minutes=5
    )
    
    # 准备测试数据
    session = create_test_session()
    # ...
    
    # 执行策略
    result = strategy.execute(session)
    
    # 断言
    assert result.success
    assert result.items_cleaned == 2
```

**优势**：
- ✅ 独立测试每个策略
- ✅ 无需启动完整系统
- ✅ 易于模拟各种场景

## 📝 设计模式说明

### 策略模式 (Strategy Pattern)

**定义**：定义一系列算法，把它们封装起来，并使它们可以互相替换。

**应用**：
- `BaseCleanupStrategy` = 策略接口
- `StaleReservationCleanupStrategy` 等 = 具体策略
- `CleanupStrategyManager` = 上下文

**好处**：
- 算法独立变化
- 易于扩展
- 符合开闭原则

### 注册器模式 (Registry Pattern)

**定义**：提供一个集中的注册表来管理对象。

**应用**：
- `CleanupStrategyManager.strategies` = 注册表
- `register()` = 注册方法
- `execute_due_strategies()` = 批量操作

**好处**：
- 集中管理
- 动态配置
- 松耦合

## 🔄 迁移指南

### 从旧架构迁移

**旧代码**（需要删除）：
```python
# scheduler/daemon.py
if current_time - self._last_cleanup_time >= self.cleanup_interval:
    self.scheduler.cleanup_stale_reservations(max_age_minutes=10)
    self._last_cleanup_time = current_time
```

**新代码**：
```python
# scheduler/daemon.py
# 一行搞定！
self.scheduler.execute_cleanup_strategies(current_time)
```

**旧的 cleanup.py**：保留作为参考，建议使用 `cleanup_v2.py`

## 🎯 总结

### 核心优势

1. **清晰的职责分离** - 每个策略一个类
2. **统一的接口** - 所有策略遵循相同契约
3. **灵活的配置** - 参数化而非硬编码
4. **自动的调度** - 管理器负责时间管理
5. **优雅的扩展** - 新增策略只需添加类
6. **简化的使用** - 调用方代码极简

### 代码质量提升

- ✅ **可读性**：一目了然，每个类职责单一
- ✅ **可维护性**：修改某个策略不影响其他
- ✅ **可测试性**：每个策略独立测试
- ✅ **可扩展性**：新增策略无需改动现有代码
- ✅ **OOP最佳实践**：继承、多态、封装

这就是**优雅的 OOP 设计**！🎨

