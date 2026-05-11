# 多模态网关仅保留 /v1 路径测试清单

# 任务执行 Celery 多进程改造测试清单

## 目标

- 任务立即执行和创建后自动执行不再同步调用 `run_task_execution()`。
- API 只创建执行记录并提交后台队列，快速返回当前执行实例状态。
- 同一任务同一时间只能存在一个 `queued/running` 执行记录。
- Worker 以 `execution_id` 为幂等键执行任务，并写入成功、失败和超时状态。
- API 进程不再启动 APScheduler，定时触发改由 Celery Beat 扫描。
- 执行中或排队中的任务禁止删除，关键配置禁止修改。

## 用例

1. `TaskExecution` 模型包含 `task_id`、`trigger_type`、`status`、`celery_task_id`、
   `started_at`、`finished_at`、`last_heartbeat_at`、`error`、`retry_count` 等字段。
2. `task_execution` 表存在同任务 active 执行唯一约束，防止重复排队和运行。
3. `TaskDispatchService.submit()` 成功时创建 `queued` 执行记录并返回执行 ID。
4. `TaskDispatchService.submit()` 传入 `manual`、`schedule`、`create_auto`、`repair`
   之外的来源时返回参数错误。
5. 同一任务已有 `queued/running` 执行记录时，手动触发返回 `3002`。
6. Celery 投递失败时，执行记录进入 `cancelled` 或 `failed`，任务清空当前执行 ID。
7. 立即执行接口快速返回，不等待 `run_task_execution()` 完成。
8. 创建自动执行任务时，创建接口快速返回，并提交后台执行。
9. Worker 只处理 `queued` 执行记录，非 `queued` 状态直接跳过。
10. Worker 成功执行后，执行记录进入 `success`，并清空任务当前执行 ID。
11. Worker 执行失败后，执行记录进入 `failed`，错误信息写入 `error`。
12. queued 超时补偿能重新投递或标记失败。
13. running 心跳超时补偿能恢复执行记录和任务聚合状态为失败。
14. 执行中删除任务返回 `3002`。
15. 执行中修改关键配置返回 `3002`。
16. 任务列表和动作接口返回 `current_execution_id`、`current_execution_status`
    与 `display_status`。
17. FastAPI lifespan 不再创建或启动 APScheduler。
18. Celery Beat 扫描 `active=True` 且 `next_run_at <= now` 的任务，并提交定时执行。

## 验证命令

```bash
.env/bin/python -m pytest tests/test_task_celery_execution.py tests/test_task_model_contract.py
```

运行 pytest 后清理：

```bash
rm -rf .pytest_cache .pytest_tmp pytest-cache-files-*
```

# Cython 打包 FastAPI Query 参数回归测试清单

## 目标

- 打包后导入 `aiSelfTest.api.task` 不再因 `int = Query(...)` 参数默认值触发
  `TypeError: Expected int, got Query`。
- 任务项列表接口继续保留 `task_id`、`media_type`、`status`、`confirm_state`、
  `page` 和 `page_size` 查询参数约束。

## 用例

1. `GET /api/task-items/list` 路由函数不再使用 `int = Query(...)`、
   `str | None = Query(...)` 等 Cython 不兼容默认值写法。
2. `GET /api/task-items/list` 路由函数使用 `Annotated[..., Query(...)]`
   表达 FastAPI 查询参数校验。
3. `task_id` 小于等于 0 时仍返回请求参数校验错误。
4. `page` 小于 1 时仍返回请求参数校验错误。
5. `page_size` 大于 200 时仍返回请求参数校验错误。
6. 合法查询仍能返回任务项分页列表。

## 验证命令

```bash
.env/bin/python -m pytest tests/test_task_item_api.py
```

运行 pytest 后清理：

```bash
rm -rf .pytest_cache .pytest_tmp pytest-cache-files-*
```

# 上游接口与大模型错误日志测试清单

## 目标

- 调用上游客户端接口失败时，日志包含完整请求地址、请求参数、HTTP 状态码和响应内容。
- 调用大模型网关失败时，日志包含完整请求地址、请求负载、HTTP 状态码和响应内容。
- 请求异常、非 JSON 响应、业务错误响应都能在日志中留下足够排查的信息。

## 用例

1. 客户端登录失败日志包含登录地址、请求参数、HTTP 状态码和响应内容。
2. 客户端刷新 token 失败日志包含刷新地址、HTTP 状态码和响应内容。
3. 通用上游接口请求异常日志包含请求地址、请求参数、请求方法和异常信息。
4. 通用上游接口返回非 200 日志包含请求地址、请求参数、请求方法、HTTP 状态码和响应内容。
5. 任务分页、详情接口解析非 JSON 或业务错误时，日志包含接口地址、响应状态和响应内容。
6. 任务文件下载失败日志包含完整下载地址、HTTP 状态码和响应内容。
7. 大模型探测请求异常日志包含候选地址、请求头和异常信息。
8. 大模型非流式调用失败日志包含候选地址、请求负载、HTTP 状态码和响应内容。
9. 大模型流式调用失败日志包含候选地址、请求负载、HTTP 状态码和响应内容。

## 验证命令

```bash
.env/bin/python -m pytest tests/test_client_auth.py tests/test_multimodal_model_api.py tests/test_task_celery_execution.py
```

运行 pytest 后清理：

```bash
rm -rf .pytest_cache .pytest_tmp pytest-cache-files-*
```

# 任务项失败补偿与下载重试测试清单

## 目标

- 单个文件下载失败不再中断整批任务。
- 单个大模型识别失败不再中断整批任务。
- 文件下载失败统一重试 3 次，不按 HTTP 状态码区分是否重试。
- 定时补偿任务能自动恢复下载失败和识别失败的任务项。
- 补偿任务复用 `TaskExecution` 执行记录，并与普通任务互斥。
- 单个任务项补偿达到最大次数后，不再继续自动补偿。

## 用例

1. 文件下载发生请求异常时，最多尝试 3 次，最终失败后记录完整错误。
2. 文件下载返回任意非 200 状态码时，最多尝试 3 次，不区分 400 或 500。
3. 单个 TaskItem 下载失败后，`down_state=False`、`status=失败`、`down_error` 有错误详情。
4. 下载阶段遇到单项失败后继续处理后续 TaskItem，不抛出整批任务异常。
5. 大模型阶段遇到未下载 TaskItem 时跳过该项，并继续处理后续 TaskItem。
6. 单个 TaskItem 大模型识别失败后，`llm_state=识别失败`、`status=失败`、
   `llm_error` 有错误详情。
