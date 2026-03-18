/**
 * MCP 集成服务 API
 * 基于统一 Tool 契约，筛选外部来源的 MCP 工具。
 */

import {
  executeTool,
  getToolCategories,
  getToolDetail,
  getToolsList,
  type Tool,
  type ToolCategory,
  type ToolExecuteResponse,
} from './toolService';

export type MCPService = Tool;
export type MCPExecuteRequest = {
  parameters: Record<string, unknown>;
};
export type MCPExecuteResponse = ToolExecuteResponse;

export const getMCPList = async (category?: string): Promise<MCPService[]> => {
  const tools = await getToolsList(category);
  return tools.filter((tool) => tool.transportProtocol === 'mcp' && tool.toolOrigin === 'external');
};

export const getMCPDetail = async (mcpName: string): Promise<MCPService> => {
  return getToolDetail(mcpName);
};

export const executeMCP = async (
  mcpName: string,
  parameters: Record<string, unknown>
): Promise<MCPExecuteResponse> => {
  return executeTool(mcpName, parameters);
};

export const getMCPCategories = async (): Promise<ToolCategory[]> => {
  const categories = await getToolCategories();
  const tools = await getMCPList();
  const allowed = new Set(tools.map((tool) => tool.category));
  return categories.filter((item) => allowed.has(item.category));
};
