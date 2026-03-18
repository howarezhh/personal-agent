/**
 * 工具管理页面
 * 显示所有可用工具，支持搜索、分类和来源筛选。
 */

import React, { useEffect, useState } from 'react';
import { Card, Row, Col, Tag, Input, Select, message, Spin, Modal, Form, Button } from 'antd';
import { ToolOutlined, SearchOutlined, FilterOutlined } from '@ant-design/icons';
import {
  getToolsList,
  getToolCategories,
  executeTool,
  getToolExecutionErrorMessage,
  normalizeToolParameters,
  Tool,
  ToolCategory,
} from '@/services/toolService';
import { MainLayout } from '@/components/layout/MainLayout';
import './ToolsPage.css';

const { Search, TextArea } = Input;
const { Option } = Select;

const ToolsPage: React.FC = () => {
  const [tools, setTools] = useState<Tool[]>([]);
  const [filteredTools, setFilteredTools] = useState<Tool[]>([]);
  const [categories, setCategories] = useState<ToolCategory[]>([]);
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const [selectedToolType, setSelectedToolType] = useState<string>('all');
  const [searchText, setSearchText] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(false);
  const [executeModalVisible, setExecuteModalVisible] = useState<boolean>(false);
  const [selectedTool, setSelectedTool] = useState<Tool | null>(null);
  const [executing, setExecuting] = useState<boolean>(false);
  const [form] = Form.useForm();

  useEffect(() => {
    void loadTools();
    void loadCategories();
  }, []);

  useEffect(() => {
    filterTools();
  }, [tools, selectedCategory, selectedToolType, searchText]);

  const loadTools = async () => {
    setLoading(true);
    try {
      const data = await getToolsList();
      setTools(data);
    } catch (error) {
      message.error('加载工具列表失败');
      console.error('加载工具列表失败:', error);
    } finally {
      setLoading(false);
    }
  };

  const loadCategories = async () => {
    try {
      const data = await getToolCategories();
      setCategories(data);
    } catch (error) {
      console.error('加载分类失败:', error);
    }
  };

  const filterTools = () => {
    let filtered = tools;

    if (selectedToolType === 'local') {
      filtered = filtered.filter((tool) => tool.toolOrigin === 'local');
    } else if (selectedToolType === 'mcp') {
      filtered = filtered.filter((tool) => tool.toolOrigin === 'external');
    }

    if (selectedCategory !== 'all') {
      filtered = filtered.filter((tool) => tool.category === selectedCategory);
    }

    if (searchText) {
      const lowerSearchText = searchText.toLowerCase();
      filtered = filtered.filter((tool) =>
        tool.name.toLowerCase().includes(lowerSearchText) ||
        tool.description.toLowerCase().includes(lowerSearchText)
      );
    }

    setFilteredTools(filtered);
  };

  const getCategoryColor = (category: string): string => {
    const colors: Record<string, string> = {
      language: 'blue',
      utility: 'green',
      creative: 'purple',
      calculation: 'orange',
      search: 'cyan',
      weather: 'geekblue',
      news: 'gold',
      knowledge: 'purple',
      finance: 'volcano',
      network: 'magenta',
      data: 'lime',
    };
    return colors[category] || 'default';
  };

  const handleToolClick = (tool: Tool) => {
    setSelectedTool(tool);
    setExecuteModalVisible(true);
    form.resetFields();
  };

  const handleExecuteTool = async () => {
    if (!selectedTool) return;

    try {
      const values = await form.validateFields();
      setExecuting(true);

      const parameters = normalizeToolParameters(selectedTool, values);
      const result = await executeTool(selectedTool.name, parameters);

      if (result.success) {
        const modalPayload = result.metadata ? { data: result.data, metadata: result.metadata } : result.data;
        Modal.success({
          title: '执行成功',
          content: (
            <div>
              <pre style={{ maxHeight: '400px', overflow: 'auto' }}>
                {JSON.stringify(modalPayload, null, 2)}
              </pre>
            </div>
          ),
          width: 600,
        });
        setExecuteModalVisible(false);
      } else {
        message.error(getToolExecutionErrorMessage(result));
      }
    } catch (error: any) {
      if (error.errorFields) {
        message.error('请填写必填参数');
      } else {
        message.error(error.message || '执行工具失败');
        console.error('执行工具失败:', error);
      }
    } finally {
      setExecuting(false);
    }
  };

  const renderParameterInput = (param: any) => {
    if (param.enum && param.enum.length > 0) {
      return (
        <Select placeholder={`请选择${param.description}`}>
          {param.enum.map((value: string) => (
            <Option key={value} value={value}>{value}</Option>
          ))}
        </Select>
      );
    }

    if (param.type === 'integer' || param.type === 'number') {
      return <Input type="number" placeholder={param.description} />;
    }

    if (param.type === 'object' || param.type === 'array') {
      return (
        <TextArea
          rows={4}
          placeholder={param.type === 'array' ? '请输入 JSON 数组，例如：[1,2,3]' : '请输入 JSON 对象，例如：{"key":"value"}'}
        />
      );
    }

    if (param.type === 'boolean') {
      return (
        <Select placeholder={`请选择${param.description}`}>
          <Option value={true}>是</Option>
          <Option value={false}>否</Option>
        </Select>
      );
    }

    if (param.description && param.description.length > 50) {
      return <TextArea rows={4} placeholder={param.description} />;
    }

    return <Input placeholder={param.description} />;
  };

  return (
    <MainLayout>
      <div className="tools-page">
        <div className="tools-header">
          <h1><ToolOutlined /> 工具管理</h1>
          <p>统一展示所有经标准 MCP 封装后的工具能力</p>
        </div>

        <Card className="tools-filters-card">
          <Row gutter={16}>
            <Col xs={24} sm={12} md={10}>
              <Search
                placeholder="搜索工具名称或描述"
                allowClear
                prefix={<SearchOutlined />}
                onSearch={setSearchText}
                onChange={(e) => setSearchText(e.target.value)}
                size="large"
              />
            </Col>
            <Col xs={12} sm={6} md={7}>
              <Select
                style={{ width: '100%' }}
                placeholder="工具来源"
                value={selectedToolType}
                onChange={setSelectedToolType}
                size="large"
              >
                <Option value="all">全部工具</Option>
                <Option value="local">本地能力</Option>
                <Option value="mcp">外部集成</Option>
              </Select>
            </Col>
            <Col xs={12} sm={6} md={7}>
              <Select
                style={{ width: '100%' }}
                placeholder="选择分类"
                value={selectedCategory}
                onChange={setSelectedCategory}
                size="large"
                suffixIcon={<FilterOutlined />}
              >
                <Option value="all">全部分类 ({tools.length})</Option>
                {categories.map((cat) => (
                  <Option key={cat.category} value={cat.category}>
                    {cat.category} ({cat.count})
                  </Option>
                ))}
              </Select>
            </Col>
          </Row>
        </Card>

        <Spin spinning={loading} tip="加载工具列表...">
          <Row gutter={[16, 16]} className="tools-grid">
            {filteredTools.map((tool) => (
              <Col key={tool.name} xs={24} sm={12} md={8} lg={6}>
                <Card
                  hoverable
                  className="tool-card"
                  onClick={() => handleToolClick(tool)}
                >
                  <div className="tool-card-header">
                    <h3><ToolOutlined /> {tool.name}</h3>
                    <div>
                      <Tag color={getCategoryColor(tool.category)}>{tool.category}</Tag>
                      {tool.transportProtocol === 'mcp' && <Tag color="orange">MCP</Tag>}
                      <Tag color={tool.toolOrigin === 'external' ? 'purple' : 'green'}>
                        {tool.toolOrigin === 'external' ? '外部' : '本地'}
                      </Tag>
                    </div>
                  </div>
                  <p className="tool-description">{tool.description}</p>
                  <div className="tool-meta">
                    <span>参数: {tool.parameters.length}</span>
                    <span>超时: {tool.timeout}s</span>
                  </div>
                </Card>
              </Col>
            ))}
          </Row>
        </Spin>

        {filteredTools.length === 0 && !loading && (
          <div className="empty-state">
            <p>未找到匹配的工具</p>
          </div>
        )}

        <Modal
          title={selectedTool ? `执行工具：${selectedTool.name}` : '执行工具'}
          open={executeModalVisible}
          onCancel={() => setExecuteModalVisible(false)}
          footer={[
            <Button key="cancel" onClick={() => setExecuteModalVisible(false)}>
              取消
            </Button>,
            <Button key="execute" type="primary" loading={executing} onClick={handleExecuteTool}>
              执行
            </Button>,
          ]}
          width={720}
        >
          {selectedTool && (
            <>
              <div style={{ marginBottom: 16 }}>
                <Tag color={getCategoryColor(selectedTool.category)}>{selectedTool.category}</Tag>
                <Tag color="orange">{selectedTool.transportProtocol.toUpperCase()}</Tag>
                <Tag color={selectedTool.toolOrigin === 'external' ? 'purple' : 'green'}>
                  {selectedTool.toolOrigin === 'external' ? '外部集成' : '本地能力'}
                </Tag>
                {selectedTool.mcpServer && <Tag>{selectedTool.mcpServer}</Tag>}
              </div>

              <Form form={form} layout="vertical">
                {selectedTool.parameters.map((param) => (
                  <Form.Item
                    key={param.name}
                    name={param.name}
                    label={param.name}
                    extra={param.description}
                    rules={[{ required: param.required, message: `请填写参数 ${param.name}` }]}
                  >
                    {renderParameterInput(param)}
                  </Form.Item>
                ))}
              </Form>
            </>
          )}
        </Modal>
      </div>
    </MainLayout>
  );
};

export default ToolsPage;
