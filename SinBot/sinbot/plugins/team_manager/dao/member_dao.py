import datetime
import time
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


async def get_member_by_team_id_and_member_name(team_id: int, member_name: str) -> Member | None:
    """按团队和成员名查询未删除成员，用于重复报团校验。"""
    async with get_session() as session:
        result = await session.execute(
            select(Member)
            .where(
                Member.team_id == team_id,
                Member.member_name == member_name,
                Member.delete_flag == "N",
            )
            .limit(1)
        )
        return result.scalars().first()


async def insert_new_member(member_info: JoinTeamVo) -> bool:
    logger.info("执行落库")
    t0 = time.perf_counter()
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
        t1 = time.perf_counter()
        async with get_session() as session:
            t2 = time.perf_counter()
            async with session.begin():               # ← BEGIN
                t3 = time.perf_counter()
                session.add(member)
                t4 = time.perf_counter()
            t5 = time.perf_counter()                  # ← COMMIT（真正写库+fsync+等锁在这里）
        logger.info("落库完成")
        t6 = time.perf_counter()
        logger.warning(
            f"insert耗时: 取连接={t2-t1:.3f}s BEGIN={t3-t2:.3f}s "
            f"add={t4-t3:.3f}s COMMIT={t5-t4:.3f}s close={t6-t5:.3f}s 总={t6-t0:.3f}s"
        )
    except SQLAlchemyError as e:
        logger.exception("创建团队失败：数据库操作异常")
        return False
    return True
