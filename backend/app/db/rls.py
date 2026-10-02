"""SQL builders for row-level security, grants and database-enforced invariants.

Used by migrations so every table gets exactly the same protection. When you add a
private table in a new migration, call `private_table_sql(table)` for it and list the
table in `PRIVATE_TABLES` (core tables in `app.db.models`, feature tables in the feature's
models module); a test checks the list matches the live database policies.

Migrations that shipped keep frozen copies of any SQL that later changed here (see
revision 0001), so editing a builder never rewrites history.
"""

from __future__ import annotations

import os
import re

_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


def app_role() -> str:
    role = os.environ.get("APP_DB_USER", "adapt_app")
    if not _IDENT.match(role):
        raise ValueError(f"invalid APP_DB_USER role name: {role!r}")
    return role


def _ident(name: str) -> str:
    if not _IDENT.match(name):
        raise ValueError(f"invalid identifier: {name!r}")
    return name


def if_role_exists(role: str, statement: str) -> str:
    """Run `statement` only when the runtime role exists (bare local DBs may lack it)."""
    escaped = statement.replace("'", "''")
    return (
        "DO $do$ BEGIN "
        f"IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN "
        f"EXECUTE '{escaped}'; "
        "END IF; END $do$;"
    )


OWNER_PREDICATE = (
    "user_id = (SELECT app_current_user_id()) AND tenant_id = (SELECT app_current_tenant_id())"
)

CONTEXT_FUNCTIONS_SQL = """
CREATE OR REPLACE FUNCTION app_current_user_id() RETURNS uuid
  LANGUAGE sql STABLE PARALLEL SAFE
  AS $$ SELECT nullif(current_setting('app.user_id', true), '')::uuid $$;

CREATE OR REPLACE FUNCTION app_current_tenant_id() RETURNS uuid
  LANGUAGE sql STABLE PARALLEL SAFE
  AS $$ SELECT nullif(current_setting('app.tenant_id', true), '')::uuid $$;
"""

DROP_CONTEXT_FUNCTIONS_SQL = """
DROP FUNCTION IF EXISTS app_current_user_id();
DROP FUNCTION IF EXISTS app_current_tenant_id();
"""


