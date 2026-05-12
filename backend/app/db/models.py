from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class DrawHistory(Base):
    """One row per draw. Month is unique unless is_redraw=True."""

    __tablename__ = "draw_history"

    id: Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    month: Mapped[str]        = mapped_column(String(7), nullable=False, index=True)  # "2026-04"
    drawn_at: Mapped[datetime]= mapped_column(DateTime(timezone=True), server_default=func.now())
    drawn_by: Mapped[str]     = mapped_column(String(256), nullable=False)
    num_winners: Mapped[int]  = mapped_column(Integer, nullable=False, default=1)
    winners: Mapped[dict]     = mapped_column(JSON, nullable=False)   # list of qualifier dicts
    pool_size: Mapped[int]    = mapped_column(Integer, nullable=False)
    is_redraw: Mapped[bool]   = mapped_column(Boolean, nullable=False, default=False)
    summary: Mapped[dict]     = mapped_column(JSON, nullable=True)    # processing funnel


class AuditLog(Base):
    """
    Append-only event log. Never deleted or updated — provides a full
    paper trail of every action taken (draws, redraws, manager approvals,
    emails sent, manual email lookups).
    """

    __tablename__ = "audit_log"

    id: Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    action: Mapped[str]        = mapped_column(String(64), nullable=False)
    month: Mapped[str]         = mapped_column(String(7), nullable=False, index=True)
    timestamp: Mapped[datetime]= mapped_column(DateTime(timezone=True), server_default=func.now())
    actor: Mapped[str]         = mapped_column(String(256), nullable=False)
    details: Mapped[dict]      = mapped_column(JSON, nullable=True)


class MissingEmailQueue(Base):
    """
    Plates that qualified but have no email address (non-permit holders).
    Manager manually resolves these before winner notifications can be sent.
    """

    __tablename__ = "missing_email_queue"

    id: Mapped[int]          = mapped_column(Integer, primary_key=True, autoincrement=True)
    month: Mapped[str]       = mapped_column(String(7), nullable=False, index=True)
    plate: Mapped[str]       = mapped_column(String(32), nullable=False)
    resolved: Mapped[bool]   = mapped_column(Boolean, nullable=False, default=False)
    email: Mapped[str | None]= mapped_column(String(256), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
