import datetime

from nonebot_plugin_orm import get_session
from sqlalchemy import select
from sqlalchemy.exc import NoResultFound

from sinbot.plugins.team_manager.model.entity.team import Team
from sinbot.plugins.team_manager.model.vo.create_team_vo import CreateTeamVo
from ..api import api


async def insert_new_team(team_info: CreateTeamVo) -> bool:
    """开团：VO 自动摊平成 body，两个 X-* 请求头由契约里的模板填充。"""
    await api.team.create(team_info)
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


