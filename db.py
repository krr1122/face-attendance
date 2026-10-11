"""数据模型：MySQL 和本地演示共用，业务不依赖浏览器存储。"""
from datetime import datetime
from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(60), unique=True)
    employee_no: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(60))
    department: Mapped[str] = mapped_column(String(80), default="未分配")
    role: Mapped[str] = mapped_column(String(16), default="employee")
    password_hash: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    session_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class FaceTemplate(Base):
    __tablename__ = "face_templates"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    encrypted_features: Mapped[bytes] = mapped_column(LargeBinary)
    model_version: Mapped[str] = mapped_column(String(60), default="sface-2021dec")
    sample_count: Mapped[int] = mapped_column(Integer)
    enrolled_at: Mapped[datetime] = mapped_column(DateTime)

class Attendance(Base):
    __tablename__ = "attendance"
    __table_args__ = (UniqueConstraint("user_id", "work_date", name="uq_attendance_user_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    work_date: Mapped[object] = mapped_column(Date)
    check_in: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    check_out: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    in_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    out_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    in_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    out_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    shift_start: Mapped[str] = mapped_column(String(5))
    shift_end: Mapped[str] = mapped_column(String(5))
    grace_minutes: Mapped[int] = mapped_column(Integer, default=0)

class Setting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(Text)

class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(40))
    target: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime)
