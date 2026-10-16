from pathlib import Path

from nonebot import get_driver, get_plugin_config, load_plugins, logger, require
from nonebot.plugin import PluginMetadata


logger.info("jm模块初始化")

__plugin_meta__ = PluginMetadata(
    name="jm",
    description="",
    usage=""
)

import sinbot.plugins.jm_download.download
