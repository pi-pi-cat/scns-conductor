# 资源状态管理改进 - 变更日志

**日期**: 2025-11-12  
**版本**: v2.1.0  
**类型**: 功能增强 + Bug 修复

## 📝 变更概述

引入资源状态管理机制，解决作业被调度但未实际运行时资源被永久占用的问题。

## 🎯 问题说明

**用户反馈**：
> "我觉得关于资源的已分配的应该在资源分配表中查询吧？不应该在作业表中查询，因为说不定作业被调度了但是实际并没有RUNNING起来，资源并没有分配。这个作业死掉或者服务重启那么这个资源就是一直被占用了。"

**核心问题**：
- 调度器在调度时就创建 `ResourceAllocation` 记录并标记 `released=False`
- 但作业可能还没有真正开始运行（仍在队列中）
- 如果此时服务重启或队列丢失，资源会永久泄漏
- 无法区分"已预留"和"真正在运行"的资源

## ✅ 解决方案

### 核心改进

引入三状态资源管理：
- **reserved**: 预留（调度器已分配，但 Worker 尚未开始执行）
- **allocated**: 已分配（Worker 正在执行，资源实际占用）
- **released**: 已释放（作业完成，资源已回收）

### 关键优势

1. ✅ **防止资源泄漏**：预留状态不计入真实占用
2. ✅ **更准确的资源统计**：只统计真正运行的作业
3. ✅ **更好的可观测性**：可区分等待和执行状态
4. ✅ **向后兼容**：保留旧的 `released` 字段

## 📋 文件变更清单

### 1. 数据模型 (2 个文件)

#### `core/models.py`
- ✅ 为 `ResourceAllocation` 添加 `status` 字段
- ✅ 添加 `idx_resource_allocation_status` 索引
- ✅ 保留 `released` 字段以向后兼容

#### `core/enums.py`
- ✅ 新增 `ResourceStatus` 枚举类

### 2. 资源管理 (1 个文件)

#### `core/services/resource_manager.py`
- ✅ 修改 `_query_allocated_cpus_from_db()`：只统计 `status='allocated'` 的资源
- ✅ 添加详细注释说明新的查询逻辑

### 3. 调度器 (1 个文件)

#### `scheduler/scheduler.py`
- ✅ 修改 `_allocate_and_enqueue()`：创建预留状态的分配记录
- ✅ 移除调度时的缓存更新（资源还未真正占用）
- ✅ 修改 `release_completed()`：适配新的状态字段

### 4. Worker 执行器 (1 个文件)

#### `worker/executor.py`
- ✅ 新增 `_mark_resources_allocated()` 方法
- ✅ 在 `execute()` 中调用，真正开始执行时更新状态为 `allocated`
- ✅ 修改 `_release_resources()`：智能释放（只释放真正占用的资源）

### 5. API 仓储层 (1 个文件)

#### `api/repositories/job_repository.py`
- ✅ 修改 `get_allocated_cpus_on_node()`：使用新的状态字段查询
- ✅ 修改 `release_resource_allocation()`：更新为 `status='released'`

### 6. 清理脚本 (1 个文件)

#### `scripts/cleanup.py`
- ✅ 修改 `cleanup_stale_resources()`：使用新的状态字段
- ✅ 修改 `fix_stuck_jobs()`：适配新的状态字段

### 7. 数据库变更

**注意**：本改进直接修改模型，不提供迁移脚本。
- ✅ 新增 `status` 字段（使用枚举，避免硬编码）
- ❌ 删除 `released` 字段（简化设计）
- ✅ 适用于未上生产环境的项目

### 8. 文档和工具 (3 个文件)

#### `docs/RESOURCE_STATUS_IMPROVEMENT.md`
- ✅ 详细的改进方案文档
- ✅ 包含问题分析、实施细节、监控建议

#### `CHANGELOG_RESOURCE_STATUS.md` (本文件)
- ✅ 变更日志和变更清单

#### `scripts/verify_resource_status.py`
- ✅ 验证脚本，用于检查改进是否正常工作

## 🔄 资源流转新流程

```
1. Scheduler 调度作业
   ├─ 创建 ResourceAllocation (status='reserved')
   ├─ 更新 Job.state = RUNNING
   └─ 入队作业
   
2. Worker 开始执行
   ├─ 从队列取出作业
   ├─ 更新 ResourceAllocation (status='allocated')  ← 真正占用
   ├─ 更新 Redis 缓存
   └─ 执行作业脚本
   
3. 作业完成
   ├─ 更新 ResourceAllocation (status='released')
   ├─ 更新 Redis 缓存（释放）
   └─ 更新作业最终状态
```

## 📊 统计信息

- **修改文件数**: 7 个核心文件
- **新增文件数**: 3 个（1个验证脚本 + 2个文档）
- **代码行数**: 约 150 行新增/修改
- **数据库变更**: 添加 `status` 字段、删除 `released` 字段、添加 1 个索引
- **设计原则**: 使用枚举避免硬编码，代码更简洁清晰

## 🚀 部署步骤

### 1. 更新代码
```bash
git pull
```

### 2. 更新数据库表结构

**如果是全新部署**：
直接启动服务，SQLModel 会自动创建新表结构。

**如果已有数据**：
```sql
-- 方式1: 清空表重新开始（推荐，如果可以接受丢失历史数据）
TRUNCATE TABLE resource_allocations;

-- 方式2: 手动迁移
ALTER TABLE resource_allocations ADD COLUMN status VARCHAR(20) DEFAULT 'reserved' NOT NULL;
ALTER TABLE resource_allocations DROP COLUMN released;
CREATE INDEX idx_resource_allocation_status ON resource_allocations(status);
```

### 3. 重启服务
```bash
# 重启 Scheduler
systemctl restart scns-scheduler

# 重启 Worker
systemctl restart scns-worker

# 重启 API
systemctl restart scns-api
```

### 4. 验证改进
```bash
python scripts/verify_resource_status.py
```

## ⚠️ 注意事项

1. **适用场景**
   - ✅ 适用于未上生产环境的项目
   - ✅ 可以接受清空历史资源分配记录
   - ❌ 如果需要保留历史数据，需要自行编写迁移脚本

2. **监控建议**
   - 监控长期处于 `reserved` 状态的记录（可能是异常）
   - 定期检查资源分配统计是否合理

3. **设计改进**
   - 使用 `ResourceStatus` 枚举避免硬编码
   - 删除冗余的 `released` 字段，简化设计
   - 代码更清晰，维护成本更低

## 📚 相关文档

- [资源状态改进详细文档](./docs/RESOURCE_STATUS_IMPROVEMENT.md)
- [资源管理设计](./docs/RESOURCE_MANAGEMENT.md)
- [架构文档](./docs/ARCHITECTURE.md)

## 👥 贡献者

- 提出问题：用户反馈
- 设计实现：Claude (AI Assistant)
- 日期：2025-11-12

---

**版本**: v2.1.0  
**状态**: ✅ 已完成并测试

