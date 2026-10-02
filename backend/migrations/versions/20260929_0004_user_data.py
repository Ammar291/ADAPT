"""user data: user_documents, extracted_facts, review_tasks (owner-only RLS)

The private user digital twin's facts and the document pipeline:

* `user_documents`: uploads (bytes encrypted in document storage) with a lifecycle
  uploaded → processing → extracted | needs_review → confirmed; failed; deleted.
* `extracted_facts`: every personal detail with provenance (value, confidence, source,
  source document, extraction method). One accepted and at most one pending value per
  (entity, attribute).
* `review_tasks`: what the person needs to check.

Security (hand-written): owner-only RLS on all three, and triggers that reject references
to governance nodes or to another user's nodes, documents or facts (FK checks bypass RLS).
User-graph nodes stop carrying facts in `properties_json`: any existing ones are moved
into `extracted_facts`, then a CHECK keeps it that way, so public knowledge and private
facts never share a JSON blob.

Revision ID: 0004_user_data
Revises: 0003_research
Create Date: 2026-09-29 18:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db import rls

revision: str = "0004_user_data"
down_revision: str | None = "0003_research"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen copies of the vocabularies at this revision.
TABLES: tuple[str, ...] = ("user_documents", "extracted_facts", "review_tasks")
KINDS = (
    "'passport', 'marriage_certificate', 'employment_letter', 'business_document', "
    "'tenancy_document', 'identity_document', 'miscellaneous'"
)
STATUSES = "'uploaded', 'processing', 'extracted', 'needs_review', 'confirmed', 'failed', 'deleted'"
SUBJECTS = "'self', 'spouse', 'child'"
FACT_SOURCES = "'user_stated', 'document_extracted', 'inferred', 'system'"
FACT_STATUSES = "'accepted', 'needs_review'"
TASK_KINDS = "'low_confidence', 'conflict', 'extraction_failed', 'kind_mismatch'"
TASK_STATUSES = "'open', 'resolved', 'dismissed'"
RESOLUTIONS = "'confirmed', 'corrected', 'rejected', 'dismissed', 'superseded'"

JSONB = postgresql.JSONB(astext_type=sa.Text())


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
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _check(table: str, name: str, sql: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(sql, name=op.f(f"ck_{table}_{name}"))


REFERENCE_TRIGGERS_SQL = """
CREATE OR REPLACE FUNCTION user_data_check_node(node uuid, owner uuid) RETURNS void
  LANGUAGE plpgsql AS $$
BEGIN
  -- SECURITY INVOKER: under RLS other users' nodes are invisible anyway; the explicit
  -- predicate also rejects governance nodes, which are world-readable.
  IF node IS NULL THEN RETURN; END IF;
  PERFORM 1 FROM graph_nodes WHERE id = node AND graph_type = 'user' AND user_id = owner;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'node % is not part of this user''s private graph', node
      USING ERRCODE = 'check_violation';
  END IF;
END $$;

CREATE OR REPLACE FUNCTION user_data_check_document(doc uuid, owner uuid) RETURNS void
  LANGUAGE plpgsql AS $$
BEGIN
  IF doc IS NULL THEN RETURN; END IF;
  PERFORM 1 FROM user_documents WHERE id = doc AND user_id = owner;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'document % does not belong to this user', doc
      USING ERRCODE = 'check_violation';
  END IF;
END $$;

CREATE OR REPLACE FUNCTION extracted_facts_enforce_refs() RETURNS trigger
  LANGUAGE plpgsql AS $$
BEGIN
  PERFORM user_data_check_node(NEW.node_id, NEW.user_id);
  PERFORM user_data_check_document(NEW.source_document_id, NEW.user_id);
  RETURN NEW;
END $$;

CREATE TRIGGER extracted_facts_enforce_refs
  BEFORE INSERT OR UPDATE ON extracted_facts
  FOR EACH ROW EXECUTE FUNCTION extracted_facts_enforce_refs();

CREATE OR REPLACE FUNCTION review_tasks_enforce_refs() RETURNS trigger
  LANGUAGE plpgsql AS $$
BEGIN
  PERFORM user_data_check_document(NEW.document_id, NEW.user_id);
  IF NEW.fact_id IS NOT NULL THEN
    PERFORM 1 FROM extracted_facts WHERE id = NEW.fact_id AND user_id = NEW.user_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'fact % does not belong to this user', NEW.fact_id
        USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER review_tasks_enforce_refs
  BEFORE INSERT OR UPDATE ON review_tasks
  FOR EACH ROW EXECUTE FUNCTION review_tasks_enforce_refs();

