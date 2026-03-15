export interface ContentOption {
  label: string;
  value: string;
}

export interface ActionMeta {
  label: string;
  description: string;
  hint: string;
}

export const novelGenreOptions: ContentOption[] = [
  { value: 'fantasy', label: '玄幻' },
  { value: 'urban', label: '都市' },
  { value: 'romance', label: '言情' },
  { value: 'scifi', label: '科幻' },
  { value: 'wuxia', label: '武侠' },
  { value: 'xianxia', label: '仙侠' },
  { value: 'history', label: '历史' },
  { value: 'military', label: '军事' },
  { value: 'mystery', label: '悬疑' },
  { value: 'horror', label: '惊悚' },
  { value: 'game', label: '游戏' },
  { value: 'sports', label: '体育' },
  { value: 'fanfic', label: '同人' },
];

export const writingStyleOptions: ContentOption[] = [
  { value: 'descriptive', label: '细腻描写' },
  { value: 'concise', label: '简洁明快' },
  { value: 'humorous', label: '轻松幽默' },
  { value: 'serious', label: '严肃克制' },
  { value: 'poetic', label: '诗意表达' },
  { value: 'suspenseful', label: '悬念推进' },
];

export const scriptTypeOptions: ContentOption[] = [
  { value: 'movie', label: '电影' },
  { value: 'tv_series', label: '剧集' },
  { value: 'short_video', label: '短视频' },
  { value: 'advertisement', label: '广告' },
  { value: 'stage_play', label: '舞台剧' },
  { value: 'animation', label: '动画' },
  { value: 'documentary', label: '纪录片' },
  { value: 'variety_show', label: '综艺' },
];

export const scriptStyleOptions: ContentOption[] = [
  { value: 'comedy', label: '喜剧' },
  { value: 'drama', label: '剧情' },
  { value: 'action', label: '动作' },
  { value: 'romance', label: '爱情' },
  { value: 'thriller', label: '惊悚' },
  { value: 'scifi', label: '科幻' },
  { value: 'fantasy', label: '奇幻' },
  { value: 'documentary', label: '纪实' },
];

export const contentStyleOptions: ContentOption[] = [
  { value: 'formal', label: '正式' },
  { value: 'casual', label: '轻松' },
  { value: 'professional', label: '专业' },
  { value: 'friendly', label: '亲和' },
  { value: 'persuasive', label: '说服型' },
  { value: 'informative', label: '信息型' },
  { value: 'creative', label: '创意型' },
  { value: 'academic', label: '学术型' },
];

export const novelActionMeta: Record<string, ActionMeta> = {
  outline: {
    label: '生成小说大纲',
    description: '基于题材、风格和主题快速搭建故事骨架。',
    hint: '适合立项阶段快速明确主线冲突、世界规则和人物成长线。',
  },
  chapter: {
    label: '生成章节正文',
    description: '根据章节编号、标题和大纲扩展完整正文。',
    hint: '补充章节标题和情节摘要后，结果会更连贯、更贴近预期。',
  },
  character: {
    label: '生成角色设定',
    description: '输出角色背景、性格标签、目标动机和关系线。',
    hint: '给出故事主题或角色定位后，更容易得到可直接落稿的人设。',
  },
  worldview: {
    label: '生成世界观',
    description: '补齐世界规则、势力关系和文明背景。',
    hint: '适合长篇创作的前期设定，也适合中途扩展世界细节。',
  },
  continue: {
    label: '续写小说',
    description: '根据前文内容延展下一段剧情和叙事节奏。',
    hint: '前文越完整，续写的语气、人物状态和情节衔接越稳定。',
  },
};

export const scriptActionMeta: Record<string, ActionMeta> = {
  outline: {
    label: '生成脚本大纲',
    description: '快速整理脚本结构、节奏设计和传播目标。',
    hint: '适合短视频、广告、剧集等项目的策划阶段使用。',
  },
  scene: {
    label: '生成场景',
    description: '生成单场戏的场景安排、动作推进和镜头信息。',
    hint: '补充场次、人物和大纲后，场景衔接质量会更高。',
  },
  dialogue: {
    label: '生成对白',
    description: '围绕指定场景和角色输出可直接改写的对白。',
    hint: '适合推进情绪冲突、拉开角色差异和表达重点信息。',
  },
  storyboard: {
    label: '生成分镜',
    description: '把场景描述转成更具执行性的分镜说明。',
    hint: '适合导演、剪辑或拍摄团队快速对齐画面语言。',
  },
  complete: {
    label: '生成完整脚本',
    description: '基于主题、时长和受众输出完整脚本草案。',
    hint: '适合先拿到可讨论的第一版，再继续人工精修。',
  },
};

export const optimizationActionMeta: Record<string, ActionMeta> = {
  polish: {
    label: '润色表达',
    description: '提升文字流畅度、节奏感和可读性。',
    hint: '适合已有内容只需要优化表达，不需要大改结构时使用。',
  },
  rewrite: {
    label: '改写内容',
    description: '在保留原意的前提下重组结构和措辞。',
    hint: '适合做多平台版本、多受众版本的内容改写。',
  },
  expand: {
    label: '扩写内容',
    description: '在原文基础上补充细节、案例或说明。',
    hint: '建议填写目标字数，方便控制输出规模。',
  },
  summarize: {
    label: '压缩摘要',
    description: '提炼重点信息，输出更简洁的版本。',
    hint: '适合会议纪要、长文摘要和口播压缩等场景。',
  },
  style_transfer: {
    label: '风格迁移',
    description: '把内容转换成指定语气或表达风格。',
    hint: '适合同一份内容适配品牌风格、专业风格或社媒风格。',
  },
  grammar_check: {
    label: '语法检查',
    description: '检查语法、错别字和表达问题。',
    hint: '适合发布前做一轮快速质检。',
  },
  seo_optimize: {
    label: 'SEO 优化',
    description: '围绕关键词增强搜索友好度和可发现性。',
    hint: '提供关键词后，结果会更贴近搜索优化场景。',
  },
};
