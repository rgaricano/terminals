"""Pydantic response schemas."""

import datetime
from typing import Optional

from pydantic import BaseModel

from terminals.models.tenants import TenantStatus


class TenantResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    user_id: str
    instance_id: Optional[str] = None
    instance_name: Optional[str] = None
    backend_type: str = "docker"
    host: Optional[str] = None
    port: int
    status: TenantStatus
    created_at: Optional[datetime.datetime] = None
    updated_at: Optional[datetime.datetime] = None
    last_accessed_at: Optional[datetime.datetime] = None


class AuditLogResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    action: str
    severity: str
    user_id: Optional[str] = None
    request_id: Optional[str] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    detail: Optional[dict] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    status_code: Optional[int] = None
    created_at: Optional[datetime.datetime] = None
