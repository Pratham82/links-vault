"""requeue instagram links saved with the login-wall preview

Revision ID: 7b3f1c9d2a4e
Revises: 2e626bfd3a4f
Create Date: 2026-09-26 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "7b3f1c9d2a4e"
down_revision: str | None = "2e626bfd3a4f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Before this fix, a post Instagram hid behind its login wall was saved as "enriched" with the
# title "Instagram" and no image. Clear that and put those links back in the enrichment queue.
_REQUEUE = """
    UPDATE links
    SET status = 'pending',
        title = NULL,
        description = NULL,
        enrich_attempts = 0,
        next_attempt_at = NULL
    WHERE content_type = 'instagram'
      AND status = 'enriched'
      AND image_url IS NULL
      AND (title IS NULL OR lower(title) IN ('instagram', 'login • instagram'))
"""


def upgrade() -> None:
    op.execute(_REQUEUE)


def downgrade() -> None:
    # Nothing to undo: the worker re-fetches these links either way.
    pass
