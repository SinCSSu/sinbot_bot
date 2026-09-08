from nonebot_plugin_orm import get_session
from sqlalchemy import select, or_
from nonebot import logger
from sqlalchemy.exc import NoResultFound

from sinbot.plugins.team_manager.model.entity.specialization import Specialization


async def get_spec_id_by_name_or_nickname(name:str)->int:
    session = get_session()
    name_conditions = [Specialization.spec_name == name, Specialization.spec_nickname.like(f"%|{name}|%")]
    spec = select(Specialization).where(Specialization.delete_flag == 'N').where(or_(*name_conditions))
    result =  await session.execute(spec)
    if result:
            return  result.scalars().one().spec_id
    else:
        return -1

async def get_mult_spec_id_by_main_id(spec_id:int)->tuple[str,int|None]:
    session = get_session()
    spec = select(Specialization).where(Specialization.delete_flag == 'N').where(Specialization.spec_id == spec_id)
    result =  await session.execute(spec)
    if result:
        spec = result.scalars().one()
        return spec.spec_name,spec.relate_spec_id
    else:
        raise NoResultFound