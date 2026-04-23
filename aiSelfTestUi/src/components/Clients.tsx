import React, { useState, useEffect } from 'react';
import { Plus, Edit2, Trash2, Server, X, ShieldCheck } from 'lucide-react';
import { fetchApi } from '../utils/api';
import type { ClientAuthenticateData, ClientFormData, ClientItem, ClientListData } from '../types/client';


const emptyFormData: ClientFormData = {
  name: '',
  apiUrl: '',
  account: '',
  password: '',
  status: '启用'
};

export default function Clients() {
  const [clients, setClients] = useState<ClientItem[]>([]);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [formData, setFormData] = useState<ClientFormData>(emptyFormData);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [successMessage, setSuccessMessage] = useState('');

  const fetchClients = async () => {
    setLoading(true);
    setError('');
    try {
      const data = await fetchApi<ClientListData>('/api/clients/list');
      setClients(data.items);
    } catch (e) {
      console.error(e);
      setError((e as Error).message || '客户端列表加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchClients();
  }, []);

  const handleDelete = async (id: number) => {
    if (!confirm('确定删除此客户端吗？相关任务与任务数据也会被删除。')) return;

    try {
      setSuccessMessage('');
      await fetchApi(`/api/clients/delete/${id}`, { method: 'DELETE' });
      await fetchClients();
    } catch (e) {
      console.error(e);
      setError((e as Error).message || '删除客户端失败');
    }
  };

  const handleOpenModal = (client?: ClientItem) => {
    setError('');
    setSuccessMessage('');
    if (client) {
      setEditingId(client.id);
      setFormData({
        name: client.name,
        apiUrl: client.apiUrl,
        account: client.account,
        password: '',
        status: client.status
      });
    } else {
      setEditingId(null);
      setFormData(emptyFormData);
    }
    setIsModalOpen(true);
  };

  const handleCloseModal = () => {
    setIsModalOpen(false);
    setEditingId(null);
    setSubmitting(false);
    setError('');
    setFormData(emptyFormData);
  };

  const handleAuthenticate = async (client: ClientItem) => {
    setError('');
    setSuccessMessage('');

    try {
      const data = await fetchApi<ClientAuthenticateData>(`/api/clients/authenticate/${client.id}`, {
        method: 'POST'
      });
      const strategyTextMap = {
        reuse: '复用现有 token',
        refresh: '刷新 token',
        login: '重新登录'
      } as const;
      setSuccessMessage(`客户端“${data.client.name}”认证成功，策略：${strategyTextMap[data.usedStrategy]}`);
      await fetchClients();
    } catch (e) {
      console.error(e);
      setError((e as Error).message || '客户端认证失败');
    }
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!editingId && !formData.password.trim()) {
      setError('创建客户端时必须填写密码');
      return;
    }

    setSubmitting(true);
    setError('');
    setSuccessMessage('');

    try {
      if (editingId) {
        await fetchApi(`/api/clients/update/${editingId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(formData)
        });
      } else {
        await fetchApi('/api/clients/create', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(formData)
        });
      }
      handleCloseModal();
      await fetchClients();
    } catch (e) {
      console.error(e);
      setError((e as Error).message || '保存客户端失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="p-8">
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-2xl font-bold text-gray-900 dark:text-white">客户端管理</h2>
        <button onClick={() => handleOpenModal()} className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm font-medium flex items-center gap-2 transition-colors">
          <Plus className="w-4 h-4" />
          新增客户端
        </button>
      </div>

      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 text-red-700 dark:border-red-900/40 dark:bg-red-900/20 dark:text-red-300 px-4 py-3 text-sm">
          {error}
        </div>
      )}

      {successMessage && (
        <div className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/40 dark:bg-emerald-900/20 dark:text-emerald-300 px-4 py-3 text-sm">
          {successMessage}
        </div>
      )}

      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm overflow-hidden transition-colors">
        {loading ? (
          <div className="px-6 py-12 text-center text-sm text-gray-500 dark:text-gray-400">客户端列表加载中...</div>
        ) : clients.length === 0 ? (
          <div className="px-6 py-12 text-center text-sm text-gray-500 dark:text-gray-400">暂无客户端配置，请先新增一个客户端。</div>
        ) : (
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-gray-50 dark:bg-gray-900/50 border-b border-gray-200 dark:border-gray-700">
                <th className="px-6 py-4 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">客户端名称</th>
                <th className="px-6 py-4 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">API 地址</th>
                <th className="px-6 py-4 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">账户</th>
                <th className="px-6 py-4 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">状态</th>
                <th className="px-6 py-4 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">认证</th>
                <th className="px-6 py-4 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider text-right">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
              {clients.map((client) => (
                <tr key={client.id} className="hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors">
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-full bg-blue-100 dark:bg-blue-900/50 flex items-center justify-center text-blue-600 dark:text-blue-400 font-bold text-xs">
                        {client.name.charAt(0)}
                      </div>
                      <span className="font-medium text-gray-900 dark:text-gray-100">{client.name}</span>
                    </div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400 flex items-center gap-2">
                    <Server className="w-4 h-4 text-gray-400 dark:text-gray-500" />
                    {client.apiUrl}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">{client.account}</td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <span className={`px-2.5 py-1 rounded-full text-xs font-medium ${
                      client.status === '启用'
                        ? 'bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-400'
                        : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300'
                    }`}>
                      {client.status}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <span className={`px-2.5 py-1 rounded-full text-xs font-medium ${
                      client.authStatus === '已认证'
                        ? 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-800 dark:text-emerald-400'
                        : client.authStatus === '即将过期'
                          ? 'bg-amber-100 dark:bg-amber-900/30 text-amber-800 dark:text-amber-400'
                          : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300'
                    }`}>
                      {client.authStatus}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                    <button
                      onClick={() => handleAuthenticate(client)}
                      className="text-emerald-600 dark:text-emerald-400 hover:text-emerald-900 dark:hover:text-emerald-300 mr-3"
                      title="认证测试"
                    >
                      <ShieldCheck className="w-4 h-4" />
                    </button>
                    <button onClick={() => handleOpenModal(client)} className="text-blue-600 dark:text-blue-400 hover:text-blue-900 dark:hover:text-blue-300 mr-3"><Edit2 className="w-4 h-4" /></button>
                    <button onClick={() => handleDelete(client.id)} className="text-red-600 dark:text-red-400 hover:text-red-900 dark:hover:text-red-300"><Trash2 className="w-4 h-4" /></button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Modal */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="bg-white dark:bg-gray-800 rounded-xl p-6 w-full max-w-md border border-gray-200 dark:border-gray-700 shadow-xl">
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-lg font-bold text-gray-900 dark:text-white">
                {editingId ? '编辑客户端' : '新增客户端'}
              </h3>
              <button onClick={handleCloseModal} className="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200">
                <X className="w-5 h-5" />
              </button>
            </div>
            
            <form onSubmit={handleSave} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">客户端名称</label>
                <input 
                  type="text" 
                  value={formData.name} 
                  onChange={e => setFormData({...formData, name: e.target.value})} 
                  required 
                  className="w-full bg-white dark:bg-gray-900 border border-gray-300 dark:border-gray-600 text-gray-900 dark:text-gray-100 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-colors" 
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">API 地址</label>
                <input 
                  type="url" 
                  value={formData.apiUrl} 
                  onChange={e => setFormData({...formData, apiUrl: e.target.value})} 
                  required 
                  className="w-full bg-white dark:bg-gray-900 border border-gray-300 dark:border-gray-600 text-gray-900 dark:text-gray-100 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-colors" 
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">账户</label>
                <input 
                  type="text" 
                  value={formData.account} 
                  onChange={e => setFormData({...formData, account: e.target.value})} 
                  required 
                  className="w-full bg-white dark:bg-gray-900 border border-gray-300 dark:border-gray-600 text-gray-900 dark:text-gray-100 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-colors" 
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">密码</label>
                <input 
                  type="password" 
                  value={formData.password} 
                  onChange={e => setFormData({...formData, password: e.target.value})} 
                  className="w-full bg-white dark:bg-gray-900 border border-gray-300 dark:border-gray-600 text-gray-900 dark:text-gray-100 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-colors" 
                />
                <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                  {editingId ? '留空表示保留原密码。' : '创建时必须填写密码。'}
                </p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">状态</label>
                <select 
                  value={formData.status} 
                  onChange={e => setFormData({...formData, status: e.target.value})} 
                  className="w-full bg-white dark:bg-gray-900 border border-gray-300 dark:border-gray-600 text-gray-900 dark:text-gray-100 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-colors"
                >
                  <option value="启用">启用</option>
                  <option value="停用">停用</option>
                </select>
              </div>
              <div className="flex justify-end gap-3 pt-4 border-t border-gray-200 dark:border-gray-700">
                <button 
                  type="button" 
                  onClick={handleCloseModal}
                  className="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 rounded-lg transition-colors"
                >
                  取消
                </button>
                <button 
                  type="submit"
                  disabled={submitting}
                  className="px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors"
                >
                  {submitting ? '保存中...' : '保存'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