7. 识别阶段遇到单项失败后继续处理后续 TaskItem，不抛出整批任务异常。
8. 主流程结束时若存在可复核项，任务进入 `核查`；若全部失败，任务进入 `失败`。
9. Beat 扫描任务能发现存在下载失败或识别失败项的任务，并提交补偿执行。
10. 补偿执行能重新下载 `down_state=False` 的任务项。
11. 补偿执行能重新识别 `down_state=True` 且 `llm_state=识别失败` 的任务项。
12. 补偿任务执行期间写入 `Task.current_execution_id`，避免和普通任务并发执行。
13. 补偿任务结束后释放 `Task.current_execution_id` 并写入执行记录成功或失败状态。
14. 补偿任务日志包含 task_id、execution_id、task_item_id、下载/识别结果和错误详情。
15. 单个 TaskItem 每执行一次补偿，`compensation_count` 递增 1。
16. `compensation_count >= 3` 的失败 TaskItem 不再被 Beat 补偿扫描命中。
17. 所有失败 TaskItem 都达到补偿上限时，不再创建 `repair` 执行记录。
18. `POST /api/tasks/action-reset-compensation/{task_id}` 只允许任务下存在达到补偿上限的失败项时调用。
19. 补偿恢复接口会把达到上限的失败 TaskItem `compensation_count` 重置为 0。
20. 补偿恢复接口成功后立即创建 `repair` 执行记录并投递补偿任务。
21. 任务下没有达到补偿上限的失败项时，补偿恢复接口返回参数错误。

## 验证命令

```bash
.env/bin/python -m pytest tests/test_task_celery_execution.py
```

运行 pytest 后清理：

```bash
rm -rf .pytest_cache .pytest_tmp pytest-cache-files-*
```

# 任务级 Celery 后台提交保存测试清单

## 目标

- 远端提交和训练数据保存统一按任务发起，不再提供单个 TaskItem 提交或旧批量提交接口。
- API 只创建任务级提交记录并投递 Celery，实际提交保存由后台 Worker 执行。
- 前端复核页使用任务级“提交保存”入口，并轮询任务提交进度。

## 用例

1. `POST /api/tasks/action-submit/{task_id}` 创建 `TaskSubmission`，立即返回 `queued` 状态。
2. 同一任务已有 `queued/running` 提交流程时，再次提交返回 409，并带回当前提交记录。
3. Celery 执行任务级提交时，只处理已确认且 `remote_state` 为 `待提交` 或 `提交失败` 的 TaskItem。
4. 单个 TaskItem 提交失败不阻断后续项，最终状态按成功/失败/跳过统计生成。
5. `GET /api/tasks/submission-detail/{submission_id}` 返回进度、当前处理项和错误摘要。
6. `GET /api/tasks/submission-current/{task_id}` 返回当前未结束提交流程；没有时返回空。
7. `POST /api/task-items/action-submit` 和 `POST /api/task-items/action-submit-task` 不再注册，访问返回 404。
8. 删除任务时同步删除对应 `TaskSubmission`，避免外键阻塞。
9. 前端不再引用旧 TaskItem 提交接口，不再展示单条提交远端或批量提交远端。
10. 前端复核页展示任务级提交保存按钮和后台进度。

## 验证命令

```bash
.env/bin/python -m pytest tests/test_task_item_api.py tests/test_task_celery_execution.py tests/test_frontend_taskitem_contract.py
cd aiSelfTestUi && npm run lint
```

运行 pytest 后清理：

```bash
rm -rf .pytest_cache .pytest_tmp pytest-cache-files-*
```

# 提交训练保存目录重构测试清单

## 目标

- 提交训练成功后，训练文件保存到可配置的训练保存目录。
- 训练保存目录按 `YYYYMMDD_AI自检_模块中文_保存/租户名称/设备名称` 分层。
- 图片和视频均保存媒体文件同名主干的 `.datajson`。
- 视频额外保存媒体文件同名主干的 `.videojson`；找不到源 `*.videojson` 时只记录警告，不影响保存成功。

## 用例

1. `AI_SELF_TEST_TRAINING_SAVE_DIR` 可覆盖默认训练保存目录。
2. 未配置训练保存目录时，默认使用 `data_dir/training`。
3. 图片提交训练后，保存到 `训练保存目录/YYYYMMDD_AI自检_红外相机_保存/租户名称/设备名称`。
4. 图片 `.datajson` 文件名不带原媒体后缀，例如 `image.datajson`。
5. `.datajson` 内容来自 `TaskItemData`，字段包含 `score`、`detScore`、`miny`、
   `trackIds`、`minx`、`maxy`、`maxx`、`name`、`type`、`detName`，且 `type` 固定为 `0`。
6. 视频提交训练后，额外把同目录 `*.videojson` 保存为媒体文件同名主干的 `.videojson`。
7. 视频源目录缺少 `*.videojson` 时，仅记录警告，`train_state` 仍为 `已保存`。

## 验证命令

```bash
.env/bin/python -m pytest tests/test_app_config.py tests/test_task_item_api.py
```

运行 pytest 后清理：

```bash
rm -rf .pytest_cache .pytest_tmp pytest-cache-files-*
```

# 客户端认证 expiresIn 绝对时间戳测试清单

## 目标

- 上游登录接口返回的 `expiresIn` 支持绝对时间戳。
- 13 位毫秒级绝对时间戳入库前转换为 10 位秒级时间戳。
- 10 位秒级绝对时间戳保持不变。
- 兼容既有秒级过期时长，例如 `3600` 仍按当前时间加 3600 秒处理。
- 不修改数据库字段结构。

## 用例

1. 登录响应返回 13 位毫秒级 `expiresIn` 时，认证接口返回成功。
2. 13 位毫秒级 `expiresIn` 保存到 `client.expires_at` 前会除以 1000。
3. 10 位秒级绝对时间戳保存时不再叠加当前时间。
4. 小于绝对时间戳阈值的 `expiresIn` 继续按过期时长处理。

## 验证命令

```bash
.env/bin/python -m pytest tests/test_client_auth.py
```

运行 pytest 后清理：

```bash
rm -rf .pytest_cache .pytest_tmp pytest-cache-files-*
```

## 目标

- 多模态模型探测只调用 OpenAI 标准 `/v1/models`。
- 多模态聊天只调用 OpenAI 标准 `/v1/chat/completions`。
- 不再兼容去掉 `/v1` 后的 `/models` 与 `/chat/completions`。
- 认证头只使用 OpenAI 标准 `Authorization: Bearer <api_key>`。
- 不再兼容 `X-API-Key` 与 `api-key` 认证头。

## 用例

