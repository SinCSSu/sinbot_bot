import datetime

from nonebot_plugin_orm import Model
from sqlalchemy import INTEGER, VARCHAR, DATETIME, TEXT, Nullable
from sqlalchemy.orm import Mapped, mapped_column

class Specialization(Model):
    spec_id: Mapped[int] = mapped_column(TEXT, primary_key=True)
    relate_spec_id: Mapped[int] = mapped_column(TEXT,nullable=True)
    spec_name: Mapped[str] = mapped_column(VARCHAR(50),nullable=False)
    spec_nickname: Mapped[str] = mapped_column(VARCHAR(50),nullable=False)
    color:Mapped[int] = mapped_column(INTEGER,nullable=False)
    icon_path: Mapped[str] = mapped_column(VARCHAR(100),nullable=False)
    spec_type: Mapped[int] = mapped_column(INTEGER,nullable=False)
    delete_flag: Mapped[str] = mapped_column(VARCHAR(1), nullable=False)
    creation_date: Mapped[datetime.datetime] = mapped_column(DATETIME, nullable=False)
    created_by: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)
    last_update_date: Mapped[datetime.datetime] = mapped_column(DATETIME, nullable=False)
    last_update_by: Mapped[str] = mapped_column(VARCHAR(100), nullable=False)


