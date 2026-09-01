"""LLM 基础设施层：OpenAI 接入、工具注册与自动工具调用。"""

from sinbot.plugins.team_manager.infrastructure.llm_client import (
    LLMChatResult,
    LLMClient,
    ToolResult,
)
from sinbot.plugins.team_manager.infrastructure.schema_builder import build_tool_schema

__all__ = ["LLMChatResult", "LLMClient", "ToolResult", "build_tool_schema"]
