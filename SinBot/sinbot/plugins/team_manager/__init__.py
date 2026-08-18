from nonebot import load_plugins
from nonebot import get_plugin_config
from nonebot.plugin import PluginMetadata
from pathlib import Path

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="team_manager",
    description="",
    usage="",
    config=Config,
)

config = get_plugin_config(Config)
sub_plugins = load_plugins(
    str(Path(__file__).parent.joinpath("plugins").resolve())
)

from .service import team_service
