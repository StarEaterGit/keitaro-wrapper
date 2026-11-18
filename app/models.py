from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class OwnedCampaign(Base):
    __tablename__ = 'owned_campaigns'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # Keitaro campaign ID
    instance_url: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_marker: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default='creating')
    geo_stream_id: Mapped[int | None] = mapped_column(Integer)
    offers_stream_id: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    history: Mapped[list['AuditLog']] = relationship(back_populates='campaign')


class AuditLog(Base):
    __tablename__ = 'audit_logs'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey('owned_campaigns.id'), nullable=False)
    action: Mapped[str] = mapped_column(String(48), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    campaign: Mapped[OwnedCampaign] = relationship(back_populates='history')


class StreamDraft(Base):
    """Published snapshot + local preview for one OWNED Keitaro stream."""
    __tablename__ = 'stream_drafts'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey('owned_campaigns.id'), nullable=False, unique=True)
    stream_id: Mapped[int] = mapped_column(Integer, nullable=False)
    base_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    published_json: Mapped[str] = mapped_column(Text, nullable=False)
    draft_json: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    dirty: Mapped[bool] = mapped_column(nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
