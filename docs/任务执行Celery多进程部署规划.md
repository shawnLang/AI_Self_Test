# 任务执行 Celery 多进程部署规划

本文档用于重新规划任务执行架构，目标是替换当前同步执行和进程内调度模式。

新方案采用 PostgreSQL 作为主数据库，Redis 作为 Celery 队列依赖。Celery Worker
负责后台执行任务，Celery Beat 负责定时触发任务。

## 1. 背景问题

当前任务执行链路存在几个明确问题：

- 立即执行接口同步阻塞，任务耗时长时前端容易失败。
- 创建自动任务时，如果触发执行，也会阻塞创建接口。
- 执行中允许删除任务，可能删除正在被执行流程使用的数据和文件。
- 多个任务可以同时立即执行，缺少全局并发限制。
- 同一任务重复触发只靠状态判断，缺少可靠的原子并发控制。
- 进程内 APScheduler 在多进程部署时会重复启动，导致重复调度风险。
- 前端按钮只做了部分状态控制，不能完全防止重复点击。

## 2. 目标架构

目标是把 API 请求、后台执行、定时调度拆成独立职责：

- FastAPI API 进程只负责请求处理和快速返回。
- Celery Worker 进程负责真正执行长耗时任务。
- Celery Beat 进程作为唯一调度入口，负责产生定时触发。
- PostgreSQL 负责业务状态、执行记录和任务级并发控制。
- Redis 只负责 Celery 队列消息和 Celery 自身结果状态。

整体链路如下：

```text
前端点击立即执行
  -> FastAPI /api/tasks/action-run/{id}
  -> PostgreSQL 创建执行记录并抢占任务
  -> Celery 投递任务到 Redis
  -> API 快速返回 success
  -> Celery Worker 从 Redis 获取任务
  -> Worker 执行 run_task_execution()
  -> PostgreSQL 持续更新任务状态和进度
  -> 前端轮询任务列表展示进度
```

关键原则：

- API 不执行长任务，也不启动进程内任务调度器。
- Worker 必须支持重复消息、重试消息和 Worker 崩溃后的恢复。
- Beat 只负责产生调度信号，不直接执行业务任务。
- 业务状态最终以 PostgreSQL 为准，不以 Redis result backend 为准。

## 3. 三类进程

### 3.1 API 进程

API 进程负责：

- 接收前端请求。
- 校验请求参数。
- 查询和更新 PostgreSQL。
- 调用统一任务派发服务提交任务。
- 快速返回响应。

建议启动方式：

```bash
uvicorn aiSelfTest.main:app --host 0.0.0.0 --port 8000 --workers 4
```

API 进程不再直接执行 `run_task_execution()`，也不再启动进程内 APScheduler。

### 3.2 Worker 进程

Worker 进程负责：

- 从 Redis 队列获取 Celery 任务。
- 打开独立数据库 Session。
- 执行 `run_task_execution()`。
- 写入执行进度、成功状态、失败状态和错误信息。
- 处理超时、异常和可重试失败。

建议启动方式：

```bash
celery -A aiSelfTest.worker worker --loglevel=info --concurrency=2
```

初期建议并发数为 1 或 2，避免上游接口、模型接口、数据库和磁盘 IO 被打满。

需要注意：`--concurrency=2` 只限制单个 Worker 实例。若部署多个 Worker 进程或容器，
实际全局并发会叠加。生产部署若需要严格全局并发，应通过部署层限制 Worker 实例数，
或增加 PostgreSQL/Redis 全局信号量。

### 3.3 Beat 进程

Beat 进程负责：

- 周期扫描 PostgreSQL 中 `active=True` 的任务。
- 判断任务是否到达下一次执行时间。
- 调用统一任务派发服务提交定时任务。
- 保证系统只有一个定时触发源。

建议启动方式：

```bash
celery -A aiSelfTest.worker beat --loglevel=info
```

