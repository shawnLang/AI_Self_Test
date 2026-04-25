# 项目改进建议落实 Test.md

## 本轮目标

本轮按 `docs/项目改进建议.md` 的推荐顺序，处理后端排雷项与剩余结构性改进：

- 删除未使用的异步数据库会话死代码，并修正同步会话说明。
- 将 CORS 允许源改为环境变量可配置，默认保留本地开发地址。
- 让 `X-Request-ID` 同时写入响应头和日志上下文。
- 避免在 `Session.exec()` 中执行 SQLAlchemy Core `delete()`。
- 为现有路由补充 OpenAPI tags。
- 增加 `.env.example`，说明可配置环境变量。
- 拆分 `services/multimodal_model.py`，按 CRUD、聊天、网关、附件职责分层。
- 将启动建表改为 Alembic 迁移，避免 `create_all` 与迁移双轨。
- 引入集中 `ErrorCode`，减少业务错误码魔法数字。
- 优先从 Pydantic 字段描述生成验证错误中文名，硬编码映射只做兜底。
- 将客户端认证缓存写入 `auth_header_style` 与 `working_url_path`。
- 将 token 过期字段从 `expires_in` 迁移为绝对时间戳 `expires_at`。
- 补齐 task、dashboard、流式聊天和认证缓存相关测试。
- 完善前端 `utils/api.ts`，支持超时、默认 JSON 请求头、取消信号和 `ApiError`。
- 引入 TanStack Query，并抽取聊天与复核 API / hooks，降低大组件职责。

## 清理计划

1. 后端先写测试，再按数据模型、迁移、服务层、路由启动顺序改造。
2. 多模态服务先机械拆分，保持原有函数名从聚合模块导出，避免改动 API 路由。
3. 认证改造保留旧响应字段别名 `expiresIn`，内部字段改为 `expires_at`。
4. 前端先补 API 基础设施，再接入 QueryClient 和局部 hooks，不改视觉样式。
5. 每批改完运行相关测试，最后执行后端 pytest 全量与前端 typecheck/build。

## 验收标准

- 默认 CORS 源包含 `http://localhost:5173` 和 `http://localhost:3000`。
- 设置 `AI_SELF_TEST_CORS_ORIGINS` 后，应用使用环境变量中的来源。
- 请求携带 `X-Request-ID` 时，响应头返回同一个 ID。
- 删除客户端时，关联 `Task`、`TaskItem`、`TaskItemData` 被清理。
- `/openapi.json` 中客户端、提示词、首页统计、多模态模型路由带有分组标签。
- 数据库模块不再保留未使用的异步引擎与异步会话入口。
- `multimodal_model.py` 只作为兼容导出层，核心实现分散到 4 个职责模块。
- 应用启动会执行 Alembic `upgrade head`，测试库包含 `alembic_version`。
- 业务异常优先使用 `ErrorCode` 枚举。
- 客户端认证成功后保存 token 绝对过期时间，并缓存可用认证头格式。
- 认证请求优先使用缓存组合，失败后回退全量探测。
- 前端 API 工具能区分 HTTP、业务、网络和超时错误。
- `MultimodalChat` 和 `Review` 的 API 调用与会话/复核状态逻辑已抽到独立文件。
- React Query Provider 已注册，并有至少一个页面查询使用缓存能力。

## 自动验证

- `uv run pytest tests/test_client_api.py`
- `uv run pytest tests/test_app_config.py`
- `uv run pytest tests/test_client_auth.py`
- `uv run pytest tests/test_multimodal_model_api.py`
- `uv run pytest tests/test_task_api.py`
- `uv run pytest`
- `npm run lint`
- `npm run build`

## 手工验证

- 查看 `aiSelfTest/aiSelfTest/database.py`，确认只保留同步会话入口。
- 查看 `.env.example`，确认包含数据目录与 CORS 配置示例。
- 查看 `aiSelfTest/aiSelfTest/services/multimodal_model.py`，确认不再承载大段业务实现。
- 查看 `aiSelfTestUi/src/api/` 与 `aiSelfTestUi/src/hooks/`，确认聊天与复核逻辑已抽离。
