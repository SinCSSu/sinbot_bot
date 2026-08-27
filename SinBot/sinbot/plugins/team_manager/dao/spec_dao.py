from nonebot_plugin_orm import get_session
from sqlalchemy import select, or_
from nonebot import logger
from sqlalchemy.exc import NoResultFound

from sinbot.plugins.team_manager.model.entity.specialization import Specialization


async def get_spec_id_by_name_or_nickname(name:str)->int:
    session = get_session()
    name_conditions = [Specialization.spec_name == name, Specialization.spec_nickname.like(f"%|{name}|%")]
    spec = select(Specialization).where(Specialization.delete_flag == 'N').where(or_(*name_conditions))
    logger.info(spec)
    result =  await session.execute(spec)
    if result:
            return  result.scalars().one().spec_id
    else:
        return -1