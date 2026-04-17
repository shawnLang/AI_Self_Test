<div align="center">
<img width="1200" height="475" alt="GHBanner" src="https://github.com/user-attachments/assets/0aa67016-6eaf-458a-adb2-6e31a0763ed6" />
</div>

# AI Self Test

人工智能自检系统。前端项目位于 `aiSelfTestUi/`，使用 Vite + React + Tailwind CSS；后端包位于 `aiSelfTest/`，使用 Python、FastAPI、SQLModel、Alembic、SQLite 和 loguru。

生产环境只需要运行 Python 命令 `aiSelfTest`。FastAPI 会同时提供 `/api/*` 接口和打包后的前端静态页面。

## 本地开发

**前置要求：** Node.js、Python 3.10+。

1. 进入前端目录并安装依赖：
   `cd aiSelfTestUi && npm install`
2. 安装 Python 包：
   `pip install -e ./aiSelfTest`
3. 启动 Python 后端：
   `cd aiSelfTestUi && npm run dev:api`
4. 启动 Vite 前端：
   `cd aiSelfTestUi && npm run dev`

开发时 Vite 运行在 `3000` 端口，`/api` 代理到 Python 后端 `3001` 端口。

## 构建与发布

1. 在前端目录构建前端：
   `cd aiSelfTestUi && npm run build`
2. 安装或构建 Python 包。
3. 运行：
   `aiSelfTest`

在 `aiSelfTestUi/` 下执行 `npm run build` 会直接把 Vite 构建输出写到 `aiSelfTest/aiSelfTest/static/`。

## 数据与日志

- SQLite 默认写入当前工作目录下的 `.aiSelfTest/database.sqlite`。
- 可通过 `AI_SELF_TEST_DATA_DIR` 或 `AI_SELF_TEST_DB_PATH` 调整数据库位置。
- loguru 默认写入 `./logs/`。
- 日志会完整记录请求、响应、外部调用、模型调用和异常；请把日志视为敏感本地数据。
- 本次架构不迁移也不备份旧 `server/db/database.sqlite*` 数据。
