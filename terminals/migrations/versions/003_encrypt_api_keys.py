"""Rename api_key to api_key_encrypted on tenants table.

Revision ID: 003
Revises: 002
Create Date: 2026-03-06
"""

from typing import Sequence, Union

from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("tenants") as batch_op:
        batch_op.alter_column("api_key", new_column_name="api_key_encrypted")


def downgrade() -> None:
    with op.batch_alter_table("tenants") as batch_op:
        batch_op.alter_column("api_key_encrypted", new_column_name="api_key")
