from backend.tools.adapters.mcp_tool_adapter import MCPToolAdapter

# 中文说明：保留旧类名兼容，避免旧代码导入路径立即失效。
MCPProxyTool = MCPToolAdapter

__all__ = ["MCPToolAdapter", "MCPProxyTool"]
