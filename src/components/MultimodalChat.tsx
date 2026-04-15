import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Check, Copy, Cpu, LoaderCircle, MessageSquare, Paperclip, RefreshCw, Send, Trash2, X } from 'lucide-react';

type MultimodalModel = {
  id: number;
  modelName: string;
  endpointUrl: string;
  status: string;
};

type AttachmentPayload = {
  name: string;
  mimeType: string;
  kind: 'image' | 'video' | 'audio' | 'document';
  dataUrl?: string;
  textContent?: string;
};

type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  attachments: AttachmentPayload[];
};

const attachmentKindLabel: Record<AttachmentPayload['kind'], string> = {
  image: '图片',
  video: '视频',
  audio: '音频',
  document: '文档'
};

const textFileExtensions = new Set(['txt', 'md', 'csv', 'json', 'xml', 'log']);

const readAsDataUrl = (file: File) => new Promise<string>((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(String(reader.result || ''));
  reader.onerror = () => reject(reader.error);
  reader.readAsDataURL(file);
});

const readAsText = (file: File) => new Promise<string>((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(String(reader.result || ''));
  reader.onerror = () => reject(reader.error);
  reader.readAsText(file);
});

const getFileExtension = (fileName: string) => fileName.split('.').pop()?.toLowerCase() || '';

const isTextLikeFile = (file: File) => {
  return file.type.startsWith('text/')
    || ['application/json', 'application/xml'].includes(file.type)
    || textFileExtensions.has(getFileExtension(file.name));
};

const getFileKind = (file: File): AttachmentPayload['kind'] => {
  if (file.type.startsWith('image/')) return 'image';
  if (file.type.startsWith('video/')) return 'video';
  if (file.type.startsWith('audio/')) return 'audio';
  return 'document';
};

async function fileToAttachment(file: File): Promise<AttachmentPayload> {
  const kind = getFileKind(file);
  if (isTextLikeFile(file)) {
    return {
      name: file.name,
      mimeType: file.type || 'text/plain',
      kind,
      textContent: await readAsText(file)
    };
  }

  return {
    name: file.name,
    mimeType: file.type || 'application/octet-stream',
    kind,
    dataUrl: await readAsDataUrl(file)
  };
}

const getAttachmentPreviewText = (attachment: AttachmentPayload) => {
  const text = String(attachment.textContent || '').trim();
  if (!text) return '';
  return text.length > 220 ? `${text.slice(0, 220)}...` : text;
};

