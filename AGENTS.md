# Repository Guidelines

## 项目结构与模块组织
本仓库包含两个并列目录：前端项目 `aiSelfTestUi/` 与 Python FastAPI 后端包 `aiSelfTest/`。前端代码位于 `aiSelfTestUi/src/`：`App.tsx` 负责导航与页面切换，`components/` 存放视图组件，`constants/` 存放共享常量。全局样式位于 `aiSelfTestUi/src/index.css`，并使用 Tailwind CSS。后端代码位于 `aiSelfTest/aiSelfTest/`，使用 FastAPI、SQLModel、Alembic、SQLite 和 loguru。前端生产构建产物直接输出到 `aiSelfTest/aiSelfTest/static/` 并由 FastAPI 托管。运行数据默认位于 `.aiSelfTest/`，日志默认位于 `logs/`。

## 构建、测试与开发命令
- `cd aiSelfTestUi && npm install`：安装前端依赖。
- `pip install -e ./aiSelfTest`：以可编辑模式安装 Python 后端包。
- `cd aiSelfTestUi && npm run dev:api`：启动 Python FastAPI 后端，默认监听 `3001` 端口。
- `cd aiSelfTestUi && npm run dev`：启动 Vite 前端 `3000` 端口，并通过代理访问 Python 后端。
- `cd aiSelfTestUi && npm run build`：把前端生产构建直接输出到 `aiSelfTest/aiSelfTest/static/`。
- `cd aiSelfTestUi && npm run preview`：本地预览已构建的 Vite 应用。
- `cd aiSelfTestUi && npm run lint`：运行 `tsc --noEmit` 做 TypeScript 校验。
- `aiSelfTest`：生产形态单命令运行，FastAPI 同时提供 `/api/*` 和前端静态页面。

## 代码风格与命名约定
前端使用 ES modules、分号、单引号和两个空格缩进。React 组件文件与导出使用 PascalCase，例如 `Tasks.tsx`；hooks、辅助函数和变量使用 camelCase。优先把组件专用逻辑放在对应组件文件中，确有复用需求时再抽取共享工具。样式优先使用 Tailwind 工具类。Python 后端遵循 PEP 8、类型注解和清晰分层：`api/` 放 FastAPI 路由，`services/` 放业务逻辑，`db/` 放 SQLModel 和 session，`alembic/` 放迁移。后端接口统一放在 `/api/*` 路径下。前端 `@` 导入别名映射到 `aiSelfTestUi/` 项目根。

## 测试指南
当前未配置专用前端测试框架。提交前至少运行 `cd aiSelfTestUi && npm run lint`、`cd aiSelfTestUi && npm run build` 和 `python -m compileall aiSelfTest/aiSelfTest`。修改后端或集成流程时，运行 Python 后端并手动验证受影响的 API 路由或 UI 流程。如果新增测试，请在同一次变更中加入测试框架和脚本，并使用清晰命名，例如 `Tasks.test.tsx` 或 `test_tasks_api.py`。

## 提交与 Pull Request 指南
当前检出目录没有本地 `.git` 历史，因此无法推断项目既有提交规范。提交信息建议使用简短祈使句，例如 `Add task filter validation`。Pull Request 应包含变更摘要、验证步骤、关联 issue（如有），以及可见 UI 变更的截图或录屏。涉及数据库结构、环境变量或运行配置变化时，需要在说明中明确列出。

## 安全与配置提示
不要提交真实 API key、客户端账号密码、生成的 SQLite 数据库内容或 loguru 日志。后端模型默认值应通过环境变量配置，例如 `OMLX_API_URL`、`OMLX_API_KEY` 和 `OMLX_MODEL`。当前日志策略是完整记录请求、响应、外部调用和模型调用，日志可能包含敏感信息；`logs/` 必须视为本地敏感运行状态。
