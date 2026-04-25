import { apiRequest, fetchApi } from '../utils/api';

export type MultimodalModel = {
  id: number;
  modelName: string;
  endpointUrl: string;
  status: '启用' | '停用';
};

export type MultimodalModelListData = {
  items: MultimodalModel[];
};

export type MultimodalChatSession = {
  id: number;
  modelId: number;
  modelName: string;
  title: string;
  messageCount: number;
  createdAt: string;
  updatedAt: string;
  lastMessageAt: string | null;
};

export type MultimodalChatSessionListData = {
  items: MultimodalChatSession[];
};

export type MultimodalChatData = {
  reply: string;
  modelName: string;
  usedUrl: string;
  sessionId: number;
};

export type AttachmentPayload = {
  name: string;
  mimeType: string;
  kind: 'image' | 'video' | 'audio' | 'document';
  dataUrl?: string;
  textContent?: string;
};

export type StoredChatMessage = {
  id: number;
  role: 'system' | 'user' | 'assistant';
  content: string;
  attachments: AttachmentPayload[];
  usedUrl?: string | null;
  createdAt: string;
};

export type MultimodalChatSessionDetailData = {
  session: MultimodalChatSession;
  messages: StoredChatMessage[];
};

export type DeleteSessionData = {
  id: number;
};

export function listMultimodalModels(): Promise<MultimodalModelListData> {
  return fetchApi<MultimodalModelListData>('/api/multimodal-models/list');
}

export function listMultimodalChatSessions(modelId: string): Promise<MultimodalChatSessionListData> {
  return fetchApi<MultimodalChatSessionListData>(`/api/multimodal-models/session-list/${modelId}`);
}

export function getMultimodalChatSessionDetail(sessionId: number): Promise<MultimodalChatSessionDetailData> {
  return fetchApi<MultimodalChatSessionDetailData>(`/api/multimodal-models/session-detail/${sessionId}`);
}

export function deleteMultimodalChatSession(sessionId: number): Promise<DeleteSessionData> {
  return fetchApi<DeleteSessionData>(`/api/multimodal-models/delete-session/${sessionId}`, {
    method: 'DELETE',
  });
}

export function sendMultimodalChat(modelId: string, body: string): Promise<MultimodalChatData> {
  return fetchApi<MultimodalChatData>(`/api/multimodal-models/chat/${modelId}`, {
    method: 'POST',
    body,
  });
}

export function streamMultimodalChat(modelId: string, body: string): Promise<Response> {
  return apiRequest(`/api/multimodal-models/chat-stream/${modelId}`, {
    method: 'POST',
    body,
  });
}
