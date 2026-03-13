import type { AskEnvelopeContract, PauseEnvelopeContract } from '@/contracts/chat';
import { adaptAskResponse, toAskRequestContract, type AskRequest, type AskResponse } from '@/adapters/chatAdapter';
import { API_PATHS } from '@/constants/api';
import api from './api';

interface PauseStreamResponse {
  stream_id: string;
  paused: boolean;
}

export const chatService = {
  async ask(data: AskRequest): Promise<AskResponse> {
    const response = await api.post<AskEnvelopeContract>(API_PATHS.chat.ask, {
      ...toAskRequestContract(data),
      stream: false,
    });
    return adaptAskResponse(response.data.data!);
  },

  async pauseStream(streamId: string): Promise<PauseStreamResponse> {
    const response = await api.post<PauseEnvelopeContract>(API_PATHS.chat.pause, {
      stream_id: streamId,
    });
    return response.data.data || { stream_id: streamId, paused: false };
  },
};
