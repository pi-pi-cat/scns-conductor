# 项目文档索引

> 本文档是项目的文档中心，提供所有文档的索引和导航

## 📚 文档分类

### 🏗️ 架构与设计

- **[ARCHITECTURE.md](./ARCHITECTURE.md)** - 系统架构设计
- **[STRUCTURE.md](./STRUCTURE.md)** - 项目结构说明
- **[REDIS_KEYS_REFERENCE.md](./REDIS_KEYS_REFERENCE.md)** - Redis 键值参考

### 🚀 快速开始

- **[INSTALL.md](./INSTALL.md)** - 安装指南
- **[DEPLOYMENT.md](./DEPLOYMENT.md)** - 部署指南
- **[MIGRATION.md](./MIGRATION.md)** - 迁移指南
- **[API_EXAMPLES.md](./API_EXAMPLES.md)** - API 使用示例

### 🔧 Scheduler 重构

> **重要**：所有 Scheduler 重构相关文档都在 `scheduler-refactoring/` 目录下

- **[scheduler-refactoring/](./scheduler-refactoring/README.md)** - Scheduler 重构文档索引
  - **清理策略重构** - `scheduler-refactoring/cleanup-strategies/`
  - **资源管理重构** - `scheduler-refactoring/resource-management/`

### 📊 项目状态

- **[PROJECT_STATUS.md](./PROJECT_STATUS.md)** - 项目当前状态
- **[archive/](./archive/)** - 历史文档归档

## 🎯 文档组织规则

### 文档分类原则

1. **架构与设计文档** - 放在 `docs/` 根目录
2. **Scheduler 重构文档** - 放在 `docs/scheduler-refactoring/` 目录
3. **历史文档** - 放在 `docs/archive/` 目录

### 新增文档规则

为了避免过多 token 消耗，**所有新的重构文档都应该放在 `docs/scheduler-refactoring/` 目录下**：

- 清理策略相关 → `scheduler-refactoring/cleanup-strategies/`
- 资源管理相关 → `scheduler-refactoring/resource-management/`
- 其他 scheduler 相关 → `scheduler-refactoring/` 根目录

## 📖 推荐阅读顺序

### 新用户
1. [INSTALL.md](./INSTALL.md) - 安装项目
2. [ARCHITECTURE.md](./ARCHITECTURE.md) - 了解架构
3. [API_EXAMPLES.md](./API_EXAMPLES.md) - 学习使用

### 开发者
1. [ARCHITECTURE.md](./ARCHITECTURE.md) - 系统架构
2. [scheduler-refactoring/](./scheduler-refactoring/README.md) - 重构文档
3. [PROJECT_STATUS.md](./PROJECT_STATUS.md) - 项目状态

### 重构参与者
1. [scheduler-refactoring/README.md](./scheduler-refactoring/README.md) - 重构文档索引
2. 根据具体任务查看对应的子目录文档

## 🔍 快速查找

### 按主题查找

- **清理策略** → `scheduler-refactoring/cleanup-strategies/`
- **资源管理** → `scheduler-refactoring/resource-management/`
- **API 使用** → `API_EXAMPLES.md`
- **部署运维** → `DEPLOYMENT.md`
- **历史变更** → `archive/`

### 按类型查找

- **设计文档** → `ARCHITECTURE.md`, `STRUCTURE.md`
- **使用指南** → `INSTALL.md`, `API_EXAMPLES.md`
- **重构文档** → `scheduler-refactoring/`
- **历史文档** → `archive/`

## 📝 文档维护

- 所有文档使用 Markdown 格式
- 文档命名使用大写字母和下划线（如 `CLEANUP_STRATEGY_V4.md`）
- 重要文档应在开头包含目录和概述
- 定期归档过时文档到 `archive/` 目录

## 🔗 外部链接

- [项目 GitHub](https://github.com/your-org/scns-conductor)
- [问题反馈](https://github.com/your-org/scns-conductor/issues)

---

**最后更新**: 2024  
**维护者**: 开发团队