Beat 只能运行一个实例。多实例会产生重复调度信号，虽然数据库锁可以兜底，但会增加无效竞争。

如果部署环境无法保证 Beat 单实例，应在扫描任务入口使用 PostgreSQL advisory lock。抢锁失败的
Beat 实例直接跳过本轮扫描。

## 4. 依赖规划

后端依赖新增：

```text
celery
redis
psycopg[binary]
```

保留现有核心依赖：

```text
fastapi
uvicorn
sqlmodel
sqlalchemy
alembic
loguru
requests
```

SQLite 相关默认配置应迁移为 PostgreSQL 配置。Alembic 继续作为数据库迁移工具。

APScheduler 不再作为任务执行调度依赖。若项目其他模块仍依赖 APScheduler，应单独确认用途；
任务执行链路不再调用它。

## 5. 配置规划

项目使用 `.env.self` 作为本方案的环境配置文件。

`.env.self` 中已经配置好 PostgreSQL 数据库地址和 Redis 地址。后续实现时只需要从
`.env.self` 加载配置，不要在文档、日志或错误信息中输出完整连接串和密码。

按当前确认结果，Redis 只保留一个统一配置项：

```env
DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/ai_self_test
REDIS_URL=redis://localhost:6379/0
TASK_WORKER_CONCURRENCY=2
TASK_TIME_LIMIT_SECONDS=21600
TASK_SOFT_TIME_LIMIT_SECONDS=21000
TASK_BEAT_SCAN_SECONDS=60
TASK_RUNNING_STALE_SECONDS=21600
TASK_QUEUE_STALE_SECONDS=600
```

说明：

- `DATABASE_URL` 是 PostgreSQL 数据库连接。
- `REDIS_URL` 是 Redis 连接，Celery broker 和 result backend 都从它派生。
- `TASK_WORKER_CONCURRENCY=2` 表示单个 Worker 实例最多同时执行 2 个任务。
- `TASK_TIME_LIMIT_SECONDS=21600` 表示硬超时 6 小时。
- `TASK_SOFT_TIME_LIMIT_SECONDS=21000` 表示软超时 5 小时 50 分钟。
- `TASK_BEAT_SCAN_SECONDS=60` 表示 Beat 每 60 秒扫描一次调度任务。
- `TASK_RUNNING_STALE_SECONDS=21600` 表示运行态超过 6 小时可被恢复任务判定为异常。
- `TASK_QUEUE_STALE_SECONDS=600` 表示排队态超过 10 分钟仍未被 Worker 接收可进入补偿流程。

代码中不再暴露 `CELERY_BROKER_URL` 和 `CELERY_RESULT_BACKEND` 两个配置。

Celery 初始化时统一使用：

```python
broker_url = settings.redis_url
result_backend = settings.redis_url
```

业务最终状态仍以 PostgreSQL 为准。Redis result backend 只作为 Celery 自身状态辅助，不作为业务状态源。

配置加载要求：

- 优先从 `.env.self` 读取本方案需要的环境变量。
- 缺少 `DATABASE_URL` 或 `REDIS_URL` 时，应用启动应直接失败并给出清晰错误。
- `TASK_WORKER_CONCURRENCY`、`TASK_TIME_LIMIT_SECONDS`、`TASK_SOFT_TIME_LIMIT_SECONDS`
  可提供默认值，但生产环境建议显式配置。
- 不再使用 SQLite 默认数据库作为任务执行方案的运行数据库。

### 5.1 数据库连接策略

切换 PostgreSQL 后，需要调整当前 SQLite 专用数据库初始化逻辑。

要求如下：

- `create_engine()` 不再传入 `connect_args={"check_same_thread": False}`。
- PostgreSQL 不执行 SQLite PRAGMA，例如 `journal_mode`、`busy_timeout`、`foreign_keys`。
- 生产环境建议使用 SQLAlchemy 默认连接池，或显式配置 `pool_pre_ping=True`。
- API、Worker、Beat 使用同一套 `DATABASE_URL`，但每个进程独立创建 engine 和 Session。
- 数据库连接日志必须脱敏，不输出用户名、密码和完整 DSN。

