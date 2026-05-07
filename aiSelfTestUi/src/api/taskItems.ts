import { fetchApi } from '../utils/api';

export type ExecutionMode = 'auto' | 'manual';
export type MediaType = 'image' | 'video';

export type TaskFiltersPayload = {
  classify_list: number[];
  keyword: string;
  sp_name: string;
  start_at: string;
  end_at: string;
  media_types: MediaType[];
  upload_types: number[];
  identify_source: number[];
};

export type TaskSummary = {
  id: number;
  name: string;
  client_id: number;
  config_id: number;
  interval_hours: number;
  execution_mode: ExecutionMode;
  auto_execute: boolean;
  active: boolean;
  execution_status: string;
  total_count: number;
  processed_count: number;
  skipped_count: number;
  last_error: string | null;
  estimated_remaining_seconds: number | null;
  started_at?: string | null;
  finished_at?: string | null;
  filters: TaskFiltersPayload;
};

export type TaskListData = {
  items: TaskSummary[];
};

export type TaskActionData = {
  id: number;
  active: boolean;
  execution_status: string;
};

export type TaskItemListRow = {
  id: number;
  task_id: number;
  media_type: MediaType;
  name: string;
  file_url: string;
  status: string;
  down_state: boolean;
  llm_state: string | null;
  confirm_state: string | null;
  remote_state: string | null;
};

export type TaskItemListData = {
  items: TaskItemListRow[];
  total: number;
  page: number;
  page_size: number;
};

export type TaskItemDataStatus = '默认' | '新增' | '修改' | '删除';

export type TaskItemBBox = {
  minx: number;
  miny: number;
  maxx: number;
  maxy: number;
};

export type TaskItemSourceSize = {
  width: number;
  height: number;
};

export type TaskItemReviewRow = {
  task_item_data_id: number;
  source_name: string | null;
  llm_name: string | null;
  status: TaskItemDataStatus | string;
  bbox: TaskItemBBox | null;
  source_size: TaskItemSourceSize | null;
};

export type TaskItemReviewSummary = {
  submit_count: number;
  exclude_count: number;
  submit_empty: boolean;
};

export type TaskItemStepState = {
  download: string;
  llm: string;
  confirm: string;
  remote: string;
  train: string;
};

export type TaskItemDetailData = {
  id: number;
  task_id: number;
  media_type: MediaType;
  media: {
    url: string;
    result_file_url: string | null;
  };
  step_state: TaskItemStepState;
  review_summary: TaskItemReviewSummary;
  review_rows: TaskItemReviewRow[];
};

export type TaskItemActionData = {
  id: number;
  confirm_state?: string | null;
  remote_state?: string | null;
  train_state?: string | null;
};

export type ReviewTaskOption = {
  id: string | number;
  name: string;
};

export type ReviewRow = {
  recordId: number;
  originalName: string | null;
  aiName: string | null;
  decision: 'keep' | 'add' | 'rename' | 'exclude' | 'error';
  willSubmit: boolean;
  groundingStatus: string;
  sourceStatus: string;
  bbox: TaskItemBBox | null;
  sourceSize: TaskItemSourceSize | null;
  groundingMeta?: {
    sourceSize: TaskItemSourceSize;
  };
};

export type TaskItemReviewRowUpdateRequest = {
  task_item_id: number;
  task_item_data_id: number;
  status: TaskItemDataStatus | string;
  llm_name: string | null;
};

export type ReviewItem = {
  id: number;
  taskId: number;
  taskName: string;
  mediaType: MediaType;
  imageUrl: string;
  mediaUrl: string;
  status: string;
  originalResult: string;
  aiResult: string;
  reviewRows: ReviewRow[];
  submitCount: number;
  excludedCount: number;
  willSubmitEmptyArray: boolean;
  confirmState: string | null;
  remoteState: string | null;
  remoteError?: string | null;
  stepState: TaskItemStepState;
};

export type TaskItemBatchActionResult = {
  successCount: number;
  failureCount: number;
  results: Array<{ id: number; status: 'success' | 'failed'; message: string }>;
};

export type TaskItemServerBatchActionData = {
  success_count: number;
  failure_count: number;
  results: Array<{ id: number; status: 'success' | 'failed'; message: string }>;
};

const REVIEWABLE_TASK_STATUSES = new Set(['核查', '结束']);

export async function listTasks(): Promise<TaskSummary[]> {
  const data = await fetchApi<TaskListData>('/api/tasks/list');
  return data.items;
}

export function getTaskDetail(taskId: number): Promise<TaskSummary> {
  return fetchApi<TaskSummary>(`/api/tasks/detail/${taskId}`);
}

export function runTaskNow(taskId: number): Promise<TaskActionData> {
  return fetchApi<TaskActionData>(`/api/tasks/action-run/${taskId}`, { method: 'POST' });
}

export function listTaskItems(params: {
  taskId: number;
  mediaType?: MediaType | 'all';
  page?: number;
  pageSize?: number;
}): Promise<TaskItemListData> {
  const query = new URLSearchParams({
    task_id: String(params.taskId),
    page: String(params.page ?? 1),
    page_size: String(params.pageSize ?? 100),
  });

  if (params.mediaType && params.mediaType !== 'all') {
    query.set('media_type', params.mediaType);
  }

  return fetchApi<TaskItemListData>(`/api/task-items/list?${query.toString()}`);
}

export function getTaskItemDetail(taskItemId: number): Promise<TaskItemDetailData> {
  return fetchApi<TaskItemDetailData>(`/api/task-items/detail/${taskItemId}`);
}