CREATE OR REPLACE FUNCTION user_documents_enforce_refs() RETURNS trigger
  LANGUAGE plpgsql AS $$
BEGIN
  PERFORM user_data_check_node(NEW.subject_node_id, NEW.user_id);
  PERFORM user_data_check_node(NEW.node_id, NEW.user_id);
  RETURN NEW;
END $$;

CREATE TRIGGER user_documents_enforce_refs
  BEFORE INSERT OR UPDATE ON user_documents
  FOR EACH ROW EXECUTE FUNCTION user_documents_enforce_refs();
"""

DROP_REFERENCE_TRIGGERS_SQL = """
DROP FUNCTION IF EXISTS extracted_facts_enforce_refs() CASCADE;
DROP FUNCTION IF EXISTS review_tasks_enforce_refs() CASCADE;
DROP FUNCTION IF EXISTS user_documents_enforce_refs() CASCADE;
DROP FUNCTION IF EXISTS user_data_check_node(uuid, uuid);
DROP FUNCTION IF EXISTS user_data_check_document(uuid, uuid);
"""

# Facts the interim onboarding projection stored in properties_json move to extracted_facts.
MIGRATE_PROPERTY_FACTS_SQL = """
INSERT INTO extracted_facts (
  tenant_id, user_id, node_id, attribute, value, confidence, source, source_ref,
  status, confirmed_by_user, observed_at
)
SELECT n.tenant_id, n.user_id, n.id, left(p.key, 60), p.value -> 'value',
       least(greatest(coalesce((p.value ->> 'confidence')::float, 1.0), 0.0), 1.0),
       CASE WHEN p.value ->> 'source' IN ('inferred', 'system') THEN p.value ->> 'source'
            ELSE 'user_stated' END,
       left(p.value ->> 'source_ref', 200),
       'accepted',
       coalesce((p.value ->> 'confirmed_by_user')::boolean, false),
       now()
FROM graph_nodes n, jsonb_each(n.properties_json) p
WHERE n.graph_type = 'user'
  AND jsonb_typeof(p.value) = 'object'
  AND p.value ? 'value'
  AND p.value -> 'value' <> 'null'::jsonb
ON CONFLICT DO NOTHING;

