/**
 * 脚本生成器组件
 * 提供脚本大纲、场景、对白、分镜、完整脚本等功能
 */

import React, { useState } from 'react';
import { Form, Input, Select, Button, Card, message, Spin, InputNumber, Tabs } from 'antd';
import { FileTextOutlined, VideoCameraOutlined, CommentOutlined, PictureOutlined, CheckCircleOutlined } from '@ant-design/icons';
import {
  generateScriptOutline,
  generateScriptScene,
  generateScriptDialogue,
  generateScriptStoryboard,
  generateCompleteScript,
  SCRIPT_TYPES,
  SCRIPT_STYLES
} from '@/services/contentService';
import './ScriptGenerator.css';

const { TextArea } = Input;
const { Option } = Select;
const { TabPane } = Tabs;

export const ScriptGenerator: React.FC = () => {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [activeAction, setActiveAction] = useState<string>('outline');

  const handleGenerate = async () => {
    try {
      const values = await form.validateFields();
      setLoading(true);
      setResult(null);

      let response;
      switch (activeAction) {
        case 'outline':
          response = await generateScriptOutline(values);
          break;
        case 'scene':
          response = await generateScriptScene(values);
          break;
        case 'dialogue':
          response = await generateScriptDialogue(values);
          break;
        case 'storyboard':
          response = await generateScriptStoryboard(values);
          break;
        case 'complete':
          response = await generateCompleteScript(values);
          break;
        default:
          message.error('未知操作类型');
          return;
      }

      if (response.success) {
        setResult(response.data ?? null);
        message.success('生成成功！');
      } else {
        message.error(response.error || '生成失败');
      }
    } catch (error: any) {
      if (error.errorFields) {
        message.error('请填写必填字段');
      } else {
        message.error('生成失败，请稍后重试');
        console.error('生成失败:', error);
      }
    } finally {
      setLoading(false);
    }
  };

  const handleClear = () => {
    form.resetFields();
    setResult(null);
  };

  const handleCopyResult = () => {
    if (result) {
      const text = JSON.stringify(result, null, 2);
      navigator.clipboard.writeText(text);
      message.success('已复制到剪贴板');
    }
  };

  const renderOutlineForm = () => (
    <>
      <Form.Item
        label="脚本类型"
        name="scriptType"
        rules={[{ required: true, message: '请选择脚本类型' }]}
      >
        <Select placeholder="请选择脚本类型">
          {Object.entries(SCRIPT_TYPES).map(([key, value]) => (
            <Option key={key} value={key}>{value}</Option>
          ))}
        </Select>
      </Form.Item>

      <Form.Item
        label="脚本标题"
        name="title"
        rules={[{ required: false }]}
      >
        <Input placeholder="请输入脚本标题（可选）" />
      </Form.Item>

      <Form.Item
        label="脚本风格"
        name="style"
        rules={[{ required: false }]}
      >
        <Select placeholder="请选择脚本风格（可选）">
          {Object.entries(SCRIPT_STYLES).map(([key, value]) => (
            <Option key={key} value={key}>{value}</Option>
          ))}
        </Select>
      </Form.Item>

      <Form.Item
        label="时长（分钟）"
        name="duration"
        rules={[{ required: false }]}
      >
        <InputNumber min={1} max={300} style={{ width: '100%' }} placeholder="脚本时长" />
      </Form.Item>

      <Form.Item
        label="目标受众"
        name="targetAudience"
        rules={[{ required: false }]}
      >
        <Input placeholder="请输入目标受众（可选）" />
      </Form.Item>

      <Form.Item
        label="脚本主题"
        name="theme"
        rules={[{ required: false }]}
      >
        <TextArea rows={4} placeholder="请输入脚本主题或简介（可选）" />
      </Form.Item>
    </>
  );

  const renderSceneForm = () => (
    <>
      <Form.Item
        label="脚本类型"
        name="scriptType"
        rules={[{ required: true, message: '请选择脚本类型' }]}
      >
        <Select placeholder="请选择脚本类型">
          {Object.entries(SCRIPT_TYPES).map(([key, value]) => (
            <Option key={key} value={key}>{value}</Option>
          ))}
        </Select>
      </Form.Item>

      <Form.Item
        label="场景编号"
        name="sceneNumber"
        rules={[{ required: false }]}
        initialValue={1}
      >
        <InputNumber min={1} style={{ width: '100%' }} placeholder="场景编号" />
      </Form.Item>

      <Form.Item
        label="场景描述"
        name="sceneDescription"
        rules={[{ required: false }]}
      >
        <TextArea rows={4} placeholder="请描述场景（可选）" />
      </Form.Item>

      <Form.Item
        label="出场角色"
        name="characters"
        rules={[{ required: false }]}
      >
        <Input placeholder="请输入出场角色，用逗号分隔（可选）" />
      </Form.Item>

      <Form.Item
        label="脚本风格"
        name="style"
        rules={[{ required: false }]}
      >
        <Select placeholder="请选择脚本风格（可选）">
          {Object.entries(SCRIPT_STYLES).map(([key, value]) => (
            <Option key={key} value={key}>{value}</Option>
          ))}
        </Select>
      </Form.Item>

      <Form.Item
        label="脚本大纲"
        name="outline"
        rules={[{ required: false }]}
      >
        <TextArea rows={4} placeholder="请输入脚本大纲（可选）" />
      </Form.Item>
    </>
  );

  const renderDialogueForm = () => (
    <>
      <Form.Item
        label="脚本类型"
        name="scriptType"
        rules={[{ required: true, message: '请选择脚本类型' }]}
      >
        <Select placeholder="请选择脚本类型">
          {Object.entries(SCRIPT_TYPES).map(([key, value]) => (
            <Option key={key} value={key}>{value}</Option>
          ))}
        </Select>
      </Form.Item>

      <Form.Item
        label="对话角色"
        name="characters"
        rules={[{ required: false }]}
      >
        <Input placeholder="请输入对话角色，用逗号分隔（可选）" />
      </Form.Item>

      <Form.Item
        label="场景描述"
        name="sceneDescription"
        rules={[{ required: false }]}
      >
        <TextArea rows={4} placeholder="请描述对话场景（可选）" />
      </Form.Item>

      <Form.Item
        label="脚本风格"
        name="style"
        rules={[{ required: false }]}
      >
        <Select placeholder="请选择脚本风格（可选）">
          {Object.entries(SCRIPT_STYLES).map(([key, value]) => (
            <Option key={key} value={key}>{value}</Option>
          ))}
        </Select>
      </Form.Item>
    </>
  );

  const renderStoryboardForm = () => (
    <>
      <Form.Item
        label="脚本类型"
        name="scriptType"
        rules={[{ required: true, message: '请选择脚本类型' }]}
      >
        <Select placeholder="请选择脚本类型">
          {Object.entries(SCRIPT_TYPES).map(([key, value]) => (
            <Option key={key} value={key}>{value}</Option>
          ))}
        </Select>
      </Form.Item>

      <Form.Item
        label="场景描述"
        name="sceneDescription"
        rules={[{ required: false }]}
      >
        <TextArea rows={6} placeholder="请详细描述需要分镜的场景（可选）" />
      </Form.Item>

      <Form.Item
        label="脚本风格"
        name="style"
        rules={[{ required: false }]}
      >
        <Select placeholder="请选择脚本风格（可选）">
          {Object.entries(SCRIPT_STYLES).map(([key, value]) => (
            <Option key={key} value={key}>{value}</Option>
          ))}
        </Select>
      </Form.Item>
    </>
  );

  const renderCompleteForm = () => (
    <>
      <Form.Item
        label="脚本类型"
        name="scriptType"
        rules={[{ required: true, message: '请选择脚本类型' }]}
      >
        <Select placeholder="请选择脚本类型">
          {Object.entries(SCRIPT_TYPES).map(([key, value]) => (
            <Option key={key} value={key}>{value}</Option>
          ))}
        </Select>
      </Form.Item>

      <Form.Item
        label="脚本标题"
        name="title"
        rules={[{ required: false }]}
      >
        <Input placeholder="请输入脚本标题（可选）" />
      </Form.Item>

      <Form.Item
        label="脚本风格"
        name="style"
        rules={[{ required: false }]}
      >
        <Select placeholder="请选择脚本风格（可选）">
          {Object.entries(SCRIPT_STYLES).map(([key, value]) => (
            <Option key={key} value={key}>{value}</Option>
          ))}
        </Select>
      </Form.Item>

      <Form.Item
        label="时长（分钟）"
        name="duration"
        rules={[{ required: false }]}
      >
        <InputNumber min={1} max={300} style={{ width: '100%' }} placeholder="脚本时长" />
      </Form.Item>

      <Form.Item
        label="目标受众"
        name="targetAudience"
        rules={[{ required: false }]}
      >
        <Input placeholder="请输入目标受众（可选）" />
      </Form.Item>

      <Form.Item
        label="脚本主题"
        name="theme"
        rules={[{ required: false }]}
      >
        <TextArea rows={4} placeholder="请输入脚本主题或简介（可选）" />
      </Form.Item>
    </>
  );

  const renderForm = () => {
    switch (activeAction) {
      case 'outline':
        return renderOutlineForm();
      case 'scene':
        return renderSceneForm();
      case 'dialogue':
        return renderDialogueForm();
      case 'storyboard':
        return renderStoryboardForm();
      case 'complete':
        return renderCompleteForm();
      default:
        return null;
    }
  };

  const renderResult = () => {
    if (!result) return null;

    return (
      <Card
        title="生成结果"
        className="result-card"
        extra={
          <Button onClick={handleCopyResult} size="small">
            复制结果
          </Button>
        }
      >
        <pre className="result-content">
          {JSON.stringify(result, null, 2)}
        </pre>
      </Card>
    );
  };

  return (
    <div className="script-generator">
      <Tabs activeKey={activeAction} onChange={(key) => { setActiveAction(key); form.resetFields(); setResult(null); }}>
        <TabPane
          tab={<span><FileTextOutlined /> 生成大纲</span>}
          key="outline"
        />
        <TabPane
          tab={<span><VideoCameraOutlined /> 生成场景</span>}
          key="scene"
        />
        <TabPane
          tab={<span><CommentOutlined /> 生成对白</span>}
          key="dialogue"
        />
        <TabPane
          tab={<span><PictureOutlined /> 生成分镜</span>}
          key="storyboard"
        />
        <TabPane
          tab={<span><CheckCircleOutlined /> 完整脚本</span>}
          key="complete"
        />
      </Tabs>

      <Card className="form-card">
        <Spin spinning={loading} tip="正在生成中，请稍候...">
          <Form form={form} layout="vertical">
            {renderForm()}

            <Form.Item>
              <Button
                type="primary"
                onClick={handleGenerate}
                loading={loading}
                size="large"
                block
              >
                开始生成
              </Button>
              <Button
                onClick={handleClear}
                size="large"
                block
                style={{ marginTop: 8 }}
              >
                清空
              </Button>
            </Form.Item>
          </Form>
        </Spin>
      </Card>

      {renderResult()}
    </div>
  );
};
