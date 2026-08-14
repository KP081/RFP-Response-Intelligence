"""Row-Level Security (RLS) utilities for tenant-scoped tables."""


def enable_rls(table_name: str, org_column: str = "org_id") -> str:
    """Generate SQL to enable RLS on a table with FORCE setting.

    The policy is intentionally defensive: empty or unset org context resolves to
    NULL so PostgreSQL will reject access cleanly instead of throwing a UUID cast
    error from an empty string.
    """
    policy_name = f"{table_name}_rls_policy"
    org_context = f"NULLIF(current_setting('app.current_org_id', true), '')::{org_column.upper()}"

    sql = f"""
    ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;
    ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY;

    CREATE POLICY {policy_name} ON {table_name}
        USING ({org_column} = {org_context})
        WITH CHECK ({org_column} = {org_context});
    """
    return sql
