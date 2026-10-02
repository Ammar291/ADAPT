"""research: research_jobs, research_results, research_citations (owner-only RLS)

Asynchronous Abu Dhabi research (communities, faith & worship, professional networks,
events, culture, lifestyle, starter kit). Results carry a trust tier (law / official
guidance / community information / AI recommendation) and a source label; CHECKs make an
official claim without an official source impossible to store.

Revision ID: 0003_research
Revises: 0002
Create Date: 2026-09-29 16:30:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db import rls

revision: str = "0003_research"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen copies of the vocabularies at this revision.
TABLES: tuple[str, ...] = ("research_jobs", "research_results", "research_citations")
CATEGORIES = (
    "'community', 'faith_and_worship', 'professional_network', 'events', 'culture', "
    "'lifestyle', 'starter_kit'"
)
EVIDENCE_KINDS = (
    "'authoritative_requirement', 'official_guidance', 'community_web', 'ai_recommendation'"
)
SOURCE_LABELS = "'official', 'organization', 'community', 'general_web'"


def _owned() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column(
            "tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
    ]


def _id() -> sa.Column:  # type: ignore[type-arg]
    return sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True)


def _ts(name: str) -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "research_jobs",
        _id(),
        sa.Column(
            "run_id",
            sa.UUID(),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("journey_id", sa.UUID(), sa.ForeignKey("journeys.id", ondelete="SET NULL")),
        sa.Column("categories", postgresql.ARRAY(sa.String(length=40)), nullable=False),
        sa.Column(
            "category_status",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "profile",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("seen_at", sa.DateTime(timezone=True)),
        _ts("created_at"),
        _ts("updated_at"),
        *_owned(),
        sa.CheckConstraint("mode IN ('live', 'snapshot')", name="mode_valid"),
        sa.CheckConstraint(
            f"categories <@ ARRAY[{CATEGORIES}]::varchar[]", name="categories_valid"
        ),
        sa.CheckConstraint("cardinality(categories) > 0", name="categories_present"),
    )
    op.create_index("ix_research_jobs_user_id", "research_jobs", ["user_id"])
    op.create_index("ix_research_jobs_user_created", "research_jobs", ["user_id", "created_at"])

    op.create_table(
        "research_results",
        _id(),
        sa.Column(
            "job_id",
            sa.UUID(),
            sa.ForeignKey("research_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("relevance", sa.Text(), nullable=False),
        sa.Column("evidence_kind", sa.String(length=40), nullable=False),
        sa.Column("source_label", sa.String(length=20), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("canonical_url", sa.String(length=2048), nullable=False),
        sa.Column("source_title", sa.String(length=500), nullable=False),
        sa.Column("source_domain", sa.String(length=255), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=64), nullable=False),
        sa.Column(
            "contacts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("event_starts_on", sa.Date()),
        sa.Column("event_ends_on", sa.Date()),
        sa.Column("event_timing", sa.String(length=200)),
        sa.Column(
            "fact_keys",
            postgresql.ARRAY(sa.String(length=40)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("saved_at", sa.DateTime(timezone=True)),
        sa.Column(
            "journey_node_id", sa.UUID(), sa.ForeignKey("journey_nodes.id", ondelete="SET NULL")
        ),
        _ts("created_at"),
        _ts("updated_at"),
        *_owned(),
        sa.CheckConstraint(f"category IN ({CATEGORIES})", name="category_valid"),
        sa.CheckConstraint(f"evidence_kind IN ({EVIDENCE_KINDS})", name="evidence_kind_valid"),
        sa.CheckConstraint(f"source_label IN ({SOURCE_LABELS})", name="source_label_valid"),
        sa.CheckConstraint(
            "evidence_kind NOT IN ('authoritative_requirement', 'official_guidance') "
            "OR source_label = 'official'",
            name="official_claims_need_official_source",
        ),
        sa.CheckConstraint(
            "source_label <> 'official' OR starts_with(source_url, 'https://')",
            name="official_sources_are_https",
        ),
        sa.CheckConstraint(
            "starts_with(source_url, 'http://') OR starts_with(source_url, 'https://')",
            name="source_url_is_web",
        ),
        sa.CheckConstraint("quality_score BETWEEN 0 AND 1", name="quality_score_range"),
        sa.CheckConstraint(
            "event_ends_on IS NULL OR event_starts_on IS NULL OR event_ends_on >= event_starts_on",
            name="event_dates_ordered",
        ),
        sa.UniqueConstraint("job_id", "category", "dedupe_key", name="uq_research_results_dedupe"),
    )
    op.create_index("ix_research_results_job_id", "research_results", ["job_id"])
    op.create_index("ix_research_results_user_id", "research_results", ["user_id"])
    op.create_index("ix_research_results_user_saved", "research_results", ["user_id", "saved_at"])

    op.create_table(
        "research_citations",
        _id(),
        sa.Column(
            "job_id",
            sa.UUID(),
            sa.ForeignKey("research_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "result_id",
            sa.UUID(),
            sa.ForeignKey("research_results.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("canonical_url", sa.String(length=2048), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("source_domain", sa.String(length=255), nullable=False),
        sa.Column("source_label", sa.String(length=20), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        _ts("created_at"),
        *_owned(),
        sa.CheckConstraint(f"category IN ({CATEGORIES})", name="category_valid"),
        sa.CheckConstraint(f"source_label IN ({SOURCE_LABELS})", name="source_label_valid"),
        sa.CheckConstraint(
            "starts_with(url, 'http://') OR starts_with(url, 'https://')", name="url_is_web"
        ),
        sa.UniqueConstraint("result_id", "canonical_url", name="uq_research_citations_result_url"),
    )
    op.create_index("ix_research_citations_job_id", "research_citations", ["job_id"])
    op.create_index("ix_research_citations_result_id", "research_citations", ["result_id"])
    op.create_index("ix_research_citations_user_id", "research_citations", ["user_id"])

    for table in TABLES:
        for statement in rls.private_table_sql(table):
            op.execute(statement)


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
