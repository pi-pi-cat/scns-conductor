# 重构说明文档

## 📋 关键设计决策说明

### 1. 脚本生成与执行策略 ✅

**最终决策：在 API 层接收完整脚本，Worker 直接执行**

#### 方案对比

| 维度 | API生成脚本 | Worker生成脚本 | **当前方案（用户提供脚本）** |
|------|------------|---------------|---------------------------|
| **灵活性** | 受限于模板 | 受限于模板 | ✅ 完全灵活 |
| **可维护性** | 需维护模板 | 需维护模板 | ✅ 无需维护模板 |
| **可审计性** | 中等 | 中等 | ✅ 完整脚本可追溯 |
| **复杂度** | 高 | 高 | ✅ 低（关注点分离） |
| **用户体验** | 受限 | 受限 | ✅ 自由度高 |

#### 实现流程

```
User
  │
  │ 1. 提交完整脚本（bash/python/any）
  ▼
API Service
  │
  │ 2. 验证脚本（非空检查）
  │ 3. 存储到数据库 jobs.script
  │ 4. 返回 job_id
  ▼
PostgreSQL
  │
  │ 调度器检测到 PENDING 作业
  ▼
Worker Scheduler
  │
  │ 5. 分配资源
  │ 6. 更新状态为 RUNNING
  ▼
Worker Executor
  │
  │ 7. 从数据库读取 job.script
  │ 8. 写入临时文件 /var/scns-conductor/scripts/job_{id}.sh
  │ 9. 执行：bash job_{id}.sh
  │ 10. 收集输出和退出码
  ▼
Update Database
  │
  └─> 完成（COMPLETED/FAILED）
```

#### 代码示例

```python
# API 层：只负责接收和存储
@router.post("/jobs/submit")
async def submit_job(request: JobSubmitRequest, db: AsyncSession):
    job = Job(
        script=request.script,  # 用户提供的完整脚本
        # ... 其他字段
    )
    db.add(job)
    await db.commit()
    return {"job_id": job.id}

# Worker 层：只负责执行
class JobExecutor:
    def _run_job(self, job: Job):
        # 1. 写脚本到文件
        script_path = f"/var/scns-conductor/scripts/job_{job.id}.sh"
        with open(script_path, 'w') as f:
            f.write(job.script)  # 直接使用数据库中的脚本
        
        # 2. 执行
        process = subprocess.Popen(['/bin/bash', script_path], ...)
        exit_code = process.wait()
        
        return exit_code
```

---

### 2. Worker 数据库访问 ✅

**结论：Worker 必须直接访问数据库**

#### 必要原因

1. **状态更新**
   - PENDING → RUNNING（调度器）
   - RUNNING → COMPLETED/FAILED（执行器）
   - 记录时间戳（start_time, end_time）

2. **资源管理**
   - 查询可用资源
   - 创建/释放资源分配记录
   - 维护资源跟踪器的一致性

3. **调度逻辑**
   - 查询 PENDING 作业（按提交时间排序）
   - 检查资源约束
   - 分配资源并更新状态

4. **性能考虑**
   - 直接数据库访问避免网络往返
   - 减少 API 层压力
   - 支持事务一致性

#### 架构图

```
┌─────────────┐
│   API       │ - 接收用户请求
│  (FastAPI)  │ - 验证数据
└──────┬──────┘ - 返回响应
       │
       │ 异步写入
       ▼
┌─────────────┐
│ PostgreSQL  │ ◄──────┐
│  (持久化)    │        │ 同步读写
└──────┬──────┘        │
       │               │
       └───────────────┤
                       │
                ┌──────┴──────┐
                │   Worker    │ - 查询 PENDING 作业
                │  (RQ + 调度) │ - 更新作业状态
                └─────────────┘ - 管理资源分配
```

---

### 3. SQLModel vs SQLAlchemy ✅

**最终选择：SQLModel**

#### SQLModel 优势

```python
# ✅ SQLModel：一个类同时作为 ORM 模型和 Pydantic 模型
from sqlmodel import SQLModel, Field

class Job(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True, description="作业ID")
    name: str = Field(max_length=255, description="作业名称")
    state: JobState = Field(default=JobState.PENDING, description="作业状态")
    
    # 既是数据库模型，也可以直接序列化为 JSON
    # 类型安全，自动验证
```

vs

```python
# ❌ 传统 SQLAlchemy：需要分别定义 ORM 和 Pydantic
# ORM 模型
class JobDB(Base):
    __tablename__ = "jobs"
    id = Column(Integer, primary_key=True)
    name = Column(String(255))
    state = Column(Enum(JobState))

# Pydantic 模型（用于 API）
class JobSchema(BaseModel):
    id: int
    name: str
    state: JobState
    
    class Config:
        from_attributes = True

# 需要手动转换
job_db = JobDB(name="test")
job_schema = JobSchema.from_orm(job_db)
```

