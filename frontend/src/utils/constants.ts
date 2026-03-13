export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL !== undefined ? import.meta.env.VITE_API_BASE_URL : '';
export const APP_NAME = import.meta.env.VITE_APP_NAME || 'Personal Agent';
export const APP_VERSION = import.meta.env.VITE_APP_VERSION || '1.0.0';

export const MESSAGE_TYPE = {
  USER: 'user',
  ASSISTANT: 'assistant',
  SYSTEM: 'system',
} as const;

export const SSE_EVENT_TYPE = {
  THINKING: 'thinking',
  CONTENT: 'content',
  ERROR: 'error',
  DONE: 'done',
} as const;
