export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL !== undefined ? import.meta.env.VITE_API_BASE_URL : '';

export const API_PATHS = {
  auth: {
    login: '/api/v1/auth/login',
    register: '/api/v1/auth/register',
    logout: '/api/v1/auth/logout',
    profile: '/api/v1/auth/profile',
    refresh: '/api/v1/auth/refresh',
  },
  chat: {
    ask: '/api/v1/chat/ask',
    pause: '/api/v1/chat/pause',
  },
  conversations: '/api/v1/conversations',
  knowledge: {
    bases: '/api/v1/knowledge/bases',
    upload: '/api/v1/knowledge/upload',
    uploadBatch: '/api/v1/knowledge/upload/batch',
    documents: '/api/v1/knowledge/documents',
    documentStatus: '/api/v1/knowledge/documents',
    rebuildVectors: '/api/v1/knowledge/rebuild-vectors',
    fullRebuildVectors: '/api/v1/knowledge/rebuild-vectors/full',
    fullRebuildVectorTasks: '/api/v1/knowledge/rebuild-vectors/full/tasks',
    search: '/api/v1/knowledge/search',
  },
  content: {
    novelOutline: '/api/v1/content/novel/outline',
    novelChapter: '/api/v1/content/novel/chapter',
    novelCharacter: '/api/v1/content/novel/character',
    novelWorldview: '/api/v1/content/novel/worldview',
    novelContinue: '/api/v1/content/novel/continue',
    scriptOutline: '/api/v1/content/script/outline',
    scriptScene: '/api/v1/content/script/scene',
    scriptDialogue: '/api/v1/content/script/dialogue',
    scriptStoryboard: '/api/v1/content/script/storyboard',
    scriptComplete: '/api/v1/content/script/complete',
    optimize: '/api/v1/content/optimize',
  },
} as const;
