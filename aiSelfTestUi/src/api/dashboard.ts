import { fetchApi } from '../utils/api';

export type DashboardStats = {
  activeTasks: number;
  processedToday: number;
  pendingReviews: number;
  anomalies: number;
  recentActivities: Array<{
    id: number;
    name: string;
    status: string;
    processedCount: number;
    totalCount: number;
    finishedAt: string;
  }>;
};

export function getDashboardStats(): Promise<DashboardStats> {
  return fetchApi<DashboardStats>('/api/dashboard/stats');
}