UPDATE graph_nodes SET properties_json = '{}'::jsonb
WHERE graph_type = 'user' AND properties_json <> '{}'::jsonb;
"""


def upgrade() -> None:
    op.create_table(
        "user_documents",
        _id(),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("declared_kind", sa.String(length=40)),
        sa.Column("kind_confidence", sa.Float()),
        sa.Column("subject", sa.String(length=40), server_default="self", nullable=False),
        sa.Column(
            "subject_node_id", sa.UUID(), sa.ForeignKey("graph_nodes.id", ondelete="SET NULL")
        ),
        sa.Column("node_id", sa.UUID(), sa.ForeignKey("graph_nodes.id", ondelete="SET NULL")),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64)),
        sa.Column("storage_key", sa.String(length=300), unique=True),
        sa.Column("status", sa.String(length=40), server_default="uploaded", nullable=False),
        sa.Column("status_reason", sa.String(length=300)),
        sa.Column("extraction", JSONB),
        sa.Column(
            "extraction_run_id", sa.UUID(), sa.ForeignKey("agent_runs.id", ondelete="SET NULL")
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        _ts("created_at"),
        _ts("updated_at"),
        *_owned(),
        _check("user_documents", "kind_valid", f"kind IN ({KINDS})"),
        _check("user_documents", "declared_kind_valid", f"declared_kind IN ({KINDS})"),
        _check("user_documents", "status_valid", f"status IN ({STATUSES})"),
        _check("user_documents", "subject_valid", f"subject IN ({SUBJECTS})"),
        _check(
            "user_documents",
            "deleted_at_matches_status",
            "(status = 'deleted') = (deleted_at IS NOT NULL)",
        ),
        _check(
            "user_documents",
            "live_documents_have_bytes",
            "status = 'deleted' OR (storage_key IS NOT NULL AND size_bytes > 0)",
        ),
        _check(
            "user_documents",
            "kind_confidence_range",
            "kind_confidence IS NULL OR kind_confidence BETWEEN 0 AND 1",
        ),
    )
    op.create_index("ix_user_documents_user_created", "user_documents", ["user_id", "created_at"])
    op.create_index(op.f("ix_user_documents_user_id"), "user_documents", ["user_id"])

    op.create_table(
        "extracted_facts",
        _id(),
        sa.Column(
            "node_id",
            sa.UUID(),
            sa.ForeignKey("graph_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attribute", sa.String(length=60), nullable=False),
        sa.Column("value", JSONB),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column(
            "source_document_id",
            sa.UUID(),
            sa.ForeignKey("user_documents.id", ondelete="CASCADE"),
        ),
        sa.Column("source_ref", sa.String(length=200)),
        sa.Column("extraction_method", sa.String(length=80)),
        sa.Column("field", sa.String(length=60)),
        sa.Column("status", sa.String(length=40), server_default="accepted", nullable=False),
        sa.Column(
            "confirmed_by_user", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("corrected", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("issues", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        _ts("observed_at"),
        _ts("created_at"),
        _ts("updated_at"),
        *_owned(),
        _check("extracted_facts", "source_valid", f"source IN ({FACT_SOURCES})"),
        _check("extracted_facts", "status_valid", f"status IN ({FACT_STATUSES})"),
        _check("extracted_facts", "confidence_range", "confidence BETWEEN 0 AND 1"),
        _check(
            "extracted_facts",
            "accepted_facts_have_values",
            "status <> 'accepted' OR (value IS NOT NULL AND value <> 'null'::jsonb)",
        ),
        _check(
            "extracted_facts",
            "extracted_facts_cite_document",
            "source <> 'document_extracted' "
            "OR (source_document_id IS NOT NULL AND extraction_method IS NOT NULL)",
        ),
        _check(
            "extracted_facts",
            "faith_is_user_stated",
            "attribute <> 'faith_community' OR source = 'user_stated'",
        ),
    )
    op.create_index(
        "uq_extracted_facts_accepted",
        "extracted_facts",
        ["node_id", "attribute"],
        unique=True,
        postgresql_where=sa.text("status = 'accepted'"),
    )
    op.create_index(
        "uq_extracted_facts_pending",
        "extracted_facts",
        ["node_id", "attribute"],
        unique=True,
        postgresql_where=sa.text("status = 'needs_review'"),
    )
    op.create_index(
        "ix_extracted_facts_source_document_id", "extracted_facts", ["source_document_id"]
    )
    op.create_index(op.f("ix_extracted_facts_user_id"), "extracted_facts", ["user_id"])

    op.create_table(
        "review_tasks",
        _id(),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("document_id", sa.UUID(), sa.ForeignKey("user_documents.id", ondelete="CASCADE")),
        sa.Column("fact_id", sa.UUID(), sa.ForeignKey("extracted_facts.id", ondelete="SET NULL")),
        sa.Column("field", sa.String(length=60)),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=40), server_default="open", nullable=False),
        sa.Column("resolution", sa.String(length=40)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        _ts("created_at"),
        _ts("updated_at"),
        *_owned(),
        _check("review_tasks", "kind_valid", f"kind IN ({TASK_KINDS})"),
        _check("review_tasks", "status_valid", f"status IN ({TASK_STATUSES})"),
        _check("review_tasks", "resolution_valid", f"resolution IN ({RESOLUTIONS})"),
        _check(
            "review_tasks",
            "resolved_at_matches_status",
            "(status = 'open') = (resolved_at IS NULL)",
        ),
        _check(
            "review_tasks",
            "resolution_matches_status",
            "(status = 'open') = (resolution IS NULL)",
        ),
    )
    op.create_index(
        "uq_review_tasks_open_fact",
        "review_tasks",
        ["fact_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open' AND fact_id IS NOT NULL"),
    )
    op.create_index("ix_review_tasks_user_status", "review_tasks", ["user_id", "status"])
    op.create_index(op.f("ix_review_tasks_document_id"), "review_tasks", ["document_id"])
    op.create_index(op.f("ix_review_tasks_user_id"), "review_tasks", ["user_id"])

    # --- security (hand-written) -------------------------------------------------
    op.execute(REFERENCE_TRIGGERS_SQL)
    for table in TABLES:
        for statement in rls.private_table_sql(table):
            op.execute(statement)

    op.execute(MIGRATE_PROPERTY_FACTS_SQL)
    op.create_check_constraint(
        op.f("ck_graph_nodes_user_nodes_have_no_properties"),
        "graph_nodes",
        "graph_type = 'governance' OR properties_json = '{}'::jsonb",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_graph_nodes_user_nodes_have_no_properties"), "graph_nodes", type_="check"
    )
    op.execute(DROP_REFERENCE_TRIGGERS_SQL)
    for table in reversed(TABLES):
        op.drop_table(table)
