import datetime
from nonebot import logger
from datetime import timedelta

from nonebot_plugin_orm import get_session

from sinbot.plugins.team_manager.model.vo.create_team_vo import CreateTeamVo
from sinbot.plugins.team_manager.model.entity.team import Team

import short_unique_id


async def insert_new_team(team_info: CreateTeamVo) -> bool:
    session = get_session()
    try:
        async with session.begin():
            team = Team(
                team_id=str(short_unique_id.get_next_snowflake_id()),
                team_name=team_info.team_name,
                dungeon=team_info.team_name,
                comment=team_info.comment,
                group_number=team_info.group_number,
                start_time=datetime.datetime.strptime(team_info.start_time, "%Y-%m-%d %H:%M:%S"),
                overtime_time=datetime.datetime.strptime(team_info.start_time, "%Y-%m-%d %H:%M:%S") + timedelta(
                    hours=3),
                limit_method=team_info.limit_method,
                delete_flag='N',
                created_by=team_info.create_by,
                creation_date=datetime.datetime.now(),
                last_update_by=team_info.create_by,
                last_update_date=datetime.datetime.now()
            )
            session.add(team)
            return True
    except Exception as e:
        logger.error(e)
        return False
