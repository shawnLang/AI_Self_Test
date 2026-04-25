import { fetchApi } from '../utils/api';

export type ReviewTaskOption = {
  id: string | number;
  name: string;
};

export type ReviewItem = Record<string, any>;

export type ReviewConfirmResult = {
  successCount?: number;
  failureCount?: number;
  results?: Array<{ status?: string; message?: string }>;
  error?: string;
};

type TaskListData = {
  items: Array<{
    id: number;
    name: string;
    execution_status: string;
  }>;
};

type TaskDetailData = {
  id: number;
  name: string;
};

type TaskItemListData = {
  items: Array<{
    id: number;
    media_type: 'image' | 'video';
    name: string;
    file_url: string;
    remote_state?: string | null;
  }>;
};

type TaskItemDetailData = {
  id: number;
  media_type: 'image' | 'video';
  media: {
    url: string;
    result_file_url?: string | null;
  };
  review_summary: {
    submit_count: number;
    exclude_count: number;
    submit_empty: boolean;
  };
  review_rows: Array<{
    task_item_data_id: number;
    source_name?: string | null;
    llm_name?: string | null;
    status: string;
  }>;
};

export async function listCompletedReviewTasks(): Promise<ReviewTaskOption[]> {
  const data = await fetchApi<TaskListData>('/api/tasks/list');
  return data.items
    .filter((task) => task.execution_status === '结束')
    .map((task) => ({
      id: task.id,
      name: task.name,
    }));
}

export async function listReviews(taskId: string): Promise<ReviewItem[]> {
  const [task, listData] = await Promise.all([
    fetchApi<TaskDetailData>(`/api/tasks/detail/${encodeURIComponent(taskId)}`),
    fetchApi<TaskItemListData>(`/api/task-items/list?task_id=${encodeURIComponent(taskId)}&page_size=200`),
  ]);

  const detailItems = await Promise.all(
    listData.items.map((item) => fetchApi<TaskItemDetailData>(`/api/task-items/detail/${item.id}`))
  );

  return detailItems.map((item) => {
    const reviewRows = item.review_rows.map((row) => {
      const decision = resolveDecision(row.status, row.source_name, row.llm_name);
      return {
        recordId: row.task_item_data_id,
        originalName: row.source_name,
        aiName: row.llm_name,
        decision,
        willSubmit: decision !== 'exclude' && Boolean(row.llm_name),
        groundingStatus: 'structured',
      };
    });
    const submitCount = reviewRows.filter((row) => row.willSubmit).length;
    const excludedCount = reviewRows.filter((row) => row.decision === 'exclude').length;
    const originalValues = reviewRows.map((row) => row.originalName).filter(Boolean);
    const aiValues = reviewRows.map((row) => row.aiName).filter(Boolean);

    return {
      id: item.id,
      taskName: task.name,
      mediaType: item.media_type,
      imageUrl: item.media.url,
      mediaUrl: item.media.url,
      resultFileUrl: item.media.result_file_url,
      originalResult: originalValues.join('、'),
      aiResult: aiValues.join('、'),
      reviewRows,
      submitCount,
      excludedCount,
      willSubmitEmptyArray: submitCount === 0,
    };
  });
}

export async function confirmReviews(ids: string[]): Promise<ReviewConfirmResult> {
  return runBatchAction(ids, async (id) => {
    await fetchApi('/api/task-items/action-confirm', {
      method: 'POST',
      body: JSON.stringify({ task_item_id: Number(id) }),
    });
  }, '确认成功');
}

export async function deleteReview(id: string): Promise<void> {
  const detail = await fetchApi<TaskItemDetailData>(`/api/task-items/detail/${encodeURIComponent(id)}`);
  await fetchApi('/api/task-items/action-delete', {
    method: 'POST',
    body: JSON.stringify({
      task_item_id: Number(id),
      task_item_data_ids: detail.review_rows.map((row) => row.task_item_data_id),
    }),
  });
}

export async function deleteReviews(ids: string[]): Promise<void> {
  await Promise.all(ids.map((id) => deleteReview(id)));
}

function resolveDecision(status: string, sourceName?: string | null, llmName?: string | null) {
  if (status === '删除') return 'exclude';
  if (sourceName && llmName && sourceName.trim() === llmName.trim()) return 'keep';
  if (llmName) return 'rename';
  return 'exclude';
}

async function runBatchAction(
  ids: string[],
  action: (id: string) => Promise<void>,
  successMessage: string,
): Promise<ReviewConfirmResult> {
  const results: Array<{ status: string; message: string }> = [];
  let successCount = 0;
  let failureCount = 0;

  for (const id of ids) {
    try {
      await action(id);
      successCount += 1;
      results.push({ status: 'success', message: `${id} ${successMessage}` });
    } catch (error) {
      failureCount += 1;
      results.push({ status: 'failed', message: (error as Error).message || `${id} 操作失败` });
    }
  }

  return {
    successCount,
    failureCount,
    results,
  };
}
