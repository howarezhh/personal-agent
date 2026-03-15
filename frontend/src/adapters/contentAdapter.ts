import type {
  ContentGenerationResponseContract,
  ContentOptimizeRequestContract,
  NovelChapterRequestContract,
  NovelCharacterRequestContract,
  NovelContinueRequestContract,
  NovelOutlineRequestContract,
  NovelWorldviewRequestContract,
  ScriptCompleteRequestContract,
  ScriptDialogueRequestContract,
  ScriptOutlineRequestContract,
  ScriptSceneRequestContract,
  ScriptStoryboardRequestContract,
} from '@/contracts/content';

export interface ContentGenerationResponse<T = Record<string, unknown>> {
  success: boolean;
  data?: T;
  error?: string;
}

export interface NovelOutlineRequest {
  title?: string;
  theme?: string;
  genre?: string;
  style?: string;
}

export interface NovelChapterRequest {
  chapterNumber: number;
  chapterTitle?: string;
  outline?: string;
  genre?: string;
  style?: string;
  wordCount?: number;
}

export interface NovelCharacterRequest {
  characterName?: string;
  genre?: string;
  theme?: string;
}

export interface NovelWorldviewRequest {
  title?: string;
  theme?: string;
  genre?: string;
}

export interface NovelContinueRequest {
  previousContent: string;
  genre?: string;
  style?: string;
  wordCount?: number;
}

export interface ScriptOutlineRequest {
  scriptType: string;
  title?: string;
  theme?: string;
  style?: string;
  duration?: number;
  targetAudience?: string;
}

export interface ScriptSceneRequest {
  scriptType: string;
  sceneNumber?: number;
  sceneDescription?: string;
  characters?: string;
  style?: string;
  outline?: string;
}

export interface ScriptDialogueRequest {
  scriptType: string;
  characters?: string;
  sceneDescription?: string;
  style?: string;
}

export interface ScriptStoryboardRequest {
  scriptType: string;
  sceneDescription?: string;
  style?: string;
}

export interface ScriptCompleteRequest {
  scriptType: string;
  title?: string;
  theme?: string;
  style?: string;
  duration?: number;
  targetAudience?: string;
}

export interface ContentOptimizeRequest {
  action: string;
  content: string;
  targetStyle?: string;
  targetLength?: number;
  keywords?: string;
  requirements?: string;
}

export interface ContentOptimizeResult {
  optimizedContent?: string;
  checkResult?: string;
  originalLength?: number;
  optimizedLength?: number;
  compressionRatio?: number | string;
  [key: string]: unknown;
}

const toCamelCase = (value: string): string => value.replace(/_([a-z])/g, (_, letter: string) => letter.toUpperCase());

export const camelizeKeys = (value: unknown): unknown => {
  if (Array.isArray(value)) {
    return value.map((item) => camelizeKeys(item));
  }

  if (value && typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>).reduce<Record<string, unknown>>((result, [key, entryValue]) => {
      result[toCamelCase(key)] = camelizeKeys(entryValue);
      return result;
    }, {});
  }

  return value;
};

export const adaptContentGenerationResponse = <T = Record<string, unknown>>(
  response: ContentGenerationResponseContract
): ContentGenerationResponse<T> => ({
  success: response.success,
  data: response.data ? (camelizeKeys(response.data) as T) : undefined,
  error: response.error ?? undefined,
});

export const adaptContentGenerationData = <T = Record<string, unknown>>(data: unknown): T =>
  camelizeKeys(data) as T;

export const toNovelOutlineRequestContract = (request: NovelOutlineRequest): NovelOutlineRequestContract => ({
  title: request.title,
  theme: request.theme,
  genre: request.genre,
  style: request.style,
});

export const toNovelChapterRequestContract = (request: NovelChapterRequest): NovelChapterRequestContract => ({
  chapter_number: request.chapterNumber,
  chapter_title: request.chapterTitle,
  outline: request.outline,
  genre: request.genre,
  style: request.style,
  word_count: request.wordCount ?? 2000,
});

export const toNovelCharacterRequestContract = (request: NovelCharacterRequest): NovelCharacterRequestContract => ({
  character_name: request.characterName,
  genre: request.genre,
  theme: request.theme,
});

export const toNovelWorldviewRequestContract = (request: NovelWorldviewRequest): NovelWorldviewRequestContract => ({
  title: request.title,
  theme: request.theme,
  genre: request.genre,
});

export const toNovelContinueRequestContract = (request: NovelContinueRequest): NovelContinueRequestContract => ({
  previous_content: request.previousContent,
  genre: request.genre,
  style: request.style,
  word_count: request.wordCount ?? 1000,
});

export const toScriptOutlineRequestContract = (request: ScriptOutlineRequest): ScriptOutlineRequestContract => ({
  script_type: request.scriptType,
  title: request.title,
  theme: request.theme,
  style: request.style,
  duration: request.duration,
  target_audience: request.targetAudience,
});

export const toScriptSceneRequestContract = (request: ScriptSceneRequest): ScriptSceneRequestContract => ({
  script_type: request.scriptType,
  scene_number: request.sceneNumber ?? 1,
  scene_description: request.sceneDescription,
  characters: request.characters,
  style: request.style,
  outline: request.outline,
});

export const toScriptDialogueRequestContract = (request: ScriptDialogueRequest): ScriptDialogueRequestContract => ({
  script_type: request.scriptType,
  characters: request.characters,
  scene_description: request.sceneDescription,
  style: request.style,
});

export const toScriptStoryboardRequestContract = (request: ScriptStoryboardRequest): ScriptStoryboardRequestContract => ({
  script_type: request.scriptType,
  scene_description: request.sceneDescription,
  style: request.style,
});

export const toScriptCompleteRequestContract = (request: ScriptCompleteRequest): ScriptCompleteRequestContract => ({
  script_type: request.scriptType,
  title: request.title,
  theme: request.theme,
  style: request.style,
  duration: request.duration,
  target_audience: request.targetAudience,
});

export const toContentOptimizeRequestContract = (request: ContentOptimizeRequest): ContentOptimizeRequestContract => ({
  action: request.action,
  content: request.content,
  target_style: request.targetStyle,
  target_length: request.targetLength,
  keywords: request.keywords,
  requirements: request.requirements,
});