1. 输入网关根地址时，模型探测只生成 `/v1/models` 候选地址。
2. 输入网关根地址时，聊天调用只生成 `/v1/chat/completions` 候选地址。
3. 输入完整 `/v1/chat/completions` 地址时，模型探测仍推导为 `/v1/models`。
4. 模型探测请求只发送 `Authorization: Bearer <api_key>` 认证头。

## 验证命令

```bash
.env/bin/python -m pytest tests/test_multimodal_model_api.py
```

运行 pytest 后清理：

```bash
rm -rf .pytest_cache .pytest_tmp pytest-cache-files-*
```

# TaskExecutionRunner 大模型识别与匹配测试清单

# 删除任务同步清理下载文件测试清单

## 目标

- 删除任务时，除清理 `task`、`task_item`、`task_item_data` 数据外，同步删除该任务下载目录。
- 文件清理必须限制在 `AI_SELF_TEST_DATA_DIR/task_files` 内，避免误删任意路径。
- 前端删除任务时必须重点提示“任务数据和已下载文件都会删除”，并要求用户再次确认。

## 用例

1. 删除任务成功后，对应 `TaskItem.file_path` 所在任务下载目录被删除。
2. 删除任务时，`TaskItem.file_path` 不存在或为空不会影响数据库删除。
3. 删除任务时，位于 `task_files` 外部的路径不会被删除。
4. 任务管理页面删除确认文案明确包含“任务数据”“已下载文件”“不可恢复”。

## 验证命令

```bash
.env/bin/python -m pytest tests/test_task_celery_execution.py tests/test_frontend_contract_static.py
```

运行 pytest 后清理：

```bash
rm -rf .pytest_cache .pytest_tmp pytest-cache-files-*
```

## 目标

- `TaskExecutionRunner.run` 按“分页拉取 -> 新增/跳过 -> 详情入库 -> 下载 -> 模型识别”顺序执行。
- 大模型统一返回 `{width,height,data}`，不再按 `TaskItemData.id` 返回名称。
- 图片分支整图识别后按 bbox IoU 匹配，支持默认、修改、删除、新增。
- 视频识别方式支持配置开关，默认使用整帧识别，可切回旧的逐行裁剪识别。
- 整帧视频分支按整个视频从 `*.videojson` 全局选择最多 30 帧原始整图。
- 整帧视频分支尽量让每个 `track_id` 覆盖 3 帧，优先目标数量多和目标面积大的帧。
- `*.videojson` 不发给大模型，其中 `name / errorName / detName` 不参与最终名称判定。
- 视频分支不产生新增，只按每条 `TaskItemData` 判定默认、修改、删除。
- 大模型识别阶段必须先处理所有图片任务项，再处理视频任务项。
- 大模型聊天调用使用独立超时配置，避免整帧视频识别被 30 秒全局请求超时提前中断。

## 用例

1. 自动任务首次执行时，分页数据按 `file_id` 写入 `task_item`，详情 `recordData` 写入 `task_item_data`。
2. 第二次执行遇到相同 `file_id` 时跳过，即使 `file_fid` 不同也不新增。
3. 两条数据 `file_fid` 相同但 `file_id` 不同时，允许作为不同 `TaskItem` 新增。
4. 详情接口使用 `GET /openApi/icFile/getResultDetByFileId`，并通过 `params={"fileId": file_id}` 传参。
5. 所有新增项先完成 `TaskItemData` 入库，再进入下载阶段。
6. 自动任务下载后调用大模型识别，手动任务下载后保持 `llm_state=待识别`。
7. 代码中不再保留 `RequestFunc = Callable[..., Response]` 和 `request_func` 注入参数。
8. 图片模型返回 bbox 与原始 bbox IoU 命中且名称不同，原始行标记为 `修改`。
9. 图片模型返回 bbox 未命中任何原始 bbox，新增 `TaskItemData` 并标记为 `新增`。
10. 图片模型返回空 `data`，原始行标记为 `删除`。
11. 视频 `videojson` 二维数组可按 `TaskItemData.track_ids` 命中多条 track detection。
12. 环境变量 `VIDEO_RECOGNITION_MODE=full_frame` 时，视频默认走整帧识别。
13. 环境变量 `VIDEO_RECOGNITION_MODE=crop_per_row` 时，视频切回旧的逐行裁剪识别。
14. 整帧视频关键帧最多 30 帧，每帧抽取原始整图并单独调用一次大模型。
15. 整帧视频关键帧尽量让每个 track 覆盖 3 次，优先选择覆盖未达标 track 多、
    同帧目标数量多、bbox 面积大的帧。
16. 整帧模型返回 bbox 与当前帧 videojson detection bbox IoU 命中后，反查 trackId 并写回对应 TaskItemData。
17. 整帧视频多帧命中同一行时按名称投票，票数相同用 bbox 面积更大的命中结果。
18. 旧裁剪视频关键帧最多 5 帧，包含首帧、末帧、bbox 最大帧、score 最高帧、时间中位帧。
19. 视频模型返回空 `data` 时，对应 `TaskItemData` 标记为 `删除`。
20. 视频模型返回名称与 `TaskItemData.name` 不同时，对应行标记为 `修改`。
21. 视频分支不创建 `新增` 行。
22. 单个 TaskItem 大模型识别遇到网关临时异常时，最多重试 3 次。
23. 某次识别重试成功后，任务继续执行并进入人工复核阶段。
24. 多次重试仍失败时，仅该 TaskItem 标记为识别失败，任务整体按原逻辑失败并记录错误。
25. 即使视频 TaskItem 先入库，大模型识别阶段也必须先识别全部图片，再识别视频。
26. 大模型聊天调用默认超时为 120 秒，并支持 `MODEL_CHAT_TIMEOUT_SECONDS` 环境变量覆盖。
27. 模型探测、文件下载等其它请求继续使用全局 `request_timeout_seconds`，不受聊天超时影响。

## 验证命令

```bash
.env/bin/python -m pytest tests/test_task_celery_execution.py
```

运行 pytest 后清理：

```bash
rm -rf .pytest_cache .pytest_tmp pytest-cache-files-*
```

# API 层直接实现业务测试清单

## 目标

- `api/task.py` 不再通过 `TaskService(session)` 或 `TaskItemService(session)` 中转。
- `api/multimodal_model.py` 不再通过 `MultimodalModelService(session)` 或
  `MultimodalChatService(session)` 中转。
- 两个 API 文件直接实现当前路由对应业务流程，同时继续复用非中转型工具类。
- 路由路径、响应结构、错误码和已有行为保持不变。

## 用例

