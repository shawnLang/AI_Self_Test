import React, { useEffect, useState } from 'react';
import { Braces, Edit2, FileText, Plus, Trash2, X } from 'lucide-react';
import { fetchApi } from '../utils/api';

type ConfigFormat = 0 | 1 | 2;

type PromptConfig = {
  id: number;
  name: string;
  remark: string;
  text: string;
  format: ConfigFormat;
};

type PromptConfigListData = {
  items: PromptConfig[];
};

type PromptConfigForm = {
  name: string;
  remark: string;
  text: string;
  format: ConfigFormat;
};

const FORMAT_OPTIONS: Array<{ value: ConfigFormat; label: string; description: string }> = [
  { value: 0, label: '纯文本', description: '直接读取模型返回文本' },
  { value: 1, label: 'JSON 对象', description: '期望模型返回单个 JSON 对象' },
  { value: 2, label: 'JSON 列表', description: '期望模型返回记录数组' }
];

const createEmptyForm = (): PromptConfigForm => ({
  name: '',
  remark: '',
  text: '',
  format: 0
});

function getFormatOption(format: ConfigFormat) {
  return FORMAT_OPTIONS.find((item) => item.value === format) || FORMAT_OPTIONS[0];
}

export default function PromptConfigs() {
  const [configs, setConfigs] = useState<PromptConfig[]>([]);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [formData, setFormData] = useState<PromptConfigForm>(createEmptyForm());
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const fetchConfigs = async () => {
    setLoading(true);
    setError('');

    try {
      const data = await fetchApi<PromptConfigListData>('/api/configs/list');
      setConfigs(data.items);
    } catch (requestError) {
      setError((requestError as Error).message || '提示词配置加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchConfigs();
  }, []);

  const openModal = (item?: PromptConfig) => {
    if (item) {
      setEditingId(item.id);
      setFormData({
        name: item.name,
        remark: item.remark || '',
        text: item.text,
        format: item.format
      });
    } else {
      setEditingId(null);
      setFormData(createEmptyForm());
    }
    setError('');
    setIsModalOpen(true);
  };

  const closeModal = () => {
    setIsModalOpen(false);
    setEditingId(null);
    setFormData(createEmptyForm());
    setSaving(false);
    setError('');
  };

  const handleSave = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError('');

    try {
      await fetchApi(editingId ? `/api/configs/update/${editingId}` : '/api/configs/create', {
        method: editingId ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData)
      });

      closeModal();
      await fetchConfigs();
    } catch (requestError) {
      setError((requestError as Error).message || '保存提示词配置失败');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm('确定删除这条提示词配置吗？')) return;

    setError('');
    try {
      await fetchApi(`/api/configs/delete/${id}`, { method: 'DELETE' });
      await fetchConfigs();
    } catch (requestError) {
      setError((requestError as Error).message || '删除提示词配置失败');
    }
  };

  return (
    <div className="p-8">
      <div className="flex flex-col gap-4 mb-6 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">提示词配置</h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            管理任务执行时使用的模型提示词和结果解析格式；模型测试页面不会使用这些内容。
          </p>
        </div>

        <button
          type="button"
          onClick={() => openModal()}
          className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm font-medium flex items-center justify-center gap-2 transition-colors"
        >
          <Plus className="w-4 h-4" />
          添加提示词
        </button>
      </div>

      {error && !isModalOpen && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 text-red-700 dark:border-red-900/40 dark:bg-red-900/20 dark:text-red-300 px-4 py-3 text-sm">
          {error}
        </div>
      )}

      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm overflow-hidden transition-colors">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="bg-gray-50 dark:bg-gray-900/50 border-b border-gray-200 dark:border-gray-700">
              <th className="px-6 py-4 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">名称</th>
              <th className="px-6 py-4 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">解析格式</th>
              <th className="px-6 py-4 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">备注</th>
              <th className="px-6 py-4 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">提示词预览</th>
              <th className="px-6 py-4 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider text-right">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
            {loading ? (
              <tr>
                <td colSpan={5} className="px-6 py-16 text-center text-sm text-gray-500 dark:text-gray-400">
                  正在加载提示词配置...
                </td>
              </tr>
            ) : configs.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-6 py-16 text-center text-sm text-gray-500 dark:text-gray-400">
                  暂无提示词配置，请点击右上角添加。
                </td>
              </tr>
            ) : configs.map((item) => {
              const formatOption = getFormatOption(item.format);

              return (
                <tr key={item.id} className="hover:bg-gray-50 dark:hover:bg-gray-700/40 transition-colors">
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-3">
                      <div className="w-9 h-9 rounded-lg bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300 flex items-center justify-center">
                        <FileText className="w-4 h-4" />
                      </div>
                      <div>
                        <div className="font-medium text-gray-900 dark:text-gray-100">{item.name}</div>
                        <div className="text-xs text-gray-500 dark:text-gray-400">ID: {item.id}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <span className="inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300">
                      {formatOption.label}
                    </span>
                    <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">{formatOption.description}</div>
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-600 dark:text-gray-300 max-w-xs truncate">
                    {item.remark || '--'}
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-600 dark:text-gray-300 max-w-md">
                    <div className="line-clamp-2 whitespace-pre-wrap">{item.text}</div>
                  </td>
                  <td className="px-6 py-4 text-right">
                    <button
                      type="button"
                      onClick={() => openModal(item)}
                      className="text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 mr-3"
                      title="编辑提示词"
                    >
                      <Edit2 className="w-4 h-4" />
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDelete(item.id)}
                      className="text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300"
                      title="删除提示词"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
          <div className="bg-white dark:bg-gray-800 rounded-xl p-6 w-full max-w-3xl border border-gray-200 dark:border-gray-700 shadow-xl">
            <div className="flex justify-between items-start gap-4 mb-4">
              <div>
                <h3 className="text-lg font-bold text-gray-900 dark:text-white">
                  {editingId ? '编辑提示词配置' : '添加提示词配置'}
                </h3>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                  该配置只会在任务执行中使用，不会注入模型测试会话。
                </p>
              </div>
              <button
                type="button"
                onClick={closeModal}
                className="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSave} className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-[1fr_220px] gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">提示词名称</label>
                  <input
                    type="text"
                    value={formData.name}
                    onChange={(event) => setFormData((prev) => ({ ...prev, name: event.target.value }))}
                    placeholder="例如：物种复核默认提示词"
                    required
                    className="w-full bg-white dark:bg-gray-900 border border-gray-300 dark:border-gray-600 text-gray-900 dark:text-gray-100 rounded-lg px-3 py-3 text-sm focus:ring-2 focus:ring-blue-500 outline-none transition-colors"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">解析格式</label>
                  <div className="relative">
                    <Braces className="w-4 h-4 absolute left-3 top-3.5 text-gray-400" />
                    <select
                      value={formData.format}
                      onChange={(event) => setFormData((prev) => ({
                        ...prev,
                        format: Number(event.target.value) as ConfigFormat
                      }))}
                      className="w-full pl-10 bg-white dark:bg-gray-900 border border-gray-300 dark:border-gray-600 text-gray-900 dark:text-gray-100 rounded-lg px-3 py-3 text-sm focus:ring-2 focus:ring-blue-500 outline-none transition-colors"
                    >
                      {FORMAT_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>{option.label}</option>
                      ))}
                    </select>
                  </div>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">备注</label>
                <input
                  type="text"
                  value={formData.remark}
                  onChange={(event) => setFormData((prev) => ({ ...prev, remark: event.target.value }))}
                  placeholder="说明适用任务、返回格式或注意事项"
                  className="w-full bg-white dark:bg-gray-900 border border-gray-300 dark:border-gray-600 text-gray-900 dark:text-gray-100 rounded-lg px-3 py-3 text-sm focus:ring-2 focus:ring-blue-500 outline-none transition-colors"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">提示词内容</label>
                <textarea
                  value={formData.text}
                  onChange={(event) => setFormData((prev) => ({ ...prev, text: event.target.value }))}
                  placeholder="输入任务执行时发送给模型的提示词..."
                  required
                  className="w-full h-64 resize-none bg-white dark:bg-gray-900 border border-gray-300 dark:border-gray-600 text-gray-900 dark:text-gray-100 rounded-lg px-3 py-3 text-sm leading-6 focus:ring-2 focus:ring-blue-500 outline-none transition-colors"
                />
              </div>

              {error && (
                <div className="rounded-lg border border-red-200 bg-red-50 text-red-700 dark:border-red-900/40 dark:bg-red-900/20 dark:text-red-300 px-4 py-3 text-sm">
                  {error}
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
