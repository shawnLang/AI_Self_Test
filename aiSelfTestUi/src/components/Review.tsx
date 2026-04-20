import React, { useState } from 'react';
import { Check, Trash2, List, LayoutGrid, Image as ImageIcon, CheckSquare, ChevronLeft, ChevronRight } from 'lucide-react';

export default function Review({ initialTaskId = null }: { initialTaskId?: number | null }) {
  const [viewMode, setViewMode] = useState<'list' | 'grid' | 'gallery'>('grid');
  const [items, setItems] = useState<any[]>([]);
  const [activeItemId, setActiveItemId] = useState<string | null>(null);
  const [taskOptions, setTaskOptions] = useState<any[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<string>(initialTaskId ? String(initialTaskId) : '');
  const [consistencyFilter, setConsistencyFilter] = useState<'all' | 'matched' | 'mismatched'>('all');
  const [previewItem, setPreviewItem] = useState<any | null>(null);

  const fetchTaskOptions = async () => {
    try {
      const res = await fetch('/api/reviews/completed-tasks');
      const data = await res.json();
      setTaskOptions(data || []);
      if (Array.isArray(data) && data.length > 0) {
        const initialId = initialTaskId ? String(initialTaskId) : '';
        const hasInitial = initialId ? data.some((task: any) => String(task.id) === initialId) : false;
        setSelectedTaskId((current) => {
          if (current && data.some((task: any) => String(task.id) === current)) return current;
          if (hasInitial) return initialId;
          return String(data[0].id);
        });
      } else {
        setSelectedTaskId('');
      }
    } catch (e) {
      console.error(e);
    }
  };

  const fetchReviews = async (taskId = selectedTaskId) => {
    try {
      if (!taskId) {
        setItems([]);
        setActiveItemId(null);
        return;
      }

      const query = `?taskId=${taskId}`;
      const res = await fetch(`/api/reviews${query}`);
      const data = await res.json();
      setItems(data);
      if (data.length > 0) {
        const hasActive = data.some((x: any) => x.id === activeItemId);
        if (!hasActive) setActiveItemId(data[0].id);
      } else {
        setActiveItemId(null);
      }
    } catch (e) {
      console.error(e);
    }
  };

  React.useEffect(() => {
    fetchTaskOptions();
  }, []);

  React.useEffect(() => {
    if (selectedTaskId) {
      fetchReviews(selectedTaskId);
    }
  }, [selectedTaskId]);

  const handleConfirm = async (id: string) => {
    try {
      const response = await fetch('/api/reviews/confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: [id] })
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || Number(data.failureCount || 0) > 0) {
        const failed = Array.isArray(data.results) ? data.results.filter((item: any) => item.status === 'failed') : [];
        const message = failed.map((item: any) => item.message).filter(Boolean).join('\n') || data.error || '确认回写失败';
        window.alert(message);
      }
      fetchReviews();
    } catch (e) { console.error(e); }
  };

  const handleDelete = async (id: string) => {
    try {
      await fetch(`/api/reviews/${id}`, { method: 'DELETE' });
      fetchReviews();
    } catch (e) { console.error(e); }
  };

  const handleBatchDelete = async () => {
    if (!filteredItems.length) return;
    if (!window.confirm('确定要批量删除当前筛选下的全部复核数据吗？此操作不可恢复。')) {
      return;
    }
    try {
      await fetch('/api/reviews/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: filteredItems.map(i => i.id) })
      });
      fetchReviews();
    } catch (e) { console.error(e); }
  };

  const handleBatchConfirm = async () => {
    if (!filteredItems.length) return;
    try {
      const response = await fetch('/api/reviews/confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: filteredItems.map(i => i.id) })
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || Number(data.failureCount || 0) > 0) {
        window.alert(`批量确认完成：成功 ${Number(data.successCount || 0)} 条，失败 ${Number(data.failureCount || 0)} 条。失败项仍保留在待复核列表。`);
      }
      fetchReviews();
    } catch (e) { console.error(e); }
  };

  const openPreview = (item: any) => {
    setPreviewItem(item);
  };

  const closePreview = () => {
    setPreviewItem(null);
  };

  const normalizeCompareValue = (value: string) => String(value || '').trim().toLowerCase().replace(/\s+/g, '');

  const getCompareTokens = (value: string) => {
    const trimmed = String(value || '').trim();
    if (!trimmed) return [];

    const parts = trimmed
      .split(/[、,，;；|/]+/)
      .map(normalizeCompareValue)
      .filter(Boolean);

    return parts.length > 0 ? parts : [normalizeCompareValue(trimmed)];
  };

  const isResultMatched = (item: any) => {
    const rows = getReviewRows(item);
    if (Array.isArray(item.reviewRows)) {
      return rows.length > 0 && rows.every((row: any) => row.decision === 'keep' && row.willSubmit);
    }

    const aiValue = normalizeCompareValue(item.aiResult || '');
    if (!aiValue || aiValue.startsWith('识别失败:')) return false;

    const originalTokens = getCompareTokens(item.originalResult || '');
    if (originalTokens.length === 0) return false;

    return originalTokens.some((token) => token === aiValue || token.includes(aiValue) || aiValue.includes(token));
  };

  const filteredItems = items.filter((item) => {
    const matched = isResultMatched(item);
    if (consistencyFilter === 'matched') return matched;
    if (consistencyFilter === 'mismatched') return !matched;
    return true;
  });

  const matchedCount = items.filter((item) => isResultMatched(item)).length;
  const mismatchedCount = items.length - matchedCount;
  const totalCount = items.length;

  React.useEffect(() => {
    if (filteredItems.length === 0) {
      setActiveItemId(null);
      return;
    }

    const stillExists = filteredItems.some((item) => item.id === activeItemId);
    if (!stillExists) {
      setActiveItemId(filteredItems[0].id);
    }
  }, [filteredItems, activeItemId]);

  const getActiveIndex = () => filteredItems.findIndex((item) => item.id === activeItemId);

  const switchGalleryItem = (direction: 'prev' | 'next') => {
    if (filteredItems.length <= 1) return;

    const currentIndex = getActiveIndex();
    const safeIndex = currentIndex >= 0 ? currentIndex : 0;
    const nextIndex = direction === 'prev'
      ? Math.max(0, safeIndex - 1)
      : Math.min(filteredItems.length - 1, safeIndex + 1);

    if (nextIndex !== safeIndex) {
      setActiveItemId(filteredItems[nextIndex].id);
    }
  };

  React.useEffect(() => {
    if (viewMode !== 'gallery' || filteredItems.length <= 1 || previewItem) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const tagName = target?.tagName;
      const isEditable = target?.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(tagName || '');
      if (isEditable) return;

      if (event.key === 'ArrowLeft') {
        event.preventDefault();
        switchGalleryItem('prev');
      }

      if (event.key === 'ArrowRight') {
        event.preventDefault();
        switchGalleryItem('next');
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [viewMode, filteredItems, activeItemId, previewItem]);

  const renderMedia = (item: any, className: string) => {
    if (item.mediaType === 'video') {
      return <video src={item.mediaUrl || item.imageUrl} className={className} controls muted playsInline preload="metadata" />;
    }
    return <img src={item.imageUrl} alt="Thumbnail" className={className} referrerPolicy="no-referrer" />;
  };

  const BBOX_COLORS: Record<string, string> = {
    keep: 'border-green-400',
    rename: 'border-amber-400',
    exclude: 'border-gray-400',
    error: 'border-red-400',
  };
  const BBOX_LABEL_COLORS: Record<string, string> = {
    keep: 'bg-green-500',
    rename: 'bg-amber-500',
    exclude: 'bg-gray-500',
    error: 'bg-red-500',
  };

  const renderImageWithBboxOverlay = (item: any, options?: { contain?: boolean }) => {
    const rows = Array.isArray(item.reviewRows) ? item.reviewRows : [];
    const validRows = rows.filter((row: any) => {
      const b = row.bbox;
      const s = row.groundingMeta?.sourceSize;
      return b && s && s.width > 0 && s.height > 0 && b.maxx > b.minx && b.maxy > b.miny;
    });

    const renderBboxes = (rows: any[]) => rows.flatMap((row: any, index: number) => {
      const b = row.bbox;
      const s = row.groundingMeta.sourceSize;
      const borderClass = BBOX_COLORS[row.decision] ?? 'border-blue-400';
      const labelClass = BBOX_LABEL_COLORS[row.decision] ?? 'bg-blue-500';
      const toPercent = (box: any) => ({
        left: (box.minx / s.width) * 100,
        top: (box.miny / s.height) * 100,
        width: ((box.maxx - box.minx) / s.width) * 100,
        height: ((box.maxy - box.miny) / s.height) * 100,
      });
      const orig = toPercent(b);
      const elems = [
        <div
          key={`bbox-${index}`}
          className={`absolute border-2 ${borderClass} pointer-events-none`}
          style={{ left: `${orig.left}%`, top: `${orig.top}%`, width: `${orig.width}%`, height: `${orig.height}%` }}
        >
          <span className={`absolute -top-4 left-0 ${labelClass} text-white text-[10px] font-bold px-1 leading-4 rounded-sm`}>
            {index + 1}
          </span>
        </div>
      ];
      const cropBox = row.groundingMeta?.cropBox;
      if (cropBox && cropBox.maxx > cropBox.minx && cropBox.maxy > cropBox.miny) {
        const crop = toPercent(cropBox);
        elems.push(
          <div
            key={`crop-${index}`}
            className={`absolute border-2 border-dashed ${borderClass} pointer-events-none opacity-60`}
            style={{ left: `${crop.left}%`, top: `${crop.top}%`, width: `${crop.width}%`, height: `${crop.height}%` }}
          />
        );
      }
      return elems;
    });

    if (options?.contain) {
      // 用 aspect-ratio wrapper 使图片精确填满自身比例，bbox % 坐标在 wrapper 内完全准确
      const sourceSize = validRows[0]?.groundingMeta?.sourceSize;
      const aspectRatio = sourceSize ? `${sourceSize.width}/${sourceSize.height}` : undefined;
      return (
        <div className="w-full h-full flex items-center justify-center overflow-hidden">
          <div
            className="relative"
            style={aspectRatio ? { aspectRatio, maxWidth: '100%', maxHeight: '100%' } : { width: '100%', height: '100%' }}
          >
            <img src={item.imageUrl} alt="Thumbnail" className="w-full h-full object-cover" referrerPolicy="no-referrer" />
            {renderBboxes(validRows)}
          </div>
        </div>
      );
    }

    // 自然模式：图片以原始宽高比伸展，bbox % 坐标完全对齐
    return (
      <div className="relative w-full">
        <img src={item.imageUrl} alt="Thumbnail" className="w-full h-auto block" referrerPolicy="no-referrer" />
        {renderBboxes(validRows)}
      </div>
    );
  };

  function getReviewRows(item: any) {
    if (Array.isArray(item.reviewRows)) return item.reviewRows;
    const aiValue = normalizeCompareValue(item.aiResult || '');
    const originalTokens = getCompareTokens(item.originalResult || '');
    const matched = Boolean(aiValue) && !aiValue.startsWith('识别失败:') && originalTokens.some((token) => token === aiValue || token.includes(aiValue) || aiValue.includes(token));
    return [{
      originalName: item.originalResult,
      aiName: item.aiResult,
      decision: matched ? 'keep' : 'rename',
      willSubmit: Boolean(item.aiResult),
      groundingStatus: 'legacy',
      legacy: true
    }];
  }

  const getDecisionLabel = (row: any) => {
    if (row.decision === 'keep') return '提交';
    if (row.decision === 'rename') return '改名提交';
    if (row.decision === 'exclude') return '排除';
    return '错误';
  };

  const getDecisionClass = (row: any) => {
    if (row.decision === 'keep') return 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300';
    if (row.decision === 'rename') return 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300';
    if (row.decision === 'exclude') return 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300';
    return 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300';
  };

  const renderSummaryBadges = (item: any) => (
    <div className="flex flex-wrap gap-2 text-xs">
      <span className="rounded-full bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300 px-2 py-1">
        将提交 {Number(item.submitCount || 0)} 条
      </span>
      <span className="rounded-full bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300 px-2 py-1">
        排除 {Number(item.excludedCount || 0)} 条
      </span>
      {item.willSubmitEmptyArray && (
        <span className="rounded-full bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300 px-2 py-1">
          空数组提交
        </span>
      )}
      {item.remoteError && (
        <span className="rounded-full bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300 px-2 py-1">
          远端更新失败/可重试
        </span>
      )}
    </div>
  );

  const renderReviewRows = (item: any, compact = false) => {
    const rows = getReviewRows(item);
    if (rows.length === 0) {
      return (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-700 dark:border-amber-900/40 dark:bg-amber-900/20 dark:text-amber-300">
          大模型未保留可提交物种，确认后将提交空数组。
        </div>
      );
    }

    return (
      <div className={`space-y-2 ${compact ? 'text-xs' : 'text-sm'}`}>
        {rows.map((row: any, index: number) => (
          <div key={`${row.recordId ?? index}-${index}`} className="rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
              <span className="font-medium text-gray-900 dark:text-gray-100">结果 {index + 1}</span>
              <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${getDecisionClass(row)}`}>
                {getDecisionLabel(row)}
              </span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <div>
                <span className="block text-[11px] text-gray-500 dark:text-gray-400 mb-0.5">原结果</span>
                <span className="text-red-700 dark:text-red-300">{row.originalName || '--'}</span>
              </div>
              <div>
                <span className="block text-[11px] text-gray-500 dark:text-gray-400 mb-0.5">大模型</span>
                <span className="text-green-700 dark:text-green-300">{row.aiName || (row.decision === 'exclude' ? '无' : '--')}</span>
              </div>
            </div>
            {(row.groundingStatus || row.errorMessage) && (
              <div className="mt-2 text-[11px] text-gray-500 dark:text-gray-400">
                定位：{row.groundingStatus || '--'}{row.errorMessage ? `；${row.errorMessage}` : ''}
              </div>
            )}
          </div>
        ))}
      </div>
    );
  };

  const renderListView = () => (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm overflow-hidden transition-colors">
      <table className="w-full text-left border-collapse">
        <thead>
          <tr className="bg-gray-50 dark:bg-gray-900/50 border-b border-gray-200 dark:border-gray-700">
            <th className="px-4 py-3 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase">缩略图</th>
            <th className="px-4 py-3 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase">任务</th>
            <th className="px-4 py-3 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase">原有系统</th>
            <th className="px-4 py-3 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase">AI 多模态模型</th>
            <th className="px-4 py-3 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase">对比结果</th>
            <th className="px-4 py-3 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase text-right">操作</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
          {filteredItems.map(item => {
            const matched = isResultMatched(item);
            return (
            <tr key={item.id} className={`hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors ${matched ? 'border-l-4 border-l-green-500' : 'border-l-4 border-l-red-500'}`}>
              <td className="px-4 py-3 whitespace-nowrap">
                <div className="w-16 rounded overflow-hidden bg-gray-100 dark:bg-gray-900 flex-shrink-0">
                  {item.mediaType === 'video' ? (
                    renderMedia(item, 'w-full h-full object-cover')
                  ) : (
                    <button
                      type="button"
                      onClick={() => openPreview(item)}
                      className="w-full cursor-zoom-in"
                      title="查看大图"
                    >
                      {renderImageWithBboxOverlay(item)}
                    </button>
                  )}
                </div>
              </td>
              <td className="px-4 py-3 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-gray-100">
                <div className="flex flex-col gap-2">
                  <div className="flex items-center gap-2">
                  <span>{item.taskName || '--'}</span>
                  {matched && (
                    <span className="inline-flex items-center rounded-md bg-green-600 px-2 py-0.5 text-xs font-bold text-white">
                      结果一致
                    </span>
                  )}
                  </div>
                  {renderSummaryBadges(item)}
                </div>
              </td>
              <td className="px-4 py-3 text-sm text-gray-500 dark:text-gray-400" colSpan={2}>
                {renderReviewRows(item, true)}
              </td>
              <td className="px-4 py-3 whitespace-nowrap text-sm">
                <span className={`inline-flex items-center rounded-md px-2.5 py-1 font-medium ${matched ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300' : 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300'}`}>
                  {matched ? '结果一致' : '结果不一致'}
                </span>
              </td>
              <td className="px-4 py-3 whitespace-nowrap text-right space-x-2">
                <button onClick={() => handleConfirm(item.id)} className="text-blue-600 dark:text-blue-400 hover:text-blue-900 dark:hover:text-blue-300 text-sm font-medium">确认</button>
                <button onClick={() => handleDelete(item.id)} className="text-red-600 dark:text-red-400 hover:text-red-900 dark:hover:text-red-300 text-sm font-medium">删除</button>
              </td>
            </tr>
          )})}
        </tbody>
      </table>
    </div>
  );

  const renderGridView = () => (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
      {filteredItems.map((item) => {
        const matched = isResultMatched(item);
        return (
        <div key={item.id} className={`bg-white dark:bg-gray-800 rounded-xl border-2 shadow-sm overflow-hidden flex flex-col transition-colors ${matched ? 'border-green-500 dark:border-green-400' : 'border-red-500 dark:border-red-400'}`}>
          <div className="w-full bg-gray-100 dark:bg-gray-900 relative">
            {item.mediaType === 'video' ? (
              renderMedia(item, 'w-full h-auto')
            ) : (
              <button
                type="button"
                onClick={() => openPreview(item)}
                className="w-full cursor-zoom-in text-left"
                title="查看大图"
              >
                {renderImageWithBboxOverlay(item)}
              </button>
            )}
            <div className="absolute top-2 left-2 bg-black/60 text-white text-xs px-2 py-1 rounded backdrop-blur-sm">
              {item.taskName || item.id}
            </div>
            {matched && (
              <div className="absolute top-2 right-2 bg-green-600 text-white text-xs font-bold px-2.5 py-1 rounded">
                结果一致
              </div>
            )}
          </div>
          
          <div className="p-5 flex-1 flex flex-col justify-between">
            <div>
              <div className="mb-4">
                {renderSummaryBadges(item)}
              </div>
              {renderReviewRows(item, true)}
              {item.remoteError && (
                <div className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-900/40 dark:bg-red-900/20 dark:text-red-300">
                  {item.remoteError}
                </div>
              )}
            </div>

            <div className="flex gap-2 mt-6">
              <button 
                onClick={() => handleConfirm(item.id)}
                className="flex-1 bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 hover:bg-blue-100 dark:hover:bg-blue-900/50 py-2 rounded-lg text-sm font-medium transition-colors flex items-center justify-center gap-2"
              >
                <Check className="w-4 h-4" />
                确认并更新
              </button>
              <button 
                onClick={() => handleDelete(item.id)}
                className="px-4 bg-gray-50 dark:bg-gray-700 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/30 border border-gray-200 dark:border-gray-600 hover:border-red-200 dark:hover:border-red-800 py-2 rounded-lg text-sm font-medium transition-colors flex items-center justify-center"
                title="删除记录"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>
      )})}
    </div>
  );

  const renderGalleryView = () => {
    const activeItem = filteredItems.find(i => i.id === activeItemId) || filteredItems[0];
    if (!activeItem) return null;
    const activeIndex = filteredItems.findIndex(i => i.id === activeItem.id);
    const hasPrevious = activeIndex > 0;
    const hasNext = activeIndex < filteredItems.length - 1;
    const matched = isResultMatched(activeItem);

    return (
      <div className="flex flex-col lg:flex-row gap-4" style={{ height: 'calc(100vh - 220px)', minHeight: '480px' }}>
        {/* 左侧：图片 + 缩略图条 */}
        <div className={`flex-1 flex flex-col gap-3 bg-white dark:bg-gray-800 p-4 rounded-xl border-2 shadow-sm transition-colors min-w-0 ${matched ? 'border-green-500 dark:border-green-400' : 'border-red-500 dark:border-red-400'}`}>
          <div className="flex-1 bg-gray-100 dark:bg-gray-900 rounded-lg overflow-hidden relative min-h-0">
            {activeItem.mediaType === 'video' ? (
              <video src={activeItem.mediaUrl || activeItem.imageUrl} className="w-full h-full object-contain" controls playsInline />
            ) : (
              <button
                type="button"
                onClick={() => openPreview(activeItem)}
                className="w-full h-full cursor-zoom-in"
                title="查看大图"
              >
                {renderImageWithBboxOverlay(activeItem, { contain: true })}
              </button>
            )}
            <div className="absolute top-3 left-3 bg-black/60 text-white text-xs px-2 py-1 rounded backdrop-blur-sm pointer-events-none">
              {activeItem.taskName || activeItem.id}
            </div>
            {matched && (
              <div className="absolute top-3 right-3 bg-green-600 text-white text-xs font-bold px-2 py-1 rounded pointer-events-none">
                结果一致
              </div>
            )}
            {filteredItems.length > 1 && (
              <>
                <button type="button" onClick={() => switchGalleryItem('prev')} disabled={!hasPrevious}
                  className="absolute left-3 top-1/2 -translate-y-1/2 h-9 w-9 rounded-full bg-black/60 text-white flex items-center justify-center hover:bg-black/80 disabled:opacity-35 disabled:cursor-not-allowed transition-colors"
                  title="上一个" aria-label="上一个">
                  <ChevronLeft className="w-5 h-5" />
                </button>
                <button type="button" onClick={() => switchGalleryItem('next')} disabled={!hasNext}
                  className="absolute right-3 top-1/2 -translate-y-1/2 h-9 w-9 rounded-full bg-black/60 text-white flex items-center justify-center hover:bg-black/80 disabled:opacity-35 disabled:cursor-not-allowed transition-colors"
                  title="下一个" aria-label="下一个">
                  <ChevronRight className="w-5 h-5" />
                </button>
              </>
            )}
          </div>
          {/* 缩略图条 */}
          <div className="flex gap-2 overflow-x-auto flex-shrink-0 pb-1">
            {filteredItems.map(item => (
              <button key={item.id} onClick={() => setActiveItemId(item.id)}
                className={`flex-shrink-0 w-20 h-14 rounded-md overflow-hidden border-2 transition-colors ${
                  activeItemId === item.id
                    ? (isResultMatched(item) ? 'border-green-500 dark:border-green-400' : 'border-red-500 dark:border-red-400')
                    : 'border-transparent opacity-60 hover:opacity-100'
                }`}>
                {item.mediaType === 'video' ? (
                  <video src={item.mediaUrl || item.imageUrl} className="w-full h-full object-cover" muted playsInline preload="metadata" />
                ) : (
                  <img src={item.imageUrl} className="w-full h-full object-cover" referrerPolicy="no-referrer" />
                )}
              </button>
            ))}
          </div>
        </div>

        {/* 右侧：识别详情（内部可滚动，整体不超出视口） */}
        <div className={`w-full lg:w-72 flex flex-col bg-white dark:bg-gray-800 rounded-xl border-2 shadow-sm transition-colors overflow-hidden ${matched ? 'border-green-500 dark:border-green-400' : 'border-red-500 dark:border-red-400'}`}>
          <div className="p-4 border-b border-gray-200 dark:border-gray-700 flex-shrink-0">
            <h3 className="text-base font-semibold text-gray-900 dark:text-white">识别详情</h3>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 truncate">任务：{activeItem.taskName || '--'}</p>
            <div className="flex flex-wrap gap-2 mt-2">
              <span className={`inline-flex items-center rounded-md px-2.5 py-0.5 text-xs font-bold ${matched ? 'bg-green-600 text-white' : 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300'}`}>
                {matched ? '结果一致' : '结果不一致'}
              </span>
              {renderSummaryBadges(activeItem)}
            </div>
          </div>
          <div className="flex-1 overflow-y-auto p-4 space-y-3 min-h-0">
            {renderReviewRows(activeItem)}
            {activeItem.remoteError && (
              <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-900/40 dark:bg-red-900/20 dark:text-red-300">
                {activeItem.remoteError}
              </div>
            )}
          </div>
          <div className="p-4 flex flex-col gap-2 border-t border-gray-200 dark:border-gray-700 flex-shrink-0">
            <button onClick={() => handleConfirm(activeItem.id)}
              className="w-full bg-blue-600 hover:bg-blue-700 text-white py-2.5 rounded-lg text-sm font-medium transition-colors flex items-center justify-center gap-2">
              <Check className="w-4 h-4" />确认并更新
            </button>
            <button onClick={() => handleDelete(activeItem.id)}
              className="w-full bg-white dark:bg-gray-800 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 border border-gray-200 dark:border-gray-700 hover:border-red-200 dark:hover:border-red-800 py-2.5 rounded-lg text-sm font-medium transition-colors flex items-center justify-center gap-2">
              <Trash2 className="w-4 h-4" />删除记录
            </button>
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="p-8">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-6 gap-4">
        <div>
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">结果复核</h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">复核并确认 AI 多模态模型的识别结果。</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <select
            value={selectedTaskId}
            onChange={(e) => setSelectedTaskId(e.target.value)}
            className="bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm"
          >
            {taskOptions.map(task => (
              <option key={task.id} value={String(task.id)}>{task.name}</option>
            ))}
          </select>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setConsistencyFilter('all')}
              className={`rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                consistencyFilter === 'all'
                  ? 'bg-gray-900 text-white dark:bg-white dark:text-gray-900'
                  : 'bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300'
              }`}
            >
              全部 {totalCount}
            </button>
            <button
              type="button"
              onClick={() => setConsistencyFilter('matched')}
              className={`rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                consistencyFilter === 'matched'
                  ? 'bg-green-600 text-white'
                  : 'bg-white dark:bg-gray-800 border border-green-300 dark:border-green-700 text-green-700 dark:text-green-300'
              }`}
            >
              一致 {matchedCount}
            </button>
            <button
              type="button"
              onClick={() => setConsistencyFilter('mismatched')}
              className={`rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                consistencyFilter === 'mismatched'
                  ? 'bg-red-600 text-white'
                  : 'bg-white dark:bg-gray-800 border border-red-300 dark:border-red-700 text-red-700 dark:text-red-300'
              }`}
            >
              不一致 {mismatchedCount}
            </button>
          </div>

          <div className="flex bg-gray-100 dark:bg-gray-800 p-1 rounded-lg border border-gray-200 dark:border-gray-700">
            <button 
              onClick={() => setViewMode('list')}
              className={`p-1.5 rounded-md transition-colors ${viewMode === 'list' ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm' : 'text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-200'}`}
              title="列表视图"
            >
              <List className="w-4 h-4" />
            </button>
            <button 
              onClick={() => setViewMode('grid')}
              className={`p-1.5 rounded-md transition-colors ${viewMode === 'grid' ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm' : 'text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-200'}`}
              title="图标视图"
            >
              <LayoutGrid className="w-4 h-4" />
            </button>
            <button 
              onClick={() => setViewMode('gallery')}
              className={`p-1.5 rounded-md transition-colors ${viewMode === 'gallery' ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm' : 'text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-200'}`}
              title="画廊视图"
            >
              <ImageIcon className="w-4 h-4" />
            </button>
          </div>

          <div className="w-px h-6 bg-gray-300 dark:bg-gray-700 mx-1"></div>

          <button onClick={handleBatchDelete} className="bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 px-4 py-2 rounded-lg text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors">
            批量删除
          </button>
          <button onClick={handleBatchConfirm} className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors">
            批量确认
          </button>
        </div>
      </div>

      {filteredItems.length === 0 ? (
        <div className="py-16 text-center text-gray-500 dark:text-gray-400 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 border-dashed transition-colors">
          <CheckSquare className="w-12 h-12 mx-auto text-gray-300 dark:text-gray-600 mb-3" />
          <p className="text-lg font-medium text-gray-900 dark:text-white">{items.length === 0 ? '全部处理完毕！' : '暂无匹配结果'}</p>
          <p>当前筛选下没有匹配的复核数据。</p>
        </div>
      ) : (
        <>
          {viewMode === 'list' && renderListView()}
          {viewMode === 'grid' && renderGridView()}
          {viewMode === 'gallery' && renderGalleryView()}
        </>
      )}

      {previewItem && (
        <div
          className="fixed inset-0 z-50 bg-black/85 flex items-center justify-center p-4"
          onClick={closePreview}
        >
          <div
            className="relative w-full max-w-6xl max-h-[92vh] rounded-xl bg-black border border-white/20 p-3"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              type="button"
              onClick={closePreview}
              className="absolute right-3 top-3 z-10 h-8 w-8 rounded-full bg-black/60 text-white hover:bg-black/80 text-lg leading-none"
              aria-label="关闭预览"
            >
              ×
            </button>

            <div className="text-white text-sm mb-3 pr-10 truncate">
              {previewItem.taskName || previewItem.id}
            </div>

            <div className="w-full max-h-[78vh] flex items-center justify-center overflow-auto">
              {previewItem.mediaType === 'video' ? (
                <video
                  src={previewItem.mediaUrl || previewItem.imageUrl}
                  className="max-h-[78vh] max-w-full rounded-md"
                  controls
                  autoPlay
                  playsInline
                />
              ) : (
                <div className="w-full">
                  {renderImageWithBboxOverlay(previewItem)}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