1. `api/task.py` 内直接完成任务列表、创建、详情、更新、删除、启动、停止和立即执行。
2. `api/task.py` 内直接完成任务项列表、详情、确认、跳过、复核行更新、单项提交和任务级批量提交。
3. `api/multimodal_model.py` 内直接完成模型配置 CRUD 和模型探测。
4. `api/multimodal_model.py` 内直接完成非流式聊天、流式聊天、会话列表、会话详情和会话删除。
5. `api/task.py` 不再出现 `TaskService(` 或 `TaskItemService(`。
6. `api/multimodal_model.py` 不再出现 `MultimodalModelService(` 或 `MultimodalChatService(`。

## 验证命令

```bash
.env/bin/python -m pytest tests/test_task_celery_execution.py tests/test_task_item_api.py tests/test_task_celery_execution.py tests/test_multimodal_model_api.py
```

运行 pytest 后清理：

```bash
rm -rf .pytest_cache .pytest_tmp pytest-cache-files-*
```

# 真实远端提交与整型 file_id 测试清单

# 批量大模型重新识别测试清单

## 目标

- 复核页面支持按选中任务项批量重新识别。
- 支持按任务重新识别所有 `llm_state=识别失败` 的任务项。
- 批量重新识别异步执行，API 快速返回批量执行记录。
- 批量执行可查询进度，包含总数、成功数、失败数、跳过数和当前任务项。
- 已提交、已跳过、识别中、未下载的任务项不进入重新识别执行。
- 重新识别前清理旧大模型结果和旧模型新增行，避免重复新增。
- 单个任务项失败不影响同批次后续任务项。

## 用例

1. `POST /api/task-items/action-re-recognize-batch` 支持 `scope=selected` 和 `task_item_ids`。
2. `scope=selected` 至少需要一个任务项 ID。
3. `scope=failed` 通过 `task_id` 选择该任务下所有识别失败任务项。
4. 批量记录包含 `queued/running/success/partial_failed/failed` 状态和进度计数。
5. 创建批量记录后投递 Celery 任务，并返回 `batch_id` 和初始进度。
6. `GET /api/task-items/re-recognize-batch-detail/{batch_id}` 返回批量进度。
7. 已提交到远端的任务项自动跳过。
8. 正在识别中的任务项自动跳过。
9. 未下载或缺少本地文件的任务项记为失败。
10. 重新识别会删除旧的 `新增` 行，并重置原始行的 `llm_name/status`。
11. 重新识别成功后任务项进入 `识别完成/待复核`。
12. 重新识别失败后任务项进入 `识别失败` 并写入 `llm_error`。
13. 单项失败时批量继续处理后续项，最终状态为 `partial_failed`。
14. 前端任务项列表支持多选并触发批量重新识别。
15. 前端支持“重新识别失败项”，并展示批量进度。

## 验证命令

```bash
.env/bin/python -m pytest tests/test_task_item_re_recognition.py tests/test_task_item_api.py
```

运行 pytest 后清理：

```bash
rm -rf .pytest_cache .pytest_tmp pytest-cache-files-*
```

## 目标

- `TaskItem.file_id` 保存上游文件整数 `id`，不再保存字符串。
- 结果复核的“提交远端”真实调用客户端 `更新ai巡检结果` 接口。
- 远端响应 HTTP 200 且 JSON 为 `true` 时，才标记 `remote_state=已提交`。
- 远端失败时标记 `remote_state=提交失败`，保留可重试状态。

## 用例

1. `TaskItem.file_id` 模型字段为整数，唯一约束仍为 `task_id + file_id`。
2. Alembic 迁移将 `task_item.file_id` 从字符串改为整数。
3. 任务执行从上游分页 `id` 解析出整数 `file_id` 并落库。
4. 上游分页 `id` 缺失或不是整数时，任务执行失败并给出明确错误。
5. `ClientApi.update_ai_polling_result()` 调用 `/openApi/icFile/aiPollingResult`。
6. 提交 payload 顶层为 `{"id": task_item.file_id, "recordData": [...]}`。
7. `recordData` 不包含单条记录 `id` 字段。
8. `默认` 行提交原始 `name`。
9. `修改` 与 `新增` 行提交 `llm_name`。
10. `删除` 行不进入 `recordData`，最终无结果时提交空数组。
11. 远端返回 `true` 后，TaskItem 才进入 `已完成 / 已提交`。
12. 远端返回 `false` 或 HTTP 500 时，TaskItem 进入 `提交失败` 且不进入 `已完成`。
13. 批量提交能继续处理后续项，并正确统计成功与失败。

## 验证命令

```bash
.env/bin/python -m pytest tests/test_client_auth.py tests/test_task_celery_execution.py tests/test_task_item_api.py tests/test_task_model_contract.py
```

运行 pytest 后清理：

```bash
rm -rf .pytest_cache .pytest_tmp pytest-cache-files-*
```

# 视频 videojson 前端绘框测试清单

## 目标

- 后端不解析 `.videojson` 内容，只向前端暴露视频结果文件 URL。
- 后端在复核行中返回 `TaskItemData.track_ids`，供前端匹配轨迹。
- 前端读取 `.videojson`，按视频当前帧和 `track_ids` 筛选 bbox 并叠加绘制。
- 视频叠框编号必须对应右侧详细结果中的 `结果 1`、`结果 2` 行序号。
- 绘框颜色只用于区分每条结果，结果列表中的编号必须使用相同颜色。
- 结果状态使用文字、图标和框线样式区分，不再占用结果对应色。
- 视频绘框优先覆盖画廊视图和预览弹窗，列表和网格可保持轻量预览。

## 用例

1. 视频 TaskItem 详情接口的 `media.result_file_url` 返回本地 `.videojson` 静态 URL。
2. 图片 TaskItem 详情接口的 `media.result_file_url` 返回 `null`。
3. TaskItem 详情接口的每条 `review_rows` 返回 `track_ids`。
4. 前端类型包含 `track_ids`、`trackIds`、`resultFileUrl` 与视频 detection 类型。
5. 前端通过 `fetch(item.resultFileUrl)` 加载 `.videojson`，并处理加载失败。
6. 前端按 `TaskItemData.track_ids` 与 `.videojson.trackId` 匹配当前帧 detection。
7. 前端按视频 `videoWidth/videoHeight` 将 bbox 像素坐标换算为百分比绘制。
8. 画廊视图和预览弹窗使用视频叠框组件，不再直接裸渲染视频。
9. 前端同时支持 `.videojson` 外层帧序号和 detection.index 建立帧索引。
10. 当前播放帧没有 detection 时，前端使用最近有效帧的 detection 保持连续绘制，
    避免只在少数关键帧闪现。
