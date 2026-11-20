"""add unknown institution type lookup

Revision ID: b7c41e98f2ad
Revises: 3a0a53b36641
Create Date: 2026-11-19 23:30:00

"""
from typing import Sequence, Union

from alembic import op

revision: str = "b7c41e98f2ad"
down_revision: Union[str, Sequence[str], None] = "3a0a53b36641"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "INSERT INTO institution_types (code, name) "
            "VALUES ('unknown', 'Unknown') ON CONFLICT DO NOTHING"
        )
    else:
        op.execute(
            "INSERT OR IGNORE INTO institution_types (code, name) "
            "VALUES ('unknown', 'Unknown')"
        )


def downgrade() -> None:
    pass
