# 设计决策文档

本文档解释了 SCNS-Conductor 项目中的关键设计决策。

## 问题1：脚本应该在哪里生成？

### ❓ 问题描述
作业执行最终需要一个 bash 脚本。有两种方案：
1. **API 端生成**：根据参数生成脚本 → 传给 Worker 执行
2. **Worker 端生成**：接收参数 → Worker 生成脚本 → 执行

### ✅ 最终决策：用户提供完整脚本，API 存储，Worker 执行

### 理由
1. **最大灵活性**：用户可以提交任意复杂的脚本，不受模板限制
2. **关注点分离**：
   - API：负责接收、验证、存储
   - Worker：负责执行
3. **可审计性**：完整脚本存储在数据库，便于追溯和重现
4. **简化维护**：无需维护脚本模板
5. **类似 Slurm**：Slurm 也是用户提交完整脚本

### 实现方式
```python
# 用户提交
{
  "job": { ... },
  "script": "#!/bin/bash\necho 'Hello'\npython train.py\n"
}

# Worker 执行
def execute_job(job_id):
    job = db.query(Job).get(job_id)
    with open(f"job_{job_id}.sh", 'w') as f:
        f.write(job.script)  # 直接使用数据库中的脚本
    subprocess.run(["/bin/bash", f"job_{job_id}.sh"])
```

---

## 问题2：Worker 需要操作数据库吗？

### ❓ 问题描述
Worker 是否应该直接访问数据库，还是通过 API？

### ✅ 最终决策：Worker 必须直接访问数据库

### 理由
1. **状态更新**：需要频繁更新作业状态（PENDING → RUNNING → COMPLETED）
2. **调度需求**：调度器需要查询 PENDING 作业
3. **资源管理**：需要原子性地分配和释放资源
4. **性能考虑**：直接数据库访问避免网络往返
5. **事务保证**：资源分配需要数据库事务支持

### 架构说明
```
┌─────────┐         ┌──────────────┐
│   API   │────────▶│  PostgreSQL  │
└─────────┘         └───────┬──────┘
                            │
                            ▼
                    ┌───────────────┐
                    │    Worker     │
                    │ - 查询 PENDING │
                    │ - 更新状态    │
                    │ - 管理资源    │
                    └───────────────┘
```

---

## 问题3：为什么选择 SQLModel 而不是 SQLAlchemy？

### ❓ 问题描述
数据库 ORM 框架的选择

### ✅ 最终决策：使用 SQLModel

### 对比

| 方面 | SQLAlchemy | SQLModel |
|------|------------|----------|
| 代码量 | 需要双模型（ORM + Pydantic） | ✅ 单一模型 |
| 类型安全 | 部分支持 | ✅ 完全类型安全 |
| FastAPI 集成 | 需手动转换 | ✅ 原生支持 |
| 学习曲线 | 较陡 | ✅ 更平缓 |
| 成熟度 | 非常成熟 | 相对较新但稳定 |

### 示例对比

**SQLAlchemy 传统方式**：
```python
# ORM 模型
class JobDB(Base):
    __tablename__ = "jobs"
    id = Column(Integer, primary_key=True)
    name = Column(String(255))

# Pydantic 模型（API 用）
class JobSchema(BaseModel):
    id: int
    name: str

# 需要手动转换
job_schema = JobSchema.from_orm(job_db)
```

**SQLModel 方式**：
```python
# 一个类，两用
class Job(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=255)

# 直接使用，自动验证和序列化
```

### 优势
1. **减少 50% 代码量**：不需要重复定义模型
2. **类型安全**：mypy 可以检查所有数据库操作
3. **自动验证**：Pydantic 验证在插入/更新时自动触发
4. **FastAPI 集成**：无缝集成，无需手动转换

---

## 问题4：为什么使用中文注释？

### ✅ 最终决策：全面使用中文注释和文档字符串

### 理由
1. **团队语言**：团队主要使用中文交流
2. **可读性**：中文注释更直观，减少理解成本
3. **维护效率**：新人更容易上手
4. **业务术语**：某些业务概念用中文更准确

### 示例
```python
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

## 其他重要设计决策

### 异步 + 同步双架构

**问题**：为什么同时使用异步和同步？

**答案**：
- **API 服务**：使用异步（FastAPI + asyncpg）实现高并发
- **Worker 服务**：使用同步（RQ 不支持异步）

这样可以各取所长，充分利用两种模式的优势。

### FIFO + First Fit 调度

**问题**：为什么选择这个调度算法？

**答案**：
1. **简单可靠**：易于实现和维护
2. **公平性**：FIFO 保证先来先服务
3. **资源利用**：First Fit 提高资源利用率
4. **单节点场景**：适合当前单节点部署

### PostgreSQL 作为唯一真相源

**问题**：为什么不用 Redis 存储状态？

**答案**：
1. **持久化**：PostgreSQL 保证数据不丢失
2. **事务支持**：需要原子性操作
3. **复杂查询**：支持复杂的调度查询
4. **Redis 角色**：仅作临时消息队列

---

**文档版本**: v1.0.1  
**最后更新**: 2025-11-07
