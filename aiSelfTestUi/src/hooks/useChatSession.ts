import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  listMultimodalChatSessions,
  listMultimodalModels,
} from '../api/multimodalChat';

export const multimodalChatKeys = {
  models: ['multimodal-models'] as const,
  sessions: (modelId: string) => ['multimodal-chat-sessions', modelId] as const,
};

export function useEnabledMultimodalModels() {
  return useQuery({
    queryKey: multimodalChatKeys.models,
    queryFn: listMultimodalModels,
    select: (data) => data.items.filter((item) => item.status === '启用'),
  });
}

export function useMultimodalChatSessions(modelId: string) {
  return useQuery({
    queryKey: multimodalChatKeys.sessions(modelId),
    queryFn: () => listMultimodalChatSessions(modelId),
    enabled: Boolean(modelId),
    select: (data) => data.items,
  });
}

export function useInvalidateMultimodalChat() {
  const queryClient = useQueryClient();

  return {
    invalidateModels: () => queryClient.invalidateQueries({ queryKey: multimodalChatKeys.models }),
    invalidateSessions: (modelId: string) => queryClient.invalidateQueries({
      queryKey: multimodalChatKeys.sessions(modelId),
    }),
  };
}
