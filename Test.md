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

- 上游分页请求体只包含有实际值的筛选参数。
- `None`、空字符串、空列表不写入上游分页请求体。
- 有值的筛选参数仍按既有字段名和转换规则写入。

## 用例

1. `keyword`、`sp_name`、`start_at`、`end_at` 为空字符串时，请求体不包含
   `keyword`、`spName`、`startTime`、`endTime`。
2. `classify_list`、`media_types`、`upload_types`、`identify_source` 为空列表时，
   请求体不包含对应上游字段。
3. `module` 为空字符串时，请求体不包含 `module`，避免覆盖上游默认条件。
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
