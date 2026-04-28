# AGENTS.md

This file provides guidance to codex when working with code in this repository.

# python 环境

本项目使用 `python venv` 管理 Python 虚拟环境。当前根目录 `.env` 环境是在
WSL 的 Ubuntu 环境中通过 `python3 -m venv .env` 创建的，仅用于 WSL/Linux。

Windows 不能直接复用 WSL 创建的 `.env`。如需在 Windows 原生 Python 中运行
项目，必须重新创建 Windows 专用虚拟环境，建议使用 `.env-win`，避免覆盖 WSL
环境。

## python venv 操作规范

### WSL / Linux 环境

- 创建虚拟环境：`python3 -m venv .env`
- 激活虚拟环境（bash / zsh）：`source .env/bin/activate`
- 安装项目依赖：`python -m pip install -e ./aiSelfTest`
- 安装测试依赖（如需）：`python -m pip install pytest`
- 运行 Python 脚本：`python <script.py>`
- 运行项目服务：`aiSelfTest` 或 `cd aiSelfTest && python run.py`
- 运行测试：`python -m pytest`
- 运行指定测试：`python -m pytest <test_path>`
- 安装单个依赖：`python -m pip install <package>`
- 升级 pip：`python -m pip install --upgrade pip`
- 退出虚拟环境：`deactivate`

### Windows 环境

- 创建虚拟环境：`python -m venv .env-win`
- 激活虚拟环境（PowerShell）：`.env-win\Scripts\Activate.ps1`
- 激活虚拟环境（CMD）：`.env-win\Scripts\activate.bat`
- 安装项目依赖：`python -m pip install -e .\aiSelfTest`
- 安装测试依赖（如需）：`python -m pip install pytest`
- 运行项目服务：`aiSelfTest`
- 运行测试：`python -m pytest`
- 运行指定测试：`python -m pytest <test_path>`
- 退出虚拟环境：`deactivate`

除非有明确原因，不要在未激活 `.env` 虚拟环境的情况下直接使用系统级
`pip`、`python`、`pytest` 等命令。需要执行 Python 相关命令时，优先在已
激活的 `.env` 环境中执行；如需显式指定解释器，优先使用 `.env/bin/python`
或 `.env/bin/pip`。

在 Windows 中执行 Python 命令时，应激活 `.env-win`，或显式使用
`.env-win\Scripts\python.exe` 与 `.env-win\Scripts\pip.exe`。不要混用 WSL
的 `.env` 与 Windows 的 `.env-win`。

# 开发规范

## Python 开发规范

### 概览

本技能用于在编写、重构、审查或解释 Python 代码时，提供一致的开发规范与检查清单，确保可读性、健壮性与可维护性。

### 使用方式

- 动手前先浏览现有代码风格与约定；若无明确规范，默认遵循本技能。
- 输出与说明始终使用中文，给出必要的决策理由与可执行建议。

### 规范清单

#### 代码风格

- 遵循 PEP 8：4 空格缩进、合理换行、清晰命名。
- 头部 import：所有 import 置于文件顶部，禁止在函数/类内部导入（除非为避免循环依赖，需说明原因）。

#### 类型与数据模型

- 为公开函数、关键逻辑与复杂数据结构添加类型注解。
- 优先使用 `dataclasses` 或 `pydantic` 模型表示结构化数据。

#### 资源与异常

- 资源使用上下文管理器（如 `with open(...)`）确保释放。
- 使用异常处理提升健壮性：捕获具体异常，避免裸 `except`。

#### 可读性与性能

- 优先使用列表/字典/集合推导式与生成器表达式，但避免过度嵌套导致难读。
- 为模块、类、函数编写 docstrings，说明用途、参数、返回值与异常。

#### 设计原则

- 遵循 SOLID，控制类与函数职责单一，降低耦合。

### 交付检查

- 代码是否符合 PEP 8 与命名规范？
- 是否补全类型注解与 docstrings？
- 是否使用上下文管理器和合理的异常处理？
- 是否使用 dataclasses/pydantic 表达数据模型？
- 是否避免内部 import 并说明特殊情况？

### API 路由规范

