/**
 * 服务层统一导出
 */

// 导出服务
export * from './authService';
export * from './chatService';
export * from './conversationService';
export * from './knowledgeService';
export * from './toolService';
export * from './contentService';

// 导出类型
export type {
  SearchRequest,
  SearchResult,
  SearchResponse,
  DocumentListResponse,
  KnowledgeBaseListResponse,
} from './knowledgeService';

export type {
  Tool,
  ToolParameter,
  ToolExecuteRequest,
  ToolExecuteResponse,
  ToolCategory,
} from './toolService';

export type {
  ContentGenerationResponse,
  NovelOutlineRequest,
  NovelChapterRequest,
  NovelCharacterRequest,
  NovelWorldviewRequest,
  NovelContinueRequest,
  ScriptOutlineRequest,
  ScriptSceneRequest,
  ScriptDialogueRequest,
  ScriptStoryboardRequest,
  ScriptCompleteRequest,
  ContentOptimizeRequest,
} from './contentService';
