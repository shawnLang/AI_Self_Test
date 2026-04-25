# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

AI 自检平台 — 全栈应用，后端 FastAPI + SQLite/SQLModel，前端 React 19 + TypeScript + Vite + Tailwind CSS v4。

## 常用命令

### 后端

```bash
# 启动开发服务器 (端口 3001)
cd aiSelfTest && python run.py
# 或
aiSelfTest

# 运行全部测试 (在仓库根目录)
pytest

# 运行单个测试文件
pytest tests/test_config_api.py

# 运行指定测试函数
pytest tests/test_config_api.py::test_create_config_and_get_detail

# 创建数据库迁移 (修改 models 后)
cd aiSelfTest && alembic revision --autogenerate -m "描述"
cd aiSelfTest && alembic upgrade head

# 打包 (Cython 编译)
cd aiSelfTest && python setup.py build_ext --inplace
```

### 前端

```bash
cd aiSelfTestUi

npm run dev          # 开发服务器 (端口 3000, 代理 /api → localhost:3001)
npm run build        # 构建产物输出到 ../aiSelfTest/aiSelfTest/static
npm run lint         # TypeScript 类型检查 (tsc --noEmit)
npm run clean        # 删除构建产物目录
```

## 架构概览

### 后端分层 (aiSelfTest/aiSelfTest/)

```
api/        → FastAPI 路由层，只做参数接收和响应包装，不含业务逻辑
services/   → 业务逻辑层，操作数据库、调用外部 API
schemas/    → Pydantic 请求/响应模型，所有 API 的 data 字段必须为 BaseModel
models/     → SQLModel 数据库表定义
```

路由注册在 `main.py` 的 `create_app()` 中，所有路由统一挂载在 `/api` 前缀下，模块内部再各自追加 prefix（如 `prefix="/configs"`）。

### 前端 (aiSelfTestUi/src/)

单页应用，`App.tsx` 通过侧边栏切换视图，每个页面是一个独立组件（`components/*.tsx`）。API 调用通过 `utils/api.ts` 中的 `fetchApi<T>()` 封装，自动解包 `{code, message, data}` 并在 code≠0 时抛出异常。

### 关键文件

- `aiSelfTest/main.py:92` — FastAPI app 实例创建
- `aiSelfTest/config.py:34` — 全局配置（数据目录、数据库路径），通过 `AI_SELF_TEST_DATA_DIR` 环境变量控制
- `aiSelfTest/database.py` — 数据库引擎和会话管理（同步+异步），SQLite + WAL 模式
- `aiSelfTest/exceptions.py:11` — `AppException` 统一业务异常，code/message/status_code 三元组
- `aiSelfTest/schemas/common.py:13` — `ApiResponse[DataT]` 泛型响应模型

### 数据库模型关系

- `Client` — 上游 API 客户端配置（含认证令牌缓存）
- `Config` — 模型提示词配置（name/text/format）
- `MultimodalModel` — 多模态模型网关配置 → `MultimodalChatSession` → `MultimodalChatMessage`
- `Task` — 任务（关联 Client + Config）→ `TaskItem` → `TaskItemData`

## 开发规范要点

全部规范见 `AGENTS.md`，本节仅强调经常被遗漏的规则：

- **API 路由**：禁止空路径或纯动态参数路由（如 `@router.get("/{id}")`），必须使用 `/list`、`/detail/{id}`、`/update/{id}` 等命名路径
- **日志**：统一使用 `loguru`（`from loguru import logger`）
- **API 响应**：全部使用统一格式 `{code: 0, message: "success", data: {...}}`，data 必须为 Pydantic BaseModel
- **错误码**：0=成功, 1001=参数错误, 1002=资源不存在, 2001=认证失败, 5001=服务器内部错误
- **接口参数**：参数 ≥2 个时必须用 Pydantic BaseModel 接收，不得逐个声明为查询参数
- **测试清理**：`pytest` 运行后需清理 `.pytest_tmp/` 和根目录的 `pytest-cache-files-*`

## 测试

- 测试文件放在仓库根目录 `tests/`
- `conftest.py` 提供 `app_client` fixture，为每个测试创建独立的临时数据目录和 SQLite 数据库
- 使用 FastAPI `TestClient` 做端到端接口测试
- TDD 流程：先写 `Test.md`（测试方案）→ 再写测试用例 → 再写实现代码

## 前端构建与后端集成

前端 `npm run build` 将产物输出到 `aiSelfTest/aiSelfTest/static/`，后端直接作为静态文件服务。开发时前端 dev server（5173/3000）通过 Vite proxy 转发 `/api` 请求到后端 3001 端口。