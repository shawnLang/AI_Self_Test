import React, { useEffect, useMemo, useState } from 'react';
import { Cpu, Edit2, KeyRound, Link2, Plus, RefreshCw, Trash2, X } from 'lucide-react';
import { fetchApi } from '../utils/api';

const MASKED_SECRET_PLACEHOLDER = '********';
type ModelStatus = '启用' | '停用';

type MultimodalModel = {
  id: number;
  modelName: string;
  endpointUrl: string;
  apiKey: string;
  apiKeyConfigured?: boolean;
  status: ModelStatus;
  detectedModels: string[];
  lastDetectedAt?: string | null;
};

type MultimodalModelListData = {
  items: MultimodalModel[];
};

type MultimodalModelDetectData = {
  models: string[];
  detectedUrl: string;
  recommendedModel: string;
};

const createEmptyForm = () => ({
  modelName: '',
  endpointUrl: '',
  apiKey: '',
  status: '启用' as ModelStatus,
  detectedModels: [] as string[],
  detectedModelsUpdated: false
});

export default function MultimodalModels() {
  const [models, setModels] = useState<MultimodalModel[]>([]);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [formData, setFormData] = useState(createEmptyForm());
  const [detecting, setDetecting] = useState(false);
  const [detectError, setDetectError] = useState('');
  const [detectInfo, setDetectInfo] = useState('');
  const [saving, setSaving] = useState(false);

  const hasDetectInputs = useMemo(
    () => Boolean(
      formData.endpointUrl.trim() &&
      formData.apiKey.trim() &&
      formData.apiKey.trim() !== MASKED_SECRET_PLACEHOLDER
    ),
    [formData.endpointUrl, formData.apiKey]
  );

  const fetchModels = async () => {
    try {
      const data = await fetchApi<MultimodalModelListData>('/api/multimodal-models/list');
      setModels(data.items);
    } catch (error) {
      console.error(error);
    }
  };

  useEffect(() => {
    fetchModels();
  }, []);

  const runDetect = async () => {
    if (!hasDetectInputs) return;
    setDetecting(true);
    setDetectError('');
    setDetectInfo('');

    try {
      const data = await fetchApi<MultimodalModelDetectData>('/api/multimodal-models/detect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          endpointUrl: formData.endpointUrl,
          apiKey: formData.apiKey
        })
      });

      const detectedModels = Array.isArray(data.models) ? data.models : [];
      setFormData((prev) => ({
        ...prev,
        detectedModels,
        detectedModelsUpdated: true,
        modelName: detectedModels.includes(prev.modelName) ? prev.modelName : (detectedModels[0] || prev.modelName)
      }));
      setDetectInfo(detectedModels.length > 0 ? `已从 ${data.detectedUrl || '接口'} 检索到 ${detectedModels.length} 个模型。` : '接口可访问，但未返回模型列表。');
    } catch (error) {
      setDetectError((error as Error).message || '模型自动检索失败');
    } finally {
      setDetecting(false);
    }
  };

  useEffect(() => {
    if (!isModalOpen || !hasDetectInputs) return;

    const timer = window.setTimeout(() => {
      runDetect();
    }, 700);

    return () => window.clearTimeout(timer);
  }, [isModalOpen, hasDetectInputs, formData.endpointUrl, formData.apiKey]);

  const openModal = (item?: MultimodalModel) => {
    if (item) {
      setEditingId(item.id);
      setFormData({
        modelName: item.modelName,
        endpointUrl: item.endpointUrl,
        apiKey: item.apiKey,
        status: item.status || '启用',
        detectedModels: Array.isArray(item.detectedModels) ? item.detectedModels : [],
        detectedModelsUpdated: false
      });
      setDetectInfo(
        item.apiKeyConfigured
          ? '当前已配置访问密钥；若需重新检索模型，请重新输入真实 API Key。'
          : item.detectedModels?.length
            ? `已缓存 ${item.detectedModels.length} 个模型候选。`
            : ''
      );
    } else {
      setEditingId(null);
      setFormData(createEmptyForm());
      setDetectInfo('');
    }
    setDetectError('');
    setIsModalOpen(true);
  };

  const closeModal = () => {
    setIsModalOpen(false);
    setEditingId(null);
    setFormData(createEmptyForm());
    setDetectError('');
    setDetectInfo('');
    setDetecting(false);
    setSaving(false);
  };

  const handleSave = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);

    try {
      await fetchApi(editingId ? `/api/multimodal-models/update/${editingId}` : '/api/multimodal-models/create', {
        method: editingId ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData)
      });

      closeModal();
      await fetchModels();
    } catch (error) {
      setDetectError((error as Error).message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm('确定删除这条多模态模型配置吗？')) return;

    try {
      await fetchApi(`/api/multimodal-models/delete/${id}`, { method: 'DELETE' });
      await fetchModels();
    } catch (error) {
      console.error(error);
    }
  };

  return (
    <div className="p-8">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">多模态模型管理</h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">维护多模态模型地址、密码和模型名称，支持自动检索模型列表。</p>
        </div>

        <button
          onClick={() => openModal()}
          className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm font-medium flex items-center gap-2 transition-colors"
        >
          <Plus className="w-4 h-4" />
          添加模型
        </button>
      </div>

      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm overflow-hidden transition-colors">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="bg-gray-50 dark:bg-gray-900/50 border-b border-gray-200 dark:border-gray-700">
              <th className="px-6 py-4 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">模型名称</th>
              <th className="px-6 py-4 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">地址</th>
              <th className="px-6 py-4 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">状态</th>
              <th className="px-6 py-4 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">最近检索</th>
              <th className="px-6 py-4 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider text-right">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
            {models.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-6 py-16 text-center text-sm text-gray-500 dark:text-gray-400">
                  暂无多模态模型配置，请点击右上角添加。
                </td>
              </tr>
            ) : models.map((item) => (
              <tr key={item.id} className="hover:bg-gray-50 dark:hover:bg-gray-700/40 transition-colors">
                <td className="px-6 py-4">
                  <div className="flex items-center gap-3">
                    <div className="w-9 h-9 rounded-lg bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 flex items-center justify-center">
                      <Cpu className="w-4 h-4" />
                    </div>
                    <div>
                      <div className="font-medium text-gray-900 dark:text-gray-100">{item.modelName}</div>
                      <div className="text-xs text-gray-500 dark:text-gray-400">
                        {item.detectedModels?.length ? `可选模型 ${item.detectedModels.length} 个` : '未缓存候选模型'}
                      </div>
                    </div>
                  </div>
                </td>
                <td className="px-6 py-4 text-sm text-gray-600 dark:text-gray-300 max-w-xl truncate">
                  {item.endpointUrl}
                </td>
                <td className="px-6 py-4">
                  <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${
                    item.status === '启用'
                      ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300'
                      : 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300'
                  }`}>
                    {item.status}
                  </span>
                </td>
                <td className="px-6 py-4 text-sm text-gray-500 dark:text-gray-400">
                  {item.lastDetectedAt ? new Date(item.lastDetectedAt).toLocaleString() : '--'}
                </td>
                <td className="px-6 py-4 text-right">
                  <button onClick={() => openModal(item)} className="text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 mr-3">
                    <Edit2 className="w-4 h-4" />
                  </button>
                  <button onClick={() => handleDelete(item.id)} className="text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300">
                    <Trash2 className="w-4 h-4" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
          <div className="bg-white dark:bg-gray-800 rounded-xl p-6 w-full max-w-2xl border border-gray-200 dark:border-gray-700 shadow-xl">
            <div className="flex justify-between items-center mb-4">
              <div>
                <h3 className="text-lg font-bold text-gray-900 dark:text-white">{editingId ? '编辑多模态模型' : '添加多模态模型'}</h3>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">输入地址和密码后，会自动尝试检索可用模型。</p>
              </div>
              <button onClick={closeModal} className="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSave} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">多模态地址</label>
                <div className="relative">
                  <Link2 className="w-4 h-4 absolute left-3 top-3.5 text-gray-400" />
                  <input
                    type="url"
                    value={formData.endpointUrl}
                    onChange={(e) => setFormData((prev) => ({
                      ...prev,
                      endpointUrl: e.target.value,
                      detectedModelsUpdated: false
                    }))}
                    placeholder="例如：https://xxx/v1/chat/completions"
                    required
                    className="w-full pl-10 bg-white dark:bg-gray-900 border border-gray-300 dark:border-gray-600 text-gray-900 dark:text-gray-100 rounded-lg px-3 py-3 text-sm focus:ring-2 focus:ring-blue-500 outline-none transition-colors"
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">密码 / API Key</label>
                <div className="relative">
                  <KeyRound className="w-4 h-4 absolute left-3 top-3.5 text-gray-400" />
                  <input
                    type="password"
                    value={formData.apiKey}
                    onChange={(e) => setFormData((prev) => ({
                      ...prev,
                      apiKey: e.target.value,
                      detectedModelsUpdated: false
                    }))}
                    placeholder="输入访问密码或 API Key"
                    required
                    className="w-full pl-10 bg-white dark:bg-gray-900 border border-gray-300 dark:border-gray-600 text-gray-900 dark:text-gray-100 rounded-lg px-3 py-3 text-sm focus:ring-2 focus:ring-blue-500 outline-none transition-colors"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-[1fr_auto] gap-3 items-end">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">模型名称</label>
                  <input
                    type="text"
                    value={formData.modelName}
                    onChange={(e) => setFormData((prev) => ({ ...prev, modelName: e.target.value }))}
                    placeholder="例如：gpt-4.1-mini / qwen-vl-max"
                    required
                    className="w-full bg-white dark:bg-gray-900 border border-gray-300 dark:border-gray-600 text-gray-900 dark:text-gray-100 rounded-lg px-3 py-3 text-sm focus:ring-2 focus:ring-blue-500 outline-none transition-colors"
                  />
                </div>
                <button
                  type="button"
                  onClick={runDetect}
                  disabled={!hasDetectInputs || detecting}
                  className="h-[46px] px-4 rounded-lg border border-blue-200 dark:border-blue-800 text-blue-700 dark:text-blue-300 bg-blue-50 dark:bg-blue-900/20 hover:bg-blue-100 dark:hover:bg-blue-900/40 disabled:opacity-50 disabled:cursor-not-allowed text-sm font-medium flex items-center justify-center gap-2 transition-colors"
                >
                  <RefreshCw className={`w-4 h-4 ${detecting ? 'animate-spin' : ''}`} />
                  {detecting ? '检索中...' : '自动检索模型'}
                </button>
              </div>

              {formData.detectedModels.length > 0 && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">已检索到的模型</label>
                  <select
                    value={formData.modelName}
                    onChange={(e) => setFormData((prev) => ({ ...prev, modelName: e.target.value }))}
                    className="w-full bg-white dark:bg-gray-900 border border-gray-300 dark:border-gray-600 text-gray-900 dark:text-gray-100 rounded-lg px-3 py-3 text-sm focus:ring-2 focus:ring-blue-500 outline-none transition-colors"
                  >
                    {formData.detectedModels.map((modelName) => (
                      <option key={modelName} value={modelName}>{modelName}</option>
                    ))}
                  </select>
                </div>
              )}

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">状态</label>
                <select
                  value={formData.status}
                  onChange={(e) => setFormData((prev) => ({ ...prev, status: e.target.value }))}
                  className="w-full bg-white dark:bg-gray-900 border border-gray-300 dark:border-gray-600 text-gray-900 dark:text-gray-100 rounded-lg px-3 py-3 text-sm focus:ring-2 focus:ring-blue-500 outline-none transition-colors"
                >
                  <option value="启用">启用</option>
                  <option value="停用">停用</option>
                </select>
              </div>

              {detectError && (
                <div className="rounded-lg border border-red-200 bg-red-50 text-red-700 dark:border-red-900/40 dark:bg-red-900/20 dark:text-red-300 px-4 py-3 text-sm">
                  {detectError}
                </div>
              )}
              {detectInfo && !detectError && (
                <div className="rounded-lg border border-green-200 bg-green-50 text-green-700 dark:border-green-900/40 dark:bg-green-900/20 dark:text-green-300 px-4 py-3 text-sm">
                  {detectInfo}
                </div>
              )}

              <div className="flex justify-end gap-3 pt-4 border-t border-gray-200 dark:border-gray-700">
                <button
                  type="button"
                  onClick={closeModal}
                  className="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 rounded-lg transition-colors"
                >
                  取消
                </button>
                <button
                  type="submit"
                  disabled={saving}
                  className="px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors disabled:opacity-60"
                >
                  {saving ? '保存中...' : '保存配置'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
