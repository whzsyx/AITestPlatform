"""add test data semantic fields for Phase 13 Task 13.4.

Revision ID: 13f4a6b8c9d0
Revises: d9b1c2e4f5a6
Create Date: 2026-05-20 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "13f4a6b8c9d0"
down_revision: Union[str, None] = "d9b1c2e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "test_data_sets",
        sa.Column("purpose", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "test_data_sets",
        sa.Column(
            "tags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "test_data_items",
        sa.Column("semantic", sa.String(length=50), nullable=True),
    )
    op.create_index(
        "idx_test_data_items_semantic",
        "test_data_items",
        ["semantic"],
        unique=False,
        postgresql_where=sa.text("semantic IS NOT NULL"),
    )
    op.add_column(
        "testcases",
        sa.Column(
            "required_test_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("testcases", "required_test_data")
    op.drop_index(
        "idx_test_data_items_semantic",
        table_name="test_data_items",
    )
    op.drop_column("test_data_items", "semantic")
    op.drop_column("test_data_sets", "tags")
    op.drop_column("test_data_sets", "purpose")
