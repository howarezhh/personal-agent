/**
 * MCP服务管理页面
 * 展示和管理所有可用的MCP服务
 */

import React, { useState, useEffect } from 'react';
import { Card, List, Tag, Button, Modal, Form, Input, Select, message, Spin, Descriptions, Space, Typography } from 'antd';
import { ApiOutlined, PlayCircleOutlined, InfoCircleOutlined } from '@ant-design/icons';
import { getToolsList, getToolDetail, executeTool, normalizeToolParameters, Tool } from '@/services/toolService';
import { MainLayout } from '@/components/layout/MainLayout';
import './MCPPage.css';

const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;

const MCPPage: React.FC = () => {
  const [mcpList, setMcpList] = useState<Tool[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedMCP, setSelectedMCP] = useState<Tool | null>(null);
  const [detailModalVisible, setDetailModalVisible] = useState(false);
  const [executeModalVisible, setExecuteModalVisible] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [executeResult, setExecuteResult] = useState<any>(null);
  const [form] = Form.useForm();

  // 加载MCP列表（只加载MCP工具）
  useEffect(() => {
    loadMCPList();
  }, []);

  const loadMCPList = async () => {
    try {
      setLoading(true);
      // 获取所有工具，然后筛选出MCP工具
      const allTools = await getToolsList();
      const mcpTools = allTools.filter(tool => tool.category === 'mcp');
      setMcpList(mcpTools);
    } catch (error: any) {
      message.error('加载MCP列表失败: ' + (error.response?.data?.detail || error.message));
    } finally {
      setLoading(false);
    }
  };

  // 查看MCP详情
  const handleViewDetail = async (mcp: Tool) => {
    try {
      const detail = await getToolDetail(mcp.name);
      setSelectedMCP(detail);
      setDetailModalVisible(true);
    } catch (error: any) {
      message.error('获取MCP详情失败: ' + (error.response?.data?.detail || error.message));
    }
  };

  // 打开执行对话框
  const handleOpenExecute = (mcp: Tool) => {
    setSelectedMCP(mcp);
    setExecuteResult(null);
    form.resetFields();
    setExecuteModalVisible(true);
  };

  // 执行MCP服务
  const handleExecute = async () => {
    if (!selectedMCP) return;

    try {
      const values = await form.validateFields();
      setExecuting(true);

      // 构建参数对象
      const parameters = normalizeToolParameters(selectedMCP, values);

      const result = await executeTool(selectedMCP.name, parameters);
      setExecuteResult(result);

      if (result.success) {
        message.success('执行成功');
      } else {
        message.error('执行失败: ' + result.error);
      }
    } catch (error: any) {
      message.error('执行失败: ' + (error.response?.data?.detail || error.message));
    } finally {
      setExecuting(false);
    }
  };

  // 渲染参数表单项
  const renderFormItems = () => {
    if (!selectedMCP || !selectedMCP.parameters) return null;

    return selectedMCP.parameters.map((param) => {
      // 根据参数类型渲染不同的表单项
      if (param.enum) {
        return (
          <Form.Item
            key={param.name}
            name={param.name}
            label={param.description || param.name}
            rules={[{ required: param.required, message: `请选择${param.description || param.name}` }]}
          >
            <Select placeholder={`请选择${param.description || param.name}`}>
              {param.enum.map((value: string) => (
                <Select.Option key={value} value={value}>
                  {value}
                </Select.Option>
              ))}
            </Select>
          </Form.Item>
        );
      } else if (param.type === 'number' || param.type === 'integer') {
        return (
          <Form.Item
            key={param.name}
            name={param.name}
            label={param.description || param.name}
            rules={[{ required: param.required, message: `请输入${param.description || param.name}` }]}
          >
            <Input
              type="number"
              placeholder={param.default !== undefined ? `默认: ${param.default}` : `请输入${param.description || param.name}`}
            />
          </Form.Item>
        );
      } else if (param.type === 'boolean') {
        return (
          <Form.Item
            key={param.name}
            name={param.name}
            label={param.description || param.name}
            rules={[{ required: param.required, message: `请选择${param.description || param.name}` }]}
          >
            <Select placeholder={`请选择${param.description || param.name}`}>
              <Select.Option value={true}>是</Select.Option>
              <Select.Option value={false}>否</Select.Option>
            </Select>
          </Form.Item>
        );
      } else if (param.type === 'object' || param.type === 'array') {
        return (
          <Form.Item
            key={param.name}
            name={param.name}
            label={param.description || param.name}
            rules={[{ required: param.required, message: `请输入${param.description || param.name}` }]}
          >
            <TextArea
              rows={4}
              placeholder={param.type === 'array' ? '请输入JSON数组，例如：[1,2,3]' : '请输入JSON对象，例如：{"key":"value"}'}
            />
          </Form.Item>
        );
      } else {
        return (
          <Form.Item
            key={param.name}
            name={param.name}
            label={param.description || param.name}
            rules={[{ required: param.required, message: `请输入${param.description || param.name}` }]}
          >
            <Input placeholder={param.default !== undefined ? `默认: ${param.default}` : `请输入${param.description || param.name}`} />
          </Form.Item>
        );
      }
    });
  };

  return (
    <MainLayout>
      <div className="mcp-page">
      <div className="page-header">
        <Title level={2}>
          <ApiOutlined /> MCP服务管理
        </Title>
        <Paragraph>
          Model Context Protocol (MCP) 服务提供了丰富的外部数据源和功能扩展
        </Paragraph>
      </div>

      <Spin spinning={loading}>
        <List
          grid={{ gutter: 16, xs: 1, sm: 2, md: 2, lg: 3, xl: 3, xxl: 4 }}
          dataSource={mcpList}
          renderItem={(mcp) => (
            <List.Item>
              <Card
                hoverable
                className="mcp-card"
                actions={[
                  <Button
                    type="link"
                    icon={<InfoCircleOutlined />}
                    onClick={() => handleViewDetail(mcp)}
                  >
                    详情
                  </Button>,
                  <Button
                    type="link"
                    icon={<PlayCircleOutlined />}
                    onClick={() => handleOpenExecute(mcp)}
                  >
                    执行
                  </Button>
                ]}
              >
                <Card.Meta
                  title={
                    <Space>
                      <ApiOutlined />
                      <span>{mcp.name}</span>
                    </Space>
                  }
                  description={
                    <div>
                      <Paragraph ellipsis={{ rows: 2 }}>{mcp.description}</Paragraph>
                      <Tag color="green">{mcp.category}</Tag>
                    </div>
                  }
                />
              </Card>
            </List.Item>
          )}
        />
      </Spin>

      {/* MCP详情对话框 */}
      <Modal
        title={
          <Space>
            <ApiOutlined />
            <span>MCP服务详情</span>
          </Space>
        }
        open={detailModalVisible}
        onCancel={() => setDetailModalVisible(false)}
        footer={[
          <Button key="close" onClick={() => setDetailModalVisible(false)}>
            关闭
          </Button>,
          <Button
            key="execute"
            type="primary"
            icon={<PlayCircleOutlined />}
            onClick={() => {
              setDetailModalVisible(false);
              if (selectedMCP) {
                handleOpenExecute(selectedMCP);
              }
            }}
          >
            执行
          </Button>
        ]}
        width={700}
      >
        {selectedMCP && (
          <Descriptions column={1} bordered>
            <Descriptions.Item label="服务名称">{selectedMCP.name}</Descriptions.Item>
            <Descriptions.Item label="描述">{selectedMCP.description}</Descriptions.Item>
            <Descriptions.Item label="分类">{selectedMCP.category}</Descriptions.Item>
            <Descriptions.Item label="参数">
              <pre style={{ margin: 0, maxHeight: 300, overflow: 'auto' }}>
                {JSON.stringify(selectedMCP.parameters, null, 2)}
              </pre>
            </Descriptions.Item>
          </Descriptions>
        )}
      </Modal>

      {/* MCP执行对话框 */}
      <Modal
        title={
          <Space>
            <PlayCircleOutlined />
            <span>执行 {selectedMCP?.name}</span>
          </Space>
        }
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
            onClick={handleExecute}
          >
            执行
          </Button>
        ]}
        width={700}
      >
        <Form form={form} layout="vertical">
          {renderFormItems()}
        </Form>

        {executeResult && (
          <Card
            title="执行结果"
            style={{ marginTop: 16 }}
            type="inner"
          >
            {executeResult.success ? (
              <pre style={{ maxHeight: 400, overflow: 'auto', background: '#f5f5f5', padding: 12, borderRadius: 4 }}>
                {JSON.stringify(executeResult.data, null, 2)}
              </pre>
            ) : (
              <Text type="danger">{executeResult.error}</Text>
            )}
          </Card>
        )}
      </Modal>
      </div>
    </MainLayout>
  );
};

export default MCPPage;
