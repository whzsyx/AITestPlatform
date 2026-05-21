"""add UI execution runtime_data for Phase 13 Task 13.7.

Revision ID: 13f6c8d0e1f2
Revises: 13f5b7c9d0e1
Create Date: 2026-05-20 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "13f6c8d0e1f2"
down_revision: Union[str, None] = "13f5b7c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ui_executions",
        sa.Column(
            "runtime_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("ui_executions", "runtime_data")
