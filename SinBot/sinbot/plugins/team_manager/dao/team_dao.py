from ..api import api
from ..model.vo.team_detail_vo import TeamDetailVo
from ..model.vo.team_info_vo import TeamInfoVo


async def insert_new_team(group_number: str, sender: str, msg: str) -> TeamInfoVo:
    return await api.team.create(msg, group_number, sender)


async def get_available_team_by_group_id(group_id: str, sender: str) -> list[TeamInfoVo]:
    return await api.team.list_available(group_id, sender)


async def get_team_detail(group_id: str, sender: str, msg: str) -> TeamDetailVo:
    return await api.team.get_team_detail(msg, group_id, sender)
