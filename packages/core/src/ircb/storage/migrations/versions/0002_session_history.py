"""session history: owner, title, updated_at on sessions; payload_json on messages

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("owner", sa.Text(), nullable=True))
    op.add_column("sessions", sa.Column("title", sa.Text(), nullable=True))
    op.add_column("sessions", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_sessions_owner", "sessions", ["owner"])
    op.add_column("messages", sa.Column("payload_json", sa.Text(), nullable=True))
    # sessions from before this revision: the first question is the title, the last message the update
    op.execute(
        "UPDATE sessions SET "
        "title = (SELECT substr(m.content, 1, 80) FROM messages m "
        "WHERE m.session_id = sessions.id AND m.role = 'user' ORDER BY m.id LIMIT 1), "
        "updated_at = COALESCE((SELECT MAX(m.created_at) FROM messages m WHERE m.session_id = sessions.id), "
        "created_at)"
    )


def downgrade() -> None:
    with op.batch_alter_table("messages") as batch:
        batch.drop_column("payload_json")
    op.drop_index("ix_sessions_owner", table_name="sessions")
    with op.batch_alter_table("sessions") as batch:
        batch.drop_column("updated_at")
        batch.drop_column("title")
        batch.drop_column("owner")
