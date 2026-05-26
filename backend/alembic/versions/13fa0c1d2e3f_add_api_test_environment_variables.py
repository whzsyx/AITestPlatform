"""add_api_test_environment_variables

Revision ID: 13fa0c1d2e3f
Revises: 13f9b2c3d4e5
Create Date: 2026-05-26 19:05:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "13fa0c1d2e3f"
down_revision: Union[str, None] = "13f9b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_test_environment_variables",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("environment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["environment_id"], ["api_test_environments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("environment_id", "key", name="uq_api_test_environment_variables_env_key"),
    )
    op.create_index(
        "ix_api_test_environment_variables_environment_id",
        "api_test_environment_variables",
        ["environment_id"],
        unique=False,
    )
    op.create_index("ix_api_test_environment_variables_id", "api_test_environment_variables", ["id"], unique=False)
    op.create_index(
        "ix_api_test_environment_variables_project_id",
        "api_test_environment_variables",
        ["project_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_api_test_environment_variables_project_id", table_name="api_test_environment_variables")
    op.drop_index("ix_api_test_environment_variables_id", table_name="api_test_environment_variables")
    op.drop_index("ix_api_test_environment_variables_environment_id", table_name="api_test_environment_variables")
    op.drop_table("api_test_environment_variables")