Alembic 迁移不建议放在每个 API worker 的 lifespan 中自动执行。多 worker 同时启动时，
并发迁移会引入锁等待和不可控失败。

推荐部署顺序：

1. 停止旧服务或进入维护窗口。
2. 执行数据库备份。
3. 使用独立命令执行 Alembic 升级。
4. 启动 API 进程。
5. 启动 Worker 进程。
6. 启动唯一 Beat 进程。

### 5.2 Alembic 初始化策略

本次数据库切换到 PostgreSQL 后，Alembic 直接重新初始化。

执行策略：

- 不沿用现有 SQLite 迁移历史。
- 重新生成 Alembic 环境和初始迁移。
- 初始迁移一次性创建当前业务所需全部表、索引和约束。
- `task_execution` 表和 PostgreSQL 部分唯一索引纳入初始迁移。
- 初始化前需要确认目标 PostgreSQL 数据库为空库，避免误删或覆盖已有数据。

注意事项：

- 如果后续需要迁移历史 SQLite 数据，应单独编写数据迁移脚本，不放在 Alembic
  schema 初始化流程里。
- 重新初始化 Alembic 属于数据库基线变更，实施前需要备份旧数据库和旧迁移目录。
- 新 Alembic 配置应从 `.env.self` 读取 `DATABASE_URL`，不要硬编码连接串。

## 6. 数据库模型规划

新增 `task_execution` 表，记录每次任务执行实例。

建议字段：

| 字段 | 说明 |
|---|---|
| `id` | 执行记录主键 |
| `task_id` | 关联任务 ID |
| `trigger_type` | `manual` / `schedule` / `create_auto` / `repair` |
| `status` | `queued` / `running` / `success` / `failed` / `skipped` / `cancelled` |
| `celery_task_id` | Celery 任务 ID |
| `started_at` | 开始执行时间 |
| `finished_at` | 结束时间 |
| `last_heartbeat_at` | Worker 最近心跳时间 |
| `error` | 失败错误信息 |
| `retry_count` | 补偿或重试次数 |
| `created_at` | 创建时间 |
| `updated_at` | 更新时间 |

建议约束和索引：

```sql
CREATE UNIQUE INDEX uq_task_execution_active
ON task_execution(task_id)
WHERE status IN ('queued', 'running');

CREATE INDEX ix_task_execution_status_updated_at
ON task_execution(status, updated_at);

CREATE INDEX ix_task_execution_task_id_created_at
ON task_execution(task_id, created_at DESC);
```

`task` 表继续保存任务定义和当前聚合状态：

- `active`
- `interval`
- `execution_status`
- `total_count`
- `processed_count`
- `last_run_started_at`
- `last_pull_end_at`
- `last_error`

建议新增或明确以下字段：

- `next_run_at`：下一次定时触发时间。
- `current_execution_id`：当前排队或运行中的执行记录 ID，可为空。

`task_execution` 是执行实例事实表，`task` 是任务当前视图。发生不一致时，以
`task_execution` 中最新的 active 执行记录为准修正 `task.current_execution_id`。

## 7. 状态模型

本方案必须明确三类状态，避免前端、任务聚合状态和执行实例状态混用。

### 7.1 执行实例状态

`task_execution.status` 表示一次后台执行实例的生命周期：

| 状态 | 含义 | 终态 |
|---|---|---|
| `queued` | 已创建执行记录，等待 Worker 消费 | 否 |
| `running` | Worker 已接收并开始执行 | 否 |
| `success` | Worker 成功结束 | 是 |
| `failed` | Worker 执行失败或超时 | 是 |
| `skipped` | 因已有执行或不满足条件被跳过 | 是 |
| `cancelled` | 投递失败或人工取消 | 是 |

