import datetime
from nonebot import logger
from nonebot_plugin_orm import get_session

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from sinbot.plugins.team_manager.model.entity.member import Member
from sinbot.plugins.team_manager.model.vo.join_team_vo import JoinTeamVo
from sinbot.plugins.team_manager.utils.ids import next_id


async def get_members_by_team_id(team_id: int) -> list[Member]:
    """按团队查询全部未删除成员，按报名先后排序。"""
    async with get_session() as session:
        result = await session.execute(
            select(Member)
            .where(Member.team_id == team_id, Member.delete_flag == "N")
            .order_by(Member.creation_date, Member.member_id)
        )
        return list(result.scalars().all())


async def insert_new_member(member_info: JoinTeamVo) -> bool:
    try:
        now = datetime.datetime.now()
        member = Member(
            member_id=next_id(),
            team_id=member_info.team_id,
            member_qq_number=member_info.member_id,
            member_name=member_info.member_name,
            specialization=member_info.member_spec,
            sub_spec=member_info.sub_spec,
            delete_flag='N',
            creation_date=now,
            created_by=member_info.sender,
            last_update_by=member_info.sender,
            last_update_date=now
        )
        async with get_session() as session, session.begin():
            session.add(member)
    except SQLAlchemyError as e:
        logger.exception("创建团队失败：数据库操作异常")
        return False
    return True
