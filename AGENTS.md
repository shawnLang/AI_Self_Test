# Repository Guidelines

## 项目结构与模块组织
本仓库是一个 Vite React 应用，并包含一个轻量 Express API。前端代码位于 `src/`：`src/App.tsx` 负责导航与页面切换，`src/components/` 存放视图组件，`src/constants/` 存放共享常量。全局样式在 `src/index.css`，并使用 Tailwind CSS。后端代码位于 `server/`，其中 `server/index.js` 定义 API 路由，`server/db.js` 负责 SQLite 初始化与迁移。`server/db/` 下的数据库文件属于本地运行状态，不应作为源代码提交。构建产物输出到 `dist/`，依赖安装在 `node_modules/`。

## 构建、测试与开发命令
- `npm install`：根据 `package-lock.json` 安装依赖。
- `npm run dev`：同时启动 Vite 前端 `3000` 端口和 Express 后端 `3001` 端口。
- `npm run build`：生成生产环境前端构建产物到 `dist/`。
- `npm run preview`：本地预览已构建的 Vite 应用。
- `npm run lint`：运行 `tsc --noEmit` 做 TypeScript 校验。
- `docker compose up --build`：使用提供的 Node 容器运行应用，并挂载 `server/db`。

## 代码风格与命名约定
使用 ES modules、分号、单引号和两个空格缩进。React 组件文件与导出使用 PascalCase，例如 `Tasks.tsx`；hooks、辅助函数和变量使用 camelCase。优先把组件专用逻辑放在对应组件文件中，确有复用需求时再抽取共享工具。样式优先使用 Tailwind 工具类，后端接口统一放在 `/api/*` 路径下。`@` 导入别名映射到仓库根目录。

## 测试指南
当前未配置专用测试框架。提交前至少运行 `npm run lint` 和 `npm run build`。修改后端或集成流程时，运行 `npm run dev`，并手动验证受影响的 API 路由或 UI 流程。如果新增测试，请在同一次变更中加入测试框架和 npm 脚本，并使用清晰命名，例如 `Tasks.test.tsx` 或 `server/index.test.js`。

## 提交与 Pull Request 指南
当前检出目录没有本地 `.git` 历史，因此无法推断项目既有提交规范。提交信息建议使用简短祈使句，例如 `Add task filter validation`。Pull Request 应包含变更摘要、验证步骤、关联 issue（如有），以及可见 UI 变更的截图或录屏。涉及数据库结构、环境变量或运行配置变化时，需要在说明中明确列出。

## 安全与配置提示
不要提交真实 API key、客户端账号密码或生成的 SQLite 数据库内容。后端模型默认值应通过环境变量配置，例如 `OMLX_API_URL`、`OMLX_API_KEY` 和 `OMLX_MODEL`。