### 7.2 任务聚合状态

`task.execution_status` 表示业务阶段，保留当前中文枚举：

- `创建`
- `数据加载`
- `下载`
- `模型识别`
- `核查`
- `结束`
- `失败`

排队状态不写入 `task.execution_status` 的业务阶段枚举。是否排队以
`task_execution.status = 'queued'` 或 `task.current_execution_id` 为准。

### 7.3 API 展示状态

接口响应建议补充以下字段：

| 字段 | 来源 |
|---|---|
| `execution_status` | 当前业务阶段，来自 `task.execution_status` |
| `current_execution_id` | 当前执行实例 ID |
| `current_execution_status` | `queued` / `running` / 终态 / `null` |
| `display_status` | 后端聚合出的前端展示状态 |
| `estimated_remaining_seconds` | 已有预计剩余时间 |

展示状态映射如下：

| 条件 | `display_status` |
|---|---|
| `current_execution_status = queued` | `排队中` |
| `current_execution_status = running` 且业务阶段为 `创建` | `准备中` |
| 业务阶段为 `数据加载` | `数据加载中` |
| 业务阶段为 `下载` | `下载中` |
| 业务阶段为 `模型识别` | `模型识别中` |
| 业务阶段为 `核查` | `待核查` |
| 业务阶段为 `结束` | `已完成` |
| 执行实例或业务阶段失败 | `执行失败` |

按钮禁用应以 `current_execution_status in ('queued', 'running')` 为最终依据。

## 8. 并发控制规划

### 8.1 同任务并发控制

同一个 `task_id` 同一时间只能存在一个 `queued` 或 `running` 执行实例。

使用 PostgreSQL 部分唯一索引：

```sql
CREATE UNIQUE INDEX uq_task_execution_active
ON task_execution(task_id)
WHERE status IN ('queued', 'running');
```

这样立即执行、定时触发、创建后自动执行同时发生时，数据库可以提供最终一致的抢占保护。

### 8.2 全局并发控制

单 Worker 实例内并发由 Celery Worker 控制：

```bash
celery -A aiSelfTest.worker worker --loglevel=info --concurrency=2
```

如果模型接口或下载压力较大，初期可以把并发设为 1。确认资源稳定后再逐步提高。

如需严格全局并发，不应只依赖 `--concurrency`。可选方案：

- 部署层只允许一个 Worker 实例运行。
- 使用 PostgreSQL 表实现全局运行令牌。
- 使用 Redis semaphore 控制进入 `run_task_execution()` 的 Worker 数量。

初期推荐采用“单 Worker 实例 + 小并发”的方式，降低实现复杂度。

### 8.3 多进程调度控制

FastAPI 多 worker 时，不允许每个 API worker 启动调度器。

定时调度只能由 Celery Beat 负责。Beat 投递任务后，Worker 统一消费执行。

## 9. 统一派发服务

新增 `TaskDispatchService`，所有执行触发都走它。

职责包括：

- 校验任务是否存在。
- 判断任务是否允许执行。
- 创建 `task_execution` 记录。
- 利用 PostgreSQL 唯一索引防止重复入队。
- 使用确定性 Celery task id 投递任务。
- 写入 `celery_task_id`。
- 快速返回执行记录。

触发来源统一使用：

| 来源 | `trigger_type` |
|---|---|
| 前端立即执行 | `manual` |
| 创建后自动执行 | `create_auto` |
| Celery Beat 定时触发 | `schedule` |
| 补偿任务重新派发 | `repair` |

### 9.1 派发事务边界

PostgreSQL 写入和 Redis 投递不是同一个事务，必须显式处理边界。

推荐流程：

