"""drop sessions.owner: the app is single-user (no sign-in), every session is listed

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_sessions_owner", table_name="sessions")
    with op.batch_alter_table("sessions") as batch:
        batch.drop_column("owner")


def downgrade() -> None:
    op.add_column("sessions", sa.Column("owner", sa.Text(), nullable=True))
    op.create_index("ix_sessions_owner", "sessions", ["owner"])
