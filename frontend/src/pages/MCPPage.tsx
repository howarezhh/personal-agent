import React, { useEffect, useState } from 'react';
import {
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  List,
  Modal,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from 'antd';
import { ApiOutlined, InfoCircleOutlined, PlayCircleOutlined } from '@ant-design/icons';

import {
  buildToolInitialValues,
  executeTool,
  getToolDetail,
  getToolExecutionErrorMessage,
  getToolParameterDefaultText,
  getToolsList,
  normalizeToolParameters,
  type Tool,
  type ToolExecuteResponse,
  type ToolParameter,
} from '@/services/toolService';
import { MainLayout } from '@/components/layout/MainLayout';
import ToolExecutionResult from '@/components/tools/ToolExecutionResult';
import './MCPPage.css';

const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;

const formatParameterTypeLabel = (parameterType: string): string => {
  const typeLabelMap: Record<string, string> = {
    string: '字符串',
    number: '数字',
    integer: '整数',
    boolean: '布尔值',
    object: '对象',
    array: '数组',
  };

  return typeLabelMap[parameterType] || parameterType;
};

const renderParameterInput = (param: ToolParameter) => {
  if (param.enum && param.enum.length > 0) {
    return (
      <Select placeholder={`请选择${param.description || param.name}`}>
        {param.enum.map((value) => (
          <Select.Option key={value} value={value}>
            {value}
          </Select.Option>
        ))}
      </Select>
    );
  }

  if (param.type === 'boolean') {
    return (
      <Select placeholder={`请选择${param.description || param.name}`}>
        <Select.Option value={true}>是</Select.Option>
        <Select.Option value={false}>否</Select.Option>
      </Select>
    );
  }

  if (param.type === 'object' || param.type === 'array') {
    return (
      <TextArea
        rows={4}
        placeholder={param.type === 'array' ? '请输入 JSON 数组' : '请输入 JSON 对象'}
      />
    );
  }

  if (param.type === 'number' || param.type === 'integer') {
    return <Input type="number" placeholder={param.description || param.name} />;
  }

  if ((param.description || '').length > 40) {
    return <TextArea rows={4} placeholder={param.description || param.name} />;
  }

  return <Input placeholder={param.description || param.name} />;
};

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
      setMcpList(allTools.filter((tool) => tool.transportProtocol === 'mcp'));
    } catch (error: any) {
      message.error(`加载 MCP 工具列表失败：${error.response?.data?.detail || error.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleViewDetail = async (tool: Tool) => {
    try {
      const detail = await getToolDetail(tool.name);
      setSelectedMCP(detail);
      setDetailModalVisible(true);
    } catch (error: any) {
      message.error(`加载工具详情失败：${error.response?.data?.detail || error.message}`);
    }
  };

  const handleOpenExecute = (tool: Tool) => {
    setSelectedMCP(tool);
    setExecuteResult(null);
    form.resetFields();
    form.setFieldsValue(buildToolInitialValues(tool));
    setExecuteModalVisible(true);
  };

  const handleExecute = async () => {
    if (!selectedMCP) {
      return;
    }

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
      if (error.errorFields) {
        message.error('请补全必填参数');
      } else {
        message.error(`执行失败：${error.response?.data?.detail || error.message}`);
      }
    } finally {
      setExecuting(false);
    }
  };

  const renderFormItems = () => {
    if (!selectedMCP) {
      return null;
    }

    return selectedMCP.parameters.map((param) => (
      <Form.Item
        key={param.name}
        name={param.name}
        label={param.description || param.name}
        rules={[{ required: param.required, message: `请填写${param.description || param.name}` }]}
        extra={`类型：${formatParameterTypeLabel(param.type)}；默认示例：${getToolParameterDefaultText(param)}`}
      >
        {renderParameterInput(param)}
      </Form.Item>
    ));
  };

  const renderParameterDescriptions = () => {
    if (!selectedMCP || selectedMCP.parameters.length === 0) {
      return <Text type="secondary">该工具没有参数。</Text>;
    }

    return (
      <List
        size="small"
        dataSource={selectedMCP.parameters}
        renderItem={(param) => (
          <List.Item>
            <Space direction="vertical" size={0} style={{ width: '100%' }}>
              <Space wrap>
                <Text strong>{param.name}</Text>
                <Tag color={param.required ? 'red' : 'default'}>{param.required ? '必填' : '可选'}</Tag>
                <Tag>{formatParameterTypeLabel(param.type)}</Tag>
              </Space>
              <Text>{param.description || '无描述'}</Text>
              {param.enum && param.enum.length > 0 && (
                <Text type="secondary">可选值：{param.enum.join(' / ')}</Text>
              )}
            </Space>
          </List.Item>
        )}
      />
    );
  };

  return (
    <MainLayout>
      <div className="app-page-scroll mcp-page">
        <div className="page-header">
          <Title level={2}>MCP 工具</Title>
          <Paragraph>
            当前页面展示通过 MCP 协议接入的工具能力。默认配置下，这些能力主要来自本地内置的
            builtin MCP server，它再代理外部 HTTP 服务；这不同于“直接接入外部 MCP server”。
          </Paragraph>
        </div>

        <Spin spinning={loading} tip="加载 MCP 工具中...">
          <List
            grid={{ gutter: 16, xs: 1, sm: 2, lg: 3 }}
            dataSource={mcpList}
            locale={{ emptyText: '暂无 MCP 工具' }}
            renderItem={(tool) => (
              <List.Item>
                <Card
                  className="mcp-card"
                  hoverable
                  actions={[
                    <Button key="detail" type="link" icon={<InfoCircleOutlined />} onClick={() => void handleViewDetail(tool)}>
                      详情
                    </Button>,
                    <Button key="execute" type="link" icon={<PlayCircleOutlined />} onClick={() => handleOpenExecute(tool)}>
                      执行
                    </Button>,
                  ]}
                >
                  <Card.Meta
                    title={
                      <Space>
                        <ApiOutlined />
                        <span>{tool.name}</span>
                      </Space>
                    }
                    description={
                      <Space direction="vertical" size={12} style={{ width: '100%' }}>
                        <Paragraph ellipsis={{ rows: 3, expandable: false }} style={{ marginBottom: 0 }}>
                          {tool.description}
                        </Paragraph>
                        <Space wrap>
                          <Tag color="orange">MCP</Tag>
                          <Tag color={tool.toolOrigin === 'external' ? 'purple' : 'green'}>
                            {tool.toolOrigin === 'external' ? '外部来源' : '本地来源'}
                          </Tag>
                          <Tag>{tool.category}</Tag>
                          {tool.mcpServer && <Tag>{tool.mcpServer}</Tag>}
                        </Space>
                      </Space>
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
              <span>MCP 工具详情</span>
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
          width={760}
        >
          {selectedMCP && (
            <Descriptions column={1} bordered>
              <Descriptions.Item label="名称">{selectedMCP.name}</Descriptions.Item>
              <Descriptions.Item label="描述">{selectedMCP.description}</Descriptions.Item>
              <Descriptions.Item label="分类">{selectedMCP.category}</Descriptions.Item>
              <Descriptions.Item label="传输协议">{selectedMCP.transportProtocol}</Descriptions.Item>
              <Descriptions.Item label="来源">{selectedMCP.toolOrigin}</Descriptions.Item>
              <Descriptions.Item label="MCP Server">{selectedMCP.mcpServer || '-'}</Descriptions.Item>
              <Descriptions.Item label="参数说明">{renderParameterDescriptions()}</Descriptions.Item>
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
          onCancel={() => {
            setExecuteModalVisible(false);
            setExecuteResult(null);
          }}
          footer={[
            <Button
              key="cancel"
              onClick={() => {
                setExecuteModalVisible(false);
                setExecuteResult(null);
              }}
            >
              取消
            </Button>,
            <Button key="execute" type="primary" loading={executing} onClick={() => void handleExecute()}>
              执行
            </Button>,
          ]}
          width={760}
        >
          <Form form={form} layout="vertical">
            {renderFormItems()}
          </Form>

          {executeResult && (
            <Card title="执行结果" style={{ marginTop: 16 }} type="inner">
              <ToolExecutionResult result={executeResult} />
            </Card>
          )}
        </Modal>
      </div>
    </MainLayout>
  );
};

export default MCPPage;