export function confirmTaskItem(taskItemId: number): Promise<TaskItemActionData> {
  return fetchApi<TaskItemActionData>('/api/task-items/action-confirm', {
    method: 'POST',
    body: JSON.stringify({ task_item_id: taskItemId }),
  });
}

export function rejectTaskItem(taskItemId: number, reason: string): Promise<TaskItemActionData> {
  return fetchApi<TaskItemActionData>('/api/task-items/action-reject', {
    method: 'POST',
    body: JSON.stringify({ task_item_id: taskItemId, reason }),
  });
}

export function updateTaskItemReviewRow(payload: TaskItemReviewRowUpdateRequest): Promise<TaskItemActionData> {
  return fetchApi<TaskItemActionData>('/api/task-items/action-update-row', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function submitTaskItem(taskItemId: number): Promise<TaskItemActionData> {
  return fetchApi<TaskItemActionData>('/api/task-items/action-submit', {
    method: 'POST',
    body: JSON.stringify({ task_item_id: taskItemId }),
  });
}

export async function submitTaskReviewItems(taskId: number): Promise<TaskItemBatchActionResult> {
  const data = await fetchApi<TaskItemServerBatchActionData>('/api/task-items/action-submit-task', {
    method: 'POST',
    body: JSON.stringify({ task_id: taskId }),
  });
  return {
    successCount: data.success_count,
    failureCount: data.failure_count,
    results: data.results,
  };
}

export async function listReviewTaskOptions(): Promise<ReviewTaskOption[]> {
  const tasks = await listTasks();
  return tasks
    .filter((task) => REVIEWABLE_TASK_STATUSES.has(task.execution_status))
    .map((task) => ({ id: task.id, name: task.name }));
}

export async function listTaskItemReviewItems(taskId: string): Promise<ReviewItem[]> {
  if (!taskId) return [];

  const numericTaskId = Number(taskId);
  const [task, listData] = await Promise.all([
    getTaskDetail(numericTaskId),
    listTaskItems({ taskId: numericTaskId, pageSize: 100 }),
  ]);

  const details = await Promise.all(
    listData.items.map(async (item) => ({
      listRow: item,
      detail: await getTaskItemDetail(item.id),
    })),
  );

  return details.map(({ listRow, detail }) => toReviewItem(task, listRow, detail));
}

export async function confirmReviewItems(ids: string[]): Promise<TaskItemBatchActionResult> {
  return runBatchAction(ids, async (id) => {
    await confirmTaskItem(id);
    return `任务项 ${id} 已确认`;
  });
}

export async function skipReviewItems(ids: string[]): Promise<TaskItemBatchActionResult> {
  return runBatchAction(ids, async (id) => {
    await rejectTaskItem(id, 'manual_skip');
    return `任务项 ${id} 已跳过`;
  });
}

async function runBatchAction(
  ids: string[],
  action: (id: number) => Promise<string>,
): Promise<TaskItemBatchActionResult> {
  const results: TaskItemBatchActionResult['results'] = [];

  for (const rawId of ids) {
    const id = Number(rawId);
    try {
      const message = await action(id);
      results.push({ id, status: 'success', message });
    } catch (error) {
      results.push({
        id,
        status: 'failed',
        message: (error as Error).message || '操作失败',
      });
    }
  }

  return {
    successCount: results.filter((item) => item.status === 'success').length,
    failureCount: results.filter((item) => item.status === 'failed').length,
    results,
  };
}

function toReviewItem(task: TaskSummary, listRow: TaskItemListRow, detail: TaskItemDetailData): ReviewItem {
  const reviewRows = detail.review_rows.map(toReviewRow);
  const originalValues = reviewRows.map((row) => row.originalName).filter(Boolean);
  const aiValues = reviewRows.map((row) => row.aiName).filter(Boolean);

  return {
    id: detail.id,
    taskId: detail.task_id,
    taskName: task.name,
    mediaType: detail.media_type,
    imageUrl: detail.media.url,
    mediaUrl: detail.media.url,
    status: listRow.status,
    originalResult: originalValues.join('、'),
    aiResult: aiValues.join('、'),
    reviewRows,
    submitCount: reviewRows.filter((row) => row.willSubmit).length,
    excludedCount: reviewRows.filter((row) => row.decision === 'exclude').length,
    willSubmitEmptyArray: reviewRows.filter((row) => row.willSubmit).length === 0,
    confirmState: listRow.confirm_state,
    remoteState: listRow.remote_state,
    stepState: detail.step_state,
  };
}

function toReviewRow(row: TaskItemReviewRow): ReviewRow {
  const sourceName = row.source_name?.trim() || '';
  const llmName = row.llm_name?.trim() || '';
  const decision = resolveDecision(sourceName, llmName, row.status);

  return {
    recordId: row.task_item_data_id,
    originalName: row.source_name,
    aiName: row.llm_name,
    decision,
    willSubmit: ['默认', '新增', '修改'].includes(row.status),
    groundingStatus: '',
    sourceStatus: row.status,
    bbox: row.bbox,
    sourceSize: row.source_size,
    groundingMeta: row.source_size ? { sourceSize: row.source_size } : undefined,
  };
}

function resolveDecision(sourceName: string, llmName: string, status: string): ReviewRow['decision'] {
  if (status === '新增') return 'add';
  if (status === '修改') return 'rename';
  if (status === '删除') return 'exclude';
  if (status === '默认') return 'keep';
  if (!llmName) return 'exclude';
  if (sourceName && sourceName === llmName) return 'keep';
  return 'rename';
}
