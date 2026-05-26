"""add_api_test_cases

Revision ID: 13f7d9e0a1b2
Revises: 13f6c8d0e1f2
Create Date: 2026-05-26 10:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "13f7d9e0a1b2"
down_revision: Union[str, None] = "13f6c8d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_test_cases",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("module_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column(
            "headers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "query_params",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("body_type", sa.String(length=20), server_default="none", nullable=False),
        sa.Column("body_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column(
            "assertions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "method IN ('GET','POST','PUT','PATCH','DELETE')",
            name="ck_api_test_cases_method",
        ),
        sa.CheckConstraint(
            "body_type IN ('none','json','text')",
            name="ck_api_test_cases_body_type",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["module_id"], ["testcase_modules.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_api_test_cases_id", "api_test_cases", ["id"], unique=False)
    op.create_index("ix_api_test_cases_project_id", "api_test_cases", ["project_id"], unique=False)
    op.create_index("ix_api_test_cases_module_id", "api_test_cases", ["module_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_api_test_cases_module_id", table_name="api_test_cases")
    op.drop_index("ix_api_test_cases_project_id", table_name="api_test_cases")
    op.drop_index("ix_api_test_cases_id", table_name="api_test_cases")
    op.drop_table("api_test_cases")
