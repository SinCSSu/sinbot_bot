from pathlib import Path

from nonebot import get_plugin_config, load_plugins, logger, require
from nonebot.plugin import PluginMetadata

require("nonebot_plugin_orm")

from .config import Config

logger.info("TeamManager模块初始化")

__plugin_meta__ = PluginMetadata(
    name="team_manager",
    description="",
    usage="",
    config=Config,
)

config = get_plugin_config(Config).team_manager

from .service import (  # noqa: F401  # 副作用导入：初始化 LLM 单例与事件处理器
    llm_service,
    team_service,
    member_serivce,
)
from .service.llm_tools import team_tools  # noqa: F401  # 副作用导入：注册 LLM 工具