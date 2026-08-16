"""02_create_org_invites_table

Revision ID: a99d25c5fbc2
Revises: 0ec7b49318a3
Create Date: 2026-08-15 12:19:02.989660

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.db.rls import enable_rls

# revision identifiers, used by Alembic.
revision: str = 'a99d25c5fbc2'
down_revision: Union[str, Sequence[str], None] = '0ec7b49318a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # Create invite_status enum type
    invite_status_enum = postgresql.ENUM(
        'pending',
        'accepted',
        'revoked',
        name='invite_status',
        create_type=True
    )
    invite_status_enum.create(op.get_bind(), checkfirst=True)

    # Create org_invites table (RLS-scoped)
    op.create_table(
        'org_invites',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('org_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('role', sa.Enum('admin', 'proposal_manager', 'sales', 'presales_architect', 'legal', 'security', 'compliance', 'viewer', name='role', native_enum=False), nullable=False),
        sa.Column('token', sa.String(64), nullable=False),
        sa.Column('invited_by_user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('status', sa.Enum('pending', 'accepted', 'revoked', name='invite_status', native_enum=False), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['invited_by_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token', name='uq_org_invites_token'),
    )
    op.create_index('ix_org_invites_org_id', 'org_invites', ['org_id'])
    op.create_index('ix_org_invites_token', 'org_invites', ['token'])

    # Enable RLS on tenant-scoped table
    for stmt in enable_rls('org_invites'):
        op.execute(stmt)


def downgrade() -> None:
    """Downgrade schema."""

    # Drop tables (cascade will clean up RLS policies)
    op.drop_table('org_invites')

    # Drop invite_status enum
    op.execute("DROP TYPE IF EXISTS invite_status CASCADE;")