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
6. 自动任务下载后调用大模型识别，手动任务下载后保持 `llm_state=pending`。
7. 代码中不再保留 `RequestFunc = Callable[..., Response]` 和 `request_func` 注入参数。
8. 图片模型返回 bbox 与原始 bbox IoU 命中且名称不同，原始行标记为 `修改`。
9. 图片模型返回 bbox 未命中任何原始 bbox，新增 `TaskItemData` 并标记为 `新增`。
10. 图片模型返回空 `data`，原始行标记为 `删除`。
11. 视频 `datajson` 二维数组可按 `TaskItemData.track_ids` 命中多条 track detection。
12. 视频关键帧最多 5 帧，包含首帧、末帧、bbox 最大帧、score 最高帧、时间中位帧。
13. 视频模型返回空 `data` 时，对应 `TaskItemData` 标记为 `删除`。
14. 视频模型返回名称与 `TaskItemData.name` 不同时，对应行标记为 `修改`。
15. 视频分支不创建 `新增` 行。

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