11. 前端缓存已排序帧号，不在每次动画帧中重新扫描全部 `.videojson`。
12. 视频全屏时必须全屏外层叠框容器，而不是只全屏 `<video>` 元素。
13. 全屏容器内继续显示 bbox overlay，并提供进入/退出全屏按钮。
14. 当 `.videojson` 当前帧 detection 顺序与 `review_rows` 顺序不一致时，叠框文本
    仍按匹配到的详细结果行显示 `1`、`2` 等序号。
15. 图片和视频绘框通过结果序号选择颜色，结果列表 `结果 N` 编号使用同一颜色。
16. `默认/新增/修改/删除` 状态通过状态徽标、图标和边框线型区分。

## 验证命令

```bash
.env/bin/python -m pytest tests/test_task_item_api.py tests/test_frontend_taskitem_contract.py
cd aiSelfTestUi && npm run lint
```

运行 pytest 后清理：

```bash
rm -rf .pytest_cache .pytest_tmp pytest-cache-files-*
```

# 多模态聊天会话删除测试清单

## 目标

- 删除聊天会话接口返回统一 API 响应结构，`data` 必须是 Pydantic 对象。
- 删除成功后同步删除会话消息，避免残留历史消息。
- 重复删除或删除不存在会话时返回统一 404 业务错误，不再记录为数据库会话异常。

## 用例

1. `DELETE /api/multimodal-models/delete-session/{session_id}` 成功时返回
   `{"id": session_id}`。
2. 删除成功后，`multimodal_chat_session` 与 `multimodal_chat_message` 均无对应记录。
3. 再次查询或删除同一会话时返回 `404`，错误码为 `1002`。

## 验证命令

```bash
.env/bin/python -m pytest tests/test_multimodal_model_api.py
```

运行 pytest 后清理：

```bash
rm -rf .pytest_cache .pytest_tmp pytest-cache-files-*
```

# client_auth token 失效重登测试清单

## 目标

- `ClientApi.post_with_retry` 遇到上游返回 401 或 token 失效提示时，清理旧 token。
- 清理旧 token 后立即重新认证，并使用新 access token 重试原业务接口。
- 非 token 错误响应不能被误判为登录失效，避免正常 200 响应触发无效重试。

## 用例

1. `find_file_page` 首次业务请求返回 401 后，调用登录接口获取新 token。
2. 重登后使用新 token 再次请求原业务接口，并返回成功响应。
3. 数据库中的客户端 token 更新为重登返回的新 token。

## 验证命令

```bash
.env/bin/python -m pytest tests/test_client_auth.py
```

# build_upstream_page_payload 空值参数测试清单

## 目标

- 上游分页请求体只包含有实际值的筛选参数，`module` 除外。
- `None`、空字符串、空列表不写入上游分页请求体；`module` 为空时兜底为
  `camera`。
- 有值的筛选参数仍按既有字段名和转换规则写入。

## 用例

1. `keyword`、`sp_name`、`start_at`、`end_at` 为空字符串时，请求体不包含
   `keyword`、`spName`、`startTime`、`endTime`。
2. `classify_list`、`media_types`、`upload_types`、`identify_source` 为空列表时，
   请求体不包含对应上游字段。
3. `module` 为空字符串时，请求体包含 `module: "camera"`，确保默认按相机模块查询。
4. 筛选参数有值时，请求体继续包含对应上游字段，并保留分页与排序字段。

## 验证命令

```bash
.env/bin/python -m pytest tests/test_task_celery_execution.py
```

# Task 执行状态机与人工复核测试清单

## 目标

- `TaskExecutionStatus` 删除 `SUBMIT`，任务主流程只保留
  `CREATE -> DATA_LOAD -> DOWN -> LLM -> VERIFY -> FINISH / FAIL`。
- 新增 `TaskItemStatus` 枚举，统一约束 `TaskItem.status`。
- `auto_confirm` 字段更名为 `auto_execute`，语义改为自动执行前置流程，不再自动确认或提交。
- `total_count` 表示任务下所有 `TaskItem` 数量，`DATA_LOAD`、`DOWN`、`LLM`
  阶段不修改该值。
- `processed_count` 在 `DATA_LOAD`、`DOWN`、`LLM` 阶段开始时重置为 0，
  每完成或跳过一个 `TaskItem` 后递增；进入 `VERIFY` 后不重置。
- 最终提交给客户端必须人工确认，允许部分确认、部分提交，也允许跳过无需提交的数据。

## 用例

1. 自动执行任务创建后使用 `auto_execute=true`，自动跑完分页、详情、下载、LLM，并停在 `VERIFY`。
2. 手动任务创建后不自动执行，点击执行后跑完分页、详情、下载、LLM，并停在 `VERIFY`。
3. `TaskExecutionStatus` 中不存在 `SUBMIT`，运行中状态包含 `CREATE`、`DATA_LOAD`、`DOWN`、`LLM`。
4. `TaskItem.status` 使用 `TaskItemStatus` 枚举值，不再写入散落字符串。
5. `DATA_LOAD`、`DOWN`、`LLM` 阶段均不修改 `total_count`，只重置并更新 `processed_count`。
6. 未人工确认的 `TaskItem` 调用提交接口时返回参数错误。
7. 人工确认后的 `TaskItem` 可以提交，提交成功后该 item 进入完成态。
8. 人工跳过的 `TaskItem` 不提交客户端，但算作完成态。
9. 部分确认、部分跳过后，所有 item 都达到完成态时，`Task.execution_status=FINISH`。
10. 任一阶段失败后，重新执行按数据库中 item 实际状态恢复，不重复处理已完成阶段。
11. `TaskItem.llm_state`、`confirm_state`、`remote_state`、`train_state`
    均通过模型枚举统一定义，服务层不再散落硬编码状态字符串。
12. `TaskItemLlmState` 使用中文值：`待识别`、`识别中`、`识别完成`、`识别失败`。
13. `TaskItemConfirmState` 使用中文值：`待确认`、`已确认`、`已跳过`。
14. `TaskItemRemoteState` 使用中文值：`待提交`、`已提交`、`提交失败`。
15. `TaskItemTrainState` 使用中文值：`待保存`、`已保存`、`保存失败`。
16. 结果复核页面的任务下拉必须展示 `核查` 状态任务，任务无需进入 `结束` 才能选择复核。

## 验证命令

```bash
.env/bin/python -m pytest tests/test_task_celery_execution.py tests/test_task_item_api.py tests/test_task_celery_execution.py tests/test_task_model_contract.py tests/test_frontend_taskitem_contract.py
```

# TaskItem 复核界面状态、绘框与统计修复测试清单

## 目标

