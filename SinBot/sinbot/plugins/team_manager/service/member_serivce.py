from sinbot.plugins.team_manager.controller import team_controller, member_controller
from nonebot import logger
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from sqlalchemy.exc import NoResultFound

from . import team_service
from .team_service import get_available_team_list
from ..controller import team_controller
from ..dao import spec_dao
from ..dao.team_dao import insert_new_team, get_available_team_by_group_id
from ..dao.member_dao import insert_new_member
from ..infrastructure.llm_client import LLMChatResult
from ..model.entity.team import Team
from ..model.vo.create_team_vo import CreateTeamVo
from ..model.vo.join_team_vo import JoinTeamVo
from ..utils.date_utils import is_hour_specific, parse_date_from_input_with_parser

# 报名 yx 辰韶 蓬莱 明教
# 报名 蓬莱 辰韶 // 开团需要名称需要添加校验 不能使用门派名称


# [0] 一定是命令头,移除, [-1] 判断是不是数字1，是数字 双修标识置true,移除
# 此时可能 团+id+心法 团+id+心法+心法 id+心法 id+心法+心法
# 校验此时 [0] 是否为合法团队，不是的话查看当前是否只有一个团队，不是的话返回报错
# [0]是合法团队时 移除[0] 此时[0] 一定是id,判断[1]和可能有的2是否是心法，不是返回报错 另 双修标识和[2]冲突
# 是的话 团队+心法+id+双修信息完备，报团

@member_controller.join_team.handle()
async def join_team(message: Event, event: GroupMessageEvent):
    logger.info("加入团队")
    full_command = message.get_plaintext()
    command_list = full_command.strip().split()
    if len(command_list) > 5:
        await member_controller.join_team.finish("参数过多！")
    if len(command_list) < 3:
        await member_controller.join_team.finish("参数过少！")

    available_team_list = await get_available_team_list(str(event.group_id))

    mult_spec = False
    team_info = None
    join_team_vo = JoinTeamVo()

    if not available_team_list:
        await member_controller.join_team.finish("当前没有在开团队！")

    join_info_list = command_list[1:]

    if join_info_list[-1].isdecimal():
        if int(command_list[-1]) == 1:
            mult_spec = True
        join_info_list = join_info_list[:-1]

    if join_info_list[0].isdecimal():
        if int(join_info_list[0]) > len(available_team_list) or int(join_info_list[0]) <= 0:
            await member_controller.join_team.finish("请输入正确的团队序号！")
        join_team_vo.team_id = available_team_list[int(join_info_list[0]) - 1].team_id
        join_info_list = join_info_list[1:]
    elif join_info_list[0] in [team.team_name for team in available_team_list]:
        join_team_vo.team_id = next((x.team_id for x in available_team_list if x.team_name == join_info_list[0]),
                                    None)
        join_info_list = join_info_list[1:]
    else:
        await member_controller.join_team.send("请选择正确的团队序号或者名称")
        await team_service.send_team_list_to_group(member_controller.join_team,available_team_list)

    join_team_vo.member_name = join_info_list[0]
    join_info_list = join_info_list[1:]

    if (mult_spec and len(join_info_list) > 1) or (len(join_info_list) > 2):
        await member_controller.join_team.finish("你选择的心法太多了！")

    try:
        spec_id = await spec_dao.get_spec_id_by_name_or_nickname(join_info_list[0])
        join_team_vo.member_spec = spec_id
    except NoResultFound as e:
        logger.error(f"查询心法返回空:{join_info_list[0]}")
        await member_controller.join_team.finish("请输入正确的心法名称！")

    if len(join_info_list) == 2:
        try:
            sub_spec_id = await spec_dao.get_spec_id_by_name_or_nickname(join_info_list[1])
            join_team_vo.sub_spec = sub_spec_id
        except NoResultFound as e:
            logger.error(f"双修查询心法返回空:{join_info_list[1]}")
            await member_controller.join_team.finish("请输入正确的双修心法名称！")

    if mult_spec:
        try:
            sub_spec_name, sub_spec_id = await spec_dao.get_mult_spec_id_by_main_id(join_team_vo.member_spec)
            if sub_spec_id:
                join_team_vo.sub_spec = sub_spec_id
            else:
                await  member_controller.join_team.finish(f"你一个{join_info_list[0]}想切甚么！")
        except NoResultFound as e:
            logger.error(f"双修查询心法返回空:{join_info_list[1]}")
            await member_controller.join_team.finish("数据错误！")

    join_team_vo.member_id = str(event.sender.user_id)
    join_team_vo.group_number = str(event.group_id)
    join_team_vo.sender = str(event.sender.user_id)

    if await insert_new_member(join_team_vo):
        await member_controller.join_team.finish("报名成功！")
    else:
        await member_controller.join_team.finish("数据库错误！")