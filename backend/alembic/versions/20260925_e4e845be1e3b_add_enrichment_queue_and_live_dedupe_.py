"""add enrichment queue and live dedupe index

Revision ID: e4e845be1e3b
Revises: 65d309536b27
Create Date: 2026-09-25 11:09:05.036889

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e4e845be1e3b"
down_revision: str | None = "65d309536b27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Before Phase 2 every share became its own row. Fold rows with the same normalized_url
# into the earliest one (summing share_count, joining notes) so the unique index can be
# built. Written as plain SQL so this migration never depends on current app code.
_RANKED = """
    WITH ranked AS (
        SELECT id,
               first_value(id) OVER w AS keep_id,
               row_number() OVER w AS position
        FROM links
        WHERE source_channel <> 'whatsapp_import'
        WINDOW w AS (PARTITION BY normalized_url ORDER BY shared_at, created_at, id)
    )
"""
_MERGE_DUPLICATES = (
    _RANKED
    + """
    , merged AS (
        SELECT ranked.keep_id,
               sum(links.share_count) AS share_count,
               string_agg(links.note, E'\\n' ORDER BY ranked.position) AS note
        FROM ranked JOIN links ON links.id = ranked.id
        GROUP BY ranked.keep_id
        HAVING count(*) > 1
    )
    UPDATE links
    SET share_count = merged.share_count, note = merged.note
    FROM merged
    WHERE links.id = merged.keep_id
"""
)
_DELETE_DUPLICATES = (
    _RANKED
    + """
    DELETE FROM links USING ranked
    WHERE links.id = ranked.id AND ranked.position > 1
"""
)


def upgrade() -> None:
    op.add_column(
        "links",
        sa.Column("enrich_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column("links", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_links_enrich_queue",
        "links",
        ["next_attempt_at"],
        unique=False,
        postgresql_where=sa.text("status IN ('pending', 'failed')"),
    )
    op.execute(_MERGE_DUPLICATES)
    op.execute(_DELETE_DUPLICATES)
    op.create_index(
        "uq_links_normalized_url_live",
        "links",
        ["normalized_url"],
        unique=True,
        postgresql_where=sa.text("source_channel <> 'whatsapp_import'"),
    )


def downgrade() -> None:
    # Rows merged by upgrade() stay merged.
    op.drop_index("uq_links_normalized_url_live", table_name="links")
    op.drop_index("ix_links_enrich_queue", table_name="links")
    op.drop_column("links", "next_attempt_at")
    op.drop_column("links", "enrich_attempts")
