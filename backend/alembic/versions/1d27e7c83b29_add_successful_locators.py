"""phase15_9: ui_case_results 加 successful_locators jsonb 字段

Revision ID: 1d27e7c83b29
Revises: 15a1d100c4b1
Create Date: 2026-05-29 17:30:00.000000

Phase 15 / Task 15.9：成功 locator 持久化与复用。给 ``ui_case_results`` 表
新增一个 ``successful_locators`` jsonb 列，用来记录每条 case 内每个 step 命中
的 locator (脱敏后的 strategy + value 等白名单字段)；后续执行同一 testcase
时由 ``execution_engine`` 读取最近 N 次成功执行的交集，把信任 locator 加到
candidate 列表最前面。

数据形态:

    {
      "1": {"strategy": "role", "role": "button", "name": "查询",
             "miss_count": 0, "last_seen_at": "2026-05-29T17:30:00Z"},
      "2": {"strategy": "css",  "selector": "input[name='kw']",
             "miss_count": 1, "last_seen_at": "..."},
      ...
    }

字段约定 (与 plan 15.9 + ``_AI_LOCATOR_ALLOWED_STRATEGIES`` 对齐):
- 仅记录 role / text / css / xpath 四种白名单 strategy；
- 始终保持单条 dict (不存 list)，让 SQL JSON 操作简单；
- ``miss_count >= 2`` 时由 engine 主动清掉该 step 的记忆 (不写库 + 写 None)。

幂等：使用 ``IF NOT EXISTS`` 保证多次执行安全。
"""

from typing import Sequence, Union

from sqlalchemy import inspect

from alembic import op

revision: str = "1d27e7c83b29"
down_revision: Union[str, None] = "15a1d100c4b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "ui_case_results"
_COLUMN = "successful_locators"


def _existing_columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = inspect(bind)
    return {col["name"] for col in inspector.get_columns(table_name)}


def upgrade() -> None:
    cols = _existing_columns(_TABLE)
    if _COLUMN not in cols:
        # 新列 default '{}' jsonb，旧记录批量 backfill 成空对象，让后续读取
        # 永远拿到 dict 而不是 None，省掉一层 if 判断。
        op.execute(
            f"ALTER TABLE {_TABLE} "
            f"ADD COLUMN IF NOT EXISTS {_COLUMN} JSONB DEFAULT '{{}}'::jsonb"
        )
        # 幂等：如果列已有但默认值不是 jsonb {}（不太可能），不去改它。
        op.execute(
            f"UPDATE {_TABLE} SET {_COLUMN} = '{{}}'::jsonb WHERE {_COLUMN} IS NULL"
        )


def downgrade() -> None:
    cols = _existing_columns(_TABLE)
    if _COLUMN in cols:
        op.execute(f"ALTER TABLE {_TABLE} DROP COLUMN IF EXISTS {_COLUMN}")
