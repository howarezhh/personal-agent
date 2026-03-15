import { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, Button, Card, Col, Form, Input, InputNumber, Row, Select, Space, Tabs, Tag, Typography, message } from 'antd';
import { BookOutlined, EditOutlined, FileTextOutlined, GlobalOutlined, UserOutlined } from '@ant-design/icons';

import {
  toNovelChapterRequestContract,
  toNovelCharacterRequestContract,
  toNovelContinueRequestContract,
  toNovelOutlineRequestContract,
  toNovelWorldviewRequestContract,
  type NovelChapterRequest,
  type NovelCharacterRequest,
  type NovelContinueRequest,
  type NovelOutlineRequest,
  type NovelWorldviewRequest,
} from '@/adapters/contentAdapter';
import { ContentResultPanel } from '@/components/content/ContentResultPanel';
import { API_PATHS } from '@/constants/api';
import { novelActionMeta, novelGenreOptions, writingStyleOptions } from '@/constants/contentOptions';
import { useContentGenerationStream } from '@/hooks/useContentGenerationStream';

import './NovelGenerator.css';

const { TextArea } = Input;
const { Paragraph, Text, Title } = Typography;

type NovelActionKey = 'outline' | 'chapter' | 'character' | 'worldview' | 'continue';
type NovelDraft = Record<string, unknown>;

interface SavedNovelModuleResult {
  generationId: string | null;
  result: Record<string, unknown>;
  savedAt: string;
}

interface NovelWorkspaceState {
  activeAction: NovelActionKey;
  drafts: Partial<Record<NovelActionKey, NovelDraft>>;
  results: Partial<Record<NovelActionKey, SavedNovelModuleResult>>;
}

interface NovelContextSnapshot {
  title?: string;
  genre?: string;
  style?: string;
  theme?: string;
  outlineText?: string;
  characterText?: string;
  worldviewText?: string;
  latestNarrativeText?: string;
  nextChapterNumber?: number;
}

interface RecommendedContext {
  note: string;
  patch: NovelDraft;
  sources: NovelActionKey[];
}

const STORAGE_KEY = 'personal-agent:novel-generator-workspace:v1';

const actionItems: { key: NovelActionKey; label: string; icon: JSX.Element }[] = [
  { key: 'outline', label: '小说大纲', icon: <FileTextOutlined /> },
  { key: 'character', label: '角色设定', icon: <UserOutlined /> },
  { key: 'worldview', label: '世界观', icon: <GlobalOutlined /> },
  { key: 'chapter', label: '章节正文', icon: <BookOutlined /> },
  { key: 'continue', label: '续写', icon: <EditOutlined /> },
];

const actionLabels: Record<NovelActionKey, string> = {
  outline: '小说大纲',
  character: '角色设定',
  worldview: '世界观',
  chapter: '章节正文',
  continue: '续写',
};

const actionFlowHints: Record<NovelActionKey, string> = {
  outline: '大纲确定故事骨架，可吸收已有角色、世界观和正文进度反向修订。',
  character: '角色设定承接大纲与世界观，再反哺章节里的行动、动机和关系冲突。',
  worldview: '世界观承接主线与人物需求，把冲突落到规则、势力和文明背景上。',
  chapter: '章节正文会综合大纲、角色和世界观，把设定真正落到剧情推进里。',
  continue: '续写承接最近正文继续推进情节，并可作为下一章或下一轮大纲调整的前情。',
};

const defaultWorkspace = (): NovelWorkspaceState => ({
  activeAction: 'outline',
  drafts: {},
  results: {},
});

const getDefaultValues = (action: NovelActionKey): NovelDraft => {
  switch (action) {
    case 'chapter':
      return { chapterNumber: 1, wordCount: 2000 };
    case 'continue':
      return { wordCount: 1000 };
    default:
      return {};
  }
};

const isText = (value: unknown): value is string => typeof value === 'string' && value.trim().length > 0;
const pickText = (...values: unknown[]) => values.find(isText)?.trim();
const pickNumber = (...values: unknown[]) => values.find((value) => typeof value === 'number') as number | undefined;
const trimText = (value?: string, maxLength = 1600) => (value ? (value.length > maxLength ? `${value.slice(0, maxLength).trim()}…` : value) : undefined);

