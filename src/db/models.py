from sqlalchemy import Column, String, Text, DateTime, func, JSON, Uuid
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB
from sqlalchemy.orm import declarative_base
import uuid

Base = declarative_base()


class Task(Base):
    __tablename__ = "tasks"

    id = Column(
        PGUUID(as_uuid=True).with_variant(Uuid(as_uuid=True), "sqlite"),
        primary_key=True,
        default=uuid.uuid4,
    )
    prompt = Column(Text, nullable=False)
    status = Column(String(50), nullable=False, default="PENDING")
    result = Column(Text, nullable=True)
    agent_logs = Column(
        JSONB().with_variant(JSON, "sqlite"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
