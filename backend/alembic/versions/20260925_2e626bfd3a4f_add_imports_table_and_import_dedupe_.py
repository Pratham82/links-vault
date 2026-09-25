"""add imports table and import dedupe index

Revision ID: 2e626bfd3a4f
Revises: e4e845be1e3b
Create Date: 2026-09-25 12:57:45.837667

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "2e626bfd3a4f"
down_revision: str | None = "e4e845be1e3b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Until now `POST /links` accepted source_channel=whatsapp_import without deduping it, so
# repeats may exist. Keep the earliest stored row of each (normalized_url, shared_at) so
# the unique index can be built. Plain SQL so this never depends on current app code.
_DELETE_DUPLICATE_IMPORTS = """
    DELETE FROM links USING (
        SELECT id,
               row_number() OVER (
                   PARTITION BY normalized_url, shared_at ORDER BY created_at, id
               ) AS position
        FROM links
        WHERE source_channel = 'whatsapp_import'
    ) AS ranked
    WHERE links.id = ranked.id AND ranked.position > 1
"""


def upgrade() -> None:
    op.create_table(
        "imports",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(_DELETE_DUPLICATE_IMPORTS)
    op.create_index(
        "uq_links_normalized_url_shared_at_import",
        "links",
        ["normalized_url", "shared_at"],
        unique=True,
        postgresql_where=sa.text("source_channel = 'whatsapp_import'"),
    )


def downgrade() -> None:
    # Rows deleted by upgrade() stay deleted.
    op.drop_index("uq_links_normalized_url_shared_at_import", table_name="links")
    op.drop_table("imports")
