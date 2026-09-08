import datetime

from nonebot_plugin_orm import Model
from sqlalchemy import BIGINT, DATETIME, VARCHAR
from sqlalchemy.orm import Mapped, mapped_column


class Member(Model):
    member_id: Mapped[int] = mapped_column(BIGINT, primary_key=True)
    team_id: Mapped[int] = mapped_column(BIGINT, nullable=False)
    member_qq_number: Mapped[str] = mapped_column(VARCHAR(50), nullable=False)
    member_name: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)
    specialization: Mapped[int] = mapped_column(BIGINT, nullable=False)
    mult_spec_flag: Mapped[str] = mapped_column(VARCHAR(1), nullable=False)
    delete_flag: Mapped[str] = mapped_column(VARCHAR(1), nullable=False)
    creation_date: Mapped[datetime.datetime] = mapped_column(DATETIME, nullable=False)
    created_by: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)
    last_update_date: Mapped[datetime.datetime] = mapped_column(DATETIME, nullable=False)
    last_update_by: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)
