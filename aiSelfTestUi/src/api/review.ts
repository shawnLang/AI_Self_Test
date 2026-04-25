import { fetchRawJson } from '../utils/api';

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

export function listCompletedReviewTasks(): Promise<ReviewTaskOption[]> {
  return fetchRawJson<ReviewTaskOption[]>('/api/reviews/completed-tasks');
}

export function listReviews(taskId: string): Promise<ReviewItem[]> {
  return fetchRawJson<ReviewItem[]>(`/api/reviews?taskId=${encodeURIComponent(taskId)}`);
}

export function confirmReviews(ids: string[]): Promise<ReviewConfirmResult> {
  return fetchRawJson<ReviewConfirmResult>('/api/reviews/confirm', {
    method: 'POST',
    body: JSON.stringify({ ids }),
  });
}

export function deleteReview(id: string): Promise<void> {
  return fetchRawJson<void>(`/api/reviews/${id}`, { method: 'DELETE' });
}

export function deleteReviews(ids: string[]): Promise<void> {
  return fetchRawJson<void>('/api/reviews/delete', {
    method: 'POST',
    body: JSON.stringify({ ids }),
  });
}
