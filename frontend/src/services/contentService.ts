import type { ContentGenerationResponseContract } from '@/contracts/content';
import {
  adaptContentGenerationResponse,
  toContentOptimizeRequestContract,
  toNovelChapterRequestContract,
  toNovelCharacterRequestContract,
  toNovelContinueRequestContract,
  toNovelOutlineRequestContract,
  toNovelWorldviewRequestContract,
  toScriptCompleteRequestContract,
  toScriptDialogueRequestContract,
  toScriptOutlineRequestContract,
  toScriptSceneRequestContract,
  toScriptStoryboardRequestContract,
  type ContentGenerationResponse,
  type ContentOptimizeRequest,
  type ContentOptimizeResult,
  type NovelChapterRequest,
  type NovelCharacterRequest,
  type NovelContinueRequest,
  type NovelOutlineRequest,
  type NovelWorldviewRequest,
  type ScriptCompleteRequest,
  type ScriptDialogueRequest,
  type ScriptOutlineRequest,
  type ScriptSceneRequest,
  type ScriptStoryboardRequest,
} from '@/adapters/contentAdapter';
import api from './api';

const API_BASE_URL = '/api/v1/content';

async function postContentRequest<TResult = Record<string, unknown>>(
  path: string,
  payload: unknown
): Promise<ContentGenerationResponse<TResult>> {
  const response = await api.post<ContentGenerationResponseContract>(`${API_BASE_URL}${path}`, payload);
  return adaptContentGenerationResponse<TResult>(response.data);
}

export const generateNovelOutline = (params: NovelOutlineRequest) =>
  postContentRequest('/novel/outline', toNovelOutlineRequestContract(params));

export const generateNovelChapter = (params: NovelChapterRequest) =>
  postContentRequest('/novel/chapter', toNovelChapterRequestContract(params));

export const generateNovelCharacter = (params: NovelCharacterRequest) =>
  postContentRequest('/novel/character', toNovelCharacterRequestContract(params));

export const generateNovelWorldview = (params: NovelWorldviewRequest) =>
  postContentRequest('/novel/worldview', toNovelWorldviewRequestContract(params));

export const continueNovel = (params: NovelContinueRequest) =>
  postContentRequest('/novel/continue', toNovelContinueRequestContract(params));

export const generateScriptOutline = (params: ScriptOutlineRequest) =>
  postContentRequest('/script/outline', toScriptOutlineRequestContract(params));

export const generateScriptScene = (params: ScriptSceneRequest) =>
  postContentRequest('/script/scene', toScriptSceneRequestContract(params));

export const generateScriptDialogue = (params: ScriptDialogueRequest) =>
  postContentRequest('/script/dialogue', toScriptDialogueRequestContract(params));

export const generateScriptStoryboard = (params: ScriptStoryboardRequest) =>
  postContentRequest('/script/storyboard', toScriptStoryboardRequestContract(params));

export const generateCompleteScript = (params: ScriptCompleteRequest) =>
  postContentRequest('/script/complete', toScriptCompleteRequestContract(params));

export const optimizeContent = (params: ContentOptimizeRequest) =>
  postContentRequest<ContentOptimizeResult>('/optimize', toContentOptimizeRequestContract(params));

export type {
  ContentGenerationResponse,
  ContentOptimizeRequest,
  ContentOptimizeResult,
  NovelChapterRequest,
  NovelCharacterRequest,
  NovelContinueRequest,
  NovelOutlineRequest,
  NovelWorldviewRequest,
  ScriptCompleteRequest,
  ScriptDialogueRequest,
  ScriptOutlineRequest,
  ScriptSceneRequest,
  ScriptStoryboardRequest,
};

export const NOVEL_GENRES = {
  fantasy: 'Fantasy',
  urban: 'Urban',
  romance: 'Romance',
  scifi: 'Sci-Fi',
  wuxia: 'Wuxia',
  xianxia: 'Xianxia',
  history: 'History',
  military: 'Military',
  mystery: 'Mystery',
  horror: 'Horror',
  game: 'Game',
  sports: 'Sports',
  fanfic: 'Fan Fiction',
} as const;

export const WRITING_STYLES = {
  descriptive: 'Descriptive',
  concise: 'Concise',
  humorous: 'Humorous',
  serious: 'Serious',
  poetic: 'Poetic',
  suspenseful: 'Suspenseful',
} as const;

export const SCRIPT_TYPES = {
  movie: 'Movie',
  tv_series: 'TV Series',
  short_video: 'Short Video',
  advertisement: 'Advertisement',
  stage_play: 'Stage Play',
  animation: 'Animation',
  documentary: 'Documentary',
  variety_show: 'Variety Show',
} as const;

export const SCRIPT_STYLES = {
  comedy: 'Comedy',
  drama: 'Drama',
  action: 'Action',
  romance: 'Romance',
  thriller: 'Thriller',
  scifi: 'Sci-Fi',
  fantasy: 'Fantasy',
  documentary: 'Documentary',
} as const;

export const OPTIMIZATION_TYPES = {
  polish: 'Polish',
  rewrite: 'Rewrite',
  expand: 'Expand',
  summarize: 'Summarize',
  style_transfer: 'Style Transfer',
  grammar_check: 'Grammar Check',
  seo_optimize: 'SEO Optimize',
} as const;

export const CONTENT_STYLES = {
  formal: 'Formal',
  casual: 'Casual',
  professional: 'Professional',
  friendly: 'Friendly',
  persuasive: 'Persuasive',
  informative: 'Informative',
  creative: 'Creative',
  academic: 'Academic',
} as const;
