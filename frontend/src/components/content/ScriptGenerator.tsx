import { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Card, Col, Form, Input, InputNumber, Row, Select, Space, Tabs, Typography, message } from 'antd';
import { CheckCircleOutlined, CommentOutlined, FileTextOutlined, PictureOutlined, VideoCameraOutlined } from '@ant-design/icons';

import {
  toScriptCompleteRequestContract,
  toScriptDialogueRequestContract,
  toScriptOutlineRequestContract,
  toScriptSceneRequestContract,
  toScriptStoryboardRequestContract,
  type ScriptCompleteRequest,
  type ScriptDialogueRequest,
  type ScriptOutlineRequest,
  type ScriptSceneRequest,
  type ScriptStoryboardRequest,
} from '@/adapters/contentAdapter';
import { ContentResultPanel } from '@/components/content/ContentResultPanel';
import { API_PATHS } from '@/constants/api';
import { scriptActionMeta, scriptStyleOptions, scriptTypeOptions } from '@/constants/contentOptions';
import { useContentGenerationStream } from '@/hooks/useContentGenerationStream';

import './ScriptGenerator.css';

const { TextArea } = Input;
const { Paragraph, Text } = Typography;

type ScriptActionKey = 'outline' | 'scene' | 'dialogue' | 'storyboard' | 'complete';

const actionItems: { key: ScriptActionKey; label: string; icon: JSX.Element }[] = [
  { key: 'outline', label: '脚本大纲', icon: <FileTextOutlined /> },
  { key: 'scene', label: '场景生成', icon: <VideoCameraOutlined /> },
  { key: 'dialogue', label: '对白生成', icon: <CommentOutlined /> },
  { key: 'storyboard', label: '分镜生成', icon: <PictureOutlined /> },
  { key: 'complete', label: '完整脚本', icon: <CheckCircleOutlined /> },
];

const getDefaultValues = (action: ScriptActionKey) => {
  switch (action) {
    case 'scene':
      return { sceneNumber: 1 };
    case 'outline':
    case 'complete':
      return { duration: 3 };
    default:
      return {};
  }
};

const resolveRequestConfig = (action: ScriptActionKey, values: Record<string, unknown>) => {
  switch (action) {
    case 'outline':
      return {
        url: API_PATHS.content.scriptOutline,
        payload: toScriptOutlineRequestContract(values as unknown as ScriptOutlineRequest),
      };
    case 'scene':
      return {
        url: API_PATHS.content.scriptScene,
        payload: toScriptSceneRequestContract(values as unknown as ScriptSceneRequest),
      };
    case 'dialogue':
      return {
        url: API_PATHS.content.scriptDialogue,
        payload: toScriptDialogueRequestContract(values as unknown as ScriptDialogueRequest),
      };
    case 'storyboard':
      return {
        url: API_PATHS.content.scriptStoryboard,
        payload: toScriptStoryboardRequestContract(values as unknown as ScriptStoryboardRequest),
      };
    case 'complete':
      return {
        url: API_PATHS.content.scriptComplete,
        payload: toScriptCompleteRequestContract(values as unknown as ScriptCompleteRequest),
      };
    default:
      throw new Error(`Unsupported script action: ${action}`);
  }
};

