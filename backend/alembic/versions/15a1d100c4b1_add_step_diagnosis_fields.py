"""phase15_1: ui_step_results 加 4 列诊断字段 + 联合索引

Revision ID: 15a1d100c4b1
Revises: 13fb1d2e3f4a
Create Date: 2026-05-29 10:50:00.000000

Phase 15 / Task 15.1：把当前已经在 tool_calls JSONB 里以 ``execution_meta``
节点存放的诊断信息提为列，便于 SQL 聚合与 dashboard 展示；同时为
Phase 15.2 起将逐步引入的 ``loop_break_reason`` 预留字段。

新增列：

- ``execution_path``：deterministic / ai_step_runner / ai_fallback / unknown
- ``fallback_reason``：deterministic 失败转 fallback 时的原因；旧记录为 NULL
- ``loop_break_reason``：StepRunner 退出原因；本期保留 NULL，15.2 后填值
- ``assertion_method``：text_search / llm / deterministic / triage_external 等

联合索引 ``(execution_path, status)`` 用于"按执行路径聚合通过率"的常见查询。

幂等性：``op.add_column`` 在 PG 默认不幂等；这里使用 ``IF NOT EXISTS`` 原生 SQL
保证迁移在已有数据库上重复执行时安全（避免 init.sh 重启时报错）。
"""

from typing import Sequence, Union

from sqlalchemy import inspect

from alembic import op

revision: str = "15a1d100c4b1"
down_revision: Union[str, None] = "13fb1d2e3f4a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_COLUMNS = (
    "execution_path",
    "fallback_reason",
    "loop_break_reason",
    "assertion_method",
)
_INDEX_NAME = "ix_ui_step_results_execution_path_status"


def _existing_columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = inspect(bind)
    return {col["name"] for col in inspector.get_columns(table_name)}


def _existing_index_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = inspect(bind)
    return {idx["name"] for idx in inspector.get_indexes(table_name)}


def upgrade() -> None:
    existing = _existing_columns("ui_step_results")
    # 4 列均为可空 TEXT，默认 NULL，对历史行无破坏
    for col in _NEW_COLUMNS:
        if col not in existing:
            op.execute(
                f"ALTER TABLE ui_step_results "
                f"ADD COLUMN IF NOT EXISTS {col} TEXT"
            )

    if _INDEX_NAME not in _existing_index_names("ui_step_results"):
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {_INDEX_NAME} "
            "ON ui_step_results (execution_path, status)"
        )


def downgrade() -> None:
    # 仅删本迁移引入的列与索引；不动其它字段
    op.execute(f"DROP INDEX IF EXISTS {_INDEX_NAME}")
    for col in _NEW_COLUMNS:
        op.execute(f"ALTER TABLE ui_step_results DROP COLUMN IF EXISTS {col}")
