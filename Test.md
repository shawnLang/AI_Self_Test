# TaskExecutionRunner 流程调整测试清单

## 目标

- `TaskItem` 新增 `file_id` 字段，并以 `task_id + file_id` 作为唯一检查依据。
- `file_fid` 字段保留，但不再参与本次任务执行去重。
- `TaskExecutionRunner.run` 按“分页拉取 -> 新增/跳过 -> 详情入库 -> 下载 -> 模型识别”顺序执行。
- 上游接口、文件下载、多模态网关不再使用 `RequestFunc` 请求函数注入。

## 用例

1. 自动任务首次执行时，分页数据按 `file_id` 写入 `task_item`，详情 `recordData` 写入 `task_item_data`。
2. 第二次执行遇到相同 `file_id` 时跳过，即使 `file_fid` 不同也不新增。
3. 两条数据 `file_fid` 相同但 `file_id` 不同时，允许作为不同 `TaskItem` 新增。
4. 详情接口使用 `GET /openApi/icFile/getResultByFileId1`，并通过 `params={"fileId": file_id}` 传参。
5. 所有新增项先完成 `TaskItemData` 入库，再进入下载阶段。
6. 自动任务下载后调用大模型识别，手动任务下载后保持 `llm_state=pending`。
7. 代码中不再保留 `RequestFunc = Callable[..., Response]` 和 `request_func` 注入参数。

## 验证命令

```bash
.env/bin/python -m pytest tests/test_task_execution_service.py tests/test_task_model_contract.py tests/test_task_api.py tests/test_multimodal_model_api.py
```

运行 pytest 后清理：

```bash
rm -rf .pytest_cache .pytest_tmp pytest-cache-files-*
```
