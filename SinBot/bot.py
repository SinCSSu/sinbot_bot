import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OnbotV11Adapter  # 避免重复命名
from sqlalchemy.sql.ddl import CreateTable
from pathlib import Path

from sinbot.nacos_config import load_nacos_config

# 必须早于 nonebot.init()：DRIVER / LOG_LEVEL / SQLALCHEMY_DATABASE_URL 在 init 阶段固化，
# team_manager 插件在导入时就会读取 TEAM_MANAGER__* 并构造 LLMClient。
load_nacos_config()

nonebot.init()
# 注册适配器
driver = nonebot.get_driver()
driver.register_adapter(OnbotV11Adapter)

# 在这里加载插件
nonebot.load_builtin_plugins("echo")  # 内置插件
# nonebot.load_plugins("sinbot/plugins")  # 本地插件
nonebot.load_plugin(Path("./sinbot/plugins/jm_download"))



if __name__ == "__main__":
    nonebot.run()
