import React, { useState, useEffect } from 'react';
import { Plus, Clock, Settings2, Trash2, Pause, AlertTriangle, CheckSquare, Play } from 'lucide-react';
import { moduleOptions } from '../constants/taskFilters';
import { fetchApi } from '../utils/api';

type TaskFiltersPayload = {
  module?: string | null;
};

type TaskItem = {
  id: number;
  name: string;
  client_id: number;
  config_id: number;
  interval_hours: number;
  execution_mode: 'auto' | 'manual';
  auto_execute: boolean;
  active: boolean;
  execution_status: string;
  total_count: number;
  processed_count: number;
  skipped_count: number;
  last_error: string | null;
  estimated_remaining_seconds: number | null;
  started_at?: string | null;
  filters: TaskFiltersPayload;
};

type TaskListData = {
  items: TaskItem[];
};

const intervalLabelMap: Record<number, string> = {
  1: '每小时',
  6: '每 6 小时',
  12: '每 12 小时',
  24: '每天',
  168: '每周',
};

const statusTextMap: Record<string, string> = {
  创建: '未开始',
  下载: '下载中',
  数据加载: '数据加载中',
  模型识别: '识别中',
  核查: '待核查',
  结束: '已完成',
  失败: '执行失败',
};

const runningExecutionStatuses = new Set(['数据加载', '下载', '模型识别']);

export default function Tasks({
  onCreateTask,
  onQueryData,
  onReview
}: {
  onCreateTask: () => void,
  onQueryData: (taskId: number) => void,
  onReview: (taskId: number) => void
}) {
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [runningNowTaskId, setRunningNowTaskId] = useState<number | null>(null);
  const [error, setError] = useState('');

  const fetchTasks = async () => {
    try {
      const data = await fetchApi<TaskListData>('/api/tasks/list');
      setTasks(data.items);
      setError('');
    } catch(e) {
      console.error(e);
      setError((e as Error).message || '任务列表加载失败');
    }
  };

  useEffect(() => {
    fetchTasks();
    const timer = setInterval(fetchTasks, 2000);
    return () => clearInterval(timer);
  }, []);

  const handleDelete = async (id: number) => {
    if(!confirm('确定删除此任务吗？')) return;
    try {
      await fetchApi(`/api/tasks/delete/${id}`, { method: 'DELETE' });
      await fetchTasks();
    } catch (e) {
      console.error(e);
      alert(`删除任务失败：${(e as Error).message || '未知错误'}`);
    }
  };

  const updateTaskStatus = async (id: number, active: boolean) => {
    try {
      await fetchApi(active ? `/api/tasks/action-start/${id}` : `/api/tasks/action-stop/${id}`, {
        method: 'POST',
      });
      await fetchTasks();
    } catch (e) {
      console.error(e);
      alert(`${active ? '启动' : '停止'}任务失败：${(e as Error).message || '未知错误'}`);
    }
  };

  const runTaskNow = async (id: number) => {
    setRunningNowTaskId(id);
    try {
      await fetchApi(`/api/tasks/action-run/${id}`, {
        method: 'POST',
      });
      await fetchTasks();
    } catch (e) {
      console.error(e);
      alert(`立即执行失败：${(e as Error).message || '未知错误'}`);
    } finally {
      setRunningNowTaskId(null);
    }
  };

  return (
    <div className="p-8">
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-2xl font-bold text-gray-900 dark:text-white">任务管理</h2>
        <button 
          onClick={onCreateTask}
          className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm font-medium flex items-center gap-2 transition-colors"
        >
          <Plus className="w-4 h-4" />
          创建任务
        </button>
      </div>

      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 text-red-700 dark:border-red-900/40 dark:bg-red-900/20 dark:text-red-300 px-4 py-3 text-sm">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        {tasks.length === 0 ? (
          <div className="xl:col-span-2 text-center py-12 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700">
            <p className="text-gray-500 dark:text-gray-400 mb-4">暂无任务，请点击上方按钮创建</p>
          </div>
        ) : (
          tasks.map((task) => (
            <TaskMonitorCard 
              key={task.id}
              task={task}
              onDelete={() => handleDelete(task.id)}
              onStatusChange={(active: boolean) => updateTaskStatus(task.id, active)}
              onRunNow={() => runTaskNow(task.id)}
              runningNow={runningNowTaskId === task.id}
              onQueryData={() => onQueryData(task.id)}
              onReview={() => onReview(task.id)}
            />
          ))
        )}
      </div>
    </div>
  );
}