def private_table_sql(table: str) -> list[str]:
    """Owner-only RLS policy + DML grant for a private, per-user table."""
    t = _ident(table)
    role = app_role()
    return [
        f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY",
        f"CREATE POLICY {t}_owner ON {t} FOR ALL "
        f"USING ({OWNER_PREDICATE}) WITH CHECK ({OWNER_PREDICATE})",
        if_role_exists(role, f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO {role}"),
    ]


_USER_OWNED = f"graph_type = 'user' AND {OWNER_PREDICATE}"


def graph_table_sql(table: str) -> list[str]:
    """Governance rows are world-readable; user-graph rows are owner-only; the runtime role
    can write user-graph rows only. Governance writes happen solely through the owner role
    (migrations, seeding, curated ingestion), which bypasses RLS."""
    t = _ident(table)
    role = app_role()
    return [
        f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY",
        f"CREATE POLICY {t}_read ON {t} FOR SELECT "
        f"USING (graph_type = 'governance' OR ({_USER_OWNED}))",
        f"CREATE POLICY {t}_write_user ON {t} FOR ALL "
        f"USING ({_USER_OWNED}) WITH CHECK ({_USER_OWNED})",
        if_role_exists(role, f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO {role}"),
    ]


def public_read_sql(table: str) -> list[str]:
    t = _ident(table)
    role = app_role()
    return [if_role_exists(role, f"GRANT SELECT ON {t} TO {role}")]


def account_table_sql(table: str) -> list[str]:
    """tenants/users grants (policies: `account_policies_sql`)."""
    t = _ident(table)
    role = app_role()
    return [if_role_exists(role, f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO {role}")]


def account_policies_sql() -> list[str]:
    """Accounts are visible only to themselves. A new account is created inside a
    transaction that has already claimed its (random) ids via `app.user_id`/`app.tenant_id`,
    so INSERT ... RETURNING passes the same predicate."""
    tenant = "id = (SELECT app_current_tenant_id())"
    user = "id = (SELECT app_current_user_id()) AND tenant_id = (SELECT app_current_tenant_id())"
    return [
        "ALTER TABLE tenants ENABLE ROW LEVEL SECURITY",
        f"CREATE POLICY tenants_self ON tenants FOR ALL USING ({tenant}) WITH CHECK ({tenant})",
        "ALTER TABLE users ENABLE ROW LEVEL SECURITY",
        f"CREATE POLICY users_self ON users FOR ALL USING ({user}) WITH CHECK ({user})",
    ]


DROP_ACCOUNT_POLICIES_SQL = [
    "DROP POLICY IF EXISTS users_self ON users",
    "ALTER TABLE users DISABLE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS tenants_self ON tenants",
    "ALTER TABLE tenants DISABLE ROW LEVEL SECURITY",
]


def sequences_grant_sql() -> list[str]:
    role = app_role()
    return [
        if_role_exists(role, f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role}")
    ]


def langgraph_schema_sql() -> list[str]:
    """LangGraph checkpoint tables are created by the worker (AsyncPostgresSaver.setup)
    inside a schema owned by the runtime role."""
    role = app_role()
    return [
        "CREATE SCHEMA IF NOT EXISTS langgraph",
        if_role_exists(role, f"ALTER SCHEMA langgraph OWNER TO {role}"),
    ]


GRAPH_EDGE_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION graph_edges_enforce_graph_type() RETURNS trigger
  LANGUAGE plpgsql AS $$
DECLARE
  s_type text; s_user uuid;
  t_type text; t_user uuid;
BEGIN
  -- SECURITY INVOKER: under RLS the caller can only see governance nodes and their own
  -- user-graph nodes, so linking to someone else's node fails with "not found".
  SELECT graph_type, user_id INTO s_type, s_user FROM graph_nodes WHERE id = NEW.source_node_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'graph edge source % not found', NEW.source_node_id USING ERRCODE = 'check_violation';
  END IF;
  SELECT graph_type, user_id INTO t_type, t_user FROM graph_nodes WHERE id = NEW.target_node_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'graph edge target % not found', NEW.target_node_id USING ERRCODE = 'check_violation';
  END IF;

  IF NEW.graph_type = 'governance' THEN
    IF s_type <> 'governance' OR t_type <> 'governance' THEN
      RAISE EXCEPTION 'governance edges may only connect governance nodes'
        USING ERRCODE = 'check_violation';
    END IF;
  ELSE
    IF s_type <> 'user' OR s_user IS DISTINCT FROM NEW.user_id THEN
      RAISE EXCEPTION 'user-graph edges must start at a node owned by the same user'
        USING ERRCODE = 'check_violation';
    END IF;
    IF t_type = 'user' AND t_user IS DISTINCT FROM NEW.user_id THEN
      RAISE EXCEPTION 'user-graph edges may not point at another user''s node'
        USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER graph_edges_enforce_graph_type
  BEFORE INSERT OR UPDATE ON graph_edges
  FOR EACH ROW EXECUTE FUNCTION graph_edges_enforce_graph_type();
"""

DROP_GRAPH_EDGE_TRIGGER_SQL = "DROP FUNCTION IF EXISTS graph_edges_enforce_graph_type() CASCADE;"

ACTION_APPROVAL_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION actions_require_approved_approval() RETURNS trigger
  LANGUAGE plpgsql AS $$
DECLARE
    a_status text; a_action uuid; a_user uuid; a_tenant uuid; a_expires timestamptz;
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
        OR NEW.response_metadata->'parameters' IS DISTINCT FROM OLD.response_metadata->'parameters') THEN
      RAISE EXCEPTION 'approved action scope is immutable; prepare a new action for review'
        USING ERRCODE = 'check_violation';
    END IF;
    -- An action can only move past approval when a HUMAN approved exactly this action.
  IF NEW.status IN ('approved', 'submitted', 'completed') THEN
    SELECT status, action_id, user_id, tenant_id, expires_at
      INTO a_status, a_action, a_user, a_tenant, a_expires
      FROM action_approvals WHERE id = NEW.approval_id;
    IF NOT FOUND OR a_status <> 'approved' OR a_action <> NEW.id
      OR a_user IS DISTINCT FROM NEW.user_id OR a_tenant IS DISTINCT FROM NEW.tenant_id
      OR ((TG_OP = 'INSERT' OR OLD.status IS DISTINCT FROM NEW.status)
          AND a_expires IS NOT NULL AND a_expires <= now()) THEN
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

DROP_ACTION_APPROVAL_TRIGGER_SQL = (
    "DROP FUNCTION IF EXISTS actions_require_approved_approval() CASCADE;"
)


def identity_function_sql() -> list[str]:
    """Look an account up by identity-provider subject. SECURITY DEFINER (owned by the
    migration role) because under RLS the runtime role only sees its own account; it
    returns ids only, for exactly one (provider, subject)."""
    role = app_role()
    return [
        """
CREATE OR REPLACE FUNCTION app_resolve_identity(p_provider text, p_subject text)
  RETURNS TABLE (user_id uuid, tenant_id uuid)
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public
  AS $$ SELECT id, tenant_id FROM users
        WHERE auth_provider = p_provider AND auth_subject = p_subject AND p_subject IS NOT NULL $$;
""",
        "REVOKE ALL ON FUNCTION app_resolve_identity(text, text) FROM PUBLIC",
        if_role_exists(
            role, f"GRANT EXECUTE ON FUNCTION app_resolve_identity(text, text) TO {role}"
        ),
    ]


DROP_IDENTITY_FUNCTION_SQL = "DROP FUNCTION IF EXISTS app_resolve_identity(text, text);"
