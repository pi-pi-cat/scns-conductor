# macOS Fork 安全性修复

## 问题描述

在 macOS 上运行 Worker 时，遇到以下错误：

```
objc[80224]: +[__NSCFConstantString initialize] may have been in progress in another thread when fork() was called.
objc[80224]: +[__NSCFConstantString initialize] may have been in progress in another thread when fork() was called. 
We cannot safely call it or ignore it in the fork() child process. Crashing instead.
14:06:52 Moving job to FailedJobRegistry (Work-horse terminated unexpectedly; waitpid returned 6 (signal 6); )
```

## 问题根源

这是一个 macOS 特有的问题：

1. **RQ 的 fork 机制**：RQ (Redis Queue) 默认使用 `os.fork()` 创建子进程来执行任务
2. **Objective-C 运行时冲突**：在 macOS 上，如果主进程中已经初始化了某些 Objective-C 对象（如 NSString），fork 后会导致子进程状态不一致
3. **数据库连接问题**：SQLAlchemy 可能会触发 Objective-C 运行时的初始化，导致 fork 后的子进程崩溃

## 解决方案

采用了两层防护措施：

### 方案 1：环境变量（快速修复）

在 `worker/main.py` 中添加：

```python
# macOS fork 安全性设置 - 必须在任何其他导入之前
if sys.platform == "darwin":
    os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
```

**优点**：简单快速
**缺点**：禁用了安全检查，可能隐藏潜在问题

### 方案 2：延迟数据库初始化（推荐）

#### 修改 `worker/main.py`

不在主进程中初始化数据库连接，而是延迟到 fork 后的子进程中：

```python
def main():
    # ...
    
    # 注意：不在主进程中初始化数据库
    # 数据库连接将在 fork 后的子进程中初始化
    logger.info("✓ Database initialization deferred to worker processes")
    
    # 初始化 Redis（Redis 连接可以安全地被 fork）
    redis_manager.init()
    
    # ...
```

#### 修改 `worker/executor.py`

在子进程首次访问数据库时才初始化连接：

```python
def _load_job(self, job_id: int) -> Job:
    """
    加载作业信息
    
    注意：这是在 RQ fork 后的子进程中首次访问数据库
    需要确保数据库连接已初始化
    """
    # 确保数据库已初始化（在 fork 后的子进程中）
    if not sync_db.is_initialized():
        logger.info("Initializing database connection in worker process")
        sync_db.init()
    
    with sync_db.get_session() as session:
        # ...
```

**优点**：
- 真正解决了 fork 安全问题
- 每个子进程有独立的数据库连接
- 不会隐藏潜在问题

**缺点**：
- 需要修改代码逻辑
- 每个子进程都需要建立数据库连接（但这是正确的做法）

## 技术细节

### 为什么 Redis 可以 fork，数据库不行？

1. **Redis 连接**：使用简单的 socket 连接，fork 后可以继续使用（虽然不推荐）
2. **数据库连接**：
   - 使用复杂的连接池
   - 可能触发 Objective-C 运行时初始化
   - 连接状态在 fork 后可能不一致

### 为什么只影响 macOS？

- macOS 使用 Objective-C 运行时
- Linux 不使用 Objective-C，没有这个问题
- 这是 Apple 在 macOS High Sierra (10.13) 中引入的安全检查

## 相关资源

- [Python Multiprocessing and macOS](https://github.com/ansible/ansible/issues/76322)
- [RQ Documentation - Workers](https://python-rq.org/docs/workers/)
- [SQLAlchemy FAQ - Connection Pooling](https://docs.sqlalchemy.org/en/14/core/pooling.html#using-connection-pools-with-multiprocessing)

## 测试验证

修复后，Worker 应该能够正常执行任务，不再出现 fork 相关的崩溃。

```bash
# 启动 worker
python -m worker.main

# 提交测试任务
# 观察日志应该看到：
# "Initializing database connection in worker process"
```

## 日期

2025-11-11