type TaskMonitorCardProps = {
  task: TaskItem;
  onDelete: () => void;
  onStatusChange: (active: boolean) => void;
  onRunNow: () => void;
  runningNow: boolean;
  onQueryData: () => void;
  onReview: () => void;
};

const TaskMonitorCard: React.FC<TaskMonitorCardProps> = ({
  task,
  onDelete,
  onStatusChange,
  onRunNow,
  runningNow,
  onQueryData,
  onReview,
}) => {
  const isRunning = task.active;
  const processed = Number(task.processed_count || 0);
  const total = Number(task.total_count || 0);
  const progress = total > 0 ? Math.min(100, Math.round((processed / total) * 100)) : 0;
  const canReview = task.execution_status === '核查' || task.execution_status === '结束';
  const isPreparing = task.execution_status === '创建' && Boolean(task.started_at);
  const isExecuting = isPreparing || runningExecutionStatuses.has(task.execution_status);
  const statusText = isPreparing ? '准备中' : statusTextMap[task.execution_status] || task.execution_status || '未开始';
  const remainingTimeText = formatRemainingTime(task.estimated_remaining_seconds, isExecuting);
  const moduleText = formatModule(task.filters?.module);
  
  return (
    <div className="bg-white dark:bg-gray-800 p-6 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm transition-colors">
      <div className="flex flex-col gap-4 mb-4 2xl:flex-row 2xl:items-start 2xl:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-3">
            <h3 className="truncate text-lg font-semibold text-gray-900 dark:text-white" title={task.name}>{task.name}</h3>
            {isRunning ? (
              <span className="whitespace-nowrap px-2 py-0.5 rounded text-xs font-medium bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-400">
                {statusText}
              </span>
            ) : (
              <span className="whitespace-nowrap px-2 py-0.5 rounded text-xs font-medium bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300">
                {statusText}
              </span>
            )}
          </div>
          <div className="flex flex-wrap gap-4 text-sm text-gray-500 dark:text-gray-400 mt-2">
            <span className="flex items-center gap-1"><Settings2 className="w-4 h-4" /> 项目 #{task.client_id}</span>
            <span className="flex items-center gap-1"><Clock className="w-4 h-4" /> {intervalLabelMap[task.interval_hours] || `${task.interval_hours} 小时`}</span>
            <span className="flex items-center gap-1">模块: {moduleText}</span>
            <span className="flex items-center gap-1">执行方式: {task.execution_mode === 'auto' ? '自动执行' : '手动执行'}</span>
          </div>
        </div>
        
        <div className="flex flex-wrap gap-2 items-center justify-start 2xl:justify-end">
          <button 
            onClick={onQueryData}
            className="inline-flex whitespace-nowrap px-3 py-2 text-sm font-medium text-blue-600 bg-blue-50 hover:bg-blue-100 dark:text-blue-400 dark:bg-blue-900/20 dark:hover:bg-blue-900/40 border border-blue-200 dark:border-blue-800 rounded-lg items-center gap-2 transition-colors"
          >
            🔍 查看任务详情
          </button>

          {!isRunning && (
            <button 
              onClick={() => onStatusChange(true)}
              className="inline-flex whitespace-nowrap px-3 py-2 text-sm font-medium text-green-700 dark:text-green-300 bg-green-50 dark:bg-green-900/20 hover:bg-green-100 dark:hover:bg-green-900/40 border border-green-200 dark:border-green-800 rounded-lg items-center gap-2 transition-colors" 
              title="启用自动调度"
            >
              <Play className="w-4 h-4" />
              启用调度
            </button>
          )}

          {isRunning && (
            <button 
              onClick={() => onStatusChange(false)}
              className="inline-flex whitespace-nowrap px-3 py-2 text-sm font-medium text-orange-700 dark:text-orange-300 bg-orange-50 dark:bg-orange-900/20 hover:bg-orange-100 dark:hover:bg-orange-900/40 border border-orange-200 dark:border-orange-800 rounded-lg items-center gap-2 transition-colors" 
              title="暂停自动调度"
            >
              <Pause className="w-4 h-4" />
              暂停调度
            </button>
          )}

          {canReview && (
            <button
              onClick={onReview}
              className="inline-flex whitespace-nowrap px-3 py-2 text-sm font-medium text-emerald-700 bg-emerald-50 hover:bg-emerald-100 dark:text-emerald-300 dark:bg-emerald-900/20 dark:hover:bg-emerald-900/40 border border-emerald-200 dark:border-emerald-800 rounded-lg items-center gap-2 transition-colors"
            >
              <CheckSquare className="w-4 h-4" />
              结果复核
            </button>
          )}
          
          <div className="w-px h-6 bg-gray-200 dark:bg-gray-700 mx-1"></div>

          <button
            onClick={onRunNow}
            disabled={isRunning || runningNow}
            className="inline-flex whitespace-nowrap items-center gap-2 px-3 py-2 text-sm font-medium text-violet-700 bg-violet-50 hover:bg-violet-100 disabled:bg-gray-100 disabled:text-gray-400 dark:text-violet-300 dark:bg-violet-900/20 dark:hover:bg-violet-900/40 dark:disabled:bg-gray-800 dark:disabled:text-gray-500 border border-violet-200 dark:border-violet-800 rounded-lg transition-colors"
            title="立即执行"
          >
            <Play className="w-4 h-4" />
            {runningNow ? '执行中' : '立即执行'}
          </button>
          
          <button 
            onClick={onDelete} 
            className="p-2 text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300 hover:bg-red-50 dark:hover:bg-red-900/30 rounded-lg transition-colors" 
            title="删除任务"
          >
            <Trash2 className="w-5 h-5" />
          </button>
        </div>
      </div>

      <div className="mb-2 flex justify-between text-sm mt-6">
        <span className="font-medium text-gray-700 dark:text-gray-300">{progress}% 已完成</span>
        <span className="text-gray-500 dark:text-gray-400">{processed} / {total || '--'} 项</span>
      </div>
      <div className="w-full bg-gray-100 dark:bg-gray-700 rounded-full h-3 mb-4">
        <div 
          className={`h-3 rounded-full transition-all duration-500 ${isRunning ? 'bg-blue-500 dark:bg-blue-400' : 'bg-gray-400 dark:bg-gray-500'}`} 
          style={{ width: `${progress}%` }}
        ></div>
      </div>

      <div className="flex flex-wrap gap-6 text-sm text-gray-600 dark:text-gray-300 bg-gray-50 dark:bg-gray-900/50 p-3 rounded-lg transition-colors">
        <div>
          <span className="block text-xs text-gray-400 dark:text-gray-500 uppercase tracking-wider mb-1">跳过重复项</span>
          <span className="font-medium">{task.skipped_count ?? 0}</span>
        </div>
        <div>
          <span className="block text-xs text-gray-400 dark:text-gray-500 uppercase tracking-wider mb-1">预计剩余时间</span>
          <span className="font-medium">{remainingTimeText}</span>
        </div>
        {task.execution_status === '失败' && (
          <div className="flex items-center gap-2 text-orange-600 dark:text-orange-400 ml-auto">
            <AlertTriangle className="w-4 h-4" />
            <span>{task.last_error || '任务执行失败，请重试。'}</span>
          </div>
        )}
      </div>
    </div>
  );
};

function formatRemainingTime(seconds: number | null | undefined, isRunning: boolean): string {
  if (typeof seconds !== 'number') {
    return isRunning ? '计算中' : '暂未估算';
  }
  if (seconds <= 0) {
    return '即将完成';
  }

  const totalSeconds = Math.ceil(seconds);
  if (totalSeconds < 60) {
    return `约 ${totalSeconds} 秒`;
  }

  if (totalSeconds < 3600) {
    const minutes = Math.floor(totalSeconds / 60);
    const remainingSeconds = totalSeconds % 60;
    if (remainingSeconds === 0) {
      return `约 ${minutes} 分钟`;
    }
    return `约 ${minutes} 分 ${remainingSeconds} 秒`;
  }

  const totalMinutes = Math.ceil(totalSeconds / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (minutes === 0) {
    return `约 ${hours} 小时`;
  }
  return `约 ${hours} 小时 ${minutes} 分钟`;
}

function formatModule(value: string | null | undefined): string {
  if (!value) {
    return '红外相机';
  }
  return moduleOptions.find((option) => option.value === value)?.label || value;
}
