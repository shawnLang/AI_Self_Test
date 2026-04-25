import { useQuery, useQueryClient } from '@tanstack/react-query';
import { listCompletedReviewTasks, listReviews } from '../api/review';

export const reviewKeys = {
  tasks: ['review-completed-tasks'] as const,
  reviews: (taskId: string) => ['review-items', taskId] as const,
};

export function useCompletedReviewTasks() {
  return useQuery({
    queryKey: reviewKeys.tasks,
    queryFn: listCompletedReviewTasks,
  });
}

export function useReviews(taskId: string) {
  return useQuery({
    queryKey: reviewKeys.reviews(taskId),
    queryFn: () => listReviews(taskId),
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