export const ScriptGenerator = () => {
  const [form] = Form.useForm();
  const [activeAction, setActiveAction] = useState<ScriptActionKey>('outline');
  const { cancel, errorMessage, generationId, isStreaming, reset, result, runStream, streamingText } =
    useContentGenerationStream<Record<string, unknown>>();

  const actionMeta = useMemo(() => scriptActionMeta[activeAction], [activeAction]);

  useEffect(() => {
    form.resetFields();
    form.setFieldsValue(getDefaultValues(activeAction));
    reset();
  }, [activeAction, form, reset]);

  const handleGenerate = async () => {
    try {
      const values = (await form.validateFields()) as Record<string, unknown>;
      const { payload, url } = resolveRequestConfig(activeAction, values);

      message.open({
        key: 'script-generate',
        type: 'loading',
        content: `正在${actionMeta.label}...`,
        duration: 0,
      });

      const response = await runStream(url, payload);
      if (response.success) {
        message.open({ key: 'script-generate', type: 'success', content: `${actionMeta.label}完成` });
        return;
      }

      if (response.error === '已取消生成') {
        message.open({ key: 'script-generate', type: 'warning', content: '已停止当前生成' });
        return;
      }

      message.open({ key: 'script-generate', type: 'error', content: response.error || `${actionMeta.label}失败` });
    } catch (error: any) {
      if (error?.errorFields) {
        message.open({ key: 'script-generate', type: 'warning', content: '请先补充必填信息' });
      } else {
        message.open({ key: 'script-generate', type: 'error', content: `${actionMeta.label}失败，请稍后重试` });
        console.error('script generation failed', error);
      }
    }
  };

  const handleStop = () => {
    cancel();
    message.open({ key: 'script-generate', type: 'warning', content: '已停止当前生成' });
  };

  const handleReset = () => {
    form.resetFields();
    form.setFieldsValue(getDefaultValues(activeAction));
    reset();
  };

  const commonTypeField = (
    <Form.Item label="脚本类型" name="scriptType" rules={[{ required: true, message: '请选择脚本类型' }]}>
      <Select placeholder="选择脚本类型" options={scriptTypeOptions} />
    </Form.Item>
  );

  const renderFields = () => {
    switch (activeAction) {
      case 'outline':
        return (
          <>
            {commonTypeField}
            <Form.Item label="脚本标题" name="title">
              <Input placeholder="例如：三分钟产品反转短片" maxLength={100} />
            </Form.Item>
            <Form.Item label="脚本风格" name="style">
              <Select placeholder="选择脚本风格" options={scriptStyleOptions} allowClear />
            </Form.Item>
            <Form.Item label="时长（分钟）" name="duration">
              <InputNumber min={1} max={300} precision={0} style={{ width: '100%' }} placeholder="例如：3" />
            </Form.Item>
            <Form.Item label="目标受众" name="targetAudience">
              <Input placeholder="例如：18-30 岁职场用户" maxLength={80} />
            </Form.Item>
            <Form.Item label="主题 / 核心卖点" name="theme">
              <TextArea rows={7} placeholder="描述剧情方向、品牌信息、冲突点或传播目标" showCount maxLength={1600} />
            </Form.Item>
          </>
        );
      case 'scene':
        return (
          <>
            {commonTypeField}
            <Form.Item label="场次编号" name="sceneNumber">
              <InputNumber min={1} precision={0} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item label="场景描述" name="sceneDescription">
              <TextArea rows={7} placeholder="描述这一场的环境、冲突、动作推进和情绪目标" showCount maxLength={1800} />
            </Form.Item>
            <Form.Item label="角色列表" name="characters">
              <Input placeholder="多个角色用逗号分隔，例如：阿周,老秦" maxLength={200} />
            </Form.Item>
            <Form.Item label="脚本风格" name="style">
              <Select placeholder="选择脚本风格" options={scriptStyleOptions} allowClear />
            </Form.Item>
            <Form.Item label="脚本大纲" name="outline">
              <TextArea rows={5} placeholder="可补充整体剧情脉络，帮助模型保持上下文一致" showCount maxLength={1200} />
            </Form.Item>
          </>
        );
      case 'dialogue':
        return (
          <>
            {commonTypeField}
            <Form.Item label="对白角色" name="characters">
              <Input placeholder="多个角色用逗号分隔，例如：姜禾,韩越" maxLength={200} />
            </Form.Item>
            <Form.Item label="场景描述" name="sceneDescription">
              <TextArea rows={7} placeholder="描述对白发生的场景、情绪和冲突目标" showCount maxLength={1600} />
            </Form.Item>
            <Form.Item label="脚本风格" name="style">
              <Select placeholder="选择脚本风格" options={scriptStyleOptions} allowClear />
            </Form.Item>
          </>
        );
      case 'storyboard':
        return (
          <>
            {commonTypeField}
            <Form.Item label="场景描述" name="sceneDescription">
              <TextArea rows={8} placeholder="详细描述需要拆成分镜的内容，包括动作、主体、情绪和镜头重点" showCount maxLength={2000} />
            </Form.Item>
            <Form.Item label="脚本风格" name="style">
              <Select placeholder="选择脚本风格" options={scriptStyleOptions} allowClear />
            </Form.Item>
          </>
        );
      case 'complete':
        return (
          <>
            {commonTypeField}
            <Form.Item label="脚本标题" name="title">
              <Input placeholder="例如：云中列车预告片" maxLength={100} />
            </Form.Item>
            <Form.Item label="脚本风格" name="style">
              <Select placeholder="选择脚本风格" options={scriptStyleOptions} allowClear />
            </Form.Item>
            <Form.Item label="时长（分钟）" name="duration">
              <InputNumber min={1} max={300} precision={0} style={{ width: '100%' }} placeholder="例如：15" />
            </Form.Item>
            <Form.Item label="目标受众" name="targetAudience">
              <Input placeholder="例如：亲子家庭用户" maxLength={80} />
            </Form.Item>
            <Form.Item label="主题 / 剧情方向" name="theme">
              <TextArea rows={8} placeholder="输入项目主题、剧情概述、传播目标或角色关系" showCount maxLength={2000} />
            </Form.Item>
          </>
        );
      default:
        return null;
    }
  };

  return (
    <div className="script-generator">
      <Card className="script-generator__tabs-card" bordered={false}>
        <Tabs
          activeKey={activeAction}
          onChange={(key) => setActiveAction(key as ScriptActionKey)}
          items={actionItems.map((item) => ({
            key: item.key,
            label: (
              <Space size="small">
                {item.icon}
                <span>{item.label}</span>
              </Space>
            ),
          }))}
        />
      </Card>

      <Row gutter={[20, 20]} className="script-generator__layout">
        <Col xs={24} xl={11}>
          <Card className="script-generator__form-card" title={actionMeta.label} bordered={false}>
            <Space direction="vertical" size="middle" style={{ width: '100%' }}>
              <Alert type="info" showIcon message={actionMeta.description} description={actionMeta.hint} />

              {errorMessage ? <Alert type="error" showIcon message={errorMessage} /> : null}

              <Paragraph className="script-generator__guide">
                <Text strong>填写建议：</Text>
                时长、受众和剧情方向会直接影响脚本结构，建议尽量补充完整。
              </Paragraph>

              <Form form={form} layout="vertical" className="script-generator__form">
                {renderFields()}

                <Form.Item className="script-generator__actions">
                  <Space size="middle" wrap>
                    <Button type="primary" size="large" loading={isStreaming} onClick={handleGenerate}>
                      开始生成
                    </Button>
                    <Button size="large" onClick={handleReset} disabled={isStreaming}>
                      重置表单
                    </Button>
                    {isStreaming ? (
                      <Button danger size="large" onClick={handleStop}>
                        停止生成
                      </Button>
                    ) : null}
                  </Space>
                </Form.Item>
              </Form>
            </Space>
          </Card>
        </Col>

        <Col xs={24} xl={13}>
          <ContentResultPanel
            title={`${actionMeta.label}结果`}
            result={result}
            generationId={generationId}
            isStreaming={isStreaming}
            streamingContent={streamingText}
            emptyDescription="提交生成请求后，右侧会实时显示生成内容、结构化结果和完整 JSON。"
          />
        </Col>
      </Row>
    </div>
  );
};