- 所有路由必须有明确的名称前缀，禁止使用空路径（如 `@router.get("")`）或纯动态参数路由（如 `@router.get("/{id}")`）
- 正确示例：`/list`、`/create`、`/detail/{id}`、`/update/{id}`、`/delete/{id}`
- 这样做可以避免 FastAPI 路由匹配冲突（动态路由拦截固定路径），并使 API 语义更清晰
- 接口参数 ≥ 2 个时，必须使用 Pydantic BaseModel（或 dataclass）对象接收，禁止逐个声明为独立的查询字符串参数

### 日志规范

**后端统一使用 loguru 进行日志记录:**

```python
from loguru import logger

# 基本使用
logger.info(f"用户登录成功: {username}")
logger.warning(f"数据集版本状态异常: {status}")
logger.error(f"训练任务失败: {error}")

# 异常日志 (自动记录堆栈)
try:
    process_dataset(dataset_id)
except Exception as e:
    logger.exception("数据集处理异常")
```

**日志级别使用指南:**

- `DEBUG`: 详细的调试信息 (开发环境)
- `INFO`: 关键业务流程节点 (用户操作、任务状态变更)
- `WARNING`: 异常情况但不影响主流程 (重试、降级)
- `ERROR`: 错误但可恢复 (任务失败、API 调用失败)
- `CRITICAL`: 严重错误需要立即处理 (数据库连接失败、服务崩溃)

**关键位置必须记录日志:**

- API 请求入口和响应 (记录用户、操作、耗时)
- 数据库操作 (创建、更新、删除关键资源)
- 文件操作 (上传、删除、移动)
- 外部服务调用
- 异常捕获点 (使用 logger.exception)

### API 响应格式

**所有 API 接口统一使用以下响应格式：**

```json
{
  "code": 0,
  "message": "success",
  "data": {
    ...
  }
}
```

**错误码定义：**

- `0`: 成功
- `1001`: 参数错误
- `1002`: 资源不存在
- `1003`: 资源已存在
- `2001`: 认证失败（未登录或会话过期）
- `2002`: 权限不足
- `2003`: Token过期
- `3001`: 任务执行失败
- `3002`: 资源忙
- `5001`: 服务器内部错误

**重要规范：**

- ✅ 所有响应的 `data` 字段必须使用 Pydantic BaseModel 定义
- ✅ 使用 `model_dump()` 方法将 BaseModel 转换为字典
- ✅ 日期时间统一使用格式字符串（`format_datetime()`）
- ❌ 不要直接返回字典，必须先定义 BaseModel Schema

## 重要注意事项

1. **数据库迁移:** 修改 models 后必须创建 Alembic 迁移，不要直接修改数据库
2. **Cython 打包:** `build_ignore` 列表中的文件不会被编译 (如 setup.py)

# 重要: 新增功能和bug修复开发流程

## 何时使用

- 使用测试驱动方式开发新功能或修复 Bug
- 需要完整的"设计 → 测试 → 实现 → 验证"闭环

## 工作流

1. **需求分析** — 理解要实现的功能或要修复的问题
2. **查阅现有文档** — 读相关包的 `AGENTS.md`，了解现有设计
3. **查看现有实现** — 确认是否有可复用的代码
4. **编写 `Test.md`（TDD 先行）** — 在开始写代码前，先把测试方案写清楚：测什么、怎么验、预期结果
5. **编写测试用例**
6. **编写代码让测试通过**
7. **编译验证**
8. **运行测试验证**
9. **运行回归测试**
10. **反复步骤 5–9** — 逐步完善，直到 `Test.md` 中所有需求都通过
11. **必要时更新包的 `AGENTS.md`** — 只有当本次实现沉淀了新的包级规则、测试入口或 AI 易踩坑时再更新；不要机械改文档

## 关键原则

- `Test.md` 必须在写任何代码之前完成，这是 TDD 的核心
- 不要为了让测试通过而修改业务逻辑（除非业务本来就有 Bug）
- 如果任务很小，不值得单独沉淀长文档，也至少要先写出最小验证清单，再开始实现

## 测试清理规范

- pytest 测试夹具必须显式创建并清理临时目录，避免由沙箱身份留下不可删除目录。
- 每次运行 `pytest` 测试后，必须清理仓库根目录下的 `pytest-cache-files-*` 文件夹。
- 每次运行 `pytest` 测试后，必须清理 `.pytest_tmp` 目录下生成的测试文件。
- 清理前必须确认目标路径位于当前仓库内，避免误删仓库外文件。
