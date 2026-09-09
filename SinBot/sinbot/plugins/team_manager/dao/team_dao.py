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


async def insert_new_team(team_info: CreateTeamVo) -> bool:
    start_dt = team_info.start_time
    if start_dt is None:
        logger.error(f"创建团队失败：start_time 为空，输入={team_info}")
        return False
    if isinstance(start_dt, str):  # 兼容上游误传字符串的入口，归一为 datetime
        start_dt = parse_datetime_str(start_dt)
        if start_dt is None:
            logger.error(f"创建团队失败：start_time 格式无法解析，输入={team_info}")
            return False
    try:
        now = datetime.datetime.now()  # noqa: DTZ005 - DB 无时区列，naive 一致
        team = Team(
            team_id=next_id(),
            team_name=team_info.team_name,
            dungeon=team_info.team_name,
            comment=team_info.comment,
            group_number=team_info.group_number,
            start_time=start_dt,
            overtime_time=start_dt + timedelta(hours=3),
            limit_method=team_info.limit_method,
            delete_flag="N",
            created_by=team_info.create_by,
            creation_date=now,
            last_update_by=team_info.create_by,
            last_update_date=now,
        )
        async with get_session() as session, session.begin():
            session.add(team)
    except SQLAlchemyError:
        logger.exception("创建团队失败：数据库操作异常")
        return False
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


