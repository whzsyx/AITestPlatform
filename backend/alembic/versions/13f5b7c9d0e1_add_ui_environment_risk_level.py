"""add ui environment risk_level for Phase 13 Task 13.5.

Revision ID: 13f5b7c9d0e1
Revises: 13f4a6b8c9d0
Create Date: 2026-05-20 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "13f5b7c9d0e1"
down_revision: Union[str, None] = "13f4a6b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ui_test_environments",
        sa.Column(
            "risk_level",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'low'"),
        ),
    )
    op.create_check_constraint(
        "ck_ui_test_environments_risk_level",
        "ui_test_environments",
        "risk_level IN ('low', 'medium', 'high')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_ui_test_environments_risk_level",
        "ui_test_environments",
        type_="check",
    )
    op.drop_column("ui_test_environments", "risk_level")
