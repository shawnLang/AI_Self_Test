import React from 'react';
import { Activity, CheckCircle2, AlertCircle, Clock } from 'lucide-react';
import type { DashboardStats } from '../api/dashboard';
import { useDashboardStats } from '../hooks/useDashboardStats';


const emptyStats: DashboardStats = {
  activeTasks: 0,
  processedToday: 0,
  pendingReviews: 0,
  anomalies: 0,
  recentActivities: []
};

export default function Dashboard() {
  const { data, isError } = useDashboardStats();
  const stats = isError ? emptyStats : (data || emptyStats);

  return (
    <div className="p-8">
      <h2 className="text-2xl font-bold mb-6 text-gray-900 dark:text-white">总览</h2>
      
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        <StatCard title="活跃任务" value={stats.activeTasks.toString()} icon={<Activity className="text-blue-500 dark:text-blue-400" />} />
        <StatCard title="今日处理" value={stats.processedToday.toLocaleString()} icon={<CheckCircle2 className="text-green-500 dark:text-green-400" />} />
        <StatCard title="待复核" value={stats.pendingReviews.toString()} icon={<Clock className="text-orange-500 dark:text-orange-400" />} />
        <StatCard title="异常任务" value={stats.anomalies.toString()} icon={<AlertCircle className="text-red-500 dark:text-red-400" />} />
      </div>

      <div className="bg-white dark:bg-gray-800 p-6 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm transition-colors">
        <h3 className="text-lg font-semibold mb-4 text-gray-900 dark:text-white">近期活动（真实）</h3>
        {stats.recentActivities.length === 0 ? (
          <p className="text-sm text-gray-500 dark:text-gray-400">暂无真实活动数据。</p>
        ) : (
          <div className="space-y-4">
            {stats.recentActivities.map((item) => (
              <div key={item.id} className="flex items-center justify-between py-3 border-b border-gray-100 dark:border-gray-700 last:border-0">
                <div>
                  <p className="font-medium text-sm text-gray-900 dark:text-gray-100">
                    任务 #{item.id} {item.name}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    状态: {item.status}，进度: {item.processedCount}/{item.totalCount}
                  </p>
                </div>
                <span className="text-xs text-gray-400 dark:text-gray-500">
                  {item.finishedAt ? new Date(item.finishedAt).toLocaleString() : '--'}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function StatCard({ title, value, icon }: { title: string, value: string, icon: React.ReactNode }) {
  return (
    <div className="bg-white dark:bg-gray-800 p-6 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm flex items-center gap-4 transition-colors">
      <div className="p-3 bg-gray-50 dark:bg-gray-700/50 rounded-lg">
        {icon}
      </div>
      <div>
        <p className="text-sm font-medium text-gray-500 dark:text-gray-400">{title}</p>
        <p className="text-2xl font-bold text-gray-900 dark:text-white">{value}</p>
      </div>
    </div>
  );
}
