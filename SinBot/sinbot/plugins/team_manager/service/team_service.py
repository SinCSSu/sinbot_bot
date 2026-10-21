from json import tool

from nonebot import logger
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageSegment
from nonebot.internal.matcher import Matcher
from sqlalchemy.exc import NoResultFound

from ..controller import team_controller
from ..dao import spec_dao
from ..dao.team_dao import insert_new_team, get_available_team_by_group_id, get_team_detail
from ..dao.member_dao import insert_new_member
from ..infrastructure.llm_client import LLMChatResult
from ..model.entity.team import Team
from ..model.vo.create_team_vo import CreateTeamVo
from ..model.vo.join_team_vo import JoinTeamVo
from ..model.vo.team_info_vo import TeamInfoVo
from ..render import render_team_panel_for_team
from ..utils.date_utils import is_hour_specific, parse_date_from_input_with_parser, format_datatime_str


# 开团 今晚八点 yx
# 开团 yx 今晚八点
# 开团 yx 今晚八点 有事别报
# 开团 yx 今晚八点 无限制 有事别报
@team_controller.create_team.handle()
async def create_team(message: Event, event: GroupMessageEvent):
    logger.info("开始创建团队")
    team_info = None
    full_command = message.get_plaintext()

    msg = full_command[2:].strip()
    try:
        team_info = await insert_new_team(str(event.group_id),
                                          str(event.sender.user_id),
                                          msg)
        logger.info(team_info)
    except Exception as e:
        logger.error(e)
        await team_controller.create_team.finish("服务器内部错误，请联系管理员")

    if team_info:
        logger.info(f"创建在{team_info.start_time}的团队{team_info.team_name}成功！")
        await team_controller.create_team.finish(
            f"创建在{team_info.start_time}的团队{team_info.team_name}成功！")
    else:
        logger.error("数据服务请求错误")
        await team_controller.create_team.finish("服务器内部错误，请联系管理员")


async def get_available_team_list(group_number: str, sender: str) -> list[TeamInfoVo]:
    team_list = await get_available_team_by_group_id(group_number, sender)
    team_list.sort(key=lambda team: team.team_no)
    return team_list


@team_controller.view_all_team.handle()
async def view_all_team(message: Event, event: GroupMessageEvent):
    team_info = await get_available_team_list(str(event.group_id), str(event.sender.user_id))
    if len(team_info) > 0:
        await send_team_list_to_group(team_controller.view_all_team, team_info)
        await team_controller.view_all_team.finish()
    else:
        await team_controller.view_all_team.finish("当前暂无在开团队！")


@team_controller.view_team.handle()
async def view_team(message: Event, event: GroupMessageEvent):
    full_command = message.get_plaintext()
    command_list = full_command.strip().split()
    msg = " ".join(command_list[1:])

    team_info = await get_team_detail(str(event.group_id), str(event.sender.user_id), msg)

    team_index = team_info.team_no
    image_bytes = await render_team_panel_for_team(team_info, team_no=team_index)
    await team_controller.view_team.finish(MessageSegment.image(file=image_bytes))


async def send_team_list_to_group(matcher: Matcher, team_info: list[TeamInfoVo]):
    content = "当前所有在开团队如下：\n"
    for index, team in enumerate(team_info):
        start_time = format_datatime_str(team.start_time)
        temp = f"{index + 1}： {start_time},团队名称：{team.team_name}\n"
        content += temp
    content = content[:-1]
    await matcher.send(content)
    pass
