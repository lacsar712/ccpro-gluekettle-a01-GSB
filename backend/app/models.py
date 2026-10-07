from datetime import datetime, timezone
from typing import ClassVar, Optional

from sqlalchemy import Index
from sqlmodel import Field, Relationship, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    password_hash: str
    role: str = "worker"


class Workshop(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    alley: str = ""
    kettles: list["Kettle"] = Relationship(back_populates="workshop")


class Kettle(SQLModel, table=True):
    STATUS_COLD: ClassVar[str] = "cold"
    STATUS_BOILING: ClassVar[str] = "boiling"
    STATUS_DRAWN: ClassVar[str] = "drawn"

    id: Optional[int] = Field(default=None, primary_key=True)
    workshop_id: int = Field(foreign_key="workshop.id")
    code: str
    status: str = STATUS_COLD
    bench: int = 0
    workshop: Optional[Workshop] = Relationship(back_populates="kettles")
    cooks: list["CookLog"] = Relationship(back_populates="kettle")
    gravity_readings: list["GravityReading"] = Relationship(back_populates="kettle")


class CookLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    kettle_id: int = Field(foreign_key="kettle.id")
    taken_at: datetime = Field(default_factory=utcnow)
    peak_temp_c: float
    operator: str = ""
    kettle: Optional[Kettle] = Relationship(back_populates="cooks")


class GravityReading(SQLModel, table=True):
    """比重计读数：同锅未作废槽位号唯一（见部分唯一索引）。"""

    __tablename__ = "gravityreading"
    __table_args__ = (
        Index(
            "uq_gravity_kettle_slot_active",
            "kettle_id",
            "slot_no",
            unique=True,
            postgresql_where="voided_at IS NULL",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    kettle_id: int = Field(foreign_key="kettle.id")
    slot_no: int = Field(index=True)
    gravity: float
    sampled_at: datetime
    sampler: str = ""
    voided_at: Optional[datetime] = Field(default=None)
    kettle: Optional[Kettle] = Relationship(back_populates="gravity_readings")
