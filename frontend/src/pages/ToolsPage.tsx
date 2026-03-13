/**
 * 工具管理页面
 * 显示所有可用工具，支持搜索和分类筛选
 */

import React, { useState, useEffect } from 'react';
import { Card, Row, Col, Tag, Input, Select, message, Spin, Modal, Form, Button } from 'antd';
import { ToolOutlined, SearchOutlined, FilterOutlined } from '@ant-design/icons';
import { getToolsList, getToolCategories, executeTool, normalizeToolParameters, Tool, ToolCategory } from '@/services/toolService';
import { MainLayout } from '@/components/layout/MainLayout';
import './ToolsPage.css';

const { Search } = Input;
const { Option } = Select;
const { TextArea } = Input;

const ToolsPage: React.FC = () => {
  const [tools, setTools] = useState<Tool[]>([]);
  const [filteredTools, setFilteredTools] = useState<Tool[]>([]);
  const [categories, setCategories] = useState<ToolCategory[]>([]);
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const [selectedToolType, setSelectedToolType] = useState<string>('all'); // 新增：工具类型筛选
  const [searchText, setSearchText] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(false);
  const [executeModalVisible, setExecuteModalVisible] = useState<boolean>(false);
  const [selectedTool, setSelectedTool] = useState<Tool | null>(null);
  const [executing, setExecuting] = useState<boolean>(false);
  const [form] = Form.useForm();

  useEffect(() => {
    loadTools();
    loadCategories();
  }, []);

  useEffect(() => {
    filterTools();
  }, [tools, selectedCategory, selectedToolType, searchText]); // 添加selectedToolType依赖

  const loadTools = async () => {
    setLoading(true);
    try {
      const data = await getToolsList();
      setTools(data);
      console.log('工具列表加载成功:', data.length);
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
      console.log('工具分类加载成功:', data.length);
    } catch (error) {
      console.error('加载分类失败:', error);
    }
  };

  const filterTools = () => {
    let filtered = tools;

    // 按工具类型筛选（新增）
    if (selectedToolType === 'local') {
      filtered = filtered.filter(tool => tool.category !== 'mcp');
    } else if (selectedToolType === 'mcp') {
      filtered = filtered.filter(tool => tool.category === 'mcp');
    }

    // 按分类筛选
    if (selectedCategory !== 'all') {
      filtered = filtered.filter(tool => tool.category === selectedCategory);
    }

    // 按搜索文本筛选
    if (searchText) {
      const lowerSearchText = searchText.toLowerCase();
      filtered = filtered.filter(tool =>
        tool.name.toLowerCase().includes(lowerSearchText) ||
        tool.description.toLowerCase().includes(lowerSearchText)
      );
    }

    setFilteredTools(filtered);
  };

  const getCategoryColor = (category: string): string => {
    const colors: Record<string, string> = {
      'language': 'blue',
      'utility': 'green',
      'creative': 'purple',
      'calculation': 'orange',
      'search': 'cyan'
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

      // 构造参数对象
      const parameters = normalizeToolParameters(selectedTool, values);

      console.log('执行工具:', selectedTool.name, '参数:', parameters);

      const result = await executeTool(selectedTool.name, parameters);

      if (result.success) {
        Modal.success({
          title: '执行成功',
          content: (
            <div>
              <pre style={{ maxHeight: '400px', overflow: 'auto' }}>
                {JSON.stringify(result.data, null, 2)}
              </pre>
            </div>
          ),
          width: 600
        });
        setExecuteModalVisible(false);
      } else {
        message.error(result.error || '执行失败');
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
          placeholder={param.type === 'array' ? '请输入JSON数组，例如：[1,2,3]' : '请输入JSON对象，例如：{"key":"value"}'}
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
          <p>探索和使用系统中的所有AI工具</p>
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
                placeholder="工具类型"
                value={selectedToolType}
                onChange={setSelectedToolType}
                size="large"
              >
                <Option value="all">全部工具</Option>
                <Option value="local">本地工具</Option>
                <Option value="mcp">MCP工具</Option>
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
                {categories.map(cat => (
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
            {filteredTools.map(tool => (
              <Col key={tool.name} xs={24} sm={12} md={8} lg={6}>
                <Card
                  hoverable
                  className="tool-card"
                  onClick={() => handleToolClick(tool)}
                >
                  <div className="tool-card-header">
                    <h3><ToolOutlined /> {tool.name}</h3>
                    <div>
                      <Tag color={getCategoryColor(tool.category)}>
                        {tool.category}
                      </Tag>
                      {tool.name.endsWith('_mcp') && (
                        <Tag color="orange">MCP</Tag>
                      )}
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

        {/* 工具执行对话框 */}
        <Modal
          title={`执行工具: ${selectedTool?.name}`}
          open={executeModalVisible}
          onCancel={() => setExecuteModalVisible(false)}
          footer={[
            <Button key="cancel" onClick={() => setExecuteModalVisible(false)}>
              取消
            </Button>,
            <Button
              key="execute"
              type="primary"
              loading={executing}
              onClick={handleExecuteTool}
            >
              执行
            </Button>
          ]}
          width={600}
        >
          {selectedTool && (
            <div>
              <p className="tool-modal-description">{selectedTool.description}</p>
              <Form form={form} layout="vertical">
                {selectedTool.parameters.map(param => (
                  <Form.Item
                    key={param.name}
                    label={param.description}
                    name={param.name}
                    rules={[
                      {
                        required: param.required,
                        message: `请输入${param.description}`
                      }
                    ]}
                    initialValue={param.default}
                  >
                    {renderParameterInput(param)}
                  </Form.Item>
                ))}
              </Form>
            </div>
          )}
        </Modal>
      </div>
    </MainLayout>
  );
};

export default ToolsPage;
