# Task 执行链路 V1 - Test.md

## 1. 本轮目标

本轮围绕 **Task 执行链路 V1** 建立测试先行基线，
并逐步完成从契约到实现的闭环。

当前需求范围以：

- `.omx/plans/prd-task-execution-v1-20260425T092838Z.md`
- `.omx/plans/test-spec-task-execution-v1-20260425T092838Z.md`

为准。

V1 必须覆盖：

- 后端 + 前端
- 图片 + 视频
- 自动 + 手动
- Task / TaskItem / TaskItem Actions

## 2. 本轮执行策略

遵循 **Phase0 → Phase1** 顺序推进：

1. 先把任务执行链的测试基线写成**可执行失败测试**
2. 再实现 canonical contract、schema、migration 与基础路由
3. 之后再进入共享主干、媒体分支与前端语义重构

当前阶段**不允许**跳过测试直接写实现。

## 3. Phase0 验收标准

### 3.1 测试文档

- `Test.md` 已切换为当前 Task 执行链任务
- 测试范围与 PRD / test-spec 对齐

### 3.2 可执行失败测试

必须存在可执行测试，并且当前失败点正确地指向：

- `task` 正式路由尚未实现
- `task` schema 尚未实现
- `task` router 尚未接入 `main.py`
- `TaskItem` / `TaskItem Actions` 契约尚未实现

### 3.3 失败必须是“正确失败”

允许当前失败的原因：

- 404（路由缺失）
- schema / service 未实现导致的业务失败
- 断言接口返回结构不匹配

不允许当前失败的原因：

- 测试夹具损坏
- 数据库未初始化
- 仓库路径错误
- 非 task 模块无关异常

## 4. 核心验收标准

### 4.1 Task Contract

- 提供以下正式路由：
  - `GET /api/tasks/list`
  - `POST /api/tasks/create`
  - `GET /api/tasks/detail/{task_id}`
  - `POST /api/tasks/update/{task_id}`
  - `DELETE /api/tasks/delete/{task_id}`
  - `POST /api/tasks/action-start/{task_id}`
  - `POST /api/tasks/action-stop/{task_id}`
  - `POST /api/tasks/action-run/{task_id}`

- 所有接口统一返回：

```json
{
  "code": 0,
  "message": "success",
  "data": {}
}
```

### 4.2 Task Create

- 创建任务时必须保存：
  - `name`
  - `client_id`
  - `config_id`
  - `interval_hours`
  - `execution_mode`
  - `auto_confirm`
  - `filters`

- `config_id` 缺失时必须返回参数错误
- `interval_hours` 非法时必须返回参数错误

### 4.3 TaskItem / TaskItem Actions

- 提供以下正式路由：
  - `GET /api/task-items/list`
  - `GET /api/task-items/detail/{task_item_id}`
  - `POST /api/task-items/action-confirm`
  - `POST /api/task-items/action-reject`
  - `POST /api/task-items/action-delete`
  - `POST /api/task-items/action-submit`

- `delete` 的规范必须固定：
  - **不删除源媒体**
  - **不删除源 TaskItem**
  - 只作用于当前复核层对象或待提交差异集合

### 4.4 Scheduler Contract

- `active=true` 时可注册任务
- `start / stop / run` 契约明确
- 运行中任务不能重入
- 重启后 active 任务可恢复

### 4.5 Shared Trunk

- 支持 Task 创建后进入共享主干
- 支持生成 `TaskItem`
- 支持去重策略：
  - `(task_id, file_fid)` 唯一

### 4.6 Image Branch

- 支持图片下载
- 支持图片识别
- 支持 bbox 匹配
- 支持 `ADD / UPDATE / DELETE`

### 4.7 Video Branch

- 支持视频下载
- 支持 `result.json`
- 支持抽帧
- 支持 `track_id` 匹配
- 视频不产生 `ADD`

### 4.8 Frontend Contract

- `Tasks` 页面切换到新 task 契约
- `CreateTask` 页面显式提交 `config_id`
- `DataQuery` 不再以“实时查询并下发任务”为主语义
- `Review` 只做基础确认，不扩成复杂审核工作台

### 4.9 Review Compat Adapter 护栏

- `/api/reviews/*` 只能作为旧 Review 页面适配层，不能重新长成主模型。
- `GET /api/reviews?taskId=...` 必须由 `TaskItem + TaskItemData` 投影出旧卡片。
- `POST /api/reviews/confirm` 必须委托 TaskItem 确认语义，只更新 `confirm_state`。
- `confirm` 不得触发远端提交，不得把 `remote_state` 改成 `success`。
- `DELETE /api/reviews/{id}` 与 `POST /api/reviews/delete` 必须保留源 `TaskItem`。
- `delete` 只能把复核层对象或待提交差异集合标记为 `删除`。
- 保护测试集中在 `tests/test_review_compat_api.py`，与 TaskItem Actions 测试互为补充。

## 5. 自动验证

当前阶段至少运行：

- `python -m pytest tests/test_task_api.py`
- `python -m pytest tests/test_task_item_api.py`
- `python -m pytest tests/test_review_compat_api.py`

后续阶段逐步增加：

- `python -m pytest`
- 前端测试 / 构建验证

## 6. 手工验证

在后续实现可运行后，至少手工验证：

1. 创建一个任务
2. 查询任务列表
3. 查看任务详情
4. 查看 TaskItem 列表
5. 执行基础确认动作
6. 验证图片链路样本
7. 验证视频链路样本

## 7. 风险点

- `delete` 语义最容易漂移，必须单独写测试固定
- `/api/reviews` 只能做 compat adapter，不能重新长成主模型
- `DataQuery` 旧语义必须彻底退场
- `CreateTask` 当前没有 `config_id` 显式输入，必须在实现阶段补齐

## 8. 当前阶段结论

当前基线已进入 **Task 执行链路 V1 增量实现与验证阶段**。

本轮 worker-3 收敛到 **refined review compat lane**，优先固定以下证据：

- [ ] `/api/reviews` 仍只是 compat adapter
- [ ] `confirm` 不触发 `submit`
- [ ] `delete` 不删除源 `TaskItem`
- [ ] Review 首版只保留基础确认 / 删除能力
