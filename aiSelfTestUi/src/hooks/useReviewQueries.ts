import { useQuery, useQueryClient } from '@tanstack/react-query';
import { listReviewTaskOptions, listTaskItemReviewItems } from '../api/taskItems';

export const reviewKeys = {
  tasks: ['task-item-review-tasks'] as const,
  reviews: (taskId: string) => ['task-item-review-items', taskId] as const,
};

export function useCompletedReviewTasks() {
  return useQuery({
    queryKey: reviewKeys.tasks,
    queryFn: listReviewTaskOptions,
  });
}

export function useReviews(taskId: string) {
  return useQuery({
    queryKey: reviewKeys.reviews(taskId),
    queryFn: () => listTaskItemReviewItems(taskId),
    enabled: Boolean(taskId),
  });
}

export function useInvalidateReviews() {
  const queryClient = useQueryClient();

  return {
    invalidateTasks: () => queryClient.invalidateQueries({ queryKey: reviewKeys.tasks }),
    invalidateReviews: (taskId: string) => queryClient.invalidateQueries({ queryKey: reviewKeys.reviews(taskId) }),
  };
}
