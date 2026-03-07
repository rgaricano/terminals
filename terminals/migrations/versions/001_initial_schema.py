"""Initial schema — tenants table.

Revision ID: 001
Revises: None
Create Date: 2026-03-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(), nullable=False, unique=True, index=True),
        sa.Column("instance_id", sa.String(), nullable=True),
        sa.Column("instance_name", sa.String(), nullable=True),
        sa.Column("backend_type", sa.String(), nullable=False, server_default="docker"),
        sa.Column("api_key", sa.String(), nullable=False),
        sa.Column("host", sa.String(), nullable=True),
        sa.Column("port", sa.Integer(), server_default="8000"),
        sa.Column(
            "status",
            sa.Enum("provisioning", "running", "stopped", "error", name="tenantstatus"),
            server_default="provisioning",
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("last_accessed_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("tenants")
