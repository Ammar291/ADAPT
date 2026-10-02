"""domain model v2: spec entities, graph_type graphs, governance corpus, catalogue

Replaces the foundation's provisional tables with the ADAPT domain model:

* graph_nodes / graph_edges use the spec vocabulary (graph_type governance|user,
  entity_type, relation, source_node_id/target_node_id, properties_json, source_id);
* governance_sources / governance_documents / governance_chunks replace rag_sources /
  rag_chunks (pgvector HNSW + tsvector), with node AND edge evidence links;
* private tables: user_profiles, household_members, user_preferences, user_goals,
  journeys, journey_nodes, journey_edges, agent_runs, agent_events, generated_documents,
  actions, action_approvals, appointments (all owner-only RLS);
* public catalogue: communities, events, cultural_guides;
* users gain an identity-provider link (resolved by a narrow SECURITY DEFINER lookup), and
  tenants/users get RLS of their own;
* a trigger stops actions moving past approval without an approved human decision.

DATA: the foundation's private demo rows (runs, documents, journeys, drafts, approvals)
and both graphs are dropped and rebuilt empty — the governance graph and the catalogue
are re-seeded by `python -m app.seed`. Accounts (tenants/users) are kept. The downgrade
restores revision 0001's schema (again without data).

Tables of feature workstreams (user documents, extracted facts, research) are created by
their own later revisions.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-29 14:00:00.000000+00:00
"""

from collections.abc import Sequence
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db import rls

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen: the tables this revision creates and how they are protected.
PRIVATE_TABLES_0002: tuple[str, ...] = (
    "user_profiles",
    "household_members",
    "user_preferences",
    "user_goals",
    "journeys",
    "journey_nodes",
    "journey_edges",
    "agent_runs",
    "agent_events",
    "generated_documents",
    "actions",
    "action_approvals",
    "appointments",
)
PUBLIC_TABLES_0002: tuple[str, ...] = (
    "governance_sources",
    "governance_documents",
    "governance_chunks",
    "graph_node_evidence",
    "graph_edge_evidence",
    "communities",
    "events",
    "cultural_guides",
)
GRAPH_TABLES_0002: tuple[str, ...] = ("graph_nodes", "graph_edges")

# Frozen when the runtime builder gained owner/expiry/scope checks in revision 0006.
ACTION_APPROVAL_TRIGGER_0002 = """
CREATE OR REPLACE FUNCTION actions_require_approved_approval() RETURNS trigger
  LANGUAGE plpgsql AS $$
DECLARE a_status text; a_action uuid;
BEGIN
  IF NEW.status IN ('approved', 'submitted', 'completed') THEN
    SELECT status, action_id INTO a_status, a_action
      FROM action_approvals WHERE id = NEW.approval_id;
    IF NOT FOUND OR a_status <> 'approved' OR a_action <> NEW.id THEN
      RAISE EXCEPTION 'action % needs an approved approval before status %', NEW.id, NEW.status
        USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER actions_require_approved_approval
  BEFORE INSERT OR UPDATE ON actions
  FOR EACH ROW EXECUTE FUNCTION actions_require_approved_approval();
"""


