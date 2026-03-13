/**
 * 工具管理服务
 * 提供工具列表、详情、执行等API调用
 */

import api from './api';

const API_BASE_URL = '/api/v1';

export interface Tool {
  name: string;
  description: string;
  category: string;
  parameters: ToolParameter[];
  timeout: number;
}

export interface ToolParameter {
  name: string;
  type: string;
  description: string;
  required: boolean;
  default?: any;
  enum?: string[];
}

export interface ToolExecuteRequest {
  parameters: Record<string, any>;
}

export interface ToolExecuteResponse {
  success: boolean;
  data?: any;
  error?: string;
}

export interface ToolCategory {
  category: string;
  count: number;
  tools: string[];
}

const normalizeSingleParameter = (param: ToolParameter, value: any): any => {
  if (value === undefined || value === null || value === '') {
    return undefined;
  }

  if (param.type === 'integer') {
    const normalized = typeof value === 'number' ? value : Number.parseInt(String(value), 10);
    if (Number.isNaN(normalized)) {
      throw new Error(`参数 ${param.name} 必须是整数`);
    }
    return normalized;
  }

  if (param.type === 'number') {
    const normalized = typeof value === 'number' ? value : Number(value);
    if (Number.isNaN(normalized)) {
      throw new Error(`参数 ${param.name} 必须是数字`);
    }
    return normalized;
  }

  if (param.type === 'boolean') {
    if (typeof value === 'boolean') {
      return value;
    }
    if (value === 'true') {
      return true;
    }
    if (value === 'false') {
      return false;
    }
    throw new Error(`参数 ${param.name} 必须是布尔值`);
  }

  if (param.type === 'object' || param.type === 'array') {
    if (typeof value !== 'string') {
      return value;
    }
    try {
      const normalized = JSON.parse(value);
      if (param.type === 'object' && (typeof normalized !== 'object' || Array.isArray(normalized) || normalized === null)) {
        throw new Error();
      }
      if (param.type === 'array' && !Array.isArray(normalized)) {
        throw new Error();
      }
      return normalized;
    } catch {
      throw new Error(`参数 ${param.name} 必须是合法的JSON${param.type === 'array' ? '数组' : '对象'}`);
    }
  }

  return value;
};

export const normalizeToolParameters = (
  tool: Pick<Tool, 'parameters'>,
  values: Record<string, any>
): Record<string, any> => {
  const normalized: Record<string, any> = {};

  tool.parameters.forEach((param) => {
    const value = normalizeSingleParameter(param, values[param.name]);
    if (value !== undefined) {
      normalized[param.name] = value;
    }
  });

  return normalized;
};

/**
 * 获取所有工具列表
 * @param category 工具分类（可选）
 */
export const getToolsList = async (category?: string): Promise<Tool[]> => {
  try {
    const response = await api.get(`${API_BASE_URL}/tools`, {
      params: { category }
    });
    return response.data.data;
  } catch (error) {
    console.error('获取工具列表失败:', error);
    throw error;
  }
};

/**
 * 获取工具详情
 * @param toolName 工具名称
 */
export const getToolDetail = async (toolName: string): Promise<Tool> => {
  try {
    const response = await api.get(`${API_BASE_URL}/tools/${toolName}`);
    return response.data.data;
  } catch (error) {
    console.error('获取工具详情失败:', error);
    throw error;
  }
};

/**
 * 执行工具
 * @param toolName 工具名称
 * @param parameters 工具参数
 */
export const executeTool = async (
  toolName: string,
  parameters: Record<string, any>
): Promise<ToolExecuteResponse> => {
  try {
    const response = await api.post(
      `${API_BASE_URL}/tools/${toolName}/execute`,
      { parameters }
    );
    return response.data;
  } catch (error) {
    console.error('执行工具失败:', error);
    throw error;
  }
};

/**
 * 获取工具分类列表
 */
export const getToolCategories = async (): Promise<ToolCategory[]> => {
  try {
    const response = await api.get(`${API_BASE_URL}/tools/categories/list`);
    return response.data.data;
  } catch (error) {
    console.error('获取工具分类失败:', error);
    throw error;
  }
};
