# 文档中心

## 📚 核心文档

| 文档 | 说明 |
|------|------|
| [PROJECT_STATUS.md](PROJECT_STATUS.md) | 📊 项目状态总览 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 🏗️ 系统架构和设计原理 |
| [STRUCTURE.md](STRUCTURE.md) | 📁 项目目录结构详解 |
| [MIGRATION.md](MIGRATION.md) | 🔄 v2.0 迁移指南 |
| [API_EXAMPLES.md](API_EXAMPLES.md) | 💻 API 使用示例 |
| [DEPLOYMENT.md](DEPLOYMENT.md) | 🚀 生产环境部署指南 |
| [INSTALL.md](INSTALL.md) | ⚙️ 安装配置说明 |

## 🏗️ 快速了解架构

### 三层独立服务

```
┌─────────────┐
│ API Server  │  接收作业，创建 PENDING
└──────┬──────┘
       ↓
┌─────────────┐
│  Scheduler  │  调度作业，分配资源，入队
└──────┬──────┘
       ↓
┌─────────────┐
│   Worker    │  执行作业，释放资源
└─────────────┘
```

### 目录结构

```
scns-conductor/
├── scheduler/         # 调度服务
│   ├── main.py
│   ├── scheduler.py
│   └── daemon.py
├── worker/            # Worker 服务
│   ├── main.py
│   └── executor.py
├── shared/            # 共享代码
├── api/               # API 服务
└── core/              # 基础设施
```

### 工作流程

```
1. 用户 → API: 提交作业
2. API → DB: 创建 Job (PENDING)
3. Scheduler: 扫描 PENDING → 分配资源 → Job (RUNNING) → 入队
4. Worker: 从队列取任务 → 执行 → 更新状态 → 释放资源
```

## 🚀 快速开始

```bash
# 启动基础设施
make dev-infra

# 启动服务（3个终端）
make dev-scheduler
make dev-worker
make dev-api
```

## 📦 历史文档

所有历史文档（重构记录、改进报告等）已移至 `archive/` 目录。

## 📞 获取帮助

1. 先查看 [ARCHITECTURE.md](ARCHITECTURE.md) 了解系统设计
2. 参考 [API_EXAMPLES.md](API_EXAMPLES.md) 学习使用
3. 遇到问题查看 [MIGRATION.md](MIGRATION.md) 的常见问题

---

**文档版本**: v2.0  
**更新日期**: 2025-11-11