```text
1. 开启数据库事务。
2. 校验任务存在且允许执行。
3. 插入 task_execution(status='queued')。
4. 设置 task.current_execution_id。
5. 提交数据库事务。
6. 使用确定性 celery_task_id 投递 Celery。
7. 投递成功后写入 celery_task_id。
8. 投递失败则将执行记录标记为 cancelled 或 failed，并清空 task.current_execution_id。
```

确定性 Celery task id 推荐格式：

```text
task-execution-{execution_id}
```

这样即使 API 重试、网络抖动或补偿任务重复派发，也能更容易识别同一个执行实例。

### 9.2 重复触发行为

当唯一索引检测到已有 `queued/running` 执行记录时，派发服务不应抛出 500。

推荐行为：

- 手动触发：返回 `3002`，提示“任务正在执行或排队中”。
- 定时触发：写入 `skipped` 记录可选，或只增加 `task.skipped_count`。
- 创建后自动执行：返回创建成功，但任务保持已有执行状态。

## 10. 接口改造规划

### 10.1 立即执行

当前同步执行逻辑：

```python
run_task_execution(session, task_id)
```

改为提交后台队列：

```python
execution = TaskDispatchService(session).submit(
    task_id=task_id,
    trigger_type="manual",
)
```

接口快速返回：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "id": 1,
    "active": false,
    "execution_status": "创建",
    "current_execution_id": 1001,
    "current_execution_status": "queued",
    "display_status": "排队中"
  }
}
```

### 10.2 创建自动执行

`auto_execute=True` 时，不再同步执行。

创建任务提交成功后，调用派发服务入队：

```python
TaskDispatchService(session).submit(
    task_id=task.id,
    trigger_type="create_auto",
)
```

创建接口仍应快速返回，前端通过任务列表轮询查看排队和执行进度。

如果自动入队失败，应返回创建成功，并在 `last_error` 中记录“自动执行入队失败”。是否
让创建接口整体失败，需要结合产品预期确认；初期建议不要因为自动执行失败而回滚任务创建。

### 10.3 定时执行

删除 FastAPI lifespan 中启动 APScheduler 的逻辑。

改为 Celery Beat 周期任务：

```text
每 TASK_BEAT_SCAN_SECONDS 秒扫描 active=True 的任务
  -> 判断 now >= task.next_run_at
  -> 调用 TaskDispatchService.submit(trigger_type="schedule")
  -> 派发成功后推进 next_run_at
  -> 未到时间或已有 queued/running 则跳过
