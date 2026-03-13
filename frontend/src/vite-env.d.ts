/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string;
  readonly VITE_APP_NAME: string;
  readonly VITE_APP_VERSION: string;
  readonly VITE_ENABLE_KNOWLEDGE_BASE: string;
  readonly VITE_ENABLE_TOOLS: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
