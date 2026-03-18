/**
 * MCP 集成管理页面
 * 展示统一 Tool 契约下的外部来源 MCP 工具。
 */

import React, { useEffect, useState } from 'react';
import { Card, List, Tag, Button, Modal, Form, Input, Select, message, Spin, Descriptions, Space, Typography } from 'antd';
import { ApiOutlined, PlayCircleOutlined, InfoCircleOutlined } from '@ant-design/icons';
import {
  getToolsList,
  getToolDetail,
  executeTool,
  getToolExecutionErrorMessage,
  normalizeToolParameters,
  Tool,
  ToolExecuteResponse,
} from '@/services/toolService';
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
  const [executeResult, setExecuteResult] = useState<ToolExecuteResponse | null>(null);
  const [form] = Form.useForm();

  useEffect(() => {
    void loadMCPList();
  }, []);

  const loadMCPList = async () => {
    try {
      setLoading(true);
      const allTools = await getToolsList();
      const externalMcpTools = allTools.filter((tool) => tool.transportProtocol === 'mcp' && tool.toolOrigin === 'external');
      setMcpList(externalMcpTools);
    } catch (error: any) {
      message.error('加载 MCP 列表失败: ' + (error.response?.data?.detail || error.message));
    } finally {
      setLoading(false);
    }
  };

  const handleViewDetail = async (mcp: Tool) => {
    try {
      const detail = await getToolDetail(mcp.name);
      setSelectedMCP(detail);
      setDetailModalVisible(true);
    } catch (error: any) {
      message.error('获取 MCP 详情失败: ' + (error.response?.data?.detail || error.message));
    }
  };

  const handleOpenExecute = (mcp: Tool) => {
    setSelectedMCP(mcp);
    setExecuteResult(null);
    form.resetFields();
    setExecuteModalVisible(true);
  };

  const handleExecute = async () => {
    if (!selectedMCP) return;

    try {
      const values = await form.validateFields();
      setExecuting(true);

      const parameters = normalizeToolParameters(selectedMCP, values);
      const result = await executeTool(selectedMCP.name, parameters);
      setExecuteResult(result);

      if (result.success) {
        message.success('执行成功');
      } else {
        message.error(getToolExecutionErrorMessage(result));
      }
    } catch (error: any) {
      message.error('执行失败: ' + (error.response?.data?.detail || error.message));
    } finally {
      setExecuting(false);
    }
  };

  const renderFormItems = () => {
    if (!selectedMCP || !selectedMCP.parameters) return null;

    return selectedMCP.parameters.map((param) => {
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
      }

      if (param.type === 'number' || param.type === 'integer') {
        return (
          <Form.Item
            key={param.name}
            name={param.name}
            label={param.description || param.name}
            rules={[{ required: param.required, message: `请输入${param.description || param.name}` }]}
          >
            <Input type="number" placeholder={`请输入${param.description || param.name}`} />
          </Form.Item>
        );
      }

      if (param.type === 'object' || param.type === 'array') {
        return (
          <Form.Item
            key={param.name}
            name={param.name}
            label={param.description || param.name}
            rules={[{ required: param.required, message: `请输入${param.description || param.name}` }]}
          >
            <TextArea rows={4} placeholder="请输入合法 JSON" />
          </Form.Item>
        );
      }

      return (
        <Form.Item
          key={param.name}
          name={param.name}
          label={param.description || param.name}
          rules={[{ required: param.required, message: `请输入${param.description || param.name}` }]}
        >
          <Input placeholder={`请输入${param.description || param.name}`} />
        </Form.Item>
      );
    });
  };

  return (
    <MainLayout>
      <div className="mcp-page">
        <div className="page-header">
          <Title level={2}>
            <ApiOutlined /> MCP 集成管理
          </Title>
          <Paragraph>
            这里展示所有通过标准 MCP 接入、且来源为外部集成的工具能力。
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
                      key="detail"
                      type="link"
                      icon={<InfoCircleOutlined />}
                      onClick={() => handleViewDetail(mcp)}
                    >
                      详情
                    </Button>,
                    <Button
                      key="execute"
                      type="link"
                      icon={<PlayCircleOutlined />}
                      onClick={() => handleOpenExecute(mcp)}
                    >
                      执行
                    </Button>,
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
                        <Space wrap>
                          <Tag color="orange">MCP</Tag>
                          <Tag color="purple">外部</Tag>
                          <Tag>{mcp.category}</Tag>
                          {mcp.mcpServer && <Tag>{mcp.mcpServer}</Tag>}
                        </Space>
                      </div>
                    }
                  />
                </Card>
              </List.Item>
            )}
          />
        </Spin>

        <Modal
          title={
            <Space>
              <ApiOutlined />
              <span>MCP 服务详情</span>
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
            </Button>,
          ]}
          width={700}
        >
          {selectedMCP && (
            <Descriptions column={1} bordered>
              <Descriptions.Item label="服务名称">{selectedMCP.name}</Descriptions.Item>
              <Descriptions.Item label="描述">{selectedMCP.description}</Descriptions.Item>
              <Descriptions.Item label="业务分类">{selectedMCP.category}</Descriptions.Item>
              <Descriptions.Item label="运行时协议">{selectedMCP.transportProtocol}</Descriptions.Item>
              <Descriptions.Item label="工具来源">{selectedMCP.toolOrigin}</Descriptions.Item>
              <Descriptions.Item label="MCP Server">{selectedMCP.mcpServer || '-'}</Descriptions.Item>
              <Descriptions.Item label="参数">
                <pre style={{ margin: 0, maxHeight: 300, overflow: 'auto' }}>
                  {JSON.stringify(selectedMCP.parameters, null, 2)}
                </pre>
              </Descriptions.Item>
            </Descriptions>
          )}
        </Modal>

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
            </Button>,
          ]}
          width={700}
        >
          <Form form={form} layout="vertical">
            {renderFormItems()}
          </Form>

          {executeResult && (
            <Card title="执行结果" style={{ marginTop: 16 }} type="inner">
              {executeResult.success ? (
                <pre style={{ maxHeight: 400, overflow: 'auto', background: '#f5f5f5', padding: 12, borderRadius: 4 }}>
                  {JSON.stringify(executeResult.metadata ? { data: executeResult.data, metadata: executeResult.metadata } : executeResult.data, null, 2)}
                </pre>
              ) : (
                <>
                  <Text type="danger">{getToolExecutionErrorMessage(executeResult)}</Text>
                  {executeResult.metadata && (
                    <pre style={{ maxHeight: 240, overflow: 'auto', background: '#fff2f0', padding: 12, borderRadius: 4, marginTop: 12 }}>
                      {JSON.stringify(executeResult.metadata, null, 2)}
                    </pre>
                  )}
                </>
              )}
            </Card>
          )}
        </Modal>
      </div>
    </MainLayout>
  );
};

export default MCPPage;
