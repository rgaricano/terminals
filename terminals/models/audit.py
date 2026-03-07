"""Audit log database model."""

from sqlalchemy import Column, DateTime, Integer, JSON, String, func

from terminals.models.tenants import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    action = Column(String, nullable=False, index=True)
    severity = Column(String, nullable=False, server_default="info")
    user_id = Column(String, nullable=True, index=True)
    request_id = Column(String, nullable=True)
    resource_type = Column(String, nullable=True)
    resource_id = Column(String, nullable=True)
    detail = Column(JSON, nullable=True)
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    status_code = Column(Integer, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)
