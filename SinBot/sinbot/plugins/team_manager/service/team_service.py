from nonebot import logger
from nonebot import on_command
from nonebot.rule import to_me
from nonebot.adapters import Event
from nonebot.matcher import Matcher
from ...controller import team_controller


@team_controller.create_team.handle()
async def create_team(message: Event):
    print(message)
    logger.info("开始创建团队")
    await team_controller.create_team.finish("开团")
