"""Provider-confirmed external outcomes and expiring human approvals.

Revision ID: 0006_trust_boundaries
Revises: 0005_research_fact_ids
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_trust_boundaries"
down_revision = "0005_research_fact_ids"
branch_labels = None
depends_on = None

ACTION_REFERENCE = (
    "status <> 'completed' OR (coalesce(length(trim(external_reference)), 0) > 0 "
    "AND coalesce(confirmation_source, '') = 'adapter' AND NOT is_simulated)"
)
ACTION_SUBMISSION = (
    "status NOT IN ('submitted', 'completed') OR (approval_id IS NOT NULL AND "
    "NOT is_simulated AND coalesce(confirmation_source, '') = 'adapter' AND "
    "coalesce(length(trim(external_reference)), 0) > 0)"
)
BOOKING_RECEIPT = (
    "status NOT IN ('confirmed', 'completed') OR ("
    "coalesce(length(trim(external_reference)), 0) > 0 AND "
    "coalesce(booking_confirmation->>'reference', '') = external_reference AND "
    "coalesce(length(trim(booking_confirmation->>'provider')), 0) > 0 AND "
    "coalesce(length(booking_confirmation->>'confirmed_at'), 0) > 0)"
)


def upgrade() -> None:
    op.add_column(
        "appointments", sa.Column("booking_confirmation", postgresql.JSONB(), nullable=True)
    )
    # Preserve old reports as notes, and correct unsupported success states before
    # enforcing the new constraints. No historical provider receipt is invented.
    op.execute("""
        UPDATE journeys j SET
          summary = 'Plan prepared. Official steps need provider confirmation.',
          plan = jsonb_set(j.plan, '{summary}',
            to_jsonb('Plan prepared. Official steps need provider confirmation.'::text))
        WHERE EXISTS (
          SELECT 1 FROM actions a WHERE a.journey_id = j.id
            AND a.status IN ('submitted', 'completed') AND
            (coalesce(a.confirmation_source, '') <> 'adapter' OR a.is_simulated OR
             coalesce(length(trim(a.external_reference)), 0) = 0)
        ) OR EXISTS (
          SELECT 1 FROM appointments p WHERE p.journey_id = j.id
            AND p.status IN ('confirmed', 'completed') AND p.booking_confirmation IS NULL
        )
    """)
    op.execute("""
        UPDATE actions SET
          response_metadata = response_metadata || jsonb_build_object('user_report',
            jsonb_build_object('outcome', status, 'reference', external_reference,
                               'verified', false)),
          status = CASE WHEN coalesce(starts_with(official_url, 'https://'), false)
                   THEN 'handoff_required' ELSE 'prepared' END,
          external_reference = NULL, confirmation_source = NULL
        WHERE status IN ('submitted', 'completed') AND
          (coalesce(confirmation_source, '') <> 'adapter' OR is_simulated OR
           coalesce(length(trim(external_reference)), 0) = 0)
    """)
    op.execute("""
        UPDATE appointments SET status = 'planned', external_reference = NULL
        WHERE status IN ('confirmed', 'completed') AND booking_confirmation IS NULL
    """)
    # Saved projections must not continue to display an unsupported completed action.
    op.execute("""
        UPDATE journey_nodes n SET status = CASE WHEN a.status = 'handoff_required'
                                                THEN 'handoff' ELSE 'ready' END
        FROM actions a WHERE a.journey_node_id = n.id AND n.status = 'done'
          AND a.status IN ('handoff_required', 'prepared')
    """)
    for table, name, expression in (
        ("actions", "completed_requires_reference", ACTION_REFERENCE),
        ("actions", "submission_requires_approval_and_real_adapter", ACTION_SUBMISSION),
        ("appointments", "confirmed_requires_reference", BOOKING_RECEIPT),
    ):
        full_name = f"ck_{table}_{name}"
        op.drop_constraint(op.f(full_name), table, type_="check")
        op.create_check_constraint(op.f(full_name), table, expression)
    op.execute("""
        CREATE OR REPLACE FUNCTION actions_require_approved_approval() RETURNS trigger
          LANGUAGE plpgsql AS $$
        DECLARE a_status text; a_action uuid; a_user uuid; a_tenant uuid; a_expires timestamptz;
        BEGIN
          IF TG_OP = 'UPDATE' AND OLD.approval_id IS NOT NULL
            AND OLD.status IN ('approved', 'handoff_required', 'submitted', 'completed')
            AND (NEW.payload IS DISTINCT FROM OLD.payload
              OR NEW.type IS DISTINCT FROM OLD.type
              OR NEW.service_key IS DISTINCT FROM OLD.service_key
              OR NEW.adapter IS DISTINCT FROM OLD.adapter
              OR NEW.official_url IS DISTINCT FROM OLD.official_url
              OR NEW.is_simulated IS DISTINCT FROM OLD.is_simulated
              OR NEW.requires_human_approval IS DISTINCT FROM OLD.requires_human_approval
              OR NEW.consequences IS DISTINCT FROM OLD.consequences
              OR NEW.response_metadata->'parameters'
                 IS DISTINCT FROM OLD.response_metadata->'parameters') THEN
            RAISE EXCEPTION 'approved action scope is immutable; prepare a new action for review'
              USING ERRCODE = 'check_violation';
          END IF;
          IF NEW.status IN ('approved', 'submitted', 'completed') THEN
            SELECT status, action_id, user_id, tenant_id, expires_at
              INTO a_status, a_action, a_user, a_tenant, a_expires
              FROM action_approvals WHERE id = NEW.approval_id;
            IF NOT FOUND OR a_status <> 'approved' OR a_action <> NEW.id
              OR a_user IS DISTINCT FROM NEW.user_id OR a_tenant IS DISTINCT FROM NEW.tenant_id
              OR ((TG_OP = 'INSERT' OR OLD.status IS DISTINCT FROM NEW.status)
                  AND a_expires IS NOT NULL AND a_expires <= now()) THEN
              RAISE EXCEPTION 'action needs an approved, current, owner-bound approval'
                USING ERRCODE = 'check_violation';
            END IF;
          END IF;
          RETURN NEW;
        END $$;
    """)


def downgrade() -> None:
    for table, name, expression in (
        (
            "actions",
            "completed_requires_reference",
            "status <> 'completed' OR external_reference IS NOT NULL",
        ),
        (
            "actions",
            "submission_requires_approval_and_real_adapter",
            "status NOT IN ('submitted', 'completed') OR (approval_id IS NOT NULL AND "
            "(NOT is_simulated OR coalesce(confirmation_source, '') = 'user_reported'))",
        ),
        (
            "appointments",
            "confirmed_requires_reference",
            "status <> 'confirmed' OR external_reference IS NOT NULL",
        ),
    ):
        full_name = f"ck_{table}_{name}"
        op.drop_constraint(op.f(full_name), table, type_="check")
        op.create_check_constraint(op.f(full_name), table, expression)
    op.drop_column("appointments", "booking_confirmation")
    op.execute("""
        CREATE OR REPLACE FUNCTION actions_require_approved_approval() RETURNS trigger
          LANGUAGE plpgsql AS $$
        DECLARE a_status text; a_action uuid;
        BEGIN
          IF NEW.status IN ('approved', 'submitted', 'completed') THEN
            SELECT status, action_id INTO a_status, a_action
              FROM action_approvals WHERE id = NEW.approval_id;
            IF NOT FOUND OR a_status <> 'approved' OR a_action <> NEW.id THEN
              RAISE EXCEPTION 'action needs an approved approval' USING ERRCODE = 'check_violation';
            END IF;
          END IF;
          RETURN NEW;
        END $$;
    """)