def _revision_0001() -> ModuleType:
    path = Path(__file__).with_name("20260929_0001_initial_schema.py")
    spec = spec_from_file_location("adapt_migration_0001", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def upgrade() -> None:
    _revision_0001().drop_content_tables()

    op.add_column(
        "users",
        sa.Column("auth_provider", sa.String(length=40), server_default="demo", nullable=False),
    )
    op.add_column("users", sa.Column("auth_subject", sa.String(length=255), nullable=True))
    op.create_index(
        "uq_users_auth_identity",
        "users",
        ["auth_provider", "auth_subject"],
        unique=True,
        postgresql_where=sa.text("auth_subject IS NOT NULL"),
    )

    _create_tables()
    op.create_foreign_key(
        "fk_actions_approval_id_action_approvals",
        "actions",
        "action_approvals",
        ["approval_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.execute(rls.GRAPH_EDGE_TRIGGER_SQL)
    op.execute(ACTION_APPROVAL_TRIGGER_0002)
    statements: list[str] = []
    for table in PRIVATE_TABLES_0002:
        statements += rls.private_table_sql(table)
    for table in GRAPH_TABLES_0002:
        statements += rls.graph_table_sql(table)
    for table in PUBLIC_TABLES_0002:
        statements += rls.public_read_sql(table)
    statements += rls.account_policies_sql()
    statements += rls.identity_function_sql()
    statements += rls.sequences_grant_sql()
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    op.execute(rls.DROP_IDENTITY_FUNCTION_SQL)
    for statement in rls.DROP_ACCOUNT_POLICIES_SQL:
        op.execute(statement)
    op.execute(rls.DROP_ACTION_APPROVAL_TRIGGER_SQL)
    op.execute(rls.DROP_GRAPH_EDGE_TRIGGER_SQL)
    op.drop_constraint("fk_actions_approval_id_action_approvals", "actions", type_="foreignkey")
    _drop_tables()
    op.drop_index(
        "uq_users_auth_identity",
        table_name="users",
        postgresql_where=sa.text("auth_subject IS NOT NULL"),
    )
    op.drop_column("users", "auth_subject")
    op.drop_column("users", "auth_provider")

    rev0001 = _revision_0001()
    rev0001.create_content_tables()
    rev0001.secure_content_tables()
    for statement in rls.sequences_grant_sql():
        op.execute(statement)


def _create_tables() -> None:
    # ### autogenerated DDL (tenants/users excluded) ###
    op.create_table('communities',
    sa.Column('key', sa.String(length=120), nullable=False),
    sa.Column('name', sa.String(length=300), nullable=False),
    sa.Column('category', sa.Enum('professional', 'social', 'cultural', 'family', 'sports', 'language', 'volunteering', 'faith', name='communitycategory', native_enum=False, length=40), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('languages', postgresql.ARRAY(sa.String(length=35)), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('area', sa.String(length=200), nullable=True),
    sa.Column('website_url', sa.String(length=2048), nullable=True),
    sa.Column('tags', postgresql.ARRAY(sa.String(length=60)), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('source_url', sa.String(length=2048), nullable=True),
    sa.Column('source_title', sa.String(length=500), nullable=True),
    sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('evidence_kind', sa.Enum('authoritative_requirement', 'official_guidance', 'community_web', 'ai_recommendation', name='evidencekind', native_enum=False, length=40), nullable=False),
    sa.Column('is_sample', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.CheckConstraint("category IN ('professional', 'social', 'cultural', 'family', 'sports', 'language', 'volunteering', 'faith')", name=op.f('ck_communities_category_valid')),
    sa.CheckConstraint("evidence_kind <> 'authoritative_requirement'", name=op.f('ck_communities_never_authoritative')),
    sa.CheckConstraint("evidence_kind IN ('authoritative_requirement', 'official_guidance', 'community_web', 'ai_recommendation')", name=op.f('ck_communities_evidence_kind_valid')),
    sa.CheckConstraint('is_sample OR source_url IS NOT NULL', name=op.f('ck_communities_cited_or_sample')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_communities')),
    sa.UniqueConstraint('key', name='uq_communities_key')
    )
    op.create_index('ix_communities_category', 'communities', ['category'], unique=False)
    op.create_table('cultural_guides',
    sa.Column('key', sa.String(length=120), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('topic', sa.Enum('etiquette', 'ramadan', 'public_holidays', 'dress', 'workplace', 'family_life', 'language', 'heritage', 'arts', 'climate', 'government_services', 'health', 'transport', 'safety', 'utilities', name='guidetopic', native_enum=False, length=40), nullable=False),
    sa.Column('section', sa.String(length=40), server_default='culture', nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('body_markdown', sa.Text(), nullable=False),
    sa.Column('language', sa.String(length=35), server_default='en', nullable=False),
    sa.Column('authority', sa.String(length=200), nullable=True),
    sa.Column('binding', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('position', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('source_url', sa.String(length=2048), nullable=True),
    sa.Column('source_title', sa.String(length=500), nullable=True),
    sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('evidence_kind', sa.Enum('authoritative_requirement', 'official_guidance', 'community_web', 'ai_recommendation', name='evidencekind', native_enum=False, length=40), nullable=False),
    sa.Column('is_sample', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.CheckConstraint("evidence_kind <> 'authoritative_requirement'", name=op.f('ck_cultural_guides_never_authoritative')),
    sa.CheckConstraint("evidence_kind IN ('authoritative_requirement', 'official_guidance', 'community_web', 'ai_recommendation')", name=op.f('ck_cultural_guides_evidence_kind_valid')),
    sa.CheckConstraint("section IN ('culture', 'surprises', 'starter_kit')", name=op.f('ck_cultural_guides_section_valid')),
    sa.CheckConstraint("topic IN ('etiquette', 'ramadan', 'public_holidays', 'dress', 'workplace', 'family_life', 'language', 'heritage', 'arts', 'climate', 'government_services', 'health', 'transport', 'safety', 'utilities')", name=op.f('ck_cultural_guides_topic_valid')),
    sa.CheckConstraint('is_sample OR source_url IS NOT NULL', name=op.f('ck_cultural_guides_cited_or_sample')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_cultural_guides')),
    sa.UniqueConstraint('key', name='uq_cultural_guides_key')
    )
    op.create_table('governance_sources',
    sa.Column('key', sa.String(length=120), nullable=False),
    sa.Column('name', sa.String(length=300), nullable=False),
    sa.Column('authority', sa.String(length=200), nullable=True),
    sa.Column('base_url', sa.String(length=2048), nullable=False),
    sa.Column('source_type', sa.String(length=60), nullable=False),
    sa.Column('is_official', sa.Boolean(), nullable=False),
    sa.Column('priority', sa.Integer(), server_default=sa.text('100'), nullable=False),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_governance_sources')),
    sa.UniqueConstraint('key', name='uq_governance_sources_key')
    )
    op.create_index('ix_governance_sources_authority', 'governance_sources', ['authority'], unique=False)
    op.create_table('events',
    sa.Column('key', sa.String(length=120), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('category', sa.Enum('networking', 'culture', 'family', 'sports', 'education', 'community', 'faith', name='eventcategory', native_enum=False, length=40), nullable=False),
    sa.Column('starts_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('timing_note', sa.String(length=200), nullable=True),
    sa.Column('ends_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('venue', sa.String(length=300), nullable=True),
    sa.Column('area', sa.String(length=200), nullable=True),
    sa.Column('community_id', sa.UUID(), nullable=True),
    sa.Column('url', sa.String(length=2048), nullable=True),
    sa.Column('is_free', sa.Boolean(), nullable=True),
    sa.Column('languages', postgresql.ARRAY(sa.String(length=35)), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('tags', postgresql.ARRAY(sa.String(length=60)), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('source_url', sa.String(length=2048), nullable=True),
    sa.Column('source_title', sa.String(length=500), nullable=True),
    sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('evidence_kind', sa.Enum('authoritative_requirement', 'official_guidance', 'community_web', 'ai_recommendation', name='evidencekind', native_enum=False, length=40), nullable=False),
    sa.Column('is_sample', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.CheckConstraint("category IN ('networking', 'culture', 'family', 'sports', 'education', 'community', 'faith')", name=op.f('ck_events_category_valid')),
    sa.CheckConstraint("evidence_kind <> 'authoritative_requirement'", name=op.f('ck_events_never_authoritative')),
    sa.CheckConstraint("evidence_kind IN ('authoritative_requirement', 'official_guidance', 'community_web', 'ai_recommendation')", name=op.f('ck_events_evidence_kind_valid')),
    sa.CheckConstraint('ends_at IS NULL OR starts_at IS NULL OR ends_at >= starts_at', name=op.f('ck_events_ends_after_start')),
    sa.CheckConstraint('starts_at IS NOT NULL OR timing_note IS NOT NULL', name=op.f('ck_events_has_timing')),
    sa.CheckConstraint('is_sample OR source_url IS NOT NULL', name=op.f('ck_events_cited_or_sample')),
    sa.ForeignKeyConstraint(['community_id'], ['communities.id'], name=op.f('fk_events_community_id_communities'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_events')),
    sa.UniqueConstraint('key', name='uq_events_key')
    )
    op.create_index('ix_events_starts_at', 'events', ['starts_at'], unique=False)
    op.create_table('governance_documents',
    sa.Column('governance_source_id', sa.UUID(), nullable=True),
    sa.Column('source_url', sa.String(length=2048), nullable=False),
    sa.Column('title', sa.String(length=500), nullable=False),
    sa.Column('authority', sa.String(length=200), nullable=True),
    sa.Column('document_type', sa.String(length=60), nullable=False),
    sa.Column('language', sa.String(length=35), server_default='en', nullable=False),
    sa.Column('effective_date', sa.Date(), nullable=True),
    sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('is_official', sa.Boolean(), nullable=False),
    sa.Column('superseded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['governance_source_id'], ['governance_sources.id'], name=op.f('fk_governance_documents_governance_source_id_governance_sources'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_governance_documents')),
    sa.UniqueConstraint('source_url', 'content_hash', name='uq_governance_documents_url_hash')
    )
    op.create_index('ix_governance_documents_authority', 'governance_documents', ['authority'], unique=False)
    op.create_index('ix_governance_documents_document_type', 'governance_documents', ['document_type'], unique=False)
    op.create_index(op.f('ix_governance_documents_governance_source_id'), 'governance_documents', ['governance_source_id'], unique=False)
    op.create_index('uq_governance_documents_live_url', 'governance_documents', ['source_url'], unique=True, postgresql_where=sa.text('superseded_at IS NULL'))
    op.create_table('governance_chunks',
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('chunk_index', sa.Integer(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('context', sa.Text(), nullable=True),
    sa.Column('section', sa.String(length=500), nullable=True),
    sa.Column('page', sa.Integer(), nullable=True),
    sa.Column('page_or_section', sa.Text(), sa.Computed("coalesce(section, 'p. ' || page::text)", persisted=True), nullable=True),
    sa.Column('token_count', sa.Integer(), nullable=True),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=1536), nullable=True),
    sa.Column('embedding_model', sa.String(length=120), nullable=True),
    sa.Column('content_tsv', postgresql.TSVECTOR(), sa.Computed("to_tsvector('simple', coalesce(context, '') || ' ' || content)", persisted=True), nullable=False),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['governance_documents.id'], name=op.f('fk_governance_chunks_document_id_governance_documents'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_governance_chunks')),
    sa.UniqueConstraint('document_id', 'chunk_index', name='uq_governance_chunks_document_index')
    )
    op.create_index('ix_governance_chunks_content_tsv', 'governance_chunks', ['content_tsv'], unique=False, postgresql_using='gin')
    op.create_index(op.f('ix_governance_chunks_document_id'), 'governance_chunks', ['document_id'], unique=False)
    op.create_index('ix_governance_chunks_embedding', 'governance_chunks', ['embedding'], unique=False, postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.create_index('ix_governance_chunks_embedding_model', 'governance_chunks', ['embedding_model'], unique=False)
    op.create_table('graph_nodes',
    sa.Column('graph_type', sa.Enum('governance', 'user', name='graphtype', native_enum=False, length=20), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=True),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('entity_type', sa.String(length=40), nullable=False),
    sa.Column('key', sa.String(length=200), nullable=False),
    sa.Column('label', sa.String(length=300), nullable=False),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('properties_json', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('source_id', sa.UUID(), nullable=True),
    sa.Column('provenance', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('official_url', sa.String(length=2048), nullable=True),
    sa.Column('valid_from', sa.Date(), nullable=True),
    sa.Column('valid_to', sa.Date(), nullable=True),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=1536), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(graph_type = 'governance' AND entity_type IN ('authority', 'service', 'requirement', 'eligibility_rule', 'document', 'dependency', 'appointment', 'portal', 'location', 'process_step', 'fee', 'legal_instrument')) OR (graph_type = 'user' AND entity_type IN ('person', 'household', 'spouse', 'child', 'passport', 'visa', 'nationality', 'company', 'business_activity', 'goal', 'housing_preference', 'budget', 'language', 'preference', 'document', 'appointment', 'community_preference'))", name=op.f('ck_graph_nodes_entity_type_matches_graph')),
    sa.CheckConstraint("(graph_type = 'governance' AND tenant_id IS NULL AND user_id IS NULL) OR (graph_type = 'user' AND tenant_id IS NOT NULL AND user_id IS NOT NULL)", name=op.f('ck_graph_nodes_ownership_matches_graph')),
    sa.CheckConstraint("graph_type IN ('governance', 'user')", name=op.f('ck_graph_nodes_graph_type_valid')),
    sa.CheckConstraint("key ~ '^[a-z0-9_]+(\\.[a-z0-9_:-]+)*$'", name=op.f('ck_graph_nodes_key_format')),
    sa.ForeignKeyConstraint(['source_id'], ['governance_sources.id'], name=op.f('fk_graph_nodes_source_id_governance_sources'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_graph_nodes_tenant_id_tenants'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_graph_nodes_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_graph_nodes'))
    )
    op.create_index('ix_graph_nodes_embedding', 'graph_nodes', ['embedding'], unique=False, postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.create_index('ix_graph_nodes_graph_type_entity_type', 'graph_nodes', ['graph_type', 'entity_type'], unique=False)
    op.create_index('ix_graph_nodes_properties_json', 'graph_nodes', ['properties_json'], unique=False, postgresql_using='gin')
    op.create_index(op.f('ix_graph_nodes_user_id'), 'graph_nodes', ['user_id'], unique=False)
    op.create_index('uq_graph_nodes_governance_key', 'graph_nodes', ['key'], unique=True, postgresql_where=sa.text("graph_type = 'governance'"))
    op.create_index('uq_graph_nodes_user_key', 'graph_nodes', ['user_id', 'key'], unique=True, postgresql_where=sa.text("graph_type = 'user'"))
    op.create_table('journeys',
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('status', sa.Enum('draft', 'active', 'scenario', 'archived', name='journeystatus', native_enum=False, length=40), server_default='draft', nullable=False),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('goals', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('assumptions', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('considerations', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('plan', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('simulation', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('parent_journey_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.CheckConstraint("status IN ('draft', 'active', 'scenario', 'archived')", name=op.f('ck_journeys_status_valid')),
    sa.ForeignKeyConstraint(['parent_journey_id'], ['journeys.id'], name=op.f('fk_journeys_parent_journey_id_journeys'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_journeys_tenant_id_tenants'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_journeys_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_journeys'))
    )
    op.create_index(op.f('ix_journeys_user_id'), 'journeys', ['user_id'], unique=False)
    op.create_index('ix_journeys_user_updated', 'journeys', ['user_id', 'updated_at'], unique=False)
    op.create_table('user_profiles',
    sa.Column('preferred_name', sa.String(length=120), nullable=True),
    sa.Column('nationality', sa.String(length=3), nullable=True),
    sa.Column('country_of_residence', sa.String(length=3), nullable=True),
    sa.Column('date_of_birth', sa.Date(), nullable=True),
    sa.Column('occupation', sa.String(length=200), nullable=True),
    sa.Column('persona', sa.String(length=40), nullable=True),
    sa.Column('company_name', sa.String(length=200), nullable=True),
    sa.Column('business_activity', sa.String(length=300), nullable=True),
    sa.Column('monthly_income_aed', sa.Integer(), nullable=True),
    sa.Column('arrival_date', sa.Date(), nullable=True),
    sa.Column('target_city', sa.String(length=100), server_default='Abu Dhabi', nullable=False),
    sa.Column('languages', postgresql.ARRAY(sa.String(length=35)), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('assumptions', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('onboarding_completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.CheckConstraint("nationality IS NULL OR nationality ~ '^[A-Z]{3}$'", name=op.f('ck_user_profiles_nationality_iso3')),
    sa.CheckConstraint('monthly_income_aed IS NULL OR monthly_income_aed >= 0', name=op.f('ck_user_profiles_income_non_negative')),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_user_profiles_tenant_id_tenants'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_profiles_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_profiles')),
    sa.UniqueConstraint('user_id', name='uq_user_profiles_user_id')
    )
    op.create_index(op.f('ix_user_profiles_user_id'), 'user_profiles', ['user_id'], unique=False)
    op.create_table('agent_runs',
    sa.Column('agent', sa.String(length=80), nullable=False),
    sa.Column('kind', sa.Enum('journey', 'what_if', 'research', 'document_extraction', 'drafting', 'diagnostic', name='runkind', native_enum=False, length=40), nullable=False),
    sa.Column('status', sa.Enum('queued', 'running', 'awaiting_input', 'succeeded', 'failed', 'cancelled', name='runstatus', native_enum=False, length=40), server_default='queued', nullable=False),
    sa.Column('journey_id', sa.UUID(), nullable=True),
    sa.Column('thread_id', sa.String(length=100), nullable=False),
    sa.Column('input', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('output', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('error', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('pending_review', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('event_seq', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('job_id', sa.String(length=100), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.CheckConstraint("kind IN ('journey', 'what_if', 'research', 'document_extraction', 'drafting', 'diagnostic')", name=op.f('ck_agent_runs_kind_valid')),
    sa.CheckConstraint("status IN ('queued', 'running', 'awaiting_input', 'succeeded', 'failed', 'cancelled')", name=op.f('ck_agent_runs_status_valid')),
    sa.ForeignKeyConstraint(['journey_id'], ['journeys.id'], name=op.f('fk_agent_runs_journey_id_journeys'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_agent_runs_tenant_id_tenants'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_agent_runs_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_agent_runs')),
    sa.UniqueConstraint('thread_id', name=op.f('uq_agent_runs_thread_id'))
    )
    op.create_index('ix_agent_runs_user_created', 'agent_runs', ['user_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_agent_runs_user_id'), 'agent_runs', ['user_id'], unique=False)
    op.create_table('graph_edges',
    sa.Column('graph_type', sa.Enum('governance', 'user', name='graphtype', native_enum=False, length=20), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=True),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('relation', sa.Enum('provides', 'requires', 'depends_on', 'satisfied_by', 'produces', 'applies_to', 'available_at', 'may_require', 'governed_by', 'located_in', 'has_household_member', 'member_of', 'has_document', 'holds_visa', 'has_nationality', 'has_goal', 'prefers', 'seeks', 'founder_of', 'engages_in', 'speaks', 'has_budget', 'has_appointment', 'pursues', 'satisfies', 'instance_of', 'eligible_for', 'blocked_by', name='graphedgetype', native_enum=False, length=40), nullable=False),
    sa.Column('source_node_id', sa.UUID(), nullable=False),
    sa.Column('target_node_id', sa.UUID(), nullable=False),
    sa.Column('label', sa.String(length=200), nullable=True),
    sa.Column('properties_json', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('provenance', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.CheckConstraint("(graph_type = 'governance' AND tenant_id IS NULL AND user_id IS NULL) OR (graph_type = 'user' AND tenant_id IS NOT NULL AND user_id IS NOT NULL)", name=op.f('ck_graph_edges_ownership_matches_graph')),
    sa.CheckConstraint("graph_type IN ('governance', 'user')", name=op.f('ck_graph_edges_graph_type_valid')),
    sa.CheckConstraint("relation IN ('provides', 'requires', 'depends_on', 'satisfied_by', 'produces', 'applies_to', 'available_at', 'may_require', 'governed_by', 'located_in', 'has_household_member', 'member_of', 'has_document', 'holds_visa', 'has_nationality', 'has_goal', 'prefers', 'seeks', 'founder_of', 'engages_in', 'speaks', 'has_budget', 'has_appointment', 'pursues', 'satisfies', 'instance_of', 'eligible_for', 'blocked_by')", name=op.f('ck_graph_edges_relation_valid')),
    sa.CheckConstraint('source_node_id <> target_node_id', name=op.f('ck_graph_edges_no_self_loops')),
    sa.ForeignKeyConstraint(['source_node_id'], ['graph_nodes.id'], name=op.f('fk_graph_edges_source_node_id_graph_nodes'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['target_node_id'], ['graph_nodes.id'], name=op.f('fk_graph_edges_target_node_id_graph_nodes'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_graph_edges_tenant_id_tenants'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_graph_edges_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_graph_edges')),
    sa.UniqueConstraint('source_node_id', 'target_node_id', 'relation', name='uq_graph_edges_triple')
    )
    op.create_index('ix_graph_edges_graph_type_relation', 'graph_edges', ['graph_type', 'relation'], unique=False)
    op.create_index('ix_graph_edges_target', 'graph_edges', ['target_node_id'], unique=False)
    op.create_index(op.f('ix_graph_edges_user_id'), 'graph_edges', ['user_id'], unique=False)
    op.create_table('graph_node_evidence',
    sa.Column('node_id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('chunk_id', sa.UUID(), nullable=True),
    sa.Column('quote', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.ForeignKeyConstraint(['chunk_id'], ['governance_chunks.id'], name=op.f('fk_graph_node_evidence_chunk_id_governance_chunks'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['document_id'], ['governance_documents.id'], name=op.f('fk_graph_node_evidence_document_id_governance_documents'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['node_id'], ['graph_nodes.id'], name=op.f('fk_graph_node_evidence_node_id_graph_nodes'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_graph_node_evidence')),
    sa.UniqueConstraint('node_id', 'chunk_id', name='uq_graph_node_evidence_node_chunk')
    )
    op.create_index(op.f('ix_graph_node_evidence_node_id'), 'graph_node_evidence', ['node_id'], unique=False)
    op.create_table('household_members',
    sa.Column('relationship', sa.Enum('spouse', 'child', 'parent', 'sibling', 'domestic_worker', 'other', name='householdrelationship', native_enum=False, length=40), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('date_of_birth', sa.Date(), nullable=True),
    sa.Column('nationality', sa.String(length=3), nullable=True),
    sa.Column('relocation_plan', sa.Enum('with_user', 'later', 'already_in_uae', 'not_relocating', 'undecided', name='relocationplan', native_enum=False, length=40), server_default='undecided', nullable=False),
    sa.Column('arrival_date', sa.Date(), nullable=True),
    sa.Column('needs_sponsorship', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('position', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('graph_node_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.CheckConstraint("nationality IS NULL OR nationality ~ '^[A-Z]{3}$'", name=op.f('ck_household_members_nationality_iso3')),
    sa.CheckConstraint("relationship IN ('spouse', 'child', 'parent', 'sibling', 'domestic_worker', 'other')", name=op.f('ck_household_members_relationship_valid')),
    sa.CheckConstraint("relocation_plan IN ('with_user', 'later', 'already_in_uae', 'not_relocating', 'undecided')", name=op.f('ck_household_members_relocation_plan_valid')),
    sa.ForeignKeyConstraint(['graph_node_id'], ['graph_nodes.id'], name=op.f('fk_household_members_graph_node_id_graph_nodes'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_household_members_tenant_id_tenants'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_household_members_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_household_members'))
    )
    op.create_index(op.f('ix_household_members_user_id'), 'household_members', ['user_id'], unique=False)
    op.create_table('journey_nodes',
    sa.Column('journey_id', sa.UUID(), nullable=False),
    sa.Column('key', sa.String(length=160), nullable=False),
    sa.Column('kind', sa.String(length=40), server_default='task', nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('summary', sa.Text(), server_default='', nullable=False),
    sa.Column('category', sa.Enum('business', 'residency', 'family', 'housing', 'health', 'finance', 'daily_life', 'community', name='stepcategory', native_enum=False, length=40), nullable=False),
    sa.Column('status', sa.Enum('blocked', 'needs_info', 'ready', 'in_progress', 'awaiting_approval', 'handoff', 'done', 'not_applicable', name='stepstatus', native_enum=False, length=40), nullable=False),
    sa.Column('position', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('governance_node_id', sa.UUID(), nullable=True),
    sa.Column('authority', sa.String(length=200), nullable=True),
    sa.Column('official_url', sa.String(length=2048), nullable=True),
    sa.Column('estimated_duration_days', sa.Integer(), nullable=True),
    sa.Column('due_by', sa.Date(), nullable=True),
    sa.Column('blockers', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('provenance', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('basis', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.CheckConstraint("category IN ('business', 'residency', 'family', 'housing', 'health', 'finance', 'daily_life', 'community')", name=op.f('ck_journey_nodes_category_valid')),
    sa.CheckConstraint("status IN ('blocked', 'needs_info', 'ready', 'in_progress', 'awaiting_approval', 'handoff', 'done', 'not_applicable')", name=op.f('ck_journey_nodes_status_valid')),
    sa.ForeignKeyConstraint(['governance_node_id'], ['graph_nodes.id'], name=op.f('fk_journey_nodes_governance_node_id_graph_nodes'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['journey_id'], ['journeys.id'], name=op.f('fk_journey_nodes_journey_id_journeys'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_journey_nodes_tenant_id_tenants'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_journey_nodes_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_journey_nodes')),
    sa.UniqueConstraint('journey_id', 'id', name='uq_journey_nodes_journey_id_id'),
    sa.UniqueConstraint('journey_id', 'key', name='uq_journey_nodes_journey_key')
    )
    op.create_index(op.f('ix_journey_nodes_journey_id'), 'journey_nodes', ['journey_id'], unique=False)
    op.create_index(op.f('ix_journey_nodes_user_id'), 'journey_nodes', ['user_id'], unique=False)
    op.create_table('user_goals',
    sa.Column('goal_type', sa.Enum('establish_company', 'residency', 'sponsor_family', 'find_housing', 'schooling', 'healthcare', 'banking', 'employment', 'community', 'driving', 'other', name='goaltype', native_enum=False, length=40), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('status', sa.Enum('active', 'paused', 'achieved', 'dropped', name='goalstatus', native_enum=False, length=40), server_default='active', nullable=False),
    sa.Column('priority', sa.Enum('high', 'medium', 'low', name='priority', native_enum=False, length=40), server_default='medium', nullable=False),
    sa.Column('target_date', sa.Date(), nullable=True),
    sa.Column('position', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('governance_node_id', sa.UUID(), nullable=True),
    sa.Column('graph_node_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.CheckConstraint("goal_type IN ('establish_company', 'residency', 'sponsor_family', 'find_housing', 'schooling', 'healthcare', 'banking', 'employment', 'community', 'driving', 'other')", name=op.f('ck_user_goals_goal_type_valid')),
    sa.CheckConstraint("priority IN ('high', 'medium', 'low')", name=op.f('ck_user_goals_priority_valid')),
    sa.CheckConstraint("status IN ('active', 'paused', 'achieved', 'dropped')", name=op.f('ck_user_goals_status_valid')),
    sa.ForeignKeyConstraint(['governance_node_id'], ['graph_nodes.id'], name=op.f('fk_user_goals_governance_node_id_graph_nodes'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['graph_node_id'], ['graph_nodes.id'], name=op.f('fk_user_goals_graph_node_id_graph_nodes'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_user_goals_tenant_id_tenants'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_goals_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_goals'))
    )
    op.create_index(op.f('ix_user_goals_user_id'), 'user_goals', ['user_id'], unique=False)
    op.create_table('user_preferences',
    sa.Column('category', sa.Enum('housing', 'budget', 'language', 'community', 'food', 'schooling', 'transport', 'faith', 'other', name='preferencecategory', native_enum=False, length=40), nullable=False),
    sa.Column('key', sa.String(length=80), nullable=False),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('source', sa.Enum('user_stated', 'document_extracted', 'inferred', 'system', name='factsource', native_enum=False, length=40), server_default='user_stated', nullable=False),
    sa.Column('graph_node_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.CheckConstraint("category <> 'faith' OR source = 'user_stated'", name=op.f('ck_user_preferences_faith_is_user_stated')),
    sa.CheckConstraint("category IN ('housing', 'budget', 'language', 'community', 'food', 'schooling', 'transport', 'faith', 'other')", name=op.f('ck_user_preferences_category_valid')),
    sa.CheckConstraint("source IN ('user_stated', 'document_extracted', 'inferred', 'system')", name=op.f('ck_user_preferences_source_valid')),
    sa.ForeignKeyConstraint(['graph_node_id'], ['graph_nodes.id'], name=op.f('fk_user_preferences_graph_node_id_graph_nodes'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_user_preferences_tenant_id_tenants'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_preferences_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_preferences')),
    sa.UniqueConstraint('user_id', 'category', 'key', name='uq_user_preferences_user_key')
    )
    op.create_index(op.f('ix_user_preferences_user_id'), 'user_preferences', ['user_id'], unique=False)
    op.create_table('actions',
    sa.Column('journey_id', sa.UUID(), nullable=True),
    sa.Column('journey_node_id', sa.UUID(), nullable=True),
    sa.Column('run_id', sa.UUID(), nullable=True),
    sa.Column('task_key', sa.String(length=160), nullable=True),
    sa.Column('service_key', sa.String(length=200), nullable=True),
    sa.Column('type', sa.Enum('government_portal', 'appointment', 'document_submission', 'official_handoff', name='actionkind', native_enum=False, length=40), nullable=False),
    sa.Column('status', sa.Enum('draft', 'prepared', 'awaiting_approval', 'approved', 'submitted', 'completed', 'handoff_required', 'blocked', 'rejected', 'cancelled', 'failed', name='actionstatus', native_enum=False, length=40), server_default='prepared', nullable=False),
    sa.Column('adapter', sa.String(length=80), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('summary', sa.Text(), server_default='', nullable=False),
    sa.Column('consequences', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('reversible', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('requires_human_approval', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('requires_user_authentication', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('official_url', sa.String(length=2048), nullable=True),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('response_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('is_simulated', sa.Boolean(), nullable=False),
    sa.Column('confirmation_source', sa.Enum('adapter', 'user_reported', name='confirmationsource', native_enum=False, length=20), nullable=True),
    sa.Column('external_reference', sa.String(length=200), nullable=True),
    sa.Column('approval_id', sa.UUID(), nullable=True),
    sa.Column('executed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.CheckConstraint("confirmation_source IS NULL OR confirmation_source IN ('adapter', 'user_reported')", name=op.f('ck_actions_confirmation_source_valid')),
    sa.CheckConstraint("status <> 'approved' OR approval_id IS NOT NULL", name=op.f('ck_actions_approved_requires_approval')),
    sa.CheckConstraint("status <> 'completed' OR external_reference IS NOT NULL", name=op.f('ck_actions_completed_requires_reference')),
    sa.CheckConstraint("status <> 'handoff_required' OR coalesce(starts_with(official_url, 'https://'), false)", name=op.f('ck_actions_handoff_requires_https_url')),
    sa.CheckConstraint("status IN ('draft', 'prepared', 'awaiting_approval', 'approved', 'submitted', 'completed', 'handoff_required', 'blocked', 'rejected', 'cancelled', 'failed')", name=op.f('ck_actions_status_valid')),
    sa.CheckConstraint("status NOT IN ('submitted', 'completed') OR (approval_id IS NOT NULL AND (NOT is_simulated OR coalesce(confirmation_source, '') = 'user_reported'))", name=op.f('ck_actions_submission_requires_approval_and_real_adapter')),
    sa.CheckConstraint("type IN ('government_portal', 'appointment', 'document_submission', 'official_handoff')", name=op.f('ck_actions_type_valid')),
    sa.ForeignKeyConstraint(['journey_id'], ['journeys.id'], name=op.f('fk_actions_journey_id_journeys'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['journey_node_id'], ['journey_nodes.id'], name=op.f('fk_actions_journey_node_id_journey_nodes'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['run_id'], ['agent_runs.id'], name=op.f('fk_actions_run_id_agent_runs'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_actions_tenant_id_tenants'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_actions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_actions'))
    )
    op.create_index(op.f('ix_actions_journey_id'), 'actions', ['journey_id'], unique=False)
    op.create_index(op.f('ix_actions_user_id'), 'actions', ['user_id'], unique=False)
    op.create_index('ix_actions_user_status', 'actions', ['user_id', 'status'], unique=False)
    op.create_table('agent_events',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('event', sa.String(length=60), nullable=False),
    sa.Column('node', sa.String(length=80), nullable=True),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['agent_runs.id'], name=op.f('fk_agent_events_run_id_agent_runs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_agent_events_tenant_id_tenants'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_agent_events_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_agent_events')),
    sa.UniqueConstraint('run_id', 'seq', name='uq_agent_events_run_seq')
    )
    op.create_index(op.f('ix_agent_events_user_id'), 'agent_events', ['user_id'], unique=False)
    op.create_table('generated_documents',
    sa.Column('kind', sa.Enum('cover_letter', 'email', 'checklist', 'form_prefill', 'business_summary', 'appointment_brief', 'plan', name='generateddocumentkind', native_enum=False, length=40), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('body_markdown', sa.Text(), nullable=False),
    sa.Column('status', sa.Enum('draft', 'approved', 'discarded', name='generateddocumentstatus', native_enum=False, length=40), server_default='draft', nullable=False),
    sa.Column('journey_id', sa.UUID(), nullable=True),
    sa.Column('journey_node_id', sa.UUID(), nullable=True),
    sa.Column('run_id', sa.UUID(), nullable=True),
    sa.Column('provenance', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.CheckConstraint("(status = 'approved') = (approved_at IS NOT NULL)", name=op.f('ck_generated_documents_approved_at_matches_status')),
    sa.CheckConstraint("kind IN ('cover_letter', 'email', 'checklist', 'form_prefill', 'business_summary', 'appointment_brief', 'plan')", name=op.f('ck_generated_documents_kind_valid')),
    sa.CheckConstraint("status IN ('draft', 'approved', 'discarded')", name=op.f('ck_generated_documents_status_valid')),
    sa.ForeignKeyConstraint(['journey_id'], ['journeys.id'], name=op.f('fk_generated_documents_journey_id_journeys'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['journey_node_id'], ['journey_nodes.id'], name=op.f('fk_generated_documents_journey_node_id_journey_nodes'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['run_id'], ['agent_runs.id'], name=op.f('fk_generated_documents_run_id_agent_runs'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_generated_documents_tenant_id_tenants'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_generated_documents_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_generated_documents'))
    )
    op.create_index('ix_generated_documents_user_created', 'generated_documents', ['user_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_generated_documents_user_id'), 'generated_documents', ['user_id'], unique=False)
    op.create_table('graph_edge_evidence',
    sa.Column('edge_id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('chunk_id', sa.UUID(), nullable=True),
    sa.Column('quote', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.ForeignKeyConstraint(['chunk_id'], ['governance_chunks.id'], name=op.f('fk_graph_edge_evidence_chunk_id_governance_chunks'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['document_id'], ['governance_documents.id'], name=op.f('fk_graph_edge_evidence_document_id_governance_documents'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['edge_id'], ['graph_edges.id'], name=op.f('fk_graph_edge_evidence_edge_id_graph_edges'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_graph_edge_evidence')),
    sa.UniqueConstraint('edge_id', 'chunk_id', name='uq_graph_edge_evidence_edge_chunk')
    )
    op.create_index(op.f('ix_graph_edge_evidence_edge_id'), 'graph_edge_evidence', ['edge_id'], unique=False)
    op.create_table('journey_edges',
    sa.Column('journey_id', sa.UUID(), nullable=False),
    sa.Column('source_node_id', sa.Uuid(), nullable=False),
    sa.Column('target_node_id', sa.Uuid(), nullable=False),
    sa.Column('relation', sa.Enum('depends_on', 'alternative_to', name='journeyedgetype', native_enum=False, length=40), server_default='depends_on', nullable=False),
    sa.Column('properties_json', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.CheckConstraint("relation IN ('depends_on', 'alternative_to')", name=op.f('ck_journey_edges_relation_valid')),
    sa.CheckConstraint('source_node_id <> target_node_id', name=op.f('ck_journey_edges_no_self_loops')),
    sa.ForeignKeyConstraint(['journey_id', 'source_node_id'], ['journey_nodes.journey_id', 'journey_nodes.id'], name='fk_journey_edges_source_same_journey', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['journey_id', 'target_node_id'], ['journey_nodes.journey_id', 'journey_nodes.id'], name='fk_journey_edges_target_same_journey', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['journey_id'], ['journeys.id'], name=op.f('fk_journey_edges_journey_id_journeys'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_journey_edges_tenant_id_tenants'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_journey_edges_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_journey_edges')),
    sa.UniqueConstraint('source_node_id', 'target_node_id', 'relation', name='uq_journey_edges_triple')
    )
    op.create_index(op.f('ix_journey_edges_journey_id'), 'journey_edges', ['journey_id'], unique=False)
    op.create_index(op.f('ix_journey_edges_user_id'), 'journey_edges', ['user_id'], unique=False)
    op.create_table('action_approvals',
    sa.Column('action_id', sa.UUID(), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=True),
    sa.Column('review_id', sa.String(length=120), nullable=True),
    sa.Column('status', sa.Enum('pending', 'approved', 'rejected', 'expired', name='approvalstatus', native_enum=False, length=40), server_default='pending', nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.CheckConstraint("(status = 'pending') = (decided_at IS NULL)", name=op.f('ck_action_approvals_decided_at_matches_status')),
    sa.CheckConstraint("status IN ('pending', 'approved', 'rejected', 'expired')", name=op.f('ck_action_approvals_status_valid')),
    sa.ForeignKeyConstraint(['action_id'], ['actions.id'], name=op.f('fk_action_approvals_action_id_actions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['run_id'], ['agent_runs.id'], name=op.f('fk_action_approvals_run_id_agent_runs'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_action_approvals_tenant_id_tenants'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_action_approvals_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_action_approvals')),
    sa.UniqueConstraint('action_id', name='uq_action_approvals_action_id')
    )
    op.create_index(op.f('ix_action_approvals_run_id'), 'action_approvals', ['run_id'], unique=False)
    op.create_index(op.f('ix_action_approvals_user_id'), 'action_approvals', ['user_id'], unique=False)
    op.create_table('appointments',
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('service_key', sa.String(length=200), nullable=True),
    sa.Column('governance_node_id', sa.UUID(), nullable=True),
    sa.Column('journey_id', sa.UUID(), nullable=True),
    sa.Column('journey_node_id', sa.UUID(), nullable=True),
    sa.Column('authority', sa.String(length=200), nullable=True),
    sa.Column('location', sa.String(length=300), nullable=True),
    sa.Column('official_url', sa.String(length=2048), nullable=True),
    sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.Enum('planned', 'requested', 'confirmed', 'completed', 'cancelled', name='appointmentstatus', native_enum=False, length=40), server_default='planned', nullable=False),
    sa.Column('external_reference', sa.String(length=200), nullable=True),
    sa.Column('action_id', sa.UUID(), nullable=True),
    sa.Column('preparation', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('prepared_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('brief_document_id', sa.UUID(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.CheckConstraint("official_url IS NULL OR starts_with(official_url, 'https://')", name=op.f('ck_appointments_https_url')),
    sa.CheckConstraint("status <> 'confirmed' OR external_reference IS NOT NULL", name=op.f('ck_appointments_confirmed_requires_reference')),
    sa.CheckConstraint("status IN ('planned', 'requested', 'confirmed', 'completed', 'cancelled')", name=op.f('ck_appointments_status_valid')),
    sa.ForeignKeyConstraint(['action_id'], ['actions.id'], name=op.f('fk_appointments_action_id_actions'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['brief_document_id'], ['generated_documents.id'], name=op.f('fk_appointments_brief_document_id_generated_documents'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['governance_node_id'], ['graph_nodes.id'], name=op.f('fk_appointments_governance_node_id_graph_nodes'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['journey_id'], ['journeys.id'], name=op.f('fk_appointments_journey_id_journeys'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['journey_node_id'], ['journey_nodes.id'], name=op.f('fk_appointments_journey_node_id_journey_nodes'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_appointments_tenant_id_tenants'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_appointments_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_appointments'))
    )
    op.create_index(op.f('ix_appointments_user_id'), 'appointments', ['user_id'], unique=False)


def _drop_tables() -> None:
    # ### autogenerated DDL (tenants/users excluded) ###
    op.drop_index(op.f('ix_appointments_user_id'), table_name='appointments')
    op.drop_table('appointments')
    op.drop_index(op.f('ix_action_approvals_user_id'), table_name='action_approvals')
    op.drop_index(op.f('ix_action_approvals_run_id'), table_name='action_approvals')
    op.drop_table('action_approvals')
    op.drop_index(op.f('ix_journey_edges_user_id'), table_name='journey_edges')
    op.drop_index(op.f('ix_journey_edges_journey_id'), table_name='journey_edges')
    op.drop_table('journey_edges')
    op.drop_index(op.f('ix_graph_edge_evidence_edge_id'), table_name='graph_edge_evidence')
    op.drop_table('graph_edge_evidence')
    op.drop_index(op.f('ix_generated_documents_user_id'), table_name='generated_documents')
    op.drop_index('ix_generated_documents_user_created', table_name='generated_documents')
    op.drop_table('generated_documents')
    op.drop_index(op.f('ix_agent_events_user_id'), table_name='agent_events')
    op.drop_table('agent_events')
    op.drop_index('ix_actions_user_status', table_name='actions')
    op.drop_index(op.f('ix_actions_user_id'), table_name='actions')
    op.drop_index(op.f('ix_actions_journey_id'), table_name='actions')
    op.drop_table('actions')
    op.drop_index(op.f('ix_user_preferences_user_id'), table_name='user_preferences')
    op.drop_table('user_preferences')
    op.drop_index(op.f('ix_user_goals_user_id'), table_name='user_goals')
    op.drop_table('user_goals')
    op.drop_index(op.f('ix_journey_nodes_user_id'), table_name='journey_nodes')
    op.drop_index(op.f('ix_journey_nodes_journey_id'), table_name='journey_nodes')
    op.drop_table('journey_nodes')
    op.drop_index(op.f('ix_household_members_user_id'), table_name='household_members')
    op.drop_table('household_members')
    op.drop_index(op.f('ix_graph_node_evidence_node_id'), table_name='graph_node_evidence')
    op.drop_table('graph_node_evidence')
    op.drop_index(op.f('ix_graph_edges_user_id'), table_name='graph_edges')
    op.drop_index('ix_graph_edges_target', table_name='graph_edges')
    op.drop_index('ix_graph_edges_graph_type_relation', table_name='graph_edges')
    op.drop_table('graph_edges')
    op.drop_index(op.f('ix_agent_runs_user_id'), table_name='agent_runs')
    op.drop_index('ix_agent_runs_user_created', table_name='agent_runs')
    op.drop_table('agent_runs')
    op.drop_index(op.f('ix_user_profiles_user_id'), table_name='user_profiles')
    op.drop_table('user_profiles')
    op.drop_index('ix_journeys_user_updated', table_name='journeys')
    op.drop_index(op.f('ix_journeys_user_id'), table_name='journeys')
    op.drop_table('journeys')
    op.drop_index('uq_graph_nodes_user_key', table_name='graph_nodes', postgresql_where=sa.text("graph_type = 'user'"))
    op.drop_index('uq_graph_nodes_governance_key', table_name='graph_nodes', postgresql_where=sa.text("graph_type = 'governance'"))
    op.drop_index(op.f('ix_graph_nodes_user_id'), table_name='graph_nodes')
    op.drop_index('ix_graph_nodes_properties_json', table_name='graph_nodes', postgresql_using='gin')
    op.drop_index('ix_graph_nodes_graph_type_entity_type', table_name='graph_nodes')
    op.drop_index('ix_graph_nodes_embedding', table_name='graph_nodes', postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.drop_table('graph_nodes')
    op.drop_index('ix_governance_chunks_embedding_model', table_name='governance_chunks')
    op.drop_index('ix_governance_chunks_embedding', table_name='governance_chunks', postgresql_using='hnsw', postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.drop_index(op.f('ix_governance_chunks_document_id'), table_name='governance_chunks')
    op.drop_index('ix_governance_chunks_content_tsv', table_name='governance_chunks', postgresql_using='gin')
    op.drop_table('governance_chunks')
    op.drop_index('uq_governance_documents_live_url', table_name='governance_documents', postgresql_where=sa.text('superseded_at IS NULL'))
    op.drop_index(op.f('ix_governance_documents_governance_source_id'), table_name='governance_documents')
    op.drop_index('ix_governance_documents_document_type', table_name='governance_documents')
    op.drop_index('ix_governance_documents_authority', table_name='governance_documents')
    op.drop_table('governance_documents')
    op.drop_index('ix_events_starts_at', table_name='events')
    op.drop_table('events')
    op.drop_index('ix_governance_sources_authority', table_name='governance_sources')
    op.drop_table('governance_sources')
    op.drop_table('cultural_guides')
    op.drop_index('ix_communities_category', table_name='communities')
    op.drop_table('communities')
