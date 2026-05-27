"""add_api_automation_tasks

Revision ID: 13fb1d2e3f4a
Revises: 13fa0c1d2e3f
Create Date: 2026-05-27 10:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "13fb1d2e3f4a"
down_revision: Union[str, None] = "13fa0c1d2e3f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_automation_tasks",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("environment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("schedule_type", sa.String(length=20), server_default="manual", nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=True),
        sa.Column("daily_time", sa.String(length=5), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timeout_seconds", sa.Float(), server_default="20", nullable=False),
        sa.Column("stop_on_failure", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["environment_id"], ["api_test_environments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_api_automation_tasks_environment_id", "api_automation_tasks", ["environment_id"])
    op.create_index("ix_api_automation_tasks_id", "api_automation_tasks", ["id"])
    op.create_index("ix_api_automation_tasks_next_run_at", "api_automation_tasks", ["next_run_at"])
    op.create_index("ix_api_automation_tasks_project_id", "api_automation_tasks", ["project_id"])

    op.create_table(
        "api_automation_task_steps",
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("api_case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=True),
        sa.Column("order_index", sa.Integer(), server_default="0", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "request_overrides",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "extractors",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["api_case_id"], ["api_test_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["api_automation_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_api_automation_task_steps_api_case_id", "api_automation_task_steps", ["api_case_id"])
    op.create_index("ix_api_automation_task_steps_id", "api_automation_task_steps", ["id"])
    op.create_index("ix_api_automation_task_steps_task_id", "api_automation_task_steps", ["task_id"])

    op.create_table(
        "api_automation_runs",
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trigger_type", sa.String(length=20), server_default="manual", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="running", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_steps", sa.Integer(), server_default="0", nullable=False),
        sa.Column("passed_steps", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_steps", sa.Integer(), server_default="0", nullable=False),
        sa.Column("skipped_steps", sa.Integer(), server_default="0", nullable=False),
        sa.Column("elapsed_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "runtime_data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["api_automation_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_api_automation_runs_id", "api_automation_runs", ["id"])
    op.create_index("ix_api_automation_runs_project_id", "api_automation_runs", ["project_id"])
    op.create_index("ix_api_automation_runs_task_id", "api_automation_runs", ["task_id"])

    op.create_table(
        "api_automation_run_steps",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_step_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("api_case_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=True),
        sa.Column("order_index", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="running", nullable=False),
        sa.Column("request_url", sa.String(length=2000), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("elapsed_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("request_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("response_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "assertion_results",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "extracted_values",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["api_case_id"], ["api_test_cases.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["api_automation_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_step_id"], ["api_automation_task_steps.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_api_automation_run_steps_api_case_id", "api_automation_run_steps", ["api_case_id"])
    op.create_index("ix_api_automation_run_steps_id", "api_automation_run_steps", ["id"])
    op.create_index("ix_api_automation_run_steps_run_id", "api_automation_run_steps", ["run_id"])
    op.create_index("ix_api_automation_run_steps_task_step_id", "api_automation_run_steps", ["task_step_id"])


def downgrade() -> None:
    op.drop_index("ix_api_automation_run_steps_task_step_id", table_name="api_automation_run_steps")
    op.drop_index("ix_api_automation_run_steps_run_id", table_name="api_automation_run_steps")
    op.drop_index("ix_api_automation_run_steps_id", table_name="api_automation_run_steps")
    op.drop_index("ix_api_automation_run_steps_api_case_id", table_name="api_automation_run_steps")
    op.drop_table("api_automation_run_steps")

    op.drop_index("ix_api_automation_runs_task_id", table_name="api_automation_runs")
    op.drop_index("ix_api_automation_runs_project_id", table_name="api_automation_runs")
    op.drop_index("ix_api_automation_runs_id", table_name="api_automation_runs")
    op.drop_table("api_automation_runs")

    op.drop_index("ix_api_automation_task_steps_task_id", table_name="api_automation_task_steps")
    op.drop_index("ix_api_automation_task_steps_id", table_name="api_automation_task_steps")
    op.drop_index("ix_api_automation_task_steps_api_case_id", table_name="api_automation_task_steps")
    op.drop_table("api_automation_task_steps")

    op.drop_index("ix_api_automation_tasks_project_id", table_name="api_automation_tasks")
    op.drop_index("ix_api_automation_tasks_next_run_at", table_name="api_automation_tasks")
    op.drop_index("ix_api_automation_tasks_id", table_name="api_automation_tasks")
    op.drop_index("ix_api_automation_tasks_environment_id", table_name="api_automation_tasks")
    op.drop_table("api_automation_tasks")