- 复核行前端显示必须直接遵循 `TaskItemDataStatus`，不能把 `新增` 误显示为 `改名`。
- TaskItem 详情接口必须返回 `TaskItemData` 的 bbox 和图片尺寸，供前端绘制识别框。
- 复核页提交数量统计 `默认`、`新增`、`修改`，排除数量只统计 `删除`。
- 复核页不展示无意义的 `定位：task-item` 文案。

## 用例

1. `GET /api/task-items/detail/{id}` 返回复核行时，包含 `bbox` 和 `source_size`。
2. `review_summary.submit_count` 统计状态为 `默认`、`新增`、`修改` 的行。
3. `review_summary.exclude_count` 只统计状态为 `删除` 的行。
4. 前端 `TaskItemReviewRow` 类型包含 `bbox`、`source_size`。
5. 前端 `toReviewRow` 保留 `sourceStatus`，并按 `默认`、`新增`、`修改` 计算待提交数量。
6. 前端状态标签显示 `sourceStatus`，不再将 `新增` 显示为 `改名`。
7. 前端复核行不再输出 `定位：task-item`。

## 验证命令

```bash
.env/bin/python -m pytest tests/test_task_item_api.py tests/test_frontend_taskitem_contract.py
cd aiSelfTestUi && npm run lint
```

# Dashboard 真实统计接口测试清单

## 目标

- `GET /api/dashboard/stats` 不再返回固定假数据。
- 总览统计基于 `Task` 与 `TaskItem` 当前数据库状态实时计算。
- 返回结构保持前端兼容字段：`activeTasks`、`processedToday`、`pendingReviews`、
  `anomalies`、`recentActivities`。

## 用例

1. 无任务数据时，所有统计数量为 0，近期活动为空列表。
2. `activeTasks` 统计执行状态处于运行阶段的任务数量。
3. `processedToday` 统计当天已确认、已跳过、已完成的复核项数量。
4. `pendingReviews` 统计待确认复核项数量。
5. `anomalies` 统计执行状态为失败的任务数量。
6. `recentActivities` 返回最近完成任务摘要，按完成时间倒序排列。

## 验证命令

```bash
.env/bin/python -m pytest tests/test_client_api.py tests/test_dashboard_api.py
```

# 任务详情筛选条件展示测试清单

## 目标

- 任务详情页“任务保存筛选条件”展示内容与创建任务筛选条件保持一致。
- 展示字段包括识别分类、关键词、物种名称、文件格式、识别类型、上传类型、
  开始时间、结束时间、模块。
- 识别分类、文件格式、识别类型、上传类型必须显示中文标签，不直接显示原始值。
- 模块筛选为单选字段，默认值为红外相机 `camera`，可选值为红外相机、喂鸟器、
  摄像头。

## 用例

1. 任务详情页展示 `识别分类`，并通过 `classifyOptions` 转换为中文。
2. 任务详情页展示 `文件格式`，并通过 `fileBmpOptions` 转换为中文。
3. 任务详情页展示 `识别类型`，将 `identify_source` 转换为 `AI 识别 / 人工识别`。
4. 任务详情页展示 `上传类型`，将 `upload_types` 转换为中文上传来源。
5. 任务详情页分别展示 `开始时间` 和 `结束时间`，不再合并为单个时间字段。
6. 创建任务页展示模块单选，默认选择红外相机。
7. 创建任务请求将 `filters.module` 保存为 `camera`、`lure` 或 `video`。
8. 任务管理卡片展示模块中文标签。
9. 任务详情页展示模块中文标签。
10. 任务执行上游分页 payload 使用保存的单值 `module`。

## 验证命令

```bash
.env/bin/python -m pytest tests/test_task_celery_execution.py tests/test_frontend_contract_static.py tests/test_frontend_taskitem_contract.py
cd aiSelfTestUi && npm run lint
```

# 任务详情顶部布局压缩测试清单

## 目标

- 任务详情页顶部任务摘要与筛选条件两块内容重新排版，降低高度占用。
- 筛选条件采用紧凑网格展示，保留完整字段和值。
- TaskItem 列表在首屏获得更多可见空间。

## 用例

1. 任务摘要卡片使用更小内边距、字号和间距。
2. 筛选条件卡片按多列紧凑展示 8 个筛选字段。
3. 列表容器仍保持 `flex-1 min-h-0`，不被顶部区域挤压。

## 验证命令

```bash
cd aiSelfTestUi && npm run lint
```

# 任务管理按钮布局与语义测试清单

## 目标

- 任务管理卡片中的 `查看任务详情`、`结果复核`、`立即执行` 按钮文本不换行。
- 自动调度开关与立即执行区分展示，避免误以为两个按钮功能相同。
- 保留启动/停止调度路由和立即执行路由，确保两类操作都可访问。

## 用例

1. 文本按钮使用 `whitespace-nowrap` 防止中文按钮文案折行。
2. 自动调度按钮显示为 `启用调度 / 暂停调度`，不再只显示播放图标。
3. `立即执行` 按钮继续调用 `/api/tasks/action-run/{id}`。

## 验证命令

```bash
.env/bin/python -m pytest tests/test_frontend_contract_static.py
cd aiSelfTestUi && npm run lint
```

# 运行日志接管测试清单

## 目标

- API 进程接管 Uvicorn 与 Alembic 的标准 logging 输出。
- Celery Worker 与 Beat 进程接管 Celery 的标准 logging 输出。
- API、Worker、Beat 继续分别写入 `api.log`、`worker.log`、`beat.log`。
- 避免标准 logging 与 loguru 重复输出同一条日志。

## 用例

1. `configure_deploy_file_logging("api")` 配置文件日志后，可安装标准 logging 拦截器。
2. 标准 logging 的 info 事件应转发到 loguru sink。
3. 被接管的 logger 不保留原有 handler，避免重复输出。
4. `server.main()` 启动 Uvicorn 时禁用默认 `log_config`。
5. Celery 配置禁止 hijack root logger，并保留 stdout 重定向。

## 验证命令

```bash
.env/bin/python -m pytest tests/test_logging_intercept.py tests/test_static_frontend_serving.py
.env/bin/python -m py_compile aiSelfTest/aiSelfTest/logging.py aiSelfTest/aiSelfTest/server.py aiSelfTest/aiSelfTest/worker.py aiSelfTest/aiSelfTest/celery_app.py
```

# FastAPI 接口文档关闭测试清单

## 目标

- 生产运行不暴露 Swagger UI、ReDoc 和 OpenAPI JSON。
- `/health` 与业务 `/api/...` 接口保持可用。
- 前端根路径 `/` 继续返回静态页面。

## 用例

