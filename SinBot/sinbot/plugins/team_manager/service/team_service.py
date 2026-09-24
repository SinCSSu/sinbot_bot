from json import tool

from nonebot import logger
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import GroupMessageEvent,MessageSegment
from nonebot.internal.matcher import Matcher
from sqlalchemy.exc import NoResultFound

from ..controller import team_controller
from ..dao import spec_dao
from ..dao.team_dao import insert_new_team, get_available_team_by_group_id
from ..dao.member_dao import insert_new_member
from ..infrastructure.llm_client import LLMChatResult
from ..model.entity.team import Team
from ..model.vo.create_team_vo import CreateTeamVo
from ..model.vo.join_team_vo import JoinTeamVo
from ..render import render_team_panel_for_team
from ..utils.date_utils import is_hour_specific, parse_date_from_input_with_parser, format_datatime_str


# 开团 今晚八点 yx
# 开团 yx 今晚八点
# 开团 yx 今晚八点 有事别报
# 开团 yx 今晚八点 无限制 有事别报
@team_controller.create_team.handle()
async def create_team(message: Event, event: GroupMessageEvent):
    logger.info("开始创建团队")
    full_command = message.get_plaintext()
    command_list = full_command.strip().split()
    if len(command_list) > 5:
        await team_controller.create_team.finish("参数过多！")
    team_start_time = None
    team_name = None
    limit_flag = True
    llm_flag = False
    create_team_vo = CreateTeamVo()
    if "无限制" in command_list:
        limit_flag = False
        command_list.remove("无限制")

    if not is_hour_specific(command_list[1]) and not is_hour_specific(command_list[2]):
        await team_controller.create_team.finish(
            "请输入时间"
        )
    # 防止记不清时间和副本名的顺序，适配了两种方式
    if team_start_time := parse_date_from_input_with_parser(command_list[1]):
        create_team_vo.start_time = team_start_time
        create_team_vo.team_name = command_list[2]
    if team_start_time := parse_date_from_input_with_parser(command_list[2]):
        if create_team_vo.start_time:
            await team_controller.create_team.finish("时间参数输入过多！")
        else:
            create_team_vo.start_time = team_start_time
            create_team_vo.team_name = command_list[1]
    if not create_team_vo.start_time:
        create_team_vo = await _parse_team_info_with_llm(full_command)  # 无法解析日期，使用llm兜底
        if create_team_vo:
            llm_flag = True
        else:
            await team_controller.create_team.finish("输入解析失败。")

    if not team_start_time and not create_team_vo:
        await team_controller.create_team.finish("参数输入错误。")

    if not llm_flag:
        create_team_vo.limit_method = 1 if limit_flag else 0
        if len(command_list) == 4:
            create_team_vo.comment = command_list[-1]

    create_team_vo.created_by = str(message.get_user_id())
    if event:
        create_team_vo.group_number = str(event.group_id)
    else:
        return
    create_team_vo.dungeon = create_team_vo.team_name

    if create_team_vo:
        if await insert_new_team(create_team_vo):
            logger.info(f"创建在{create_team_vo.start_time}的团队{create_team_vo.team_name}成功！")
            await team_controller.create_team.finish(
                f"创建在{create_team_vo.start_time}的团队{create_team_vo.team_name}成功！")
        else:
            logger.error(f"创建在{create_team_vo.start_time}的团队{create_team_vo.team_name}失败！")
            await team_controller.create_team.finish(
                f"数据库内部错误，请联系管理员！")


async def _parse_team_info_with_llm(full_commend: str) -> CreateTeamVo | None:
    from .llm_service import llm_client
    result = await llm_client.chat([
        {
            "role": "system",
            "content": (
                "你是一个数据清洗器，负责解析用户输入数据并选择合适的工具返回结构化的数据"
            ),
        },
        {"role": "user", "content": full_commend},
    ])
    if len(result.tool_results) > 0:
        return result.tool_results[0].value
    else:
        return None


async def get_available_team_list(group_number: str) -> list[Team]:
    return await get_available_team_by_group_id(group_number)

@team_controller.view_all_team.handle()
async def view_all_team(message: Event, event: GroupMessageEvent):
    team_info = await get_available_team_list(str(event.group_id))
    if len(team_info) > 0:
        await send_team_list_to_group(team_controller.view_all_team,team_info)
        await team_controller.view_all_team.finish()
    else:
        await team_controller.view_all_team.finish("当前暂无在开团队！")


@team_controller.view_team.handle()
async def view_team(message: Event, event: GroupMessageEvent):
    full_command = message.get_plaintext()
    command_list = full_command.strip().split()

    if len(command_list) > 2:
        await team_controller.view_team.finish("参数过多！")
    team_list = await get_available_team_list(str(event.group_id))

    if len(command_list) == 1:
        if len(team_list) > 0:
            await send_team_list_to_group(team_controller.view_team, team_list)
            await team_controller.view_team.finish()
        else:
            await team_controller.view_team.finish("当前暂无在开团队！")

    team_list = await get_available_team_list(str(event.group_id))
    team_info = None
    if command_list[1].isdecimal():
        if int(command_list[1])<=0 or int(command_list[1]) > len(team_list):
            await team_controller.view_team.finish("请输入正确的团队序号！")
        else:
            team_info = team_list[int(command_list[1]) - 1]
    else:
        if command_list[1] in [team.team_name for team in team_list]:
            team_info = next((team for team in team_list if team.team_name == command_list[1]),None)
        else:
            await team_controller.view_team.finish("请输入正确的团队名称！")

    team_index = team_list.index(team_info) + 1
    image_bytes = await render_team_panel_for_team(team_info, team_no=team_index)
    await team_controller.view_team.finish(MessageSegment.image(file=image_bytes))



async def send_team_list_to_group(matcher:Matcher,team_info:list[Team]):
    content = "当前所有在开团队如下：\n"
    for index,team in enumerate(team_info):
        start_time = format_datatime_str(team.start_time)
        temp = f"{index + 1}： {start_time},团队名称：{team.team_name}\n"
        content += temp
    content = content[:-1]
    await matcher.send(content)
    pass


