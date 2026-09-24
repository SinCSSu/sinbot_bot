from collections.abc import Iterable

from nonebot_plugin_orm import get_session
from sqlalchemy import select, or_
from nonebot import logger
from sqlalchemy.exc import NoResultFound

from sinbot.plugins.team_manager.model.entity.specialization import Specialization


async def get_spec_id_by_name_or_nickname(name:str)->int:
    name_conditions = [Specialization.spec_name == name, Specialization.spec_nickname.like(f"%|{name}|%")]
    spec = select(Specialization).where(Specialization.delete_flag == 'N').where(or_(*name_conditions))
    async with get_session() as session:
        result =  await session.execute(spec)
        if result:
                return  result.scalars().one().spec_id
        else:
            return -1

async def get_mult_spec_id_by_main_id(spec_id:int)->tuple[str,int|None]:
    spec = select(Specialization).where(Specialization.delete_flag == 'N').where(Specialization.spec_id == spec_id)
    async with get_session() as session:
        result =  await session.execute(spec)
        if result:
            spec = result.scalars().one()
            return spec.spec_name,spec.relate_spec_id
        else:
            raise NoResultFound

async def get_specs_by_ids(spec_ids: Iterable[int]) -> dict[int, Specialization]:
    """按 id 批量查询心法，返回 {spec_id: Specialization}；空集合安全。"""
    ids = {sid for sid in spec_ids if sid}
    if not ids:
        return {}
    async with get_session() as session:
        result = await session.execute(
            select(Specialization).where(
                Specialization.delete_flag == "N",
                Specialization.spec_id.in_(ids),
            )
        )
        return {spec.spec_id: spec for spec in result.scalars().all()}