const sanitizeDraft = (draft: NovelDraft) =>
  Object.fromEntries(Object.entries(draft).filter(([, value]) => value !== undefined)) as NovelDraft;

const mergeMissing = (draft: NovelDraft, patch: NovelDraft) => {
  const merged = { ...draft };
  Object.entries(patch).forEach(([key, value]) => {
    const currentValue = merged[key];
    if (value !== undefined && (currentValue === undefined || currentValue === null || currentValue === '')) {
      merged[key] = value;
    }
  });
  return sanitizeDraft(merged);
};

const toContextText = (value: unknown, depth = 0): string => {
  const indent = '  '.repeat(depth);

  if (typeof value === 'string') {
    return value.trim();
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value
      .map((item, index) => {
        const text = toContextText(item, depth + 1);
        return text ? `${indent}${index + 1}. ${text}` : '';
      })
      .filter(Boolean)
      .join('\n');
  }
  if (value && typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, entryValue]) => {
        const text = toContextText(entryValue, depth + 1);
        return text ? `${indent}${key}：${text.includes('\n') ? `\n${text}` : text}` : '';
      })
      .filter(Boolean)
      .join('\n\n');
  }
  return '';
};

const loadWorkspace = (): NovelWorkspaceState => {
  if (typeof window === 'undefined') {
    return defaultWorkspace();
  }

  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return defaultWorkspace();
    }
    const parsed = JSON.parse(raw) as Partial<NovelWorkspaceState>;
    return {
      activeAction: ['outline', 'chapter', 'character', 'worldview', 'continue'].includes(String(parsed.activeAction))
        ? (parsed.activeAction as NovelActionKey)
        : 'outline',
      drafts: parsed.drafts ?? {},
      results: parsed.results ?? {},
    };
  } catch (error) {
    console.error('load novel workspace failed', error);
    return defaultWorkspace();
  }
};

const resolveRequestConfig = (action: NovelActionKey, values: Record<string, unknown>) => {
  switch (action) {
    case 'outline':
      return { url: API_PATHS.content.novelOutline, payload: toNovelOutlineRequestContract(values as NovelOutlineRequest) };
    case 'chapter':
      return { url: API_PATHS.content.novelChapter, payload: toNovelChapterRequestContract(values as unknown as NovelChapterRequest) };
    case 'character':
      return { url: API_PATHS.content.novelCharacter, payload: toNovelCharacterRequestContract(values as NovelCharacterRequest) };
    case 'worldview':
      return { url: API_PATHS.content.novelWorldview, payload: toNovelWorldviewRequestContract(values as NovelWorldviewRequest) };
    case 'continue':
      return { url: API_PATHS.content.novelContinue, payload: toNovelContinueRequestContract(values as unknown as NovelContinueRequest) };
    default:
      throw new Error(`Unsupported novel action: ${action}`);
  }
};

const getModuleText = (action: NovelActionKey, saved?: SavedNovelModuleResult) => {
  if (!saved) {
    return undefined;
  }
  switch (action) {
    case 'outline':
      return trimText(toContextText(saved.result.outline), 1400);
    case 'character':
      return trimText(toContextText(saved.result.character), 1200);
    case 'worldview':
      return trimText(toContextText(saved.result.worldview), 1400);
    case 'chapter':
      return trimText(pickText(saved.result.content), 2600);
    case 'continue':
      return trimText(pickText(saved.result.continuedContent), 2600);
    default:
      return undefined;
  }
};
const joinSections = (sections: Array<string | undefined>, maxLength = 1800) =>
  trimText(sections.filter(Boolean).join('\n\n'), maxLength);