1. `/docs` 返回 404。
2. `/redoc` 返回 404。
3. `/openapi.json` 返回 404。
4. `/health` 继续返回 `{"status": "ok"}`。

## 验证命令

```bash
.env/bin/python -m pytest tests/test_client_api.py::test_fastapi_documentation_routes_are_disabled
```

# 任务管理状态与运行指标测试清单

## 目标

- 任务管理卡片中的状态标签不换行。
- 后端已实现的 `skipped_count` 返回给前端，用于展示跳过重复项。
- 预计剩余时间当前未实现，前端应明确显示未提供，而不是伪装成真实估算。

## 用例

1. `TaskResponse` 返回 `skipped_count`。
2. 前端任务类型包含 `skipped_count`，任务卡片展示真实跳过重复项数量。
3. 状态标签使用 `whitespace-nowrap` 防止换行。
4. 预计剩余时间显示 `暂未估算`。

## 验证命令

```bash
.env/bin/python -m pytest tests/test_task_celery_execution.py tests/test_frontend_contract_static.py
cd aiSelfTestUi && npm run lint
```

# 任务管理预计剩余时间测试清单

## 目标

- 后端为任务列表和任务详情返回 `estimated_remaining_seconds`。
- 预计剩余时间表示当前执行阶段的本轮剩余耗时，不表示下次自动调度时间。
- 前端任务管理卡片展示后端估算结果，无法估算时给出明确占位。

## 用例

1. `TaskResponse` 包含 `estimated_remaining_seconds` 字段。
2. 运行中任务在有 `stage_started_at`、`last_progress_at`、`total_count`、
   `processed_count` 时返回大于 0 的剩余秒数。
3. `创建`、`核查`、`结束`、`失败` 或未开始任务返回 `null`。
4. 任务执行进入新阶段时记录 `stage_started_at`，单项进度推进时记录
   `last_progress_at`。
5. 前端任务类型包含 `estimated_remaining_seconds`，任务卡片有值时展示
   格式化的 `约 ...`，运行中但无值时展示 `计算中`，非运行状态显示
   `暂未估算`。

## 验证命令

```bash
.env/bin/python -m pytest tests/test_task_celery_execution.py tests/test_frontend_contract_static.py
cd aiSelfTestUi && npm run lint
```

# 结果复核页面重构测试清单

## 目标

- 结果一致的 TaskItem 在后端自动标记为跳过，但复核页面仍可查看。
- 结果复核页面允许逐条修改 `TaskItemData.status` 与 `TaskItemData.llm_name`。
- `TaskItemData.name` 保持只读，作为原始识别名称展示。
- 确认只做人审确认，不提交远端；远端提交使用独立按钮和接口。
- 批量提交远端是任务级操作，不依赖页面多选，并一次处理当前任务下所有待提交和提交失败的已确认项。
- 彻底删除 `/api/task-items/action-delete` 与 `/api/reviews/*` 兼容接口。
- 禁用“删除复核差异 / 移除差异 / 批量移除差异”语义。

## 用例

1. 大模型识别后，所有 `TaskItemData.status` 均为 `默认` 的 TaskItem 自动变为
   `已跳过 / 已跳过`。
2. 存在 `新增 / 修改 / 删除` 的 TaskItem 保持 `待复核 / 待确认`。
3. `POST /api/task-items/action-update-row` 可以修改指定明细的 `status` 和
   `llm_name`，且不能修改不属于当前 TaskItem 的明细。
4. 已完成远端提交的 TaskItem 不允许继续修改复核明细。
5. 修改复核明细后，TaskItem 的确认状态会按一致性重新计算。
6. `POST /api/task-items/action-confirm` 只设置 `已确认 / 已确认`，
   `remote_state` 仍为 `待提交`。
7. `POST /api/task-items/action-reject` 设置 `已跳过 / 已跳过`，不提交远端。
8. `POST /api/task-items/action-submit` 只允许已确认且待提交或提交失败的项提交。
9. 提交成功后 TaskItem 变为 `已完成`，任务在所有项均为 `已跳过` 或
   `已完成` 后进入 `结束`。
10. `/api/task-items/action-delete` 不再注册，访问返回 404。
11. `/api/reviews/*` 不再注册，访问返回 404。
12. 前端不再引用 delete review API，不再展示“移除差异”相关文案。
13. 前端复核页包含跳过、批量跳过、提交远端、批量提交远端和逐行保存能力。
14. 前端批量提交远端不依赖多选，按当前任务一次提交全部可提交项。
15. 前端复核页支持按复核状态筛选：全部、待复核、已确认、跳过。

## 验证命令

```bash
.env/bin/python -m pytest tests/test_task_item_api.py tests/test_task_celery_execution.py tests/test_frontend_taskitem_contract.py
cd aiSelfTestUi && npm run lint
```

运行 pytest 后清理：

```bash
rm -rf .pytest_cache .pytest_tmp pytest-cache-files-*
```

# TaskItemData 检测分类与远端明细 ID 测试清单

## 目标

- `TaskItemData` 保存上游详情行 ID、原始检测分类和原始检测分数。
- 大模型返回 `detName` 时只写入 `llm_det_name`，不得覆盖原始 `det_name`。
- 远端提交时按复核状态合成最终 `detName`，并仅在有上游详情行 ID 时提交 `id`。

## 用例

1. `TaskItemData` 模型包含整型可空 `source_id` 字段。
2. `TaskItemData` 模型包含 `det_name`、`det_score`、`llm_det_name` 字段。
3. 拉取任务详情时，`recordData[].id / detName / detScore` 正确落库。
4. 复核详情接口返回 `source_id / det_name / det_score / llm_det_name`。
5. 大模型 `{width,height,data:[{name,detName,bbox}]}` 解析出 `detName`。
6. 图片 bbox 匹配写回 `llm_name / llm_det_name`，不覆盖 `det_name`。
7. 视频 bbox 匹配投票写回 `llm_name / llm_det_name`，不覆盖 `det_name`。
8. 远端提交 `默认` 行提交原始 `name / detName / detScore` 和上游明细 `id`。
9. 远端提交 `修改` 行提交 `llm_name`，`detName` 优先使用 `llm_det_name`，
   为空时兜底 `det_name`，并带上上游明细 `id`。
10. 远端提交 `新增` 行提交 `llm_name / llm_det_name / detScore=0`，且不提交 `id`。
11. 远端提交 `删除` 行不进入 `recordData`。
12. 前端复核类型与映射包含检测分类字段，页面可展示原始检测分类与模型检测分类。

## 验证命令

