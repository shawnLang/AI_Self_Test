import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowLeft, CheckCircle2, Clock, Image as ImageIcon, Play, RefreshCw, Video, XCircle, ZoomIn } from 'lucide-react';
import {
  getTaskDetail,
  listTaskItems,
  runTaskNow,
  type MediaType,
  type TaskItemListRow,
  type TaskSummary,
} from '../api/taskItems';

const mediaTypeLabel: Record<MediaType, string> = {
  image: '图片',
  video: '视频',
};

const intervalLabelMap: Record<number, string> = {
  1: '每小时',
  6: '每 6 小时',
  12: '每 12 小时',
  24: '每天',
  168: '每周',
};

type MediaFilter = MediaType | 'all';
type StatusFilter = 'all' | 'pending' | 'confirmed' | 'submitted' | 'failed';

export default function DataQuery({ taskId, onBack }: { taskId: number, onBack: () => void }) {
  const [task, setTask] = useState<TaskSummary | null>(null);
  const [items, setItems] = useState<TaskItemListRow[]>([]);
  const [total, setTotal] = useState(0);
  const [mediaFilter, setMediaFilter] = useState<MediaFilter>('all');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');
  const [previewItem, setPreviewItem] = useState<TaskItemListRow | null>(null);

  const loadWorkspace = useCallback(async () => {
    if (!taskId) return;

    setLoading(true);
    setError('');
    try {
      const [taskDetail, itemData] = await Promise.all([
        getTaskDetail(taskId),
        listTaskItems({ taskId, mediaType: mediaFilter, page: 1, pageSize: 100 }),
      ]);
      setTask(taskDetail);
      setItems(itemData.items);
      setTotal(itemData.total);
    } catch (e) {
      console.error(e);
      setError((e as Error).message || '任务工作区加载失败');
      setItems([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [taskId, mediaFilter]);

  useEffect(() => {
    loadWorkspace();
  }, [loadWorkspace]);

  const filteredItems = useMemo(() => items.filter((item) => matchStatusFilter(item, statusFilter)), [items, statusFilter]);

  const handleRunTask = async () => {
    setRunning(true);
    setError('');
    try {
      await runTaskNow(taskId);
      await loadWorkspace();
    } catch (e) {
      console.error(e);
      setError((e as Error).message || '立即执行任务失败');
    } finally {
      setRunning(false);
    }
  };

  const taskFilters = task?.filters;

  return (
    <div className="p-8 flex flex-col h-full">
      <div className="flex flex-col gap-4 mb-6 xl:flex-row xl:items-start xl:justify-between">
        <div className="flex items-start gap-4">
          <button onClick={onBack} className="p-2 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-colors" aria-label="返回任务列表">
            <ArrowLeft className="w-5 h-5" />
          </button>
          <div>
            <h2 className="text-2xl font-bold text-gray-900 dark:text-white">任务详情 / TaskItem 工作区</h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
              当前页面读取正式 Task 与 TaskItem 契约；筛选条件来自任务定义，执行入口统一走任务动作。
            </p>
          </div>
        </div>

        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            onClick={loadWorkspace}
            disabled={loading}
            className="px-4 py-2.5 rounded-lg text-sm font-medium flex items-center gap-2 transition-colors bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-60"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            刷新任务项
          </button>
          <button
            type="button"
            onClick={handleRunTask}
            disabled={running}
            className="px-6 py-2.5 rounded-lg text-sm font-medium flex items-center gap-2 transition-colors bg-green-600 hover:bg-green-700 text-white shadow-md disabled:bg-green-400"
          >
            <Play className="w-4 h-4" />
            {running ? '执行中...' : '立即执行任务'}
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 text-red-700 dark:border-red-900/40 dark:bg-red-900/20 dark:text-red-300 px-4 py-3 text-sm">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4 mb-6">
        <section className="xl:col-span-2 bg-white dark:bg-gray-800 p-5 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm transition-colors">
          <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
            <div>
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white">{task?.name || `任务 #${taskId}`}</h3>
              <div className="flex flex-wrap gap-3 text-sm text-gray-500 dark:text-gray-400 mt-2">
                <span>项目 #{task?.client_id ?? '--'}</span>
                <span>提示词配置 #{task?.config_id ?? '--'}</span>
                <span>{task ? intervalLabelMap[task.interval_hours] || `${task.interval_hours} 小时` : '--'}</span>
                <span>{task?.execution_mode === 'auto' ? '自动执行' : '手动执行'}</span>
                <span>{task?.auto_confirm ? '自动确认' : '人工确认'}</span>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <StatusBadge label={`状态：${task?.execution_status || '--'}`} tone={task?.execution_status === '失败' ? 'red' : task?.active ? 'green' : 'gray'} />
              <StatusBadge label={`进度：${task?.processed_count ?? 0}/${task?.total_count ?? 0}`} tone="blue" />
            </div>
          </div>

          {task?.last_error && (
            <div className="mt-4 rounded-lg border border-orange-200 bg-orange-50 text-orange-700 dark:border-orange-900/40 dark:bg-orange-900/20 dark:text-orange-300 px-4 py-3 text-sm">
              {task.last_error}
            </div>
          )}
        </section>

        <section className="bg-white dark:bg-gray-800 p-5 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm transition-colors">
          <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-3">任务保存筛选条件</h3>
          <div className="space-y-2 text-sm text-gray-600 dark:text-gray-300">
            <FilterLine label="分类" value={formatList(taskFilters?.classify_list)} />
            <FilterLine label="关键词" value={taskFilters?.keyword || '--'} />
            <FilterLine label="物种" value={taskFilters?.sp_name || '--'} />
            <FilterLine label="时间" value={`${taskFilters?.start_at || '--'} ~ ${taskFilters?.end_at || '--'}`} />
            <FilterLine label="媒体" value={formatList(taskFilters?.media_types.map((item) => mediaTypeLabel[item]))} />
          </div>
        </section>
      </div>

      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm overflow-hidden flex flex-col transition-colors flex-1 min-h-0">
        <div className="p-4 border-b border-gray-200 dark:border-gray-700 flex flex-col gap-3 bg-gray-50/50 dark:bg-gray-800/80 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h3 className="font-semibold text-gray-700 dark:text-gray-200">
              TaskItem 列表 <span className="ml-2 font-normal text-sm bg-gray-200 dark:bg-gray-700 px-2 py-0.5 rounded-full">{filteredItems.length} / {total} 项</span>
            </h3>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">这里展示已落库任务项，不再实时查询并下发旧任务数据。</p>
          </div>

          <div className="flex flex-wrap gap-2">
            <select
              value={mediaFilter}
              onChange={(e) => setMediaFilter(e.target.value as MediaFilter)}
              className="bg-white dark:bg-gray-900 border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm dark:text-white"
            >
              <option value="all">全部媒体</option>
              <option value="image">仅图片</option>
              <option value="video">仅视频</option>
            </select>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
              className="bg-white dark:bg-gray-900 border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm dark:text-white"
            >
              <option value="all">全部状态</option>
              <option value="pending">待处理/待确认</option>
              <option value="confirmed">已确认</option>
              <option value="submitted">已提交</option>
              <option value="failed">异常</option>
            </select>
          </div>
        </div>

        <div className="p-4 flex-1 overflow-auto">
          {loading ? (
            <EmptyState icon={<RefreshCw className="w-12 h-12 mb-4 opacity-50 animate-spin" />} title="正在加载任务项..." description="请稍候" />
          ) : filteredItems.length === 0 ? (
            <EmptyState icon={<ImageIcon className="w-12 h-12 mb-4 opacity-50" />} title="暂无 TaskItem" description="请先执行任务，或调整媒体/状态筛选。" />
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-4">
              {filteredItems.map((item) => (
                <TaskItemCard key={item.id} item={item} onPreview={() => setPreviewItem(item)} />
              ))}
            </div>
          )}
        </div>
      </div>

      {previewItem && (
        <div
          className="fixed inset-0 z-50 bg-black/85 flex items-center justify-center p-4"
          onClick={() => setPreviewItem(null)}
        >
          <div
            className="relative w-full max-w-6xl max-h-[92vh] rounded-xl bg-black border border-white/20 p-3"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              type="button"
              onClick={() => setPreviewItem(null)}
              className="absolute right-3 top-3 z-10 h-8 w-8 rounded-full bg-black/60 text-white hover:bg-black/80 text-lg leading-none"
              aria-label="关闭预览"
            >
              ×
            </button>

            <div className="text-white text-sm mb-3 pr-10 truncate">
              {previewItem.name || '媒体预览'} · TaskItem #{previewItem.id}
            </div>

            <div className="w-full h-[78vh] flex items-center justify-center">
              {previewItem.media_type === 'video' ? (
                <video
                  src={previewItem.file_url}
                  className="max-h-full max-w-full rounded-md"
                  controls
                  autoPlay
                  playsInline
                />
              ) : (
                <img
                  src={previewItem.file_url}
                  className="max-h-full max-w-full object-contain rounded-md"
                  alt="预览"
                />
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function TaskItemCard({ item, onPreview }: { key?: React.Key; item: TaskItemListRow; onPreview: () => void }) {
  const failed = isFailedItem(item);
  const confirmed = isConfirmedItem(item);
  const submitted = item.remote_state === 'success';

  return (
    <article className="relative p-3 border rounded-xl overflow-hidden transition-all duration-200 bg-white dark:bg-gray-900 border-gray-100 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600">
      <div className="aspect-video w-full bg-gray-100 dark:bg-gray-800 rounded-lg overflow-hidden relative border border-gray-200 dark:border-gray-700">
        {item.file_url && item.media_type === 'video' ? (
          <video src={item.file_url} className="w-full h-full object-cover" preload="metadata" muted playsInline />
        ) : item.file_url ? (
          <img src={item.file_url} className="w-full h-full object-cover" alt={item.name || 'TaskItem'} />
        ) : (
          <div className="w-full h-full flex items-center justify-center">
            <ImageIcon className="w-8 h-8 text-gray-300 dark:text-gray-600" />
          </div>
        )}

        <button
          type="button"
          onClick={onPreview}
          className="absolute top-2 right-2 p-1.5 rounded-md bg-black/55 text-white hover:bg-black/75 transition-colors"
          title="预览"
          aria-label="预览"
        >
          <ZoomIn className="w-4 h-4" />
        </button>

        <span className="absolute top-2 left-2 inline-flex items-center gap-1 rounded-md bg-black/55 px-2 py-1 text-xs text-white">
          {item.media_type === 'video' ? <Video className="w-3 h-3" /> : <ImageIcon className="w-3 h-3" />}
          {mediaTypeLabel[item.media_type]}
        </span>
      </div>

      <div className="mt-3 px-1">
        <div className="flex items-center justify-between gap-2">
          <h4 className="truncate text-sm font-semibold text-gray-900 dark:text-gray-100" title={item.name}>{item.name || `TaskItem #${item.id}`}</h4>
          <span className="text-xs text-gray-500 dark:text-gray-400 shrink-0">#{item.id}</span>
        </div>
        <div className="mt-2 flex flex-wrap gap-2">
          <StatusBadge label={item.status || '未开始'} tone={failed ? 'red' : 'gray'} />
          <StatusBadge label={item.down_state ? '已下载' : '待下载'} tone={item.down_state ? 'green' : 'gray'} />
          <StatusBadge label={`识别：${item.llm_state || 'pending'}`} tone={item.llm_state === 'success' ? 'green' : 'blue'} />
          <StatusBadge label={confirmed ? '已确认' : '待确认'} tone={confirmed ? 'green' : 'gray'} />
          <StatusBadge label={submitted ? '已提交' : `提交：${item.remote_state || 'pending'}`} tone={submitted ? 'green' : 'blue'} />
        </div>
      </div>
    </article>
  );
}

function EmptyState({ icon, title, description }: { icon: React.ReactNode; title: string; description: string }) {
  return (
    <div className="h-full flex flex-col items-center justify-center text-gray-400 dark:text-gray-500 py-12">
      {icon}
      <p className="text-base font-medium text-gray-600 dark:text-gray-300">{title}</p>
      <p className="text-sm mt-1">{description}</p>
    </div>
  );
}

function StatusBadge({ label, tone }: { label: string; tone: 'gray' | 'blue' | 'green' | 'red' }) {
  const classes = {
    gray: 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300',
    blue: 'bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300',
    green: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300',
    red: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300',
  }[tone];

  return <span className={`rounded-full px-2 py-1 text-xs font-medium ${classes}`}>{label}</span>;
}

function FilterLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <span className="text-gray-400 dark:text-gray-500 shrink-0">{label}</span>
      <span className="text-right break-all">{value || '--'}</span>
    </div>
  );
}

function formatList(values: Array<string | number> | undefined) {
  if (!values || values.length === 0) return '--';
  return values.join('、');
}

function matchStatusFilter(item: TaskItemListRow, filter: StatusFilter) {
  if (filter === 'all') return true;
  if (filter === 'confirmed') return isConfirmedItem(item);
  if (filter === 'submitted') return item.remote_state === 'success';
  if (filter === 'failed') return isFailedItem(item);
  return !isConfirmedItem(item) && item.remote_state !== 'success';
}

function isConfirmedItem(item: TaskItemListRow) {
  return item.confirm_state === 'manual_confirmed' || item.confirm_state === 'auto_confirmed';
}

function isFailedItem(item: TaskItemListRow) {
  return [item.status, item.llm_state, item.confirm_state, item.remote_state].some((value) => String(value || '').includes('失败') || String(value || '').toLowerCase() === 'failed');
}
