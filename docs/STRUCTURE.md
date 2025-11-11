# 项目结构 v2.0

```
scns-conductor/
│
├── 📁 scheduler/              # 调度服务（独立）
│   ├── __init__.py
│   ├── main.py               # 入口：启动调度守护进程
│   ├── scheduler.py          # 核心：FIFO + First Fit 调度算法
│   └── daemon.py             # 守护进程：周期性执行调度
│
├── 📁 worker/                 # Worker 服务（独立）
│   ├── __init__.py
│   ├── main.py               # 入口：启动 RQ Worker
│   └── executor.py           # 核心：执行作业脚本
│
├── 📁 shared/                 # 共享代码
│   ├── __init__.py
│   ├── resource_manager.py   # 资源管理器（单例，线程安全）
│   └── process_utils.py      # 进程管理工具
│
├── 📁 api/                    # API 服务（保持不变）
│   ├── main.py
│   ├── routers/
│   ├── services/
│   └── schemas/
│
├── 📁 core/                   # 核心基础设施（保持不变）
│   ├── config.py             # 配置管理
│   ├── database.py           # 数据库连接
│   ├── redis_client.py       # Redis 连接
│   ├── models.py             # 数据模型
│   ├── enums.py              # 枚举类型
│   └── utils/
│
├── 📁 docs/                   # 文档
│   ├── README.md             # 文档索引
│   ├── ARCHITECTURE.md       # 架构说明
│   ├── API.md                # API 文档
│   └── DEPLOYMENT.md         # 部署指南
│
├── 📁 scripts/                # 工具脚本
│   ├── init_db.py
│   └── health_check.py
│
├── 📁 migrations/             # 数据库迁移
│
├── 📄 README.md               # 项目主文档
├── 📄 MIGRATION.md            # 迁移指南
├── 📄 STRUCTURE.md            # 本文件
├── 📄 Makefile                # 快捷命令
├── 📄 docker-compose.yml      # Docker 编排
├── 📄 app.properties          # 配置文件
├── 📄 requirements.txt        # Python 依赖
└── 📄 requirements-dev.txt    # 开发依赖
```

## 📦 模块职责

### Scheduler 服务

| 文件 | 职责 | 行数 |
|------|------|------|
| `scheduler/main.py` | 服务入口，初始化和启动 | ~100 |
| `scheduler/scheduler.py` | 调度算法实现 | ~150 |
| `scheduler/daemon.py` | 守护进程循环 | ~50 |

**总行数**: ~300 行（简洁）

### Worker 服务

| 文件 | 职责 | 行数 |
|------|------|------|
| `worker/main.py` | 服务入口，RQ Worker | ~80 |
| `worker/executor.py` | 作业执行逻辑 | ~180 |

**总行数**: ~260 行（简洁）

### 共享模块

| 文件 | 职责 | 行数 |
|------|------|------|
| `shared/resource_manager.py` | CPU 资源管理 | ~80 |
| `shared/process_utils.py` | 进程管理工具 | ~40 |

**总行数**: ~120 行（精简）

## 🔄 数据流

### 作业提交流程

```
Client
  │
  ▼
API (api/services/job_service.py)
  │ ① 创建 Job (PENDING)
  ▼
Database (PostgreSQL)
  │
  ▼
Scheduler (scheduler/scheduler.py)
  │ ② 扫描 PENDING
  │ ③ 检查资源 (shared/resource_manager.py)
  │ ④ 分配资源
  │ ⑤ 更新状态 (RUNNING)
  │ ⑥ 入队
  ▼
Redis Queue
  │
  ▼
Worker (worker/executor.py)
  │ ⑦ 执行脚本
  │ ⑧ 更新状态 (COMPLETED/FAILED)
  │ ⑨ 释放资源
  ▼
Database
```

## 🧩 依赖关系

### Scheduler 依赖

```
scheduler/
  ├─→ core/ (config, database, redis, models)
  └─→ shared/ (resource_manager)
```

### Worker 依赖

```
worker/
  ├─→ core/ (config, database, models)
  └─→ shared/ (resource_manager, process_utils)
```

### API 依赖

```
api/
  └─→ core/ (config, database, redis, models)
```

### 无循环依赖 ✅

## 📊 代码统计

| 类型 | 旧版 | 新版 | 改进 |
|------|------|------|------|
| **Scheduler** | ~600 行 | ~300 行 | ✅ -50% |
| **Worker** | ~400 行 | ~260 行 | ✅ -35% |
| **共享代码** | ~300 行 | ~120 行 | ✅ -60% |
| **文档** | 15+ 文件 | 5 文件 | ✅ -67% |
| **总复杂度** | 高 | 低 | ✅ 大幅降低 |

## 🎯 设计原则

### 1. 单一职责
- Scheduler 只管调度
- Worker 只管执行
- API 只管接口

### 2. 松耦合
- 服务间通过数据库和队列通信
- 无直接依赖

### 3. 高内聚
- 相关代码放在同一目录
- 清晰的模块边界

### 4. 简洁性
- 移除冗余代码
- 保持函数简短
- 清晰的命名

## 🔧 扩展指南

### 添加新的调度策略

在 `scheduler/scheduler.py` 中修改 `schedule()` 方法：

```python
def schedule(self) -> int:
    # 修改查询条件或排序方式
    pending_jobs = (
        session.query(Job)
        .filter(Job.state == JobState.PENDING)
        .order_by(Job.priority.desc(), Job.submit_time)  # 优先级优先
        .all()
    )
```

### 添加新的执行逻辑

在 `worker/executor.py` 中修改 `_run()` 方法：

```python
def _run(self, job: Job) -> int:
    # 添加前置检查
    if not self._validate_job(job):
        return -1
    
    # 执行脚本
    ...
```

### 添加共享工具

在 `shared/` 中创建新文件：

```python
# shared/new_utils.py
def new_utility():
    pass
```

## 📝 命名规范

### 目录命名
- 小写，单数形式
- 使用下划线分隔：`resource_manager.py`

### 类命名
- 大驼峰：`JobScheduler`, `ResourceManager`

### 函数命名
- 小写，下划线分隔：`schedule()`, `execute_job()`
- 私有方法前缀 `_`：`_run()`, `_load_job()`

### 常量命名
- 全大写：`TOTAL_CPUS`, `CHECK_INTERVAL`

## 🎉 总结

新架构的核心优势：

1. ✅ **清晰的目录结构** - 一眼就能看懂
2. ✅ **独立的服务** - 可分别开发和部署
3. ✅ **简洁的代码** - 易于维护
4. ✅ **无历史包袱** - 从零开始设计

---

**版本**: v2.0  
**日期**: 2025-11-10

