"""01_create_core_tables_orgs_users_memberships_audit_log_feature_flags

Revision ID: 0ec7b49318a3
Revises: 
Create Date: 2026-08-14 06:45:29.983426

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.db.rls import enable_rls

# revision identifiers, used by Alembic.
revision: str = '0ec7b49318a3'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    
    # Create role enum type
    role_enum = postgresql.ENUM(
        'admin',
        'proposal_manager',
        'sales',
        'presales_architect',
        'legal',
        'security',
        'compliance',
        'viewer',
        name='role',
        create_type=True
    )
    role_enum.create(op.get_bind(), checkfirst=True)

    # Create orgs table (root tenant table — not RLS-scoped itself)
    op.create_table(
        'orgs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('settings', postgresql.JSON(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    # Create users table (global identity table — not RLS-scoped itself)
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('display_name', sa.String(255), nullable=False),
        sa.Column('external_idp_subject', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email')
    )

    # Create org_memberships table (RLS-scoped)
    op.create_table(
        'org_memberships',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('org_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('role', sa.Enum('admin', 'proposal_manager', 'sales', 'presales_architect', 'legal', 'security', 'compliance', 'viewer', name='role', native_enum=False), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'user_id', name='uq_org_user')
    )
    op.create_index('ix_org_memberships_org_id', 'org_memberships', ['org_id'])

    # Create audit_log table (RLS-scoped)
    op.create_table(
        'audit_log',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('org_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('actor_user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('action', sa.String(50), nullable=False),
        sa.Column('resource_type', sa.String(50), nullable=False),
        sa.Column('resource_id', sa.String(255), nullable=False),
        sa.Column('event_metadata', postgresql.JSON(), nullable=False, server_default='{}'),
        sa.Column('correlation_id', sa.String(36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_audit_log_org_id', 'audit_log', ['org_id'])

    # Create feature_flags table (RLS-scoped)
    op.create_table(
        'feature_flags',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('org_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('flag_name', sa.String(255), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('config', postgresql.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'flag_name', name='uq_org_flag_name')
    )
    op.create_index('ix_feature_flags_org_id', 'feature_flags', ['org_id'])

    # Enable RLS on tenant-scoped tables with FORCE to prevent owner bypass.
    # Use the shared helper so future tenant-scoped tables reuse the same policy design.
    for table in ['org_memberships', 'audit_log', 'feature_flags']:
        for stmt in enable_rls(table):
            op.execute(stmt)


def downgrade() -> None:
    """Downgrade schema."""
    
    # Drop tables (cascade will clean up RLS policies)
    op.drop_table('feature_flags')
    op.drop_table('audit_log')
    op.drop_table('org_memberships')
    op.drop_table('users')
    op.drop_table('orgs')
    
    # Drop role enum
    op.execute("DROP TYPE IF EXISTS role CASCADE;")

