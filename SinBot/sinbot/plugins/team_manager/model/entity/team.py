import datetime

from nonebot_plugin_orm import Model
from sqlalchemy import INTEGER, VARCHAR, DATETIME
from sqlalchemy.orm import Mapped, mapped_column


class Team(Model):
    team_id: Mapped[int] = mapped_column(INTEGER, primary_key=True)
    team_name: Mapped[str] = mapped_column(VARCHAR(300), nullable=False)
    dungeon: Mapped[str] = mapped_column(VARCHAR(300), nullable=False)
    comment: Mapped[str] = mapped_column(VARCHAR(500), nullable=False)
    start_time: Mapped[datetime.datetime] = mapped_column(DATETIME, nullable=False)
    overtime_time: Mapped[datetime.datetime] = mapped_column(DATETIME, nullable=False)
    limit_method: Mapped[int] = mapped_column(INTEGER, nullable=True)
    delete_flag: Mapped[str] = mapped_column(VARCHAR(1), nullable=False)
    created_by: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)
    creation_date: Mapped[datetime.datetime] = mapped_column(DATETIME, nullable=False)
    last_update_by: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)
    last_update_date: Mapped[datetime.datetime] = mapped_column(DATETIME, nullable=False)
