"""Tenant database model and status enum."""

import enum

from sqlalchemy import Column, DateTime, Enum, Integer, String, func
from sqlalchemy.orm import DeclarativeBase

from terminals.crypto import decrypt, encrypt


# ---------------------------------------------------------------------------
# SQLAlchemy
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


class TenantStatus(str, enum.Enum):
    provisioning = "provisioning"
    running = "running"
    stopped = "stopped"
    error = "error"


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, unique=True, nullable=False, index=True)
    instance_id = Column(String, nullable=True)
    instance_name = Column(String, nullable=True)
    backend_type = Column(String, nullable=False, default="docker")
    api_key_encrypted = Column(String, nullable=False)
    host = Column(String, nullable=True)
    port = Column(Integer, default=8000)
    status = Column(Enum(TenantStatus), default=TenantStatus.provisioning)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    last_accessed_at = Column(DateTime, server_default=func.now())

    # ---- Transparent encrypt / decrypt property for api_key ----

    @property
    def api_key(self) -> str:
        """Decrypt and return the API key."""
        if not self.api_key_encrypted:
            return ""
        try:
            return decrypt(self.api_key_encrypted)
        except Exception:
            # Backwards compat: if value is not encrypted yet, return as-is.
            return self.api_key_encrypted

    @api_key.setter
    def api_key(self, value: str) -> None:
        """Encrypt and store the API key."""
        self.api_key_encrypted = encrypt(value) if value else ""
