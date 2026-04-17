import React, { useState, useEffect } from 'react';
import { Plus, Clock, Settings2, Trash2, Pause, Square, AlertTriangle, CheckSquare, Play } from 'lucide-react';

export default function Tasks({
  onCreateTask,
  onQueryData,
  onReview
}: {
  onCreateTask: () => void,
  onQueryData: (taskId: number) => void,
  onReview: (taskId: number) => void
}) {
  const [tasks, setTasks] = useState<any[]>([]);
  const [runningNowTaskId, setRunningNowTaskId] = useState<number | null>(null);

  const fetchTasks = async () => {
    try {
      const res = await fetch('/api/tasks');
      const data = await res.json();
      setTasks(data);
    } catch(e) { console.error(e); }
  };

  useEffect(() => {
    fetchTasks();
    const timer = setInterval(fetchTasks, 2000);
    return () => clearInterval(timer);
  }, []);

  const handleDelete = async (id: number) => {
    if(!confirm('确定删除此任务吗？')) return;
    try {
      await fetch(`/api/tasks/${id}`, { method: 'DELETE' });
      fetchTasks();
    } catch (e) {
      console.error(e);
    }
  };

  const updateTaskStatus = async (id: number, active: boolean) => {
    try {
      await fetch(`/api/tasks/${id}/status`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ active })
      });
      fetchTasks();
    } catch (e) {
      console.error(e);
    }
  };

  const runTaskNow = async (id: number) => {
    setRunningNowTaskId(id);
    try {
      const res = await fetch(`/api/tasks/${id}/run-now`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.error || data.message || '立即执行失败');
      }
      fetchTasks();
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

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        {tasks.length === 0 ? (
          <div className="xl:col-span-2 text-center py-12 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700">
            <p className="text-gray-500 dark:text-gray-400 mb-4">暂无任务，请点击上方按钮创建</p>
          </div>
        ) : (
          tasks.map(task => (
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

function TaskMonitorCard({ task, onDelete, onStatusChange, onRunNow, runningNow, onQueryData, onReview }: any) {
  const isRunning = task.active;
  const progress = Number(task.progress || 0);
  const processed = Number(task.processedCount || 0);
  const total = Number(task.totalCount || 0);
  const isCompleted = task.executionStatus === 'completed' && progress >= 100;

  const statusTextMap: Record<string, string> = {
    running: '运行中',
    completed: '已完成',
    failed: '执行失败',
    paused: '已暂停',
    idle: '未开始'
  };
  const statusText = statusTextMap[task.executionStatus] || '未开始';
  
  return (
    <div className="bg-white dark:bg-gray-800 p-6 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm transition-colors">
      <div className="flex justify-between items-start mb-4">
        <div>
          <div className="flex items-center gap-3">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">{task.name}</h3>
            {isRunning ? (
              <span className="px-2 py-0.5 rounded text-xs font-medium bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-400">
                {statusText}
              </span>
            ) : (
              <span className="px-2 py-0.5 rounded text-xs font-medium bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300">
                {statusText}
              </span>
            )}
          </div>
          <div className="flex flex-wrap gap-4 text-sm text-gray-500 dark:text-gray-400 mt-2">
            <span className="flex items-center gap-1"><Settings2 className="w-4 h-4" /> {task.clientName}</span>
            <span className="flex items-center gap-1"><Clock className="w-4 h-4" /> {task.interval}</span>
            <span className="flex items-center gap-1">执行方式: {task.executionMode === 'auto' ? '自动执行' : '手动执行'}</span>
          </div>
        </div>
        
        <div className="flex gap-2 items-center">
          {!isRunning && (
            <button 
              onClick={onQueryData}
              className="px-4 py-2 text-sm font-medium text-blue-600 bg-blue-50 hover:bg-blue-100 dark:text-blue-400 dark:bg-blue-900/20 dark:hover:bg-blue-900/40 border border-blue-200 dark:border-blue-800 rounded-lg flex items-center gap-2 transition-colors"
            >
              🔍 查询数据并执行
            </button>
          )}

          {isRunning && (
            <>
              <button 
                onClick={() => onStatusChange(false)}
                className="p-2 text-orange-600 dark:text-orange-400 bg-orange-50 dark:bg-orange-900/20 hover:bg-orange-100 dark:hover:bg-orange-900/40 rounded-lg transition-colors" 
                title="暂停"
              >
                <Pause className="w-5 h-5" />
              </button>
              <button 
                onClick={() => onStatusChange(false)}
                className="p-2 text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 hover:bg-red-100 dark:hover:bg-red-900/40 rounded-lg transition-colors" 
                title="停止"
              >
                <Square className="w-5 h-5" />
              </button>
            </>
          )}

          {isCompleted && (
            <button
              onClick={onReview}
              className="px-4 py-2 text-sm font-medium text-emerald-700 bg-emerald-50 hover:bg-emerald-100 dark:text-emerald-300 dark:bg-emerald-900/20 dark:hover:bg-emerald-900/40 border border-emerald-200 dark:border-emerald-800 rounded-lg flex items-center gap-2 transition-colors"
            >
              <CheckSquare className="w-4 h-4" />
              结果复核
            </button>
          )}
          
          <div className="w-px h-6 bg-gray-200 dark:bg-gray-700 mx-1"></div>

          <button
            onClick={onRunNow}
            disabled={isRunning || runningNow}
            className="inline-flex items-center gap-2 px-3 py-2 text-sm font-medium text-violet-700 bg-violet-50 hover:bg-violet-100 disabled:bg-gray-100 disabled:text-gray-400 dark:text-violet-300 dark:bg-violet-900/20 dark:hover:bg-violet-900/40 dark:disabled:bg-gray-800 dark:disabled:text-gray-500 border border-violet-200 dark:border-violet-800 rounded-lg transition-colors"
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
          <span className="font-medium">--</span>
        </div>
        <div>
          <span className="block text-xs text-gray-400 dark:text-gray-500 uppercase tracking-wider mb-1">预计剩余时间</span>
          <span className="font-medium">{isRunning ? '处理中...' : '--'}</span>
        </div>
        {task.executionStatus === 'failed' && (
          <div className="flex items-center gap-2 text-orange-600 dark:text-orange-400 ml-auto">
            <AlertTriangle className="w-4 h-4" />
            <span>{task.last_error || '任务执行失败，请重试。'}</span>
          </div>
        )}
      </div>
    </div>
  );
}