```bash
.env/bin/python -m pytest tests/test_task_model_contract.py tests/test_task_item_api.py tests/test_task_item_re_recognition.py tests/test_video_full_frame_recognition.py tests/test_frontend_taskitem_contract.py
cd aiSelfTestUi && npm run lint
```

运行 pytest 后清理：

```bash
rm -rf .pytest_cache .pytest_tmp pytest-cache-files-*
```

# 删除任务级联重识别批次测试清单

## 目标

- 删除任务时同步删除 `task_item_recognition_batch` 中关联任务的批量重新识别记录。
- 避免 PostgreSQL 外键 `task_item_recognition_batch_task_id_fkey` 阻止任务删除。

## 用例

1. 任务存在批量重新识别记录时，`DELETE /api/tasks/delete/{id}` 成功。
2. 删除任务后，对应 `TaskItemRecognitionBatch`、`TaskItemData`、`TaskItem` 均被清理。
3. 运行中或排队中的任务仍然按原逻辑禁止删除。

## 验证命令

```bash
.env/bin/python -m pytest tests/test_task_celery_execution.py tests/test_task_item_re_recognition.py
```

运行 pytest 后清理：

```bash
rm -rf .pytest_cache .pytest_tmp pytest-cache-files-*
```

# 大模型任务提示词透传测试清单

## 目标

- 任务执行使用用户配置的提示词作为唯一返回结构约束。
- 后端只追加通用 JSON 输出约束、文件名、图片尺寸和原始识别结果等上下文，不重复拼接固定 JSON 示例。

## 用例

1. `_build_task_recognition_prompt()` 返回内容以配置提示词开头。
2. 返回内容包含“只返回 JSON 对象，不要返回 Markdown”。
3. 返回内容包含 `文件名`、图片尺寸和原始识别结果上下文。
4. 返回内容不额外追加“没有动物、人、车时返回”和“有目标时返回”等固定格式说明。
5. 配置提示词中已有 `{width,height,data}` 和 `detName` 结构时，最终提示词只出现一次配置里的结构说明。

## 验证命令

```bash
.env/bin/python -m pytest tests/test_video_full_frame_recognition.py
```

运行 pytest 后清理：

```bash
rm -rf .pytest_cache .pytest_tmp pytest-cache-files-*
```

# Python 后端无引用 service class 清理测试清单

## 目标

- 删除已无调用方的 `TaskService`、`TaskItemService`、`MultimodalModelService`
  和 `MultimodalChatService`。
- 删除随上述 class 产生且已无调用方的配套 helper 模块。
- 保留仍被调用的网关、提交、调度、执行、复核等实际业务组件。
- API 响应结构、路由路径和已有行为保持不变。

## 用例

1. 后端代码中不再定义 `TaskService` 和 `TaskItemService`。
2. 后端代码中不再定义 `MultimodalModelService` 和 `MultimodalChatService`。
3. 后端代码中不再引用 `services/task.py`、`services/multimodal_chat.py`
   和 `services/multimodal_model_crud.py`。
4. `TaskSubmissionService`、`MultimodalGatewayClient`、`GatewayResponseParser`、
   `GatewayStreamParser` 和 `GatewayUrlBuilder` 保持可用。
5. 删除无引用 service class 后，任务 API、任务项 API、任务执行服务和多模态模型 API 继续通过回归测试。

## 验证命令

```bash
.env/bin/python -m pytest tests/test_task_celery_execution.py tests/test_task_item_api.py tests/test_task_celery_execution.py tests/test_multimodal_model_api.py
```

运行 pytest 后清理：

```bash
rm -rf .pytest_cache .pytest_tmp pytest-cache-files-*
```

# wheel 部署与 systemd 三服务测试清单

## 目标

- wheel 安装后提供 API、Celery Worker、Celery Beat 和 systemd 管理工具 CLI 入口。
- systemd 管理工具生成三个独立服务，分别管理 API、Worker 和 Beat。
- 三个服务统一读取 `/opt/aiSelfTest/aiSelfTest.env`，且该环境文件模板包含项目所有运行时配置。
- 本次只做静态与单元级验证，不执行 `setup_build.py`，不安装 wheel。

## 用例

1. `project.scripts` 包含 `aiSelfTestApi`、`aiSelfTestWorker`、`aiSelfTestBeat`
   和 `aiSelfTestSystemd` 四个 CLI 入口。
2. systemd 工具能生成 `aiSelfTest-api.service`、`aiSelfTest-worker.service`
   和 `aiSelfTest-beat.service`。
3. 三个 service 均引用同一个 `EnvironmentFile=/opt/aiSelfTest/aiSelfTest.env`。
4. API service 使用 `aiSelfTestApi` CLI 启动。
5. Worker service 使用 `aiSelfTestWorker` CLI 启动。
6. Beat service 使用 `aiSelfTestBeat` CLI 启动。
7. `install` 创建的 `aiSelfTest.env` 模板包含 `config.py` 中所有运行时配置变量。
8. 默认 service 目录使用 `/etc/systemd/system`。
9. `install` 写入 service 后自动执行 `systemctl enable` 开启自启。
10. 工具只支持 `install`、`uninstall`、`start`、`stop` 和 `restart` 子命令。
11. `start` 按 API、Worker、Beat 顺序启动三个服务。
12. `stop` 按 Beat、Worker、API 顺序停止三个服务。
13. `restart` 先按 Beat、Worker、API 顺序停止，再按 API、Worker、Beat 顺序启动。
14. 专用 API 启动入口先执行一次 Alembic 迁移，再启动 uvicorn workers。
15. FastAPI `lifespan` 不再执行数据库迁移，避免多 worker 重复迁移。
16. 部署入口配置文件日志时移除 loguru 默认控制台输出。
17. 部署入口分别写入 `logs/api.log`、`logs/worker.log` 和 `logs/beat.log`。
18. 部署日志不传自定义 `format`，保持 loguru 默认格式。
19. 开发入口不调用部署文件日志配置，保持默认控制台输出。
20. 未设置 `DATABASE_URL`、`REDIS_URL` 等运行配置时，导入 `aiSelfTest.systemd` 不应触发运行时配置加载。
21. 未设置运行配置时，`aiSelfTestSystemd install` 可渲染并写入 service/env 文件。
22. 未设置运行配置时，`aiSelfTestSystemd uninstall/start/stop/restart` 只执行 systemctl 管理动作，不加载应用运行配置。
23. `install` 遇到已存在的 `aiSelfTest.env` 时，不应重新创建或覆盖原文件内容。

## 验证命令

```bash
.env/bin/python -m pytest tests/test_systemd_deploy_static.py
```

运行 pytest 后清理：

```bash
rm -rf .pytest_cache .pytest_tmp pytest-cache-files-*
```
