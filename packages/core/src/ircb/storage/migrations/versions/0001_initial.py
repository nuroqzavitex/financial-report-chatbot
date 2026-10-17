"""initial schema: documents, index_versions, facts, sessions, messages

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from ircb.storage.orm import ExactNumeric

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("doc_id", sa.Text(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=True),
    )
    op.create_table(
        "index_versions",
        sa.Column("index_version", sa.Text(), primary_key=True),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "facts",
        sa.Column("fact_id", sa.Text(), primary_key=True),
        sa.Column("doc_id", sa.Text(), nullable=False),
        sa.Column("printed_pages", sa.Text(), nullable=True),
        sa.Column("chapter", sa.Text(), nullable=True),
        sa.Column("statement", sa.Text(), nullable=True),
        sa.Column("note_no", sa.Text(), nullable=True),
        sa.Column("table_title", sa.Text(), nullable=True),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("label_norm", sa.Text(), nullable=True),
        sa.Column("parent_label", sa.Text(), nullable=True),
        sa.Column("row_level", sa.Integer(), nullable=True),
        sa.Column("is_total", sa.Boolean(), nullable=True),
        sa.Column("col_path", sa.Text(), nullable=True),
        sa.Column("period", sa.Text(), nullable=True),
        sa.Column("value", ExactNumeric(38, 6), nullable=True),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.Column("value_vnd", ExactNumeric(38, 0), nullable=True),
        sa.Column("raw", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("pdf_page", sa.Integer(), nullable=True),
        sa.Column("bbox", sa.Text(), nullable=True),
        sa.Column("direction", sa.Text(), nullable=True),
        sa.Column("change_basis", sa.Text(), nullable=True),
    )
    op.create_index("ix_facts_lookup", "facts", ["doc_id", "statement", "note_no", "period"])
    op.create_table(
        "sessions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Text(), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("state_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_messages_session_id", "messages", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_messages_session_id", table_name="messages")
    op.drop_table("messages")
    op.drop_table("sessions")
    op.drop_index("ix_facts_lookup", table_name="facts")
    op.drop_table("facts")
    op.drop_table("index_versions")
    op.drop_table("documents")
