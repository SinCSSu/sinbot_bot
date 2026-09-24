import datetime
from datetime import timedelta

from nonebot import logger
from nonebot_plugin_orm import get_session
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError, NoResultFound

from sinbot.plugins.team_manager.model.entity.team import Team
from sinbot.plugins.team_manager.model.vo.create_team_vo import CreateTeamVo
from sinbot.plugins.team_manager.utils.date_utils import parse_datetime_str
from sinbot.plugins.team_manager.utils.ids import next_id
from ..api import get_api_client
from ..api.codec import to_entities, to_payload

async def insert_new_team(team_info: CreateTeamVo) -> bool:
    body = to_payload(team_info,datetime_format="%Y-%m-%d %H:%M:%S")

    payload = await get_api_client().request("team.create",
                                             json=body,
                                             headers={
                                                 "X-Group-Number":str(team_info.group_number),
                                                 "X-Operator-Qq":str(team_info.created_by)
                                             }
                                             )
    return True



async def get_available_team_by_group_id(group_id: str) -> list[Team]:
    async with get_session() as session:
        try:
            result = await session.execute(
                select(Team).where(
                    Team.group_number == group_id,
                    Team.delete_flag == "N",
                    Team.start_time > datetime.datetime.now(),  # noqa: DTZ005 - DB 无时区列
                ).order_by(Team.team_id)
            )
            return list(result.scalars().all())
        except NoResultFound as e:
            return []