const buildContext = (workspace: NovelWorkspaceState): NovelContextSnapshot => {
  const outlineDraft = workspace.drafts.outline ?? {};
  const chapterDraft = workspace.drafts.chapter ?? {};
  const characterDraft = workspace.drafts.character ?? {};
  const worldviewDraft = workspace.drafts.worldview ?? {};
  const continueDraft = workspace.drafts.continue ?? {};

  const outlineResult = workspace.results.outline;
  const chapterResult = workspace.results.chapter;
  const characterResult = workspace.results.character;
  const worldviewResult = workspace.results.worldview;
  const continueResult = workspace.results.continue;

  const latestNarrativeCandidates: Array<{ savedAt: string; text: string }> = [];
  const latestContinueText = pickText(continueResult?.result.continuedContent);
  const latestChapterText = pickText(chapterResult?.result.content);

  if (latestContinueText && continueResult) {
    latestNarrativeCandidates.push({ savedAt: continueResult.savedAt, text: latestContinueText });
  }

  if (latestChapterText && chapterResult) {
    latestNarrativeCandidates.push({ savedAt: chapterResult.savedAt, text: latestChapterText });
  }

  latestNarrativeCandidates.sort((left, right) => (left.savedAt < right.savedAt ? 1 : -1));
  const latestNarrative = latestNarrativeCandidates[0];

  return {
    title: pickText(outlineDraft.title, worldviewDraft.title, outlineResult?.result.title, worldviewResult?.result.title),
    genre: pickText(
      outlineDraft.genre,
      chapterDraft.genre,
      characterDraft.genre,
      worldviewDraft.genre,
      continueDraft.genre,
      outlineResult?.result.genre,
      chapterResult?.result.genre,
      characterResult?.result.genre,
      worldviewResult?.result.genre,
      continueResult?.result.genre
    ),
    style: pickText(outlineDraft.style, chapterDraft.style, continueDraft.style, outlineResult?.result.style, chapterResult?.result.style),
    theme: pickText(outlineDraft.theme, characterDraft.theme, worldviewDraft.theme),
    outlineText: getModuleText('outline', outlineResult),
    characterText: getModuleText('character', characterResult),
    worldviewText: getModuleText('worldview', worldviewResult),
    latestNarrativeText: trimText(latestNarrative?.text, 5000),
    nextChapterNumber:
      pickNumber(chapterDraft.chapterNumber, chapterResult?.result.chapterNumber) !== undefined
        ? Number(pickNumber(chapterDraft.chapterNumber, chapterResult?.result.chapterNumber)) + 1
        : 1,
  };
};

