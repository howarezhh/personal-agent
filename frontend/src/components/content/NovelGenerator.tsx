/**
 * 小说生成器组件
 * 提供小说大纲、章节、角色、世界观、续写等功能
 */

import React, { useState } from 'react';
import { Form, Input, Select, Button, Card, message, Spin, InputNumber, Tabs } from 'antd';
import { BookOutlined, FileTextOutlined, UserOutlined, GlobalOutlined, EditOutlined } from '@ant-design/icons';
import {
  generateNovelOutline,
  generateNovelChapter,
  generateNovelCharacter,
  generateNovelWorldview,
  continueNovel,
  NOVEL_GENRES,
  WRITING_STYLES
} from '@/services/contentService';
import './NovelGenerator.css';

const { TextArea } = Input;
const { Option } = Select;
const { TabPane } = Tabs;

export const NovelGenerator: React.FC = () => {
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
          response = await generateNovelOutline(values);
          break;
        case 'chapter':
          response = await generateNovelChapter(values);
          break;
        case 'character':
          response = await generateNovelCharacter(values);
          break;
        case 'worldview':
          response = await generateNovelWorldview(values);
          break;
        case 'continue':
          response = await continueNovel(values);
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
        label="小说标题"
        name="title"
        rules={[{ required: false, message: '请输入小说标题' }]}
      >
        <Input placeholder="请输入小说标题（可选）" />
      </Form.Item>

      <Form.Item
        label="小说类型"
        name="genre"
        rules={[{ required: false }]}
      >
        <Select placeholder="请选择小说类型（可选）">
          {Object.entries(NOVEL_GENRES).map(([key, value]) => (
            <Option key={key} value={key}>{value}</Option>
          ))}
        </Select>
      </Form.Item>

      <Form.Item
        label="写作风格"
        name="style"
        rules={[{ required: false }]}
      >
        <Select placeholder="请选择写作风格（可选）">
          {Object.entries(WRITING_STYLES).map(([key, value]) => (
            <Option key={key} value={key}>{value}</Option>
          ))}
        </Select>
      </Form.Item>

      <Form.Item
        label="主题简介"
        name="theme"
        rules={[{ required: false }]}
      >
        <TextArea rows={4} placeholder="请输入小说主题或简介（可选）" />
      </Form.Item>
    </>
  );

  const renderChapterForm = () => (
    <>
      <Form.Item
        label="章节编号"
        name="chapterNumber"
        rules={[{ required: true, message: '请输入章节编号' }]}
        initialValue={1}
      >
        <InputNumber min={1} style={{ width: '100%' }} placeholder="请输入章节编号" />
      </Form.Item>

      <Form.Item
        label="章节标题"
        name="chapterTitle"
        rules={[{ required: false }]}
      >
        <Input placeholder="请输入章节标题（可选）" />
      </Form.Item>

      <Form.Item
        label="小说类型"
        name="genre"
        rules={[{ required: false }]}
      >
        <Select placeholder="请选择小说类型（可选）">
          {Object.entries(NOVEL_GENRES).map(([key, value]) => (
            <Option key={key} value={key}>{value}</Option>
          ))}
        </Select>
      </Form.Item>

      <Form.Item
        label="写作风格"
        name="style"
        rules={[{ required: false }]}
      >
        <Select placeholder="请选择写作风格（可选）">
          {Object.entries(WRITING_STYLES).map(([key, value]) => (
            <Option key={key} value={key}>{value}</Option>
          ))}
        </Select>
      </Form.Item>

      <Form.Item
        label="目标字数"
        name="wordCount"
        rules={[{ required: false }]}
        initialValue={2000}
      >
        <InputNumber min={500} max={10000} style={{ width: '100%' }} placeholder="目标字数" />
      </Form.Item>

      <Form.Item
        label="小说大纲"
        name="outline"
        rules={[{ required: false }]}
      >
        <TextArea rows={4} placeholder="请输入小说大纲（可选，用于保持情节连贯）" />
      </Form.Item>
    </>
  );

  const renderCharacterForm = () => (
    <>
      <Form.Item
        label="角色名称"
        name="characterName"
        rules={[{ required: false }]}
      >
        <Input placeholder="请输入角色名称（可选）" />
      </Form.Item>

      <Form.Item
        label="小说类型"
        name="genre"
        rules={[{ required: false }]}
      >
        <Select placeholder="请选择小说类型（可选）">
          {Object.entries(NOVEL_GENRES).map(([key, value]) => (
            <Option key={key} value={key}>{value}</Option>
          ))}
        </Select>
      </Form.Item>

      <Form.Item
        label="故事主题"
        name="theme"
        rules={[{ required: false }]}
      >
        <TextArea rows={4} placeholder="请输入故事主题（可选）" />
      </Form.Item>
    </>
  );

  const renderWorldviewForm = () => (
    <>
      <Form.Item
        label="小说标题"
        name="title"
        rules={[{ required: false }]}
      >
        <Input placeholder="请输入小说标题（可选）" />
      </Form.Item>

      <Form.Item
        label="小说类型"
        name="genre"
        rules={[{ required: false }]}
      >
        <Select placeholder="请选择小说类型（可选）">
          {Object.entries(NOVEL_GENRES).map(([key, value]) => (
            <Option key={key} value={key}>{value}</Option>
          ))}
        </Select>
      </Form.Item>

      <Form.Item
        label="故事主题"
        name="theme"
        rules={[{ required: false }]}
      >
        <TextArea rows={4} placeholder="请输入故事主题（可选）" />
      </Form.Item>
    </>
  );

  const renderContinueForm = () => (
    <>
      <Form.Item
        label="前文内容"
        name="previousContent"
        rules={[{ required: true, message: '请输入前文内容' }]}
      >
        <TextArea rows={8} placeholder="请输入需要续写的前文内容" />
      </Form.Item>

      <Form.Item
        label="小说类型"
        name="genre"
        rules={[{ required: false }]}
      >
        <Select placeholder="请选择小说类型（可选）">
          {Object.entries(NOVEL_GENRES).map(([key, value]) => (
            <Option key={key} value={key}>{value}</Option>
          ))}
        </Select>
      </Form.Item>

      <Form.Item
        label="写作风格"
        name="style"
        rules={[{ required: false }]}
      >
        <Select placeholder="请选择写作风格（可选）">
          {Object.entries(WRITING_STYLES).map(([key, value]) => (
            <Option key={key} value={key}>{value}</Option>
          ))}
        </Select>
      </Form.Item>

      <Form.Item
        label="续写字数"
        name="wordCount"
        rules={[{ required: false }]}
        initialValue={1000}
      >
        <InputNumber min={500} max={5000} style={{ width: '100%' }} placeholder="续写字数" />
      </Form.Item>
    </>
  );

  const renderForm = () => {
    switch (activeAction) {
      case 'outline':
        return renderOutlineForm();
      case 'chapter':
        return renderChapterForm();
      case 'character':
        return renderCharacterForm();
      case 'worldview':
        return renderWorldviewForm();
      case 'continue':
        return renderContinueForm();
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
    <div className="novel-generator">
      <Tabs activeKey={activeAction} onChange={(key) => { setActiveAction(key); form.resetFields(); setResult(null); }}>
        <TabPane
          tab={<span><FileTextOutlined /> 生成大纲</span>}
          key="outline"
        />
        <TabPane
          tab={<span><BookOutlined /> 生成章节</span>}
          key="chapter"
        />
        <TabPane
          tab={<span><UserOutlined /> 生成角色</span>}
          key="character"
        />
        <TabPane
          tab={<span><GlobalOutlined /> 生成世界观</span>}
          key="worldview"
        />
        <TabPane
          tab={<span><EditOutlined /> 续写</span>}
          key="continue"
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
