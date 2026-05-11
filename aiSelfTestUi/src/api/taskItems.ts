import { fetchApi } from '../utils/api';

export type ExecutionMode = 'auto' | 'manual';
export type MediaType = 'image' | 'video';
export type ModuleType = 'camera' | 'lure' | 'video';

export type TaskFiltersPayload = {
  classify_list: number[];
  keyword: string;
  sp_name: string;
  start_at: string;
  end_at: string;
  media_types: MediaType[];
  upload_types: number[];
  identify_source: number[];
  module: ModuleType;
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
  current_execution_id: number | null;
  current_execution_status: string | null;
  display_status: string;
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
  current_execution_id: number | null;
  current_execution_status: string | null;
  display_status: string;
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
  source_id: number | null;
  source_name: string | null;
  llm_name: string | null;
  det_name: string | null;
  det_score: number;
  llm_det_name: string | null;
  status: TaskItemDataStatus | string;
  track_ids: string;
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
  sourceId: number | null;
  originalName: string | null;
  aiName: string | null;
  detName: string | null;
  detScore: number;
  llmDetName: string | null;
  decision: 'keep' | 'add' | 'rename' | 'exclude' | 'error';
  willSubmit: boolean;
  groundingStatus: string;
  sourceStatus: string;
  trackIds: string;
  bbox: TaskItemBBox | null;
  sourceSize: TaskItemSourceSize | null;
  groundingMeta?: {
    sourceSize: TaskItemSourceSize;
  };
};

export type VideoVideoJsonDetection = {
  index?: number | string | null;
  trackId?: number | string | null;
  bbox?: unknown;
  score?: number | string | null;
};

export type VideoVideoJsonFrame = VideoVideoJsonDetection[];
export type VideoVideoJsonPayload = VideoVideoJsonFrame[];

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
  resultFileUrl: string | null;
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

export type ReRecognitionScope = 'selected' | 'failed';

export type TaskSubmissionData = {
  submission_id: number;
  task_id: number;
  status: 'queued' | 'running' | 'success' | 'partial_failed' | 'failed' | string;
  total_count: number;
  success_count: number;
  failed_count: number;
  skipped_count: number;
  current_task_item_id: number | null;
  error_summary: string | null;
  celery_task_id: string | null;
  started_at: string | null;
  finished_at: string | null;
};

export type TaskItemReRecognitionBatchData = {
  batch_id: number;
  task_id: number;
  scope: ReRecognitionScope | string;
  status: 'queued' | 'running' | 'success' | 'partial_failed' | 'failed' | string;
  total_count: number;
  success_count: number;
  failed_count: number;
  skipped_count: number;
  current_task_item_id: number | null;
  error_summary: string | null;
  celery_task_id: string | null;
  started_at: string | null;
  finished_at: string | null;
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

export function submitTaskReviewItems(taskId: number): Promise<TaskSubmissionData> {
  return fetchApi<TaskSubmissionData>(`/api/tasks/action-submit/${taskId}`, {
    method: 'POST',
  });
}

export function getTaskSubmissionDetail(submissionId: number): Promise<TaskSubmissionData> {
  return fetchApi<TaskSubmissionData>(`/api/tasks/submission-detail/${submissionId}`);
}

export function getCurrentTaskSubmission(taskId: number): Promise<TaskSubmissionData | null> {
  return fetchApi<TaskSubmissionData | null>(`/api/tasks/submission-current/${taskId}`);
}

export function reRecognizeTaskItems(params: {
  scope: ReRecognitionScope;
  taskId?: number;
  taskItemIds?: number[];
}): Promise<TaskItemReRecognitionBatchData> {
  return fetchApi<TaskItemReRecognitionBatchData>('/api/task-items/action-re-recognize-batch', {
    method: 'POST',
    body: JSON.stringify({
      scope: params.scope,
      task_id: params.taskId ?? null,
      task_item_ids: params.taskItemIds ?? [],
    }),
  });
}

export function getReRecognitionBatchDetail(batchId: number): Promise<TaskItemReRecognitionBatchData> {
  return fetchApi<TaskItemReRecognitionBatchData>(`/api/task-items/re-recognize-batch-detail/${batchId}`);
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
    resultFileUrl: detail.media.result_file_url,
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
    sourceId: row.source_id,
    originalName: row.source_name,
    aiName: row.llm_name,
    detName: row.det_name,
    detScore: row.det_score,
    llmDetName: row.llm_det_name,
    decision,
    willSubmit: ['默认', '新增', '修改'].includes(row.status),
    groundingStatus: '',
    sourceStatus: row.status,
    trackIds: row.track_ids,
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