#### 对比表

| 特性 | SQLAlchemy 2.0 | **SQLModel** |
|------|----------------|--------------|
| 代码简洁性 | 需要双模型 | ✅ 单一模型 |
| 类型安全 | 部分支持 | ✅ 完全支持 |
| FastAPI 集成 | 需手动转换 | ✅ 原生支持 |
| 数据验证 | 需额外代码 | ✅ 自动验证 |
| 学习曲线 | 较陡 | ✅ 平缓 |
| 成熟度 | 非常成熟 | 相对较新但稳定 |
| 复杂查询 | 功能完整 | 基于 SQLAlchemy，功能相同 |

#### 迁移示例

```python
# 旧代码（SQLAlchemy）
from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class Job(Base):
    __tablename__ = "jobs"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)

# 新代码（SQLModel）
from sqlmodel import SQLModel, Field

class Job(SQLModel, table=True):
    __tablename__ = "jobs"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=255)
```

---

### 4. 中文注释与文档字符串 ✅

**全面使用中文提升可读性**

#### 示例对比

```python
# ❌ 之前（英文）
class Job(SQLModel, table=True):
    """Job table - stores all job information"""
    
    id: Optional[int] = Field(description="Job ID")
    state: JobState = Field(description="Job state")
    
    @property
    def total_cpus_required(self) -> int:
        """Calculate total CPU cores required"""
        return self.ntasks_per_node * self.cpus_per_task

# ✅ 现在（中文）
class Job(SQLModel, table=True):
    """作业表 - 存储所有作业信息"""
    
    id: Optional[int] = Field(description="作业ID")
    state: JobState = Field(description="作业状态")
    
    @property
    def total_cpus_required(self) -> int:
        """计算所需的总CPU核心数"""
        return self.ntasks_per_node * self.cpus_per_task
```

---

## 🔧 技术栈更新

### 依赖变更

```diff
# requirements.txt

- sqlalchemy==2.0.23
+ sqlmodel==0.0.14  # 包含 SQLAlchemy 2.0 + Pydantic 集成
  asyncpg==0.29.0
  psycopg2-binary==2.9.9
```

### 核心模块更新

| 模块 | 变更 | 影响 |
|------|------|------|
| `core/models.py` | SQLAlchemy → SQLModel | ✅ 代码更简洁，类型更安全 |
| `core/database.py` | `Base` → `SQLModel` | ✅ 元数据管理统一 |
| `migrations/env.py` | 导入更新 | ✅ Alembic 兼容 |
| 所有文件 | 注释中文化 | ✅ 可读性提升 |

---

## 📊 性能影响

### SQLModel 性能

- **底层仍是 SQLAlchemy 2.0**，性能完全相同
- **额外的 Pydantic 验证**在数据插入时有轻微开销（< 1ms）
- **类型检查**在开发阶段完成，运行时无影响

### 数据库访问模式

```python
# Worker 直接访问数据库（同步）
with sync_db.get_session() as session:
    job = session.query(Job).filter(Job.id == job_id).first()
    job.state = JobState.RUNNING
    session.commit()

# 性能优势：
# - 本地事务，无网络延迟
# - 连接池复用
# - 批量更新支持
```

---

## ✅ 最佳实践总结

### 1. 关注点分离

```
API 层     →  接收请求、验证数据、返回响应
Service 层 →  业务逻辑、编排操作
Worker 层  →  执行作业、更新状态
Database   →  数据持久化、事务保证
```

### 2. 数据流向

```
用户脚本
  ↓
API 验证并存储
  ↓
数据库（权威源）
  ↓
Worker 读取并执行
  ↓
结果写回数据库
  ↓
API 查询返回用户
```

### 3. 类型安全

```python
# SQLModel 提供端到端类型安全
async def submit_job(request: JobSubmitRequest) -> JobSubmitResponse:
    job = Job(**request.job.dict())  # Pydantic 验证
    # ... 数据库操作
    return JobSubmitResponse(job_id=str(job.id))  # 类型检查
```

---

## 🚀 升级指南

### 对现有部署的影响

1. **数据库兼容性**：✅ 完全兼容，表结构无变化
2. **API 兼容性**：✅ 接口定义不变
3. **依赖更新**：需要重新安装依赖

### 升级步骤

```bash
# 1. 更新代码
git pull

# 2. 更新依赖
pip install -r requirements.txt

# 3. 重启服务
docker-compose restart api
docker-compose restart worker

# 4. 验证
python scripts/health_check.py
```

---

## 📚 参考资料

- [SQLModel 官方文档](https://sqlmodel.tiangolo.com/)
- [SQLAlchemy 2.0 文档](https://docs.sqlalchemy.org/en/20/)
- [FastAPI 最佳实践](https://fastapi.tiangolo.com/tutorial/)

---

**更新日期**: 2025-11-07  
**版本**: v1.0.1

