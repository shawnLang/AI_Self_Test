# TaskExecutionRunner 大模型识别与匹配测试清单

## 目标

- `TaskExecutionRunner.run` 按“分页拉取 -> 新增/跳过 -> 详情入库 -> 下载 -> 模型识别”顺序执行。
- 大模型统一返回 `{width,height,data}`，不再按 `TaskItemData.id` 返回名称。
- 图片分支整图识别后按 bbox IoU 匹配，支持默认、修改、删除、新增。
- 视频分支按每条 `TaskItemData.track_ids` 从 `*.datajson` 抽取最多 5 帧裁剪图识别。
- `*.datajson` 不发给大模型，其中 `name / errorName / detName` 不参与最终名称判定。
- 视频分支不产生新增，只按每条 `TaskItemData` 判定默认、修改、删除。

## 用例

1. 自动任务首次执行时，分页数据按 `file_id` 写入 `task_item`，详情 `recordData` 写入 `task_item_data`。
2. 第二次执行遇到相同 `file_id` 时跳过，即使 `file_fid` 不同也不新增。
3. 两条数据 `file_fid` 相同但 `file_id` 不同时，允许作为不同 `TaskItem` 新增。
4. 详情接口使用 `GET /openApi/icFile/getResultByFileId1`，并通过 `params={"fileId": file_id}` 传参。
5. 所有新增项先完成 `TaskItemData` 入库，再进入下载阶段。
6. 自动任务下载后调用大模型识别，手动任务下载后保持 `llm_state=待识别`。
7. 代码中不再保留 `RequestFunc = Callable[..., Response]` 和 `request_func` 注入参数。
8. 图片模型返回 bbox 与原始 bbox IoU 命中且名称不同，原始行标记为 `修改`。
9. 图片模型返回 bbox 未命中任何原始 bbox，新增 `TaskItemData` 并标记为 `新增`。
10. 图片模型返回空 `data`，原始行标记为 `删除`。
11. 视频 `datajson` 二维数组可按 `TaskItemData.track_ids` 命中多条 track detection。
12. 视频关键帧最多 5 帧，包含首帧、末帧、bbox 最大帧、score 最高帧、时间中位帧。
13. 视频模型返回空 `data` 时，对应 `TaskItemData` 标记为 `删除`。
14. 视频模型返回名称与 `TaskItemData.name` 不同时，对应行标记为 `修改`。
15. 视频分支不创建 `新增` 行。
16. 单个 TaskItem 大模型识别遇到网关临时异常时，最多重试 3 次。
17. 某次识别重试成功后，任务继续执行并进入人工复核阶段。
18. 多次重试仍失败时，仅该 TaskItem 标记为识别失败，任务整体按原逻辑失败并记录错误。

## 验证命令

```bash
.env/bin/python -m pytest tests/test_task_execution_service.py
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
.env/bin/python -m pytest tests/test_task_execution_service.py
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
.env/bin/python -m pytest tests/test_task_execution_service.py tests/test_task_item_api.py tests/test_task_api.py tests/test_task_model_contract.py tests/test_frontend_taskitem_contract.py
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
  开始时间、结束时间。
- 识别分类、文件格式、识别类型、上传类型必须显示中文标签，不直接显示原始值。

## 用例

1. 任务详情页展示 `识别分类`，并通过 `classifyOptions` 转换为中文。
2. 任务详情页展示 `文件格式`，并通过 `fileBmpOptions` 转换为中文。
3. 任务详情页展示 `识别类型`，将 `identify_source` 转换为 `AI 识别 / 人工识别`。
4. 任务详情页展示 `上传类型`，将 `upload_types` 转换为中文上传来源。
5. 任务详情页分别展示 `开始时间` 和 `结束时间`，不再合并为单个时间字段。

## 验证命令

```bash
.env/bin/python -m pytest tests/test_frontend_taskitem_contract.py
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

# setup_build 使用当前 Python 环境测试清单

## 目标

- `setup_build` 构建 wheel 时使用当前运行环境的 Python 解释器。
- 构建命令不再根据系统写死为 `python` 或 `python3`。

## 用例

1. `setup_build` 调用构建命令时，第一个参数等于 `sys.executable`。
2. 构建命令参数包含 `-m build --wheel`，保持原有 wheel 构建行为。
3. Linux 与 Windows 分支只影响输出解码编码，不影响 Python 解释器选择。

## 验证命令

```bash
.env/bin/python -m pytest tests/test_build_utils.py
```

运行 pytest 后清理：

```bash
rm -rf .pytest_cache .pytest_tmp pytest-cache-files-*
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
.env/bin/python -m pytest tests/test_task_api.py tests/test_frontend_contract_static.py
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
.env/bin/python -m pytest tests/test_task_api.py tests/test_task_execution_service.py tests/test_frontend_contract_static.py
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
.env/bin/python -m pytest tests/test_task_item_api.py tests/test_task_execution_service.py tests/test_frontend_taskitem_contract.py
cd aiSelfTestUi && npm run lint
```

运行 pytest 后清理：

```bash
rm -rf .pytest_cache .pytest_tmp pytest-cache-files-*
```