const buildRecommendedContext = (action: NovelActionKey, context: NovelContextSnapshot): RecommendedContext => {
  switch (action) {
    case 'outline':
      return {
        note: '可把人物、世界观和最近正文进度回填到大纲，形成从设定到正文再反哺策划的闭环。',
        patch: sanitizeDraft({
          title: context.title,
          genre: context.genre,
          style: context.style,
          theme: joinSections([
            context.theme ? `基础主题：${context.theme}` : undefined,
            context.characterText ? `已有角色：\n${context.characterText}` : undefined,
            context.worldviewText ? `已有世界观：\n${context.worldviewText}` : undefined,
            context.latestNarrativeText ? `现有正文进度：\n${trimText(context.latestNarrativeText, 900)}` : undefined,
          ]),
        }),
        sources: [
          ...(context.characterText ? (['character'] as NovelActionKey[]) : []),
          ...(context.worldviewText ? (['worldview'] as NovelActionKey[]) : []),
          ...(context.latestNarrativeText ? (['continue'] as NovelActionKey[]) : []),
        ],
      };
    case 'character':
      return {
        note: '角色设定优先承接大纲冲突，再结合世界规则收束人物目标、弱点和关系线。',
        patch: sanitizeDraft({
          genre: context.genre,
          theme: joinSections([
            context.theme ? `故事主题：${context.theme}` : undefined,
            context.outlineText ? `故事大纲：\n${context.outlineText}` : undefined,
            context.worldviewText ? `世界观约束：\n${trimText(context.worldviewText, 700)}` : undefined,
          ]),
        }),
        sources: [
          ...(context.outlineText ? (['outline'] as NovelActionKey[]) : []),
          ...(context.worldviewText ? (['worldview'] as NovelActionKey[]) : []),
        ],
      };
    case 'worldview':
      return {
        note: '世界观会吸收故事主线与关键人物需求，补足势力结构、规则边界和冲突土壤。',
        patch: sanitizeDraft({
          title: context.title,
          genre: context.genre,
          theme: joinSections([
            context.theme ? `故事主题：${context.theme}` : undefined,
            context.outlineText ? `故事大纲：\n${context.outlineText}` : undefined,
            context.characterText ? `关键角色：\n${trimText(context.characterText, 700)}` : undefined,
          ]),
        }),
        sources: [
          ...(context.outlineText ? (['outline'] as NovelActionKey[]) : []),
          ...(context.characterText ? (['character'] as NovelActionKey[]) : []),
        ],
      };
    case 'chapter':
      return {
        note: '章节正文默认承接大纲、角色和世界观，如果已有正文也会一起带入保持连续性。',
        patch: sanitizeDraft({
          chapterNumber: context.nextChapterNumber,
          genre: context.genre,
          style: context.style,
          outline: joinSections([
            context.outlineText ? `主线大纲：\n${context.outlineText}` : undefined,
            context.characterText ? `人物设定：\n${trimText(context.characterText, 700)}` : undefined,
            context.worldviewText ? `世界规则：\n${trimText(context.worldviewText, 700)}` : undefined,
            context.latestNarrativeText ? `最近正文进度：\n${trimText(context.latestNarrativeText, 900)}` : undefined,
          ], 2200),
        }),
        sources: [
          ...(context.outlineText ? (['outline'] as NovelActionKey[]) : []),
          ...(context.characterText ? (['character'] as NovelActionKey[]) : []),
          ...(context.worldviewText ? (['worldview'] as NovelActionKey[]) : []),
          ...(context.latestNarrativeText ? (['continue'] as NovelActionKey[]) : []),
        ],
      };
    case 'continue':
      return {
        note: '续写默认承接最近章节或续写结果，并保留题材与风格，让长篇创作可以持续推进。',
        patch: sanitizeDraft({
          previousContent: context.latestNarrativeText,
          genre: context.genre,
          style: context.style,
        }),
        sources: [
          ...(context.latestNarrativeText ? (['chapter'] as NovelActionKey[]) : []),
          ...(context.outlineText ? (['outline'] as NovelActionKey[]) : []),
        ],
      };
    default:
      return { note: '', patch: {}, sources: [] };
  }
};

