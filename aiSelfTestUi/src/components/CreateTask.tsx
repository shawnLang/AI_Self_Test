import React, { useEffect, useMemo, useState } from 'react';
import { ArrowLeft } from 'lucide-react';
import { classifyOptions, defaultTaskFilters, fileBmpOptions, intervalOptions, type TaskFilterFormData } from '../constants/taskFilters';
import type { ClientItem, ClientListData } from '../types/client';
import { fetchApi } from '../utils/api';

type ExecutionMode = 'auto' | 'manual';

const buildTaskName = (projectName: string, executionMode: ExecutionMode) => {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, '0');
  const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  return `${projectName}-${executionMode === 'auto' ? '自动' : '手动'}任务-${stamp}`;
};

const sectionTitleClass = 'text-base font-semibold text-gray-900 dark:text-white';
const labelClass = 'block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2';
const inputClass = 'w-full bg-white dark:bg-gray-900 border border-gray-300 dark:border-gray-600 text-gray-900 dark:text-gray-100 rounded-lg px-4 py-3 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-colors';

export default function CreateTask({ onBack }: { onBack: () => void }) {
  const [clients, setClients] = useState<ClientItem[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [formData, setFormData] = useState<{
    clientId: string;
    interval: string;
    executionMode: ExecutionMode;
    filters: TaskFilterFormData;
  }>({
    clientId: '',
    interval: intervalOptions[2] || '每小时',
    executionMode: 'manual',
    filters: { ...defaultTaskFilters }
  });

  useEffect(() => {
    const fetchClients = async () => {
      try {
        const data = await fetchApi<ClientListData>('/api/clients/list');
        setClients(data.items);
        if (data.items.length > 0) {
          setFormData((prev) => ({ ...prev, clientId: String(data.items[0].id) }));
        }
      } catch (e) {
        console.error(e);
        setError((e as Error).message || '客户端列表加载失败');
      }
    };
    fetchClients();
  }, []);

  const selectedClient = useMemo(
    () => clients.find((client) => String(client.id) === formData.clientId) || null,
    [clients, formData.clientId]
  );

  const toggleClassify = (value: number) => {
    setFormData((prev) => {
      const exists = prev.filters.classifyList.includes(value);
      const nextClassifyList = exists
        ? prev.filters.classifyList.filter((item) => item !== value)
        : [...prev.filters.classifyList, value];
      return {
        ...prev,
        filters: {
          ...prev.filters,
          classifyList: nextClassifyList
        }
      };
    });
  };

  const updateFilter = <K extends keyof TaskFilterFormData>(key: K, value: TaskFilterFormData[K]) => {
    setFormData((prev) => ({
      ...prev,
      filters: {
        ...prev.filters,
        [key]: value
      }
    }));
  };

  const handleSave = async () => {
    if (!formData.clientId) {
      setError('请先选择一个项目。');
      return;
    }

    setSaving(true);
    setError('');

    try {
      const response = await fetch('/api/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: buildTaskName(selectedClient?.name || '项目', formData.executionMode),
          clientId: parseInt(formData.clientId, 10),
          interval: formData.interval,
          threshold: 0,
          filters: formData.filters,
          executionMode: formData.executionMode,
          autoConfirm: false,
          active: false
        })
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.error || data.message || '创建任务失败');
      }
      onBack();
    } catch (e) {
      console.error(e);
      setError((e as Error).message || '创建任务失败，请稍后重试。');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="p-8 flex flex-col h-full bg-gray-50/50 dark:bg-gray-900/10">
      <div className="flex items-center gap-4 mb-6">
        <button onClick={onBack} className="p-2 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-colors">
          <ArrowLeft className="w-5 h-5" />
        </button>
        <div>
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">创建新任务</h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">先配置客户端、定时器和筛选条件，后续执行会按这套条件进行。</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 xl:grid-cols-4 gap-6">
        {/* 左侧区域：配置项 1-4 */}
        <div className="lg:col-span-2 xl:col-span-3 bg-white dark:bg-gray-800 p-8 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm transition-colors space-y-8">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            <section className="space-y-4">
              <div className="flex items-center gap-3">
                <span className="w-8 h-8 rounded-full bg-blue-600 text-white text-sm font-semibold flex items-center justify-center">1</span>
                <h3 className={sectionTitleClass}>选择客户端</h3>
              </div>
              <div>
                <label className={labelClass}>客户端</label>
                <select
                  value={formData.clientId}
                  onChange={(e) => setFormData({ ...formData, clientId: e.target.value })}
                  className={inputClass}
                >
                  {clients.map((client) => (
                    <option key={client.id} value={client.id}>{client.name}</option>
                  ))}
                </select>
              </div>
            </section>

            <section className="space-y-4">
              <div className="flex items-center gap-3">
                <span className="w-8 h-8 rounded-full bg-blue-600 text-white text-sm font-semibold flex items-center justify-center">2</span>
                <h3 className={sectionTitleClass}>选择执行间隔时间（定时器）</h3>
              </div>
              <div>
                <label className={labelClass}>执行间隔</label>
                <select
                  value={formData.interval}
                  onChange={(e) => setFormData({ ...formData, interval: e.target.value })}
                  className={inputClass}
                >
                  {intervalOptions.map((option) => (
                    <option key={option} value={option}>{option}</option>
                  ))}
                </select>
              </div>
            </section>
          </div>

          <section className="space-y-5">
            <div className="flex items-center gap-3">
              <span className="w-8 h-8 rounded-full bg-blue-600 text-white text-sm font-semibold flex items-center justify-center">3</span>
              <div>
                <h3 className={sectionTitleClass}>筛选条件</h3>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">支持按“检视三方实时数据并下发任务”同样的条件保存筛选规则。</p>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-x-6 gap-y-5 items-end">
              <div className="md:col-span-2">
                <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">识别分类</label>
                <div className="flex flex-wrap gap-2">
                  {classifyOptions.map((option) => {
                    const checked = formData.filters.classifyList.includes(option.value);
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
                <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">关键词</label>
                <input
                  type="text"
                  value={formData.filters.keyword}
                  onChange={(e) => updateFilter('keyword', e.target.value)}
                  placeholder="输入关键字..."
                  className="w-full bg-gray-50 dark:bg-gray-900 border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none transition-colors dark:text-white"
                />
              </div>

              <div className="col-span-1">
                <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">物种名称</label>
                <input
                  type="text"
                  value={formData.filters.spName}
                  onChange={(e) => updateFilter('spName', e.target.value)}
                  placeholder="如：鸟类..."
                  className="w-full bg-gray-50 dark:bg-gray-900 border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none transition-colors dark:text-white"
                />
              </div>

              <div className="col-span-1">
                <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">文件格式</label>
                <select
                  value={formData.filters.fileBmp}
                  onChange={(e) => updateFilter('fileBmp', e.target.value)}
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
                  value={formData.filters.idType}
                  onChange={(e) => updateFilter('idType', e.target.value)}
                  className="w-full bg-gray-50 dark:bg-gray-900 border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none transition-colors dark:text-white"
                >
                  <option value="all">不限制</option>
                  <option value="0">AI 识别</option>
                  <option value="1">人工识别</option>
                </select>
              </div>

              <div className="col-span-1">
                <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">上传类型</label>
                <select
                  value={formData.filters.uploadType}
                  onChange={(e) => updateFilter('uploadType', e.target.value)}
                  className="w-full bg-gray-50 dark:bg-gray-900 border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none transition-colors dark:text-white"
                >
                  <option value="all">不限制</option>
                  <option value="0">监测设备上传</option>
                  <option value="1">移动打卡</option>
                  <option value="2">后台录入</option>
                </select>
              </div>

              <div className="col-span-1">
                <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">开始时间</label>
                <input
                  type="date"
                  value={formData.filters.startTime}
                  onChange={(e) => updateFilter('startTime', e.target.value)}
                  className="w-full bg-gray-50 dark:bg-gray-900 border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none transition-colors dark:text-white"
                />
              </div>

              <div className="col-span-1">
                <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">结束时间</label>
                <input
                  type="date"
                  value={formData.filters.endTime}
                  onChange={(e) => updateFilter('endTime', e.target.value)}
                  className="w-full bg-gray-50 dark:bg-gray-900 border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none transition-colors dark:text-white"
                />
              </div>
            </div>
          </section>

          <section className="space-y-4">
            <div className="flex items-center gap-3">
              <span className="w-8 h-8 rounded-full bg-blue-600 text-white text-sm font-semibold flex items-center justify-center">4</span>
              <h3 className={sectionTitleClass}>选择自动执行还是手动执行</h3>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <button
                type="button"
                onClick={() => setFormData({ ...formData, executionMode: 'auto' })}
                className={`text-left rounded-xl border p-5 transition-colors ${
                  formData.executionMode === 'auto'
                    ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20 dark:border-blue-400'
                    : 'border-gray-200 dark:border-gray-700 hover:border-blue-300'
                }`}
              >
                <div className="text-base font-semibold text-gray-900 dark:text-white">自动执行</div>
                <div className="text-sm text-gray-500 dark:text-gray-400 mt-2">保存为自动执行模式，后续可按设定间隔与筛选条件执行。</div>
              </button>

              <button
                type="button"
                onClick={() => setFormData({ ...formData, executionMode: 'manual' })}
                className={`text-left rounded-xl border p-5 transition-colors ${
                  formData.executionMode === 'manual'
                    ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20 dark:border-blue-400'
                    : 'border-gray-200 dark:border-gray-700 hover:border-blue-300'
                }`}
              >
                <div className="text-base font-semibold text-gray-900 dark:text-white">手动执行</div>
                <div className="text-sm text-gray-500 dark:text-gray-400 mt-2">任务创建后不会自动跑，需要你手动点击“立即执行”或“查询数据并执行”。</div>
              </button>
            </div>
          </section>
        </div>

        {/* 右侧区域：呈现选择内容与提交流程 */}
        <div className="lg:col-span-1 bg-white dark:bg-gray-800 p-8 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm flex flex-col transition-colors h-fit sticky top-8">
          <h3 className="text-lg font-bold text-gray-900 dark:text-white mb-6 border-b border-gray-100 dark:border-gray-700 pb-3">任务配置概览</h3>
          
          <div className="flex-1 space-y-6">
            <div>
              <p className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider font-semibold mb-1">目标客户端</p>
              <div className="text-base text-gray-900 dark:text-gray-100 font-medium">{selectedClient?.name || '未选择客户端'}</div>
            </div>
            
            <div>
              <p className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider font-semibold mb-1">执行调度</p>
              <div className="text-base text-gray-900 dark:text-gray-100 font-medium">
                {formData.executionMode === 'auto' ? '自动执行' : '手动执行'}
                <span className="text-gray-400 ml-2">({formData.interval})</span>
              </div>
            </div>

            <div>
              <p className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider font-semibold mb-2">已附加筛选规则</p>
              <ul className="space-y-1.5 text-sm text-gray-600 dark:text-gray-300 bg-gray-50 dark:bg-gray-900/50 p-4 rounded-lg border border-gray-100 dark:border-gray-700">
                <li className="flex justify-between gap-4">
                  <span className="shrink-0">识别分类:</span>
                  <span className="font-medium text-gray-900 dark:text-white text-right">
                    {formData.filters.classifyList.length > 0 
                      ? formData.filters.classifyList.map(v => classifyOptions.find(o => o.value === v)?.label).join('、')
                      : '未选择'}
                  </span>
                </li>
                <li className="flex justify-between">
                  <span>文件格式:</span>
                  <span className="font-medium text-gray-900 dark:text-white">{formData.filters.fileBmp === 'image' ? '图片' : formData.filters.fileBmp === 'video' ? '视频' : formData.filters.fileBmp === 'audio' ? '音频' : '不限制'}</span>
                </li>
                <li className="flex justify-between">
                  <span>识别类型:</span>
                  <span className="font-medium text-gray-900 dark:text-white">{formData.filters.idType === '0' ? 'AI 识别' : formData.filters.idType === '1' ? '人工识别' : '不限制'}</span>
                </li>
                <li className="flex justify-between">
                  <span>上传类型:</span>
                  <span className="font-medium text-gray-900 dark:text-white">{formData.filters.uploadType === '0' ? '监测设备上传' : formData.filters.uploadType === '1' ? '移动打卡' : formData.filters.uploadType === '2' ? '后台录入' : '不限制'}</span>
                </li>
                <li className="flex justify-between">
                  <span>关键词:</span>
                  <span className="font-medium text-gray-900 dark:text-white truncate max-w-[120px]">{formData.filters.keyword || '不限制'}</span>
                </li>
                <li className="flex justify-between">
                  <span>物种名称:</span>
                  <span className="font-medium text-gray-900 dark:text-white truncate max-w-[120px]">{formData.filters.spName || '不限制'}</span>
                </li>
                <li className="flex justify-between">
                  <span>开始时间:</span>
                  <span className="font-medium text-gray-900 dark:text-white">{formData.filters.startTime || '不限制'}</span>
                </li>
                <li className="flex justify-between">
                  <span>结束时间:</span>
                  <span className="font-medium text-gray-900 dark:text-white">{formData.filters.endTime || '不限制'}</span>
                </li>
              </ul>
            </div>
          </div>

          <div className="mt-8 pt-6 border-t border-gray-100 dark:border-gray-700">
            {error && (
              <div className="mb-4 rounded-lg border border-red-200 bg-red-50 text-red-700 dark:border-red-900/40 dark:bg-red-900/20 dark:text-red-300 px-4 py-3 text-sm flex items-center gap-2">
                {error}
              </div>
            )}
            
            <button
              type="button"
              onClick={handleSave}
              disabled={saving || !formData.clientId}
              className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white py-3.5 rounded-lg font-medium transition-colors shadow-sm flex items-center justify-center gap-2 text-base"
            >
              {saving ? '创建中...' : '确认创建任务'}
            </button>
            <p className="text-xs text-center text-gray-400 mt-3">配置结果将被保存至任务面板</p>
          </div>
        </div>
      </div>
    </div>
  );
}
