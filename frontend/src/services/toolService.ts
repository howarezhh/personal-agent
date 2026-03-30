import api from './api';

const API_BASE_URL = '/api/v1';

export interface ToolParameter {
  name: string;
  type: string;
  description: string;
  required: boolean;
  default?: unknown;
  enum?: string[];
  minimum?: number;
  maximum?: number;
  min_length?: number;
  max_length?: number;
  pattern?: string;
  items?: Record<string, unknown>;
  properties?: Record<string, unknown>;
  additional_properties?: boolean;
}

export interface Tool {
  name: string;
  description: string;
  category: string;
  transportProtocol: string;
  toolOrigin: string;
  mcpServer?: string | null;
  parameters: ToolParameter[];
  timeout: number;
}

export interface ToolExecuteRequest {
  parameters: Record<string, unknown>;
}

export interface ToolExecuteResponse {
  success: boolean;
  data?: unknown | null;
  error?: string | null;
  errorCode?: string | null;
  errorType?: string | null;
  metadata?: Record<string, unknown> | null;
}

export interface ToolCategory {
  category: string;
  count: number;
  tools: string[];
}

type ToolPayload = {
  name: string;
  description: string;
  category: string;
  transport_protocol?: string;
  tool_origin?: string;
  mcp_server?: string | null;
  parameters?: ToolParameter[];
  timeout?: number;
};

type ToolExecuteResponsePayload = ToolExecuteResponse & {
  error_code?: string | null;
  error_type?: string | null;
};

const adaptTool = (payload: ToolPayload): Tool => ({
  name: payload.name,
  description: payload.description,
  category: payload.category,
  transportProtocol: payload.transport_protocol ?? 'local_direct',
  toolOrigin: payload.tool_origin ?? 'local',
  mcpServer: payload.mcp_server ?? null,
  parameters: payload.parameters ?? [],
  timeout: payload.timeout ?? 30,
});

const adaptToolExecuteResponse = (payload: ToolExecuteResponsePayload): ToolExecuteResponse => ({
  success: payload.success,
  data: payload.data ?? null,
  error: payload.error ?? null,
  errorCode: payload.errorCode ?? payload.error_code ?? null,
  errorType: payload.errorType ?? payload.error_type ?? null,
  metadata: payload.metadata ?? null,
});

export const getToolExecutionErrorMessage = (
  response: Pick<ToolExecuteResponse, 'error' | 'errorCode'>
): string => {
  const baseMessage = response.error || '执行失败';
  return response.errorCode ? `${baseMessage} [${response.errorCode}]` : baseMessage;
};

const buildExampleStringValue = (param: ToolParameter): string => {
  const candidateText = `${param.name} ${param.description}`.toLowerCase();

  if (/(url|link|网址|链接)/.test(candidateText)) {
    return 'https://example.com';
  }
  if (/(email|邮箱)/.test(candidateText)) {
    return 'demo@example.com';
  }
  if (/(city|location|地区|城市)/.test(candidateText)) {
    return '北京';
  }
  if (/(date|日期)/.test(candidateText)) {
    return new Date().toISOString().slice(0, 10);
  }
  if (/(query|keyword|prompt|question|topic|content|text|message|title|name|关键词|问题|提示词|主题|内容|标题|名称)/.test(candidateText)) {
    return '示例内容';
  }

  return '示例值';
};

const normalizeDefaultValueForForm = (param: ToolParameter, value: unknown): unknown => {
  if (value === undefined) {
    return undefined;
  }

  if ((param.type === 'object' || param.type === 'array') && typeof value !== 'string') {
    return JSON.stringify(value, null, 2);
  }

  return value;
};

export const getToolParameterInitialValue = (param: ToolParameter): unknown => {
  if (param.default !== undefined) {
    return normalizeDefaultValueForForm(param, param.default);
  }

  if (param.enum && param.enum.length > 0) {
    return param.enum[0];
  }

  if (param.type === 'boolean') {
    return false;
  }

  if (param.type === 'integer' || param.type === 'number') {
    return 1;
  }

  if (param.type === 'object') {
    return '{\n  "key": "value"\n}';
  }

  if (param.type === 'array') {
    return '[\n  "item1",\n  "item2"\n]';
  }

  return buildExampleStringValue(param);
};

export const getToolParameterDefaultText = (param: ToolParameter): string => {
  const value = getToolParameterInitialValue(param);

  if (typeof value === 'boolean') {
    return value ? '是' : '否';
  }

  return String(value ?? '');
};

export const buildToolInitialValues = (
  tool: Pick<Tool, 'parameters'>
): Record<string, unknown> => {
  return tool.parameters.reduce<Record<string, unknown>>((accumulator, param) => {
    accumulator[param.name] = getToolParameterInitialValue(param);
    return accumulator;
  }, {});
};

const normalizeSingleParameter = (param: ToolParameter, value: unknown): unknown => {
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
      throw new Error(`参数 ${param.name} 必须是合法的 JSON${param.type === 'array' ? '数组' : '对象'}`);
    }
  }

  return value;
};

export const normalizeToolParameters = (
  tool: Pick<Tool, 'parameters'>,
  values: Record<string, unknown>
): Record<string, unknown> => {
  const normalized: Record<string, unknown> = {};

  tool.parameters.forEach((param) => {
    const value = normalizeSingleParameter(param, values[param.name]);
    if (value !== undefined) {
      normalized[param.name] = value;
    }
  });

  return normalized;
};

export const getToolsList = async (category?: string): Promise<Tool[]> => {
  const response = await api.get(`${API_BASE_URL}/tools`, {
    params: category ? { category } : undefined,
  });
  return (response.data.data as ToolPayload[]).map(adaptTool);
};

export const getToolDetail = async (toolName: string): Promise<Tool> => {
  const response = await api.get(`${API_BASE_URL}/tools/${toolName}`);
  return adaptTool(response.data.data as ToolPayload);
};

export const executeTool = async (
  toolName: string,
  parameters: Record<string, unknown>
): Promise<ToolExecuteResponse> => {
  const requestBody: ToolExecuteRequest = { parameters };
  const response = await api.post(`${API_BASE_URL}/tools/${toolName}/execute`, requestBody);
  return adaptToolExecuteResponse(response.data as ToolExecuteResponsePayload);
};

export const getToolCategories = async (): Promise<ToolCategory[]> => {
  const response = await api.get(`${API_BASE_URL}/tools/categories/list`);
  return response.data.data as ToolCategory[];
};
