/**
 * MCP服务API
 * 提供MCP服务的查询和调用功能
 */

import api from './api';

const API_BASE_URL = '/api/v1/tools';

// MCP服务接口
export interface MCPService {
  name: string;
  description: string;
  category: string;
  version: string;
  parameters: {
    type: string;
    properties: Record<string, any>;
    required: string[];
  };
}

// MCP执行请求
export interface MCPExecuteRequest {
  parameters: Record<string, any>;
}

// MCP执行响应
export interface MCPExecuteResponse {
  success: boolean;
  data?: any;
  error?: string;
}

/**
 * 获取MCP服务列表
 */
export const getMCPList = async (category?: string): Promise<MCPService[]> => {
  const response = await api.get(`${API_BASE_URL}`, {
    params: { category }
  });
  return (response.data.data || []).filter((tool: MCPService) => tool.category === 'mcp');
};

/**
 * 获取MCP服务详情
 */
export const getMCPDetail = async (mcpName: string): Promise<MCPService> => {
  const response = await api.get(`${API_BASE_URL}/${mcpName}`);
  return response.data.data;
};

/**
 * 执行MCP服务
 */
export const executeMCP = async (
  mcpName: string,
  parameters: Record<string, any>
): Promise<MCPExecuteResponse> => {
  const response = await api.post(`${API_BASE_URL}/${mcpName}/execute`, {
    parameters
  });
  return response.data;
};

/**
 * 获取MCP分类列表
 */
export const getMCPCategories = async (): Promise<Array<{ category: string; count: number; tools: string[] }>> => {
  const response = await api.get(`${API_BASE_URL}/categories/list`);
  return (response.data.data || []).filter((item: { category: string }) => item.category === 'mcp');
};
