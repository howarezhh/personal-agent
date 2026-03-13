import { useCallback, useRef } from 'react';

import { adaptSSEEvent, type SSEEvent } from '@/adapters/chatAdapter';
import type { SSEEventContract } from '@/contracts/chat';
import type { ErrorResponseContract } from '@/contracts/common';
import { API_BASE_URL } from '@/constants/api';
import { authSession } from '@/services/authSession';
import { clearAuthAndRedirect, refreshAccessToken } from '@/services/tokenRefresh';

export const useSSE = () => {
  const cancelFnRef = useRef<(() => void) | null>(null);
  const timeoutMs = 5 * 60 * 1000;

  const emitSSEEvents = (
    rawChunk: string,
    onEvent: (event: SSEEvent) => void,
    onComplete?: () => void,
    onTerminate?: () => void
  ) => {
    const eventBlocks = rawChunk.replace(/\r\n/g, '\n').split('\n\n');

    for (const block of eventBlocks) {
      if (!block) continue;

      const dataLines: string[] = [];
      for (const line of block.split('\n')) {
        if (!line || line.startsWith(':')) continue;
        if (line.startsWith('data:')) {
          const dataValue = line.startsWith('data: ') ? line.slice(6) : line.slice(5);
          dataLines.push(dataValue);
        }
      }

      if (dataLines.length === 0) continue;
      const contract = JSON.parse(dataLines.join('\n')) as SSEEventContract;
      const event = adaptSSEEvent(contract);
      onEvent(event);

      if (event.type === 'done' || event.type === 'error') {
        onTerminate?.();
        onComplete?.();
        return true;
      }
    }

    return false;
  };

  const buildErrorFromResponse = async (response: Response) => {
    let message = `HTTP error! status: ${response.status}`;

    try {
      const data = (await response.json()) as ErrorResponseContract;
      if (data?.message) {
        message = data.message;
      }
    } catch {
      // Ignore parse failures and keep fallback message.
    }

    return new Error(message);
  };

  const fetchStream = async (
    url: string,
    data: unknown,
    signal: AbortSignal,
    allowRefreshRetry: boolean
  ) => {
    const token = authSession.getAccessToken();
    const response = await fetch(`${API_BASE_URL}${url}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(data),
      signal,
    });

    if (response.status === 401 && allowRefreshRetry) {
      try {
        const accessToken = await refreshAccessToken();
        return fetch(`${API_BASE_URL}${url}`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${accessToken}`,
          },
          body: JSON.stringify(data),
          signal,
        });
      } catch (error) {
        clearAuthAndRedirect();
        throw error instanceof Error ? error : new Error('登录已过期，请重新登录');
      }
    }

    return response;
  };

  const connect = useCallback(
    async (
      url: string,
      data: unknown,
      onEvent: (event: SSEEvent) => void,
      onError?: (error: Error) => void,
      onComplete?: () => void
    ) => {
      const controller = new AbortController();
      let timeoutTriggered = false;
      let connectTimeoutTimer: ReturnType<typeof setTimeout> | null = null;
      let inactivityTimeoutTimer: ReturnType<typeof setTimeout> | null = null;

      const clearTimers = () => {
        if (connectTimeoutTimer) clearTimeout(connectTimeoutTimer);
        if (inactivityTimeoutTimer) clearTimeout(inactivityTimeoutTimer);
      };

      const handleTimeout = () => {
        if (timeoutTriggered) return;
        timeoutTriggered = true;
        clearTimers();
        controller.abort();
        onError?.(new Error('连接超时，已终止对话。'));
      };

      const resetInactivityTimer = () => {
        if (inactivityTimeoutTimer) clearTimeout(inactivityTimeoutTimer);
        inactivityTimeoutTimer = setTimeout(handleTimeout, timeoutMs);
      };

      connectTimeoutTimer = setTimeout(handleTimeout, timeoutMs);

      try {
        const response = await fetchStream(url, data, controller.signal, true);

        if (!response.ok || !response.body) {
          throw await buildErrorFromResponse(response);
        }

        clearTimeout(connectTimeoutTimer);
        resetInactivityTimer();

        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        cancelFnRef.current = () => {
          clearTimers();
          controller.abort();
          void reader.cancel();
        };

        let buffer = '';
        while (true) {
          const { done, value } = await reader.read();
          resetInactivityTimer();

          if (done) {
            clearTimers();
            onComplete?.();
            break;
          }

          buffer += decoder.decode(value, { stream: true });
          const normalizedBuffer = buffer.replace(/\r\n/g, '\n');
          const completedLength = normalizedBuffer.lastIndexOf('\n\n');
          if (completedLength === -1) continue;

          const completedChunk = normalizedBuffer.slice(0, completedLength);
          buffer = normalizedBuffer.slice(completedLength + 2);
          const shouldTerminate = emitSSEEvents(completedChunk, onEvent, onComplete, () => {
            clearTimers();
            void reader.cancel();
          });

          if (shouldTerminate) return;
        }
      } catch (error: unknown) {
        clearTimers();
        if (!(error instanceof DOMException && error.name === 'AbortError')) {
          onError?.(error instanceof Error ? error : new Error('流式请求失败'));
        }
      }
    },
    []
  );

  const cancel = useCallback(() => {
    cancelFnRef.current?.();
    cancelFnRef.current = null;
  }, []);

  return { connect, cancel };
};