export default function MultimodalChat({ onOpenModelManager }: { onOpenModelManager: () => void }) {
  const [models, setModels] = useState<MultimodalModel[]>([]);
  const [selectedModelId, setSelectedModelId] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputText, setInputText] = useState('');
  const [pendingAttachments, setPendingAttachments] = useState<AttachmentPayload[]>([]);
  const [sending, setSending] = useState(false);
  const [loadingModels, setLoadingModels] = useState(false);
  const [error, setError] = useState('');
  const [previewAttachment, setPreviewAttachment] = useState<AttachmentPayload | null>(null);
  const [copiedMessageId, setCopiedMessageId] = useState('');
  const bottomRef = useRef<HTMLDivElement | null>(null);

  const fetchModels = async () => {
    setLoadingModels(true);
    try {
      const response = await fetch('/api/multimodal-models');
      const data = await response.json();
      const nextModels = Array.isArray(data) ? data.filter((item) => item.status !== 'disabled') : [];
      setModels(nextModels);
    } catch (fetchError) {
      console.error(fetchError);
    } finally {
      setLoadingModels(false);
    }
  };

  useEffect(() => {
    fetchModels();
  }, []);

  useEffect(() => {
    if (models.length === 0) {
      setSelectedModelId('');
      return;
    }

    const exists = models.some((item) => String(item.id) === selectedModelId);
    if (!exists) {
      setSelectedModelId(String(models[0].id));
    }
  }, [models, selectedModelId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, pendingAttachments, sending]);

  const selectedModel = useMemo(
    () => models.find((item) => String(item.id) === selectedModelId) || null,
    [models, selectedModelId]
  );

  const handleFileChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []);
    if (files.length === 0) return;

    try {
      const converted = await Promise.all(files.map(fileToAttachment));
      setPendingAttachments((prev) => [...prev, ...converted]);
      setError('');
    } catch (conversionError) {
      setError((conversionError as Error).message || '附件读取失败');
    } finally {
      event.target.value = '';
    }
  };

  const handleRemoveAttachment = (index: number) => {
    setPendingAttachments((prev) => prev.filter((_, currentIndex) => currentIndex !== index));
  };

  const handleClearConversation = () => {
    setMessages([]);
    setPendingAttachments([]);
    setInputText('');
    setError('');
    setPreviewAttachment(null);
    setCopiedMessageId('');
  };

  const handleCopyMessage = async (message: ChatMessage) => {
    const text = String(message.content || '').trim();
    if (!text) return;

    try {
      await navigator.clipboard.writeText(text);
      setCopiedMessageId(message.id);
      window.setTimeout(() => {
        setCopiedMessageId((current) => current === message.id ? '' : current);
      }, 1600);
    } catch (copyError) {
      setError((copyError as Error).message || '复制失败');
    }
  };

  const handleSend = async () => {
    if (!selectedModelId || sending) return;
    if (!inputText.trim() && pendingAttachments.length === 0) return;

    const currentText = inputText.trim();
    const currentAttachments = pendingAttachments.map((attachment) => ({ ...attachment }));
    const attachmentSummary = currentAttachments.length > 0 ? `（已附 ${currentAttachments.length} 个附件）` : '';
    const userMessage: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: currentText || `已发送本轮测试附件 ${attachmentSummary || '（无文字内容）'}`,
      attachments: currentAttachments
    };

    setMessages((prev) => [...prev, userMessage]);
    setInputText('');
    setPendingAttachments([]);
    setSending(true);
    setError('');

    try {
      const response = await fetch(`/api/multimodal-models/${selectedModelId}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: [{
            role: 'user',
            content: currentText,
            attachments: currentAttachments
          }]
        })
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.error || data.message || '模型调用失败');
      }

      setMessages((prev) => [...prev, {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: String(data.reply || '模型未返回内容。'),
        attachments: []
      }]);
    } catch (sendError) {
      const message = (sendError as Error).message || '模型调用失败';
      setError(message);
      setMessages((prev) => [...prev, {
        id: `assistant-error-${Date.now()}`,
        role: 'assistant',
        content: `调用失败：${message}`,
        attachments: []
      }]);
    } finally {
      setSending(false);
    }
  };

  if (!loadingModels && models.length === 0) {
    return (
      <div className="p-8">
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-dashed border-gray-300 dark:border-gray-700 py-16 text-center">
          <Cpu className="w-12 h-12 mx-auto text-gray-300 dark:text-gray-600 mb-3" />
          <p className="text-lg font-medium text-gray-900 dark:text-white">还没有可用的多模态模型</p>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-2">请先到“多模态模型管理”里添加地址、密码和模型名称。</p>
          <button
            type="button"
            onClick={onOpenModelManager}
            className="mt-5 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium transition-colors"
          >
            前往多模态模型管理
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="p-8">
      <div className="flex items-center justify-between gap-4 mb-6">
        <div>
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">多模态模型测试</h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">选择一个多模态模型进行对话，支持上传图片、视频、音频和文档；已发送附件会显示在当前会话里并可打开查看。</p>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={fetchModels}
            className="px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors flex items-center gap-2"
          >
            <RefreshCw className={`w-4 h-4 ${loadingModels ? 'animate-spin' : ''}`} />
            刷新模型
          </button>
          <button
            type="button"
            onClick={onOpenModelManager}
            className="px-4 py-2 rounded-lg bg-violet-600 hover:bg-violet-700 text-white text-sm font-medium transition-colors"
          >
            管理模型
          </button>
        </div>
      </div>

      <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm overflow-hidden">
        <div className="p-4 border-b border-gray-200 dark:border-gray-700 flex flex-col lg:flex-row gap-3 lg:items-center lg:justify-between">
          <div className="flex flex-col sm:flex-row sm:items-center gap-3">
            <label className="text-sm font-medium text-gray-700 dark:text-gray-300">当前模型</label>
            <select
              value={selectedModelId}
              onChange={(e) => setSelectedModelId(e.target.value)}
              className="min-w-[320px] bg-white dark:bg-gray-900 border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm"
            >
              {models.map((model) => (
                <option key={model.id} value={String(model.id)}>
                  {model.modelName}
                </option>
              ))}
            </select>
          </div>

          <button
            type="button"
            onClick={handleClearConversation}
            className="inline-flex items-center gap-2 text-sm font-medium text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300"
          >
            <Trash2 className="w-4 h-4" />
            清空对话
          </button>
        </div>

        <div className="h-[44vh] min-h-[280px] max-h-[520px] overflow-y-auto p-4 bg-gray-50/70 dark:bg-gray-900/30 space-y-4 lg:h-[48vh]">
          {messages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-center text-gray-500 dark:text-gray-400">
              <MessageSquare className="w-12 h-12 mb-4 opacity-40" />
              <p className="text-lg font-medium text-gray-900 dark:text-white mb-2">开始一轮模型测试</p>
              <p className="max-w-xl text-sm">这里会展示当前会话的测试记录。已发送附件会显示在对话中，可点击打开查看；关闭、刷新页面或重新进入模型测试页后会自动清空。</p>
            </div>
          ) : messages.map((message) => (
            <div key={message.id} className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-3xl rounded-2xl px-4 py-3 shadow-sm ${
                message.role === 'user'
                  ? 'bg-blue-600 text-white'
                  : 'bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-gray-100'
              }`}>
                <div className="flex items-center justify-between gap-3 mb-2">
                  <div className="text-xs opacity-80">{message.role === 'user' ? '你' : selectedModel?.modelName || '模型'}</div>
                  {message.role === 'assistant' && message.content && (
                    <button
                      type="button"
                      onClick={() => handleCopyMessage(message)}
                      className="inline-flex items-center justify-center w-8 h-8 rounded-lg text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-700 transition-colors"
                      title="复制回复内容"
                    >
                      {copiedMessageId === message.id ? <Check className="w-4 h-4 text-green-600 dark:text-green-400" /> : <Copy className="w-4 h-4" />}
                    </button>
                  )}
                </div>
                {message.content && (
                  <div className="whitespace-pre-wrap text-sm leading-6">{message.content}</div>
                )}
                {message.attachments.length > 0 && (
                  <div className="mt-3 space-y-3">
                    {message.attachments.map((attachment, index) => (
                      <button
                        key={`${message.id}-${attachment.name}-${index}`}
                        type="button"
                        onClick={() => setPreviewAttachment(attachment)}
                        className={`w-full text-left rounded-xl p-3 border transition-colors ${
                          message.role === 'user'
                            ? 'bg-white/10 border-white/20 text-white hover:bg-white/15'
                            : 'bg-gray-50 dark:bg-gray-700/60 border-gray-200 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700'
                        }`}
                      >
                        <div className="flex items-center justify-between gap-3 text-xs">
                          <span className="font-semibold">{attachmentKindLabel[attachment.kind]} · {attachment.name}</span>
                          <span className={`${message.role === 'user' ? 'text-white/80' : 'text-blue-600 dark:text-blue-300'}`}>点击查看</span>
                        </div>

                        {attachment.kind === 'image' && attachment.dataUrl && (
                          <img
                            src={attachment.dataUrl}
                            alt={attachment.name}
                            className="mt-3 max-h-52 rounded-lg border border-black/10 object-contain bg-black/5"
                          />
                        )}

                        {attachment.kind === 'video' && (
                          <div className={`mt-3 rounded-lg px-3 py-2 text-xs ${message.role === 'user' ? 'bg-white/10' : 'bg-gray-100 dark:bg-gray-800'}`}>
                            视频附件，点击打开预览
                          </div>
                        )}

                        {attachment.kind === 'audio' && (
                          <div className={`mt-3 rounded-lg px-3 py-2 text-xs ${message.role === 'user' ? 'bg-white/10' : 'bg-gray-100 dark:bg-gray-800'}`}>
                            音频附件，点击打开预览
                          </div>
                        )}

                        {getAttachmentPreviewText(attachment) && (
                          <pre className={`mt-3 whitespace-pre-wrap break-words text-xs leading-5 rounded-lg p-3 overflow-hidden ${
                            message.role === 'user' ? 'bg-white/10 text-white' : 'bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-200'
                          }`}>
                            {getAttachmentPreviewText(attachment)}
                          </pre>
                        )}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}

          {sending && (
            <div className="flex justify-start">
              <div className="max-w-3xl rounded-2xl px-4 py-3 shadow-sm bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-gray-100">
                <div className="text-xs mb-2 opacity-80">{selectedModel?.modelName || '模型'}</div>
                <div className="flex items-center gap-3">
                  <LoaderCircle className="w-4 h-4 animate-spin text-blue-600 dark:text-blue-400" />
                  <div className="flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-blue-500/70 animate-bounce [animation-delay:-0.3s]" />
                    <span className="w-2 h-2 rounded-full bg-blue-500/70 animate-bounce [animation-delay:-0.15s]" />
                    <span className="w-2 h-2 rounded-full bg-blue-500/70 animate-bounce" />
                  </div>
                  <span className="text-sm text-gray-500 dark:text-gray-400">模型正在思考中...</span>
                </div>
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <div className="p-4 border-t border-gray-200 dark:border-gray-700 space-y-3">
          <div className="flex flex-wrap gap-2">
            {pendingAttachments.map((attachment, index) => (
              <button
                key={`${attachment.name}-${index}`}
                type="button"
                onClick={() => handleRemoveAttachment(index)}
                className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-gray-100 dark:bg-gray-700 text-sm text-gray-700 dark:text-gray-200"
              >
                {attachment.kind.toUpperCase()} · {attachment.name}
                <span className="text-xs opacity-70">移除</span>
              </button>
            ))}
          </div>

          <div className="flex items-center gap-3">
            <div className="shrink-0">
              <label className="inline-flex items-center gap-2 px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 cursor-pointer transition-colors">
                <Paperclip className="w-4 h-4" />
                上传附件
                <input
                  type="file"
                  multiple
                  accept="image/*,video/*,audio/*,.txt,.md,.csv,.json,.xml,.log,.pdf,.doc,.docx"
                  className="hidden"
                  onChange={handleFileChange}
                />
              </label>
            </div>

            <textarea
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              placeholder="输入想对多模态模型说的话，或配合附件一起发送……"
              className="flex-1 h-10 min-h-[40px] max-h-[96px] resize-none overflow-y-auto bg-white dark:bg-gray-900 border border-gray-300 dark:border-gray-600 text-gray-900 dark:text-gray-100 rounded-xl px-4 py-2.5 text-sm leading-5 focus:ring-2 focus:ring-blue-500 outline-none transition-colors"
            />

            <button
              type="button"
              onClick={handleSend}
              disabled={!selectedModelId || sending || (!inputText.trim() && pendingAttachments.length === 0)}
              className="shrink-0 inline-flex items-center justify-center gap-2 px-5 h-10 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white text-sm font-medium transition-colors"
            >
              <Send className="w-4 h-4" />
              发送给模型
            </button>
          </div>

          <div className="text-xs text-gray-500 dark:text-gray-400">
            每次发送后会清空当前输入框与待发送附件；已发送附件会保留在当前页面会话的对话区，关闭、刷新页面或重新进入模型测试页后自动清空。
          </div>

          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 text-red-700 dark:border-red-900/40 dark:bg-red-900/20 dark:text-red-300 px-4 py-3 text-sm">
              {error}
            </div>
          )}
        </div>
      </div>

      {previewAttachment && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4">
          <div className="w-full max-w-4xl max-h-[88vh] overflow-hidden rounded-2xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 shadow-2xl flex flex-col">
            <div className="flex items-start justify-between gap-4 px-5 py-4 border-b border-gray-200 dark:border-gray-700">
              <div>
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white">{previewAttachment.name}</h3>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                  {attachmentKindLabel[previewAttachment.kind]} · {previewAttachment.mimeType || '未知类型'}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setPreviewAttachment(null)}
                className="inline-flex items-center justify-center w-9 h-9 rounded-lg text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-5 overflow-auto">
              {previewAttachment.kind === 'image' && previewAttachment.dataUrl && (
                <img src={previewAttachment.dataUrl} alt={previewAttachment.name} className="max-w-full max-h-[68vh] mx-auto rounded-xl" />
              )}

              {previewAttachment.kind === 'video' && previewAttachment.dataUrl && (
                <video src={previewAttachment.dataUrl} controls className="w-full max-h-[68vh] rounded-xl bg-black" />
              )}

              {previewAttachment.kind === 'audio' && previewAttachment.dataUrl && (
                <div className="max-w-xl">
                  <audio src={previewAttachment.dataUrl} controls className="w-full" />
                </div>
              )}

              {previewAttachment.textContent && (
                <pre className="whitespace-pre-wrap break-words text-sm leading-6 rounded-xl bg-gray-50 dark:bg-gray-800 text-gray-800 dark:text-gray-100 p-4">
                  {previewAttachment.textContent}
                </pre>
              )}

              {!previewAttachment.textContent && previewAttachment.mimeType === 'application/pdf' && previewAttachment.dataUrl && (
                <iframe
                  src={previewAttachment.dataUrl}
                  title={previewAttachment.name}
                  className="w-full h-[68vh] rounded-xl border border-gray-200 dark:border-gray-700"
                />
              )}

              {!previewAttachment.textContent
                && previewAttachment.mimeType !== 'application/pdf'
                && previewAttachment.kind === 'document'
                && previewAttachment.dataUrl && (
                  <div className="space-y-3">
                    <div className="text-sm text-gray-600 dark:text-gray-300">
                      当前文档类型暂不支持直接内嵌预览，你可以点击下面按钮在新窗口打开。
                    </div>
                    <a
                      href={previewAttachment.dataUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium"
                    >
                      打开附件
                    </a>
                  </div>
                )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
