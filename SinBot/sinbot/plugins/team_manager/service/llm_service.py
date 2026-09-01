"""LLM 服务出口：持有全局 LLMClient 单例，供插件内业务注册工具与对话。"""
from nonebot import get_plugin_config
from nonebot import logger

from sinbot.plugins.team_manager.config import Config
from sinbot.plugins.team_manager.infrastructure.llm_client import LLMClient

__all__ = ["llm_client"]

_config = get_plugin_config(Config).team_manager

llm_client = LLMClient(
    api_key=_config.llm_api_key,
    base_url=_config.llm_base_url or None,
    model=_config.llm_model,
    max_turns=_config.llm_max_turns,
)
logger.info(f"LLM 客户端初始化完成，模型：{_config.llm_model}")
