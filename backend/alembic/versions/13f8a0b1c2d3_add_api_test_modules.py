"""add_api_test_modules

Revision ID: 13f8a0b1c2d3
Revises: 13f7d9e0a1b2
Create Date: 2026-05-26 16:20:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "13f8a0b1c2d3"
down_revision: Union[str, None] = "13f7d9e0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_test_modules",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("order_index", sa.Integer(), server_default="0", nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["parent_id"], ["api_test_modules.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_api_test_modules_id", "api_test_modules", ["id"], unique=False)
    op.create_index("ix_api_test_modules_parent_id", "api_test_modules", ["parent_id"], unique=False)
    op.create_index("ix_api_test_modules_project_id", "api_test_modules", ["project_id"], unique=False)

    op.execute(
        sa.text(
            """
            WITH RECURSIVE referenced_modules AS (
                SELECT tm.*
                FROM testcase_modules tm
                WHERE tm.id IN (
                    SELECT DISTINCT module_id
                    FROM api_test_cases
                    WHERE module_id IS NOT NULL
                )
                UNION
                SELECT parent.*
                FROM testcase_modules parent
                JOIN referenced_modules child ON child.parent_id = parent.id
            )
            INSERT INTO api_test_modules (
                id, project_id, parent_id, name, order_index, created_at, updated_at
            )
            SELECT id, project_id, parent_id, name, order_index, created_at, updated_at
            FROM referenced_modules
            """
        )
    )

    op.drop_constraint("api_test_cases_module_id_fkey", "api_test_cases", type_="foreignkey")
    op.create_foreign_key(
        "api_test_cases_module_id_fkey",
        "api_test_cases",
        "api_test_modules",
        ["module_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("api_test_cases_module_id_fkey", "api_test_cases", type_="foreignkey")

    op.execute(
        sa.text(
            """
            INSERT INTO testcase_modules (
                id, project_id, parent_id, name, order_index, entry_path, created_at, updated_at
            )
            SELECT id, project_id, parent_id, name, order_index, NULL, created_at, updated_at
            FROM api_test_modules
            WHERE id NOT IN (SELECT id FROM testcase_modules)
            """
        )
    )

    op.create_foreign_key(
        "api_test_cases_module_id_fkey",
        "api_test_cases",
        "testcase_modules",
        ["module_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_index("ix_api_test_modules_project_id", table_name="api_test_modules")
    op.drop_index("ix_api_test_modules_parent_id", table_name="api_test_modules")
    op.drop_index("ix_api_test_modules_id", table_name="api_test_modules")
    op.drop_table("api_test_modules")
