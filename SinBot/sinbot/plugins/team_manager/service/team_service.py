from json import tool

from nonebot import logger
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from sqlalchemy.exc import NoResultFound

from ..controller import team_controller
from ..dao import spec_dao
from ..dao.team_dao import insert_new_team, get_available_team_by_group_id
from ..infrastructure.llm_client import LLMChatResult
from ..model.entity.team import Team
from ..model.vo.create_team_vo import CreateTeamVo
from ..model.vo.join_team_vo import JoinTeamVo
from ..utils.date_utils import is_hour_specific, parse_date_from_input_with_parser


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

    if not is_hour_specific(command_list[1]) and not is_hour_specific(command_list[2]) :
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

    create_team_vo.create_by = message.get_user_id()
    if event:
        create_team_vo.group_number = event.group_id
    else:
        return

    if create_team_vo:
        if await insert_new_team(create_team_vo):
            logger.info(f"创建在{create_team_vo.start_time}的团队{create_team_vo.team_name}成功！")
            await team_controller.create_team.finish(
                f"创建在{create_team_vo.start_time}的团队{create_team_vo.team_name}成功！")
        else:
            logger.error(f"创建在{create_team_vo.start_time}的团队{create_team_vo.team_name}失败！")
            await team_controller.create_team.finish(
                f"数据库内部错误，请联系管理员！")


async def _parse_team_info_with_llm(full_commend: str) ->CreateTeamVo|None:
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


# 报名 1 蓬莱 辰韶
# 报名 1 蓬莱 辰韶 1
# 报名 yx 蓬莱 辰韶
# 报名 蓬莱 辰韶 // 开团需要名称需要添加校验 不能使用门派名称

@team_controller.join_team.handle()
async def join_team(message: Event, event: GroupMessageEvent):
    logger.info("加入团队")
    full_command = message.get_plaintext()
    command_list = full_command.strip().split()
    if len(command_list) > 5:
        await team_controller.join_team.finish("参数过多！")
    if len(command_list) < 3:
        await team_controller.join_team.finish("参数过少！")

    available_team_list = await _get_available_team_list(str(event.group_id))
    join_team_vo = JoinTeamVo()
    default_team_flag = False

    if available_team_list:
        if command_list[1].isdecimal(): # demo 1 2
            if int(command_list[1]) > len(available_team_list) or  int(command_list[1]) <= 0 :
                await team_controller.join_team.finish("请输入正确的团队序号！")
            join_team_vo.team_no = command_list[1]
            join_team_vo.team_id = available_team_list[int(join_team_vo.team_no) - 1].team_id
            join_team_vo.member_spec_input = command_list[2]
            join_team_vo.member_name = command_list[3]
        elif command_list[1] in [ team.team_name for team in available_team_list ]: # demo 3
            join_team_vo.team_name = command_list[1]
            join_team_vo.team_id = next((x.team_id for x in available_team_list if x.team_name == join_team_vo.team_name),None)
            join_team_vo.member_spec_input = command_list[2]
            join_team_vo.member_name = command_list[3]
        else: # demo 4?
            if len(available_team_list) > 1:
                await team_controller.join_team.finish("请输入团队名或团队序号")
            join_team_vo.team_name = available_team_list[0].team_name
            join_team_vo.team_id = available_team_list[0].team_id
            join_team_vo.member_spec_input = command_list[2]
            join_team_vo.member_name = command_list[3]

        join_team_vo.member_spec = await spec_dao.get_spec_id_by_name_or_nickname(join_team_vo.member_spec_input)
        if  join_team_vo.member_spec == -1:
            await team_controller.join_team.finish("请输入正确的心法名称！")
        else:
            join_team_vo.group_number = str(event.group_id)
            join_team_vo.member_id = str(event.sender.user_id)
            if command_list[-1].isdecimal():
                join_team_vo.mult_spec = True









    try:
        await spec_dao.get_spec_id_by_name_or_nickname(command_list[2])
    except NoResultFound as e:
        logger.error(f"查询心法名称返回空:{command_list[2]}")
        await team_controller.join_team.finish("请输入正确的心法名称！")

    await team_controller.join_team.finish("test")

async def _get_available_team_list(group_number:str)->list[Team]:
    return await get_available_team_by_group_id(group_number)