```

`next_run_at` 推荐按“本次成功派发时间 + interval”计算，而不是按任务完成时间计算。
这样长任务不会因为执行时间过长而在结束后立即补跑多次。

如果任务长期运行导致多轮 Beat 命中，Beat 只增加跳过计数，不创建新的 running 执行实例。

## 11. Worker 执行规划

Celery 任务建议形态：

```python
execute_task.delay(task_id, execution_id)
```

实际投递时建议显式指定任务 ID：

```python
execute_task.apply_async(
    args=[task_id, execution_id],
    task_id=f"task-execution-{execution_id}",
)
```

Worker 执行步骤：

1. 打开新的数据库 Session。
2. 查询 `task_execution`。
3. 校验状态必须是 `queued`。
4. 将执行记录更新为 `running`，写入 `started_at` 和 `last_heartbeat_at`。
5. 调用 `run_task_execution(session, task_id)`。
6. 执行过程中定期更新 `last_heartbeat_at`。
7. 成功时写入 `success` 和 `finished_at`。
8. 失败时写入 `failed`、`error` 和 `finished_at`。
9. 软超时时捕获异常，写入失败状态，并保留错误信息。
10. 最终清空 `task.current_execution_id`。

Worker 内部仍要再次检查执行记录状态，保证重复投递或重试时可以安全跳过。

### 11.1 Celery 配置

Celery 应用初始化建议配置：

```python
celery_app.conf.update(
    broker_url=settings.redis_url,
    result_backend=settings.redis_url,
    task_time_limit=settings.task_time_limit_seconds,
    task_soft_time_limit=settings.task_soft_time_limit_seconds,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    timezone="Asia/Shanghai",
)
```

说明：

- `task_acks_late=True`：任务执行完成后再确认消息。
- `task_reject_on_worker_lost=True`：Worker 异常退出时，消息可重新入队。
- `worker_prefetch_multiplier=1`：避免 Worker 预取过多长任务。
- `task_track_started=True`：方便观察 Celery 自身状态。

### 11.2 幂等要求

Celery 至少一次投递语义意味着任务可能重复执行。Worker 必须以 `execution_id` 为幂等键。

要求如下：

- `task_execution.status != queued` 时直接跳过。
- 同一个 `execution_id` 只能从 `queued` 转为 `running` 一次。
- 已经是终态的执行记录不再调用 `run_task_execution()`。
- `run_task_execution()` 内部已有阶段性提交，失败重试时必须接受部分数据已落库。

当前 `task_item` 已有 `(task_id, file_id)` 唯一约束，重复拉取同一上游文件时应走跳过逻辑。
后续新增写入点也应遵守 upsert 或 check-before-write 模式。

## 12. 异常恢复和补偿

### 12.1 投递失败补偿

派发服务创建执行记录后，如果 Celery 投递失败：

- 将 `task_execution.status` 改为 `cancelled` 或 `failed`。
- 写入 `error`，但错误信息不得包含 Redis 密码和完整连接串。
- 清空 `task.current_execution_id`。
- 手动触发接口返回 `3001` 或 `3002`，由产品语义决定。

如果数据库提交成功、Celery 投递成功，但写入 `celery_task_id` 失败，补偿任务可根据
`task_execution.id` 和确定性 task id 修复。

### 12.2 排队超时补偿

定时补偿任务扫描：

```text
status = 'queued'
AND updated_at < now - TASK_QUEUE_STALE_SECONDS
```

处理方式：

- 如果 `retry_count` 未超过阈值，重新使用确定性 task id 投递。
- 如果超过阈值，标记为 `failed`，写入“排队超时未被 Worker 接收”。
- 同步清理 `task.current_execution_id`。

### 12.3 运行超时和 Worker 崩溃恢复

定时补偿任务扫描：

```text
status = 'running'
AND last_heartbeat_at < now - TASK_RUNNING_STALE_SECONDS
```

处理方式：

- 将执行记录标记为 `failed`。
- 将任务聚合状态标记为 `失败`。
- 写入可读错误，例如“Worker 心跳超时，任务已恢复为失败”。
- 清空 `task.current_execution_id`。

如果 Celery 消息因 Worker 崩溃重新投递，Worker 会看到执行记录已经不是 `queued`，
应直接安全退出。

## 13. 删除规则

执行中或排队中的任务禁止删除。

禁止删除条件：

- 存在 `task_execution.status in ('queued', 'running')`。
- 或任务聚合状态处于执行阶段。

执行阶段包括：

- `创建` 且 `last_run_started_at` 不为空。
- `数据加载`。
- `下载`。
- `模型识别`。

删除接口返回：

```json
{
  "code": 3002,
  "message": "任务正在执行，不能删除",
  "data": {}
}
```

前端也应禁用删除按钮，但最终以后端校验为准。

执行中还应禁止修改关键配置，包括：

- `client_id`
- `config_id`
- `filters`
- `execution_mode`
- `auto_execute`

是否允许修改任务名称和 `active` 可单独决定。初期建议执行中只允许停止后续调度，不影响当前执行。

## 14. 前端改造规划

任务管理页需要区分 `active` 和执行状态。

`active` 只表示任务是否启用定时调度，不表示任务正在执行。

新增或补齐状态展示：

- `排队中`
- `准备中`
- `数据加载中`
- `下载中`
- `模型识别中`
- `待核查`
- `已完成`
- `执行失败`

按钮控制规则：

- `current_execution_status = queued/running` 禁用立即执行。
- `current_execution_status = queued/running` 禁用删除。
- 执行中禁用关键配置修改。
- 启用调度、暂停调度、立即执行、删除都要有每任务独立 pending 状态。
- 列表继续轮询任务状态，展示进度和预计剩余时间。

前端不应只依赖按钮禁用防重。所有防重、禁删、禁改规则必须由后端再次校验。

## 15. 测试规划

按项目规范，改代码前先写 `Test.md` 或最小验证清单。

重点测试：

- 立即执行接口快速返回，不等待任务执行完成。
- 创建自动执行不阻塞创建接口。
- 同一任务重复立即执行时，只能创建一个 queued/running 执行记录。
- 定时触发和手动触发同时发生时，不会重复执行同一任务。
- 执行中删除返回 `3002`。
- 执行中修改关键配置返回 `3002`。
- Worker 成功时写入 `success`。
- Worker 失败时写入 `failed` 和错误信息。
- 软超时时写入失败状态。
- Celery 投递失败时执行记录进入 `cancelled` 或 `failed`。
- queued 超时补偿可重新投递或标记失败。
- running 心跳超时可恢复为失败。
- 前端任务按钮存在执行中和 pending 禁用控制。

建议补充集成测试场景：

- 使用 mock Celery 派发函数验证 API 快速返回。
- 使用真实 PostgreSQL 测试部分唯一索引。
- 使用测试 Redis 或 Celery eager 模式验证 Worker 状态流转。
- 使用两个并发请求同时触发同一任务，验证只有一个请求抢占成功。

## 16. 实施顺序

建议按以下顺序实施：

1. 编写或更新 `Test.md`，明确本次任务执行改造的验证清单。
2. 调整配置系统，支持 PostgreSQL `DATABASE_URL` 和统一 `REDIS_URL`。
3. 修改数据库 engine 初始化，移除 SQLite 专用连接参数和 PRAGMA。
4. 修改依赖，新增 Celery、Redis、PostgreSQL 驱动。
5. 新增 `task_execution` 模型、状态枚举、Schema 和 Alembic 初始迁移。
6. 补充 `task.next_run_at` 和 `task.current_execution_id`。
7. 新增 Celery 应用初始化与 `aiSelfTest.worker` 入口。
8. 实现 `TaskDispatchService`，包含投递失败补偿。
9. 改造立即执行接口为后台入队。
10. 改造创建自动执行为后台入队。
11. 移除 API 进程内 APScheduler 启动逻辑。
12. 新增 Celery Beat 周期扫描任务。
13. Worker 接入 `run_task_execution()`，补齐超时、心跳和终态写入。
14. 新增 queued/running 补偿任务。
15. 增加执行中禁止删除和禁止关键配置修改。
16. 改造前端按钮状态控制和状态展示。
17. 补齐测试并运行回归验证。

## 17. 部署确认

最终部署进程分为三类：

```bash
# API，多进程
uvicorn aiSelfTest.main:app --host 0.0.0.0 --port 8000 --workers 4

# Worker，可按资源调整并发
celery -A aiSelfTest.worker worker --loglevel=info --concurrency=2

# Beat，唯一实例
celery -A aiSelfTest.worker beat --loglevel=info
```

部署前确认：

- PostgreSQL 数据库已初始化且迁移完成。
- Redis 可连接，且连接串不会输出到日志。
- API 进程未启动 APScheduler。
- Worker 至少启动一个实例。
- Beat 只启动一个实例，或已启用 advisory lock。
- `.env.self` 中 `DATABASE_URL`、`REDIS_URL` 和超时配置完整。

最终确认原则：

- API 不执行长任务。
- Worker 专门执行长任务。
- Beat 是唯一调度入口。
- Redis 只保留 `REDIS_URL`。
- PostgreSQL 负责业务状态和并发锁。
- 执行状态以 PostgreSQL 为准，不以 Redis 为准。
