"""research: research_results.fact_ids (the user facts behind each result's relevance)

Stores the ids of the stored user facts (`extracted_facts`) a result's "why this is
relevant" used, so `app.personalization.facts.explain` can show them. Only facts used
under the consent rules are recorded.

Revision ID: 0005_research_fact_ids
Revises: 0004_user_data
Create Date: 2026-09-29 18:30:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_research_fact_ids"
down_revision: str | None = "0004_user_data"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "research_results",
        sa.Column(
            "fact_ids",
            postgresql.ARRAY(sa.String(length=64)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("research_results", "fact_ids")