export const NovelGenerator = () => {
  const initialWorkspace = useMemo(() => loadWorkspace(), []);
  const [form] = Form.useForm();
  const [workspace, setWorkspace] = useState<NovelWorkspaceState>(initialWorkspace);
  const { cancel, errorMessage, generationId, isStreaming, reset, result, runStream, streamingText } =
    useContentGenerationStream<Record<string, unknown>>();

  const activeAction = workspace.activeAction;
  const actionMeta = useMemo(() => novelActionMeta[activeAction], [activeAction]);
  const context = useMemo(() => buildContext(workspace), [workspace]);
  const recommended = useMemo(() => buildRecommendedContext(activeAction, context), [activeAction, context]);
  const savedModuleResult = workspace.results[activeAction] ?? null;
  const completedCount = useMemo(() => actionItems.filter((item) => workspace.results[item.key]?.result).length, [workspace.results]);
  const nextSuggestedAction = useMemo(
    () => actionItems.find((item) => !workspace.results[item.key]?.result)?.key ?? null,
    [workspace.results]
  );

  const syncActionState = useCallback((nextAction: NovelActionKey, nextWorkspace: NovelWorkspaceState) => {
    const currentDraft = nextWorkspace.drafts[nextAction] ?? {};
    const hydratedDraft = mergeMissing(currentDraft, buildRecommendedContext(nextAction, buildContext(nextWorkspace)).patch);
    const finalWorkspace =
      JSON.stringify(currentDraft) === JSON.stringify(hydratedDraft)
        ? nextWorkspace
        : {
            ...nextWorkspace,
            drafts: {
              ...nextWorkspace.drafts,
              [nextAction]: hydratedDraft,
            },
          };

    setWorkspace(finalWorkspace);
    form.resetFields();
    form.setFieldsValue({
      ...getDefaultValues(nextAction),
      ...(finalWorkspace.drafts[nextAction] ?? {}),
    });
    reset();
  }, [form, reset]);

  useEffect(() => {
    syncActionState(initialWorkspace.activeAction, initialWorkspace);
  }, [initialWorkspace, syncActionState]);

  useEffect(() => {
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(workspace));
    }
  }, [workspace]);

  const updateDraft = (action: NovelActionKey, draft: NovelDraft) => {
    setWorkspace((current) => ({
      ...current,
      drafts: {
        ...current.drafts,
        [action]: sanitizeDraft(draft),
      },
    }));
  };

  const handleActionChange = (nextAction: NovelActionKey) => {
    syncActionState(nextAction, { ...workspace, activeAction: nextAction });
  };

  const handleGenerate = async () => {
    try {
      const values = (await form.validateFields()) as Record<string, unknown>;
      updateDraft(activeAction, values);
      const { payload, url } = resolveRequestConfig(activeAction, values);

      message.open({ key: 'novel-generate', type: 'loading', content: `正在${actionMeta.label}...`, duration: 0 });
      const response = await runStream(url, payload);
      if (response.success) {
        if (response.data) {
          const responseGenerationId = pickText((response.data as Record<string, unknown>).generationId, generationId) ?? null;
          setWorkspace((current) => ({
            ...current,
            results: {
              ...current.results,
              [activeAction]: {
                generationId: responseGenerationId,
                result: response.data,
                savedAt: new Date().toISOString(),
              },
            },
          }));
        }

        const suggestion = actionItems.find((item) => !workspace.results[item.key]?.result && item.key !== activeAction)?.key;
        message.open({
          key: 'novel-generate',
          type: 'success',
          content: suggestion ? `${actionMeta.label}完成，建议继续${actionLabels[suggestion]}` : `${actionMeta.label}完成`,
        });
        return;
      }

      if (response.error === '已取消生成') {
        message.open({ key: 'novel-generate', type: 'warning', content: '已停止当前生成' });
        return;
      }

      message.open({ key: 'novel-generate', type: 'error', content: response.error || `${actionMeta.label}失败` });
    } catch (error: any) {
      if (error?.errorFields) {
        message.open({ key: 'novel-generate', type: 'warning', content: '请先补充必填信息' });
      } else {
        message.open({ key: 'novel-generate', type: 'error', content: `${actionMeta.label}失败，请稍后重试` });
        console.error('novel generation failed', error);
      }
    }
  };

  const handleStop = () => {
    cancel();
    message.open({ key: 'novel-generate', type: 'warning', content: '已停止当前生成' });
  };

  const handleReset = () => {
    const nextDraft = getDefaultValues(activeAction);
    form.resetFields();
    form.setFieldsValue(nextDraft);
    updateDraft(activeAction, nextDraft);
    reset();
  };
  const handleApplyRecommendedContext = () => {
    if (Object.keys(recommended.patch).length === 0) {
      message.open({ key: 'novel-context', type: 'info', content: '当前还没有可承接的上游内容，可独立填写后直接生成。' });
      return;
    }

    const currentValues = form.getFieldsValue(true) as NovelDraft;
    const nextDraft = mergeMissing(currentValues, recommended.patch);
    form.setFieldsValue({ ...getDefaultValues(activeAction), ...nextDraft });
    updateDraft(activeAction, nextDraft);
    message.open({
      key: 'novel-context',
      type: 'success',
      content:
        recommended.sources.length > 0 ? `已带入${recommended.sources.map((item) => actionLabels[item]).join('、')}的上下文` : '已带入推荐上下文',
    });
  };

  const handleClearWorkspace = () => {
    if (typeof window !== 'undefined') {
      window.localStorage.removeItem(STORAGE_KEY);
    }
    const nextWorkspace = defaultWorkspace();
    syncActionState(nextWorkspace.activeAction, nextWorkspace);
    message.open({ key: 'novel-workspace', type: 'success', content: '已清空本地创作工作台' });
  };

  const handleValuesChange = (_changedValues: NovelDraft, allValues: NovelDraft) => {
    updateDraft(activeAction, allValues);
  };

  const renderFields = () => {
    switch (activeAction) {
      case 'outline':
        return (
          <>
            <Form.Item label="小说标题" name="title">
              <Input placeholder="例如：云海长歌" maxLength={80} />
            </Form.Item>
            <Form.Item label="小说题材" name="genre">
              <Select placeholder="选择小说题材" options={novelGenreOptions} allowClear />
            </Form.Item>
            <Form.Item label="写作风格" name="style">
              <Select placeholder="选择写作风格" options={writingStyleOptions} allowClear />
            </Form.Item>
            <Form.Item label="主题设定" name="theme">
              <TextArea rows={6} placeholder="简述故事主题、核心冲突、主角目标或一句话提案" showCount maxLength={1600} />
            </Form.Item>
          </>
        );
      case 'chapter':
        return (
          <>
            <Form.Item label="章节编号" name="chapterNumber" rules={[{ required: true, message: '请输入章节编号' }]}>
              <InputNumber min={1} precision={0} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item label="章节标题" name="chapterTitle">
              <Input placeholder="例如：旧城异动" maxLength={80} />
            </Form.Item>
            <Form.Item label="章节大纲" name="outline">
              <TextArea rows={10} placeholder="输入本章节的主要情节、冲突和推进目标" showCount maxLength={2600} />
            </Form.Item>
            <Form.Item label="小说题材" name="genre">
              <Select placeholder="选择小说题材" options={novelGenreOptions} allowClear />
            </Form.Item>
            <Form.Item label="写作风格" name="style">
              <Select placeholder="选择写作风格" options={writingStyleOptions} allowClear />
            </Form.Item>
            <Form.Item label="目标字数" name="wordCount">
              <InputNumber min={500} max={10000} step={100} style={{ width: '100%' }} placeholder="建议 1500~3000" />
            </Form.Item>
          </>
        );
      case 'character':
        return (
          <>
            <Form.Item label="角色名称" name="characterName">
              <Input placeholder="例如：顾行舟" maxLength={60} />
            </Form.Item>
            <Form.Item label="小说题材" name="genre">
              <Select placeholder="选择小说题材" options={novelGenreOptions} allowClear />
            </Form.Item>
            <Form.Item label="角色定位 / 故事主题" name="theme">
              <TextArea rows={8} placeholder="说明角色在故事中的作用、成长方向、关系冲突等" showCount maxLength={1600} />
            </Form.Item>
          </>
        );
      case 'worldview':
        return (
          <>
            <Form.Item label="小说标题" name="title">
              <Input placeholder="例如：星渊纪元" maxLength={80} />
            </Form.Item>
            <Form.Item label="小说题材" name="genre">
              <Select placeholder="选择小说题材" options={novelGenreOptions} allowClear />
            </Form.Item>
            <Form.Item label="世界观需求" name="theme">
              <TextArea rows={10} placeholder="描述世界背景、权力体系、文明设定、资源规则或冲突来源" showCount maxLength={2000} />
            </Form.Item>
          </>
        );
      case 'continue':
        return (
          <>
            <Form.Item label="前文内容" name="previousContent" rules={[{ required: true, message: '请输入前文内容' }]}>
              <TextArea rows={12} placeholder="粘贴需要续写的正文内容，越完整越有助于保持语气与情节连贯" showCount maxLength={10000} />
            </Form.Item>
            <Form.Item label="小说题材" name="genre">
              <Select placeholder="选择小说题材" options={novelGenreOptions} allowClear />
            </Form.Item>
            <Form.Item label="写作风格" name="style">
              <Select placeholder="选择写作风格" options={writingStyleOptions} allowClear />
            </Form.Item>
            <Form.Item label="续写字数" name="wordCount">
              <InputNumber min={500} max={5000} step={100} style={{ width: '100%' }} placeholder="建议 800~1500" />
            </Form.Item>
          </>
        );
      default:
        return null;
    }
  };

  const displayedResult = result ?? savedModuleResult?.result ?? null;
  const displayedGenerationId = generationId ?? savedModuleResult?.generationId ?? null;

  return (
    <div className="novel-generator">
      <Card className="novel-generator__tabs-card" bordered={false}>
        <Tabs
          activeKey={activeAction}
          onChange={(key) => handleActionChange(key as NovelActionKey)}
          items={actionItems.map((item, index) => ({
            key: item.key,
            label: (
              <Space size="small">
                {item.icon}
                <span>{`${index + 1}. ${item.label}`}</span>
              </Space>
            ),
          }))}
        />
      </Card>

      <Row gutter={[20, 20]} className="novel-generator__layout">
        <Col xs={24} xl={11}>
          <Card className="novel-generator__form-card" title={actionMeta.label} bordered={false}>
            <Space direction="vertical" size="middle" style={{ width: '100%' }}>
              <Alert type="info" showIcon message={actionMeta.description} description={actionMeta.hint} />
              {errorMessage ? <Alert type="error" showIcon message={errorMessage} /> : null}

              <div className="novel-generator__workspace">
                <Space direction="vertical" size="small" style={{ width: '100%' }}>
                  <div className="novel-generator__workspace-head">
                    <div>
                      <Title level={5} className="novel-generator__workspace-title">创作闭环工作台</Title>
                      <Text type="secondary">草稿与生成结果会自动保存在当前浏览器，刷新页面后仍可继续创作。</Text>
                    </div>
                    <Button size="small" onClick={handleClearWorkspace} disabled={isStreaming}>清空本地记录</Button>
                  </div>

                  <Paragraph className="novel-generator__workspace-note">{actionFlowHints[activeAction]}</Paragraph>

                  <div className="novel-generator__status-tags">
                    {actionItems.map((item) => (
                      <Tag
                        key={item.key}
                        color={item.key === activeAction ? 'processing' : workspace.results[item.key]?.result ? 'success' : 'default'}
                      >
                        {workspace.results[item.key]?.result ? '已接入' : '待补充'} · {actionLabels[item.key]}
                      </Tag>
                    ))}
                  </div>

                  <Text type="secondary">
                    当前模块可承接：{recommended.sources.length > 0 ? recommended.sources.map((item) => actionLabels[item]).join('、') : '暂无上游内容，支持独立使用'}
                  </Text>
                  <Text type="secondary">{recommended.note}</Text>

                  <Space wrap>
                    <Button onClick={handleApplyRecommendedContext} disabled={isStreaming}>带入推荐上下文</Button>
                    {nextSuggestedAction && nextSuggestedAction !== activeAction ? (
                      <Button type="link" onClick={() => handleActionChange(nextSuggestedAction)}>前往建议下一步：{actionLabels[nextSuggestedAction]}</Button>
                    ) : null}
                    <Tag color="blue">已保存模块：{completedCount}/5</Tag>
                  </Space>
                </Space>
              </div>

              <Paragraph className="novel-generator__guide">
                <Text strong>填写建议：</Text>
                当前模块既可以独立使用，也可以一键承接其他模块内容；建议先搭故事骨架，再逐步补人设、世界观、章节和续写。
              </Paragraph>

              <Form form={form} layout="vertical" className="novel-generator__form" onValuesChange={handleValuesChange}>
                {renderFields()}
                <Form.Item className="novel-generator__actions">
                  <Space size="middle" wrap>
                    <Button type="primary" size="large" loading={isStreaming} onClick={handleGenerate}>开始生成</Button>
                    <Button size="large" onClick={handleReset} disabled={isStreaming}>重置当前表单</Button>
                    {isStreaming ? <Button danger size="large" onClick={handleStop}>停止生成</Button> : null}
                  </Space>
                </Form.Item>
              </Form>
            </Space>
          </Card>
        </Col>

        <Col xs={24} xl={13}>
          <ContentResultPanel
            title={`${actionMeta.label}结果`}
            result={displayedResult}
            generationId={displayedGenerationId}
            isStreaming={isStreaming}
            streamingContent={streamingText}
            emptyDescription="填写左侧信息并提交后，这里会实时显示生成内容；完成后结果会自动保存在本地，刷新页面也能继续查看。"
          />
        </Col>
      </Row>
    </div>
  );
};


