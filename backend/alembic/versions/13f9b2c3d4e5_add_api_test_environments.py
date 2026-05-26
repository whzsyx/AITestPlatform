"""add_api_test_environments

Revision ID: 13f9b2c3d4e5
Revises: 13f8a0b1c2d3
Create Date: 2026-05-26 18:20:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "13f9b2c3d4e5"
down_revision: Union[str, None] = "13f8a0b1c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_test_environments",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("base_url", sa.String(length=1000), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("order_index", sa.Integer(), server_default="0", nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_api_test_environments_id", "api_test_environments", ["id"], unique=False)
    op.create_index(
        "ix_api_test_environments_project_id",
        "api_test_environments",
        ["project_id"],
        unique=False,
    )

    op.add_column(
        "api_test_cases",
        sa.Column("environment_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("api_test_cases", sa.Column("base_url", sa.String(length=1000), nullable=True))
    op.add_column("api_test_cases", sa.Column("path", sa.String(length=1000), nullable=True))
    op.create_index("ix_api_test_cases_environment_id", "api_test_cases", ["environment_id"], unique=False)
    op.create_foreign_key(
        "api_test_cases_environment_id_fkey",
        "api_test_cases",
        "api_test_environments",
        ["environment_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.execute(
        sa.text(
            """
            UPDATE api_test_cases
            SET
                base_url = CASE
                    WHEN url ~* '^https?://[^/?#]+'
                    THEN substring(url from '^(https?://[^/?#]+)')
                    ELSE NULL
                END,
                path = CASE
                    WHEN url ~* '^https?://[^/?#]+'
                    THEN COALESCE(NULLIF(substring(url from '^https?://[^/?#]+([^#]*)'), ''), '/')
                    ELSE url
                END
            WHERE path IS NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_constraint("api_test_cases_environment_id_fkey", "api_test_cases", type_="foreignkey")
    op.drop_index("ix_api_test_cases_environment_id", table_name="api_test_cases")
    op.drop_column("api_test_cases", "path")
    op.drop_column("api_test_cases", "base_url")
    op.drop_column("api_test_cases", "environment_id")

    op.drop_index("ix_api_test_environments_project_id", table_name="api_test_environments")
    op.drop_index("ix_api_test_environments_id", table_name="api_test_environments")
    op.drop_table("api_test_environments")
