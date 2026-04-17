import React, { useEffect, useState } from 'react';
import { ArrowLeft, Search, CheckSquare, Square, Play, Image as ImageIcon, ZoomIn } from 'lucide-react';
import { classifyOptions, defaultTaskFilters, fileBmpOptions, normalizeTaskFiltersForForm, resolveApiFileBmpValue } from '../constants/taskFilters';

const classifyLabelMap: Record<number, string> = {
  1: '确种',
  2: '有效',
  3: '空拍',
  4: '处理中'
};

const classifyColorMap: Record<number, string> = {
  1: 'bg-emerald-100 text-emerald-700 border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-300 dark:border-emerald-800',
  2: 'bg-blue-100 text-blue-700 border-blue-200 dark:bg-blue-900/30 dark:text-blue-300 dark:border-blue-800',
  3: 'bg-gray-100 text-gray-700 border-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-700',
  4: 'bg-amber-100 text-amber-700 border-amber-200 dark:bg-amber-900/30 dark:text-amber-300 dark:border-amber-800'
};

export default function DataQuery({ taskId, onBack }: { taskId: number, onBack: () => void }) {
  const [formData, setFormData] = useState(() => normalizeTaskFiltersForForm(defaultTaskFilters));

  const [results, setResults] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [queryError, setQueryError] = useState('');
  const [previewItem, setPreviewItem] = useState<any | null>(null);

  useEffect(() => {
    const fetchTaskFilters = async () => {
      try {
        const response = await fetch(`/api/tasks/${taskId}`);
        const data = await response.json().catch(() => ({}));
        if (!response.ok) return;
        setFormData(normalizeTaskFiltersForForm(data.filters || {}));
      } catch (e) {
        console.error(e);
      }
    };

    if (taskId) {
      fetchTaskFilters();
    }
  }, [taskId]);

  const handleSearch = async () => {
    setLoading(true);
    setQueryError('');
    try {
      const finalPayload: Record<string, unknown> = {
        size: formData.size,
        current: formData.current
      };

      if (formData.keyword.trim()) {
        finalPayload.keyword = formData.keyword.trim();
      }
      if (formData.spName.trim()) {
        finalPayload.spName = formData.spName.trim();
      }
      if (formData.classifyList.length > 0) {
        finalPayload.classifyList = formData.classifyList;
      }
      if (formData.startTime) {
        finalPayload.startTime = formData.startTime;
      }
      if (formData.endTime) {
        finalPayload.endTime = formData.endTime;
      }
      if (formData.fileBmp !== 'all') {
        const apiFileBmpValue = resolveApiFileBmpValue(formData.fileBmp);
        if (apiFileBmpValue !== null) {
          finalPayload.fileBmp = [apiFileBmpValue];
        }
      }
      if (formData.uploadType !== 'all') {
        finalPayload.uploadType = [Number(formData.uploadType)];
      }
      if (formData.idType !== 'all') {
        finalPayload.idType = Number(formData.idType);
      }

      const res = await fetch(`/api/tasks/${taskId}/query-data`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(finalPayload)
      });
      const data = await res.json().catch(() => ({} as Record<string, unknown>));
      if (!res.ok) {
        setResults([]);
        setQueryError(String((data as any).message || (data as any).error || '查询失败，请检查筛选条件与客户端连接状态。'));
        return;
      }

      const resolvedResults = Array.isArray((data as any).results)
        ? (data as any).results
        : Array.isArray((data as any).data?.results)
          ? (data as any).data.results
          : [];
      setResults(resolvedResults);
      setSelectedIds(new Set()); // Reset selection on new search
    } catch(e) {
      setResults([]);
      setQueryError('查询请求失败，请稍后重试。');
      console.error(e);
    }
    setLoading(false);
  };

  const handleSelectAll = () => {
    if (selectedIds.size === results.length) {
      setSelectedIds(new Set()); // deselect all
    } else {
      setSelectedIds(new Set(results.map(r => r.id))); // select all
    }
  };

  const toggleSelect = (id: number) => {
    const newSet = new Set(selectedIds);
    if (newSet.has(id)) newSet.delete(id);
    else newSet.add(id);
    setSelectedIds(newSet);
  };

  const toggleClassify = (value: number) => {
    setFormData(prev => {
      const exists = prev.classifyList.includes(value);
      const nextClassifyList = exists
        ? prev.classifyList.filter(v => v !== value)
        : [...prev.classifyList, value];
      return { ...prev, classifyList: nextClassifyList };
    });
  };

  const handleExecute = async () => {
    if (selectedIds.size === 0) {
      alert("请至少选择一条影像数据后再执行任务。");
      return;
    }
    try {
      const selectedItems = results
        .filter(item => selectedIds.has(item.id))
        .map(item => ({
          id: item.id,
          name: item.name,
          spNameList: item.spNameList,
          classify: item.classify,
          fileTime: item.fileTime,
          fileUrl: item.fileUrl,
          coverUrl: item.coverUrl,
          mediaType: item.mediaType,
          mediaUrl: item.mediaUrl
        }));

      const res = await fetch(`/api/tasks/${taskId}/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          fileIds: Array.from(selectedIds),
          selectedItems
        })
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || data.message || '执行失败');
      }
      onBack(); // Go back to task management after starting
    } catch(e) {
      console.error(e);
      alert(`执行失败：${(e as Error).message || '未知错误'}`);
    }
  };

  const openPreview = (item: any) => {
    setPreviewItem(item);
  };

  const closePreview = () => {
    setPreviewItem(null);
  };

  return (
    <div className="p-8 flex flex-col h-full">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <button onClick={onBack} className="p-2 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-colors">
            <ArrowLeft className="w-5 h-5" />
          </button>
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">检视三方实时数据并下发任务</h2>
        </div>
        <button 
          onClick={handleExecute}
          disabled={selectedIds.size === 0}
          className={`px-6 py-2.5 rounded-lg text-sm font-medium flex items-center gap-2 transition-colors ${
            selectedIds.size > 0 
              ? 'bg-green-600 hover:bg-green-700 text-white shadow-md' 
              : 'bg-gray-200 dark:bg-gray-800 text-gray-400 cursor-not-allowed'
          }`}
        >
          <Play className="w-4 h-4" />
          下发任务（已选 {selectedIds.size} 项）
        </button>
      </div>

      {/* Filter Header */}
      <div className="bg-white dark:bg-gray-800 p-5 md:p-6 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm mb-6 transition-colors">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 xl:grid-cols-5 gap-x-6 gap-y-5 items-end">
          
          <div className="md:col-span-2 xl:col-span-2">
            <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">识别分类 (Classify List)</label>
            <div className="flex flex-wrap gap-2">
              {classifyOptions.map(option => {
                const checked = formData.classifyList.includes(option.value);
                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => toggleClassify(option.value)}
                    className={`px-3 py-1.5 rounded-md text-sm border transition-colors ${
                      checked
                        ? 'bg-blue-50 border-blue-500 text-blue-700 dark:bg-blue-900/30 dark:border-blue-400 dark:text-blue-300'
                        : 'bg-gray-50 border-gray-300 text-gray-600 dark:bg-gray-900 dark:border-gray-600 dark:text-gray-300'
                    }`}
                  >
                    {checked ? '☑' : '☐'} {option.label}
                  </button>
                );
              })}
            </div>
          </div>
          
          <div className="col-span-1">
            <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">关键词 (Keyword)</label>
            <input type="text" placeholder="输入关键字..." value={formData.keyword} onChange={e => setFormData({...formData, keyword: e.target.value})} className="w-full bg-gray-50 dark:bg-gray-900 border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none transition-colors dark:text-white" />
          </div>
          
          <div className="col-span-1">
            <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">物种名称 (SpName)</label>
            <input type="text" placeholder="如：鸟类..." value={formData.spName} onChange={e => setFormData({...formData, spName: e.target.value})} className="w-full bg-gray-50 dark:bg-gray-900 border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none transition-colors dark:text-white" />
          </div>
          
          <div className="col-span-1">
            <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">文件格式</label>
            <select 
              value={formData.fileBmp}
              onChange={e => setFormData({...formData, fileBmp: e.target.value})}
              className="w-full bg-gray-50 dark:bg-gray-900 border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none transition-colors dark:text-white"
            >
              <option value="all">不限制</option>
              {fileBmpOptions.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </div>
          
          <div className="col-span-1">
            <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">识别类型</label>
            <select 
              value={formData.idType} 
              onChange={e => setFormData({...formData, idType: e.target.value})} 
              className="w-full bg-gray-50 dark:bg-gray-900 border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none transition-colors dark:text-white"
            >
              <option value="all">不限制</option>
              <option value={0}>AI 识别</option>
              <option value={1}>人工识别</option>
            </select>
          </div>
          
          <div className="col-span-1">
            <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">上传类型</label>
            <select 
              value={formData.uploadType}
              onChange={e => setFormData({...formData, uploadType: e.target.value})}
              className="w-full bg-gray-50 dark:bg-gray-900 border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none transition-colors dark:text-white"
            >
              <option value="all">不限制</option>
              <option value={0}>监测设备上传</option>
              <option value={1}>移动打卡</option>
              <option value={2}>后台录入</option>
            </select>
          </div>
          
          <div className="col-span-1">
            <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">开始时间</label>
            <input type="date" value={formData.startTime} onChange={e => setFormData({...formData, startTime: e.target.value})} className="w-full bg-gray-50 dark:bg-gray-900 border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none transition-colors dark:text-white" />
          </div>
          
          <div className="col-span-1">
            <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">结束时间</label>
            <input type="date" value={formData.endTime} onChange={e => setFormData({...formData, endTime: e.target.value})} className="w-full bg-gray-50 dark:bg-gray-900 border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none transition-colors dark:text-white" />
          </div>
          
          <div className="col-span-1 flex flex-col justify-end">
            <button onClick={handleSearch} disabled={loading} className="w-full h-[38px] bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm font-medium flex items-center justify-center gap-2 transition-colors disabled:bg-blue-400">
              <Search className="w-4 h-4" />
              {loading ? '查询中...' : '查询'}
            </button>
          </div>

        </div>
      </div>

      {/* Results View */}
      <div className="flex-1 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm overflow-hidden flex flex-col transition-colors">
        <div className="p-4 border-b border-gray-200 dark:border-gray-700 flex justify-between items-center bg-gray-50/50 dark:bg-gray-800/80">
          <h3 className="font-semibold text-gray-700 dark:text-gray-200">
            查询结果 {results.length > 0 && <span className="ml-2 font-normal text-sm bg-gray-200 dark:bg-gray-700 px-2 py-0.5 rounded-full">{results.length} 项</span>}
          </h3>
          {results.length > 0 && (
            <button onClick={handleSelectAll} className="text-sm flex items-center gap-2 text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 transition-colors font-medium">
              {selectedIds.size === results.length ? <CheckSquare className="w-4 h-4" /> : <Square className="w-4 h-4" />}
              {selectedIds.size === results.length ? '取消全选' : '全选此页'}
            </button>
          )}
        </div>
        
        <div className="p-4 flex-1 overflow-auto">
          {results.length === 0 ? (
           <div className="h-full flex flex-col items-center justify-center text-gray-400 dark:text-gray-500 py-12">
             <ImageIcon className="w-12 h-12 mb-4 opacity-50" />
             {queryError && <p className="mb-2 text-red-500 dark:text-red-400">{queryError}</p>}
             <p>暂无数据记录，请调整顶部的筛选条件并点击查询。</p>
           </div>
          ) : (
            <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
              {results.map(item => {
                const isSelected = selectedIds.has(item.id);
                const classifyLabel = classifyLabelMap[Number(item.classify)] || '未知';
                const classifyColorClass = classifyColorMap[Number(item.classify)] || 'bg-gray-100 text-gray-700 border-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-700';
                const speciesName = item.spNameList?.trim() || '--';
                return (
                  <div 
                    key={item.id} 
                    onClick={() => toggleSelect(item.id)}
                    className={`relative p-2 border-2 rounded-xl cursor-pointer overflow-hidden transition-all duration-200 group ${
                      isSelected ? 'border-blue-500 bg-blue-50/30 dark:bg-blue-900/10' : 'border-gray-100 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600'
                    }`}
                  >
                    <div
                      className="aspect-video w-full bg-gray-100 dark:bg-gray-800 rounded-lg overflow-hidden relative border border-gray-200 dark:border-gray-700"
                      onDoubleClick={(e) => {
                        e.stopPropagation();
                        openPreview(item);
                      }}
                    >
                      {item.mediaUrl && item.mediaType === 'video' ? (
                        <video
                          src={item.mediaUrl}
                          className="w-full h-full object-cover"
                          preload="metadata"
                          muted
                          playsInline
                        />
                      ) : item.mediaUrl ? (
                        <img src={item.mediaUrl} className="w-full h-full object-cover" alt="封面" />
                      ) : item.coverUrl ? (
                        <img src={item.coverUrl} className="w-full h-full object-cover" alt="封面" />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center">
                          <ImageIcon className="w-8 h-8 text-gray-300 dark:text-gray-600" />
                        </div>
                      )}

                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          openPreview(item);
                        }}
                        className="absolute top-2 right-2 p-1.5 rounded-md bg-black/55 text-white hover:bg-black/75 transition-colors"
                        title="预览"
                        aria-label="预览"
                      >
                        <ZoomIn className="w-4 h-4" />
                      </button>
                      
                      {/* Checkbox overlay indicator */}
                      <div className={`absolute top-2 left-2 p-1 rounded-md transition-colors ${isSelected ? 'bg-blue-500 text-white' : 'bg-white/80 text-gray-400 dark:bg-gray-800/80 group-hover:text-gray-600'}`}>
                        {isSelected ? <CheckSquare className="w-5 h-5" /> : <Square className="w-5 h-5" />}
                      </div>
                    </div>
                    
                    <div className="mt-3 px-1">
                      <div
                        className="flex items-center gap-2 text-sm text-gray-900 dark:text-gray-100"
                        title={`分类：${classifyLabel}    物种：${speciesName}`}
                      >
                        <span className={`inline-flex shrink-0 items-center rounded-md border px-2 py-0.5 text-xs font-semibold ${classifyColorClass}`}>
                          分类：{classifyLabel}
                        </span>
                        <span className="truncate font-medium">
                          物种：{speciesName}
                        </span>
                      </div>
                      <div className="flex flex-col text-xs text-gray-500 dark:text-gray-400 mt-1 gap-0.5">
                        <span className="truncate">设备: {item.deName || '未知'}</span>
                        <span>时间: {item.fileTime || '--'}</span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

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
              {previewItem.spNameList?.trim() || previewItem.name || '媒体预览'}
            </div>

            <div className="w-full h-[78vh] flex items-center justify-center">
              {previewItem.mediaType === 'video' ? (
                <video
                  src={previewItem.mediaUrl}
                  className="max-h-full max-w-full rounded-md"
                  controls
                  autoPlay
                  playsInline
                />
              ) : (
                <img
                  src={previewItem.mediaUrl || previewItem.coverUrl}
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
