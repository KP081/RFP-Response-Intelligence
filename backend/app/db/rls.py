"""Row-Level Security (RLS) utilities for tenant-scoped tables."""


def enable_rls(table_name: str, org_column: str = "org_id") -> list[str]:
    """Generate SQL statements to enable RLS on a table with FORCE setting.

    The policy is intentionally defensive: empty or unset org context resolves to
    NULL so PostgreSQL will reject access cleanly instead of throwing a UUID cast
    error from an empty string.

    Returns a list of separate SQL statements to avoid asyncpg's limitation
    on multiple commands in a single prepared statement.
    """
    policy_name = f"{table_name}_rls_policy"
    # Use uuid type for the cast since org_id is a UUID column
    org_context = "NULLIF(current_setting('app.current_org_id', true), '')::uuid"

    return [
        f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY {policy_name} ON {table_name} USING ({org_column} = {org_context}) WITH CHECK ({org_column} = {org_context})",
    ]